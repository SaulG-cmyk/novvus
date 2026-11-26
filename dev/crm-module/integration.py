"""Integration with Proyectos through its public API (contracts, never tables).

The CRM never runs the project engine: it asks Proyectos to register a project
(`POST /api/projects/projects/actions/register`) for a won opportunity and
reads project summaries (`GET /api/projects/reports/portfolio`). Calls go
through the gateway with the service permissions declared in novvus.toml
`[dependencies] service_permissions`; when Proyectos is not installed or is
down, the actions explain it instead of failing silently (503), and the rest
of the CRM keeps working. Idempotency: a project code is unique per
organization in Proyectos, so repeating «Crear proyecto» with the same code is
refused there (409 here) instead of duplicating; links opportunity ↔ project
are kept by Proyectos (`project_links`, many projects per opportunity).
"""

from datetime import date
from typing import Any
from uuid import UUID

import httpx
from fastapi import HTTPException
from models import Company, Contact, Opportunity
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from novvus_sdk import NovvusModule

PROJECTS_UNAVAILABLE = "Proyectos no está disponible en esta instalación"


async def projects_call(module: NovvusModule, method: str, path: str, **kwargs: Any) -> Any:
    """One place to translate transport failures into a readable 503."""
    try:
        return await module.call(method, path, **kwargs)
    except RuntimeError as error:  # offline mode: no kernel
        raise HTTPException(status_code=503, detail=PROJECTS_UNAVAILABLE) from error
    except httpx.HTTPStatusError as error:
        status = error.response.status_code
        if status in (404, 502, 503):
            raise HTTPException(status_code=503, detail=PROJECTS_UNAVAILABLE) from error
        detail: Any
        try:
            detail = error.response.json().get("detail", error.response.text)
        except ValueError:
            detail = error.response.text
        raise HTTPException(status_code=409 if status == 422 else status, detail=detail) from error
    except httpx.HTTPError as error:
        raise HTTPException(status_code=503, detail=PROJECTS_UNAVAILABLE) from error


async def template_options(module: NovvusModule) -> list[dict[str, Any]]:
    try:
        page = await projects_call(module, "GET", "/api/projects/templates?limit=100")
    except HTTPException:
        return [{"value": "", "label": "Sin plantilla", "description": PROJECTS_UNAVAILABLE}]
    items = page.get("items", []) if isinstance(page, dict) else []
    return [{"value": "", "label": "Sin plantilla"}] + [
        {
            "value": str(t["id"]),
            "label": str(t.get("name", "")),
            "description": str(t.get("description", ""))[:120],
        }
        for t in items
        if t.get("is_active", True)
    ]


def _project_lines(projects: list[dict[str, Any]]) -> list[str]:
    labels = {
        "draft": "borrador",
        "active": "activo",
        "paused": "pausado",
        "completed": "concluido",
        "cancelled": "cancelado",
        "archived": "archivado",
    }
    health = {
        "on_track": "en tiempo",
        "at_risk": "en riesgo",
        "delayed": "retrasado",
        "blocked": "bloqueado",
    }
    lines = []
    for p in projects:
        status = labels.get(p.get("status", ""), p.get("status", ""))
        tone = health.get(p.get("health", ""), p.get("health", ""))
        code, name, progress = p.get("code") or "—", p.get("name", ""), p.get("progress", "0")
        line = f"{code} · {name} · {status} · avance {progress} % · {tone}"
        if p.get("due_date"):
            line += f" · entrega {p['due_date']}"
        if p.get("overdue_tasks"):
            line += f" · {p['overdue_tasks']} actividades vencidas"
        lines.append(line)
    return [line for line in lines]


async def projects_of_company(module: NovvusModule, company_id: UUID) -> list[dict[str, Any]]:
    report = await projects_call(
        module, "GET", f"/api/projects/reports/portfolio?company_id={company_id}"
    )
    return list(report.get("projects", [])) if isinstance(report, dict) else []


async def projects_of_opportunity(
    module: NovvusModule, opportunity_id: UUID
) -> list[dict[str, Any]]:
    """Projects linked through `project_links` (several per opportunity) plus the originating
    one."""
    condition = f'{{"field": "opportunity_id", "op": "eq", "value": "{opportunity_id}"}}'
    links = await projects_call(
        module, "GET", f"/api/projects/project_links?limit=100&filter={condition}"
    )
    ids = {
        str(link["project_id"])
        for link in (links.get("items", []) if isinstance(links, dict) else [])
    }
    report = await projects_call(module, "GET", "/api/projects/reports/portfolio")
    rows = report.get("projects", []) if isinstance(report, dict) else []
    return [
        p
        for p in rows
        if str(p.get("id")) in ids or str(p.get("opportunity_id") or "") == str(opportunity_id)
    ]


def register(module: NovvusModule) -> None:
    @module.action(Opportunity, "create_project")
    async def create_project(
        session: AsyncSession, ctx: Any, opportunity: Opportunity, body: dict[str, Any]
    ) -> dict[str, Any]:
        if opportunity.is_won is not True:
            raise HTTPException(status_code=409, detail="only a won opportunity becomes a project")
        code = str(body.get("code") or "").strip()
        if not code:
            raise HTTPException(status_code=422, detail={"code": "Indica el código del proyecto"})
        company = (
            await session.scalar(select(Company).where(Company.id == opportunity.company_id))
            if opportunity.company_id
            else None
        )
        contact = (
            await session.scalar(select(Contact).where(Contact.id == opportunity.contact_id))
            if opportunity.contact_id
            else None
        )
        payload: dict[str, Any] = {
            "code": code,
            "name": str(body.get("name") or "").strip() or opportunity.name,
            "template_id": str(body.get("template_id") or ""),
            "start_date": str(body.get("start_date") or ""),
            "due_date": str(body.get("due_date") or ""),
            "kind": str(body.get("kind") or ""),
            "opportunity_id": str(opportunity.id),
            "opportunity_name": opportunity.name,
            "company_id": str(opportunity.company_id) if opportunity.company_id else "",
            "company_name": company.name if company else "",
            "contact_id": str(opportunity.contact_id) if opportunity.contact_id else "",
            "contact_name": contact.name if contact else "",
            "budget": str(opportunity.amount) if body.get("use_amount_as_budget", True) else "",
            "currency": opportunity.currency,
            "description": opportunity.description,
        }
        result = await projects_call(
            module, "POST", "/api/projects/projects/actions/register", json=payload
        )
        project_id = (
            str((result or {}).get("record", {}).get("id", "")) if isinstance(result, dict) else ""
        )
        return {
            "message": module._(
                "Proyecto {code} creado en Proyectos y vinculado a la oportunidad"
            ).format(code=code),
            "proyecto": project_id,
            "detalle": [str((result or {}).get("message", ""))] if isinstance(result, dict) else [],
        }

    @module.action_options(Opportunity, "create_project")
    async def create_project_options(
        session: AsyncSession, ctx: Any, opportunity: Opportunity, body: dict[str, Any]
    ) -> dict[str, Any]:
        return {"template_id": await template_options(module)}

    @module.action_validator(Opportunity, "create_project")
    async def create_project_validate(
        session: AsyncSession, ctx: Any, opportunity: Opportunity, body: dict[str, Any]
    ) -> dict[str, str]:
        errors: dict[str, str] = {}
        if opportunity.is_won is not True:
            errors["code"] = "Solo una oportunidad ganada se convierte en proyecto"
        start, due = body.get("start_date"), body.get("due_date")
        if start and due and date.fromisoformat(str(due)) < date.fromisoformat(str(start)):
            errors["due_date"] = "La conclusión no puede ser anterior al inicio"
        return errors

    @module.action(Opportunity, "projects_summary")
    async def opportunity_projects(
        session: AsyncSession, ctx: Any, opportunity: Opportunity, body: dict[str, Any]
    ) -> dict[str, Any]:
        rows = await projects_of_opportunity(module, opportunity.id)
        if not rows:
            return {"message": module._("La oportunidad no tiene proyectos vinculados")}
        return {
            "message": module._("{count} proyectos vinculados").format(count=len(rows)),
            "proyectos": _project_lines(rows),
        }

    @module.action(Company, "projects_summary")
    async def company_projects(
        session: AsyncSession, ctx: Any, company: Company, body: dict[str, Any]
    ) -> dict[str, Any]:
        rows = await projects_of_company(module, company.id)
        if not rows:
            return {"message": module._("La empresa no tiene proyectos")}
        return {
            "message": module._("{count} proyectos de la empresa").format(count=len(rows)),
            "proyectos": _project_lines(rows),
        }
