"""Business rules for Reclutamiento."""

from typing import Annotated, Any
from uuid import UUID

from fastapi import Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime, UTC
from fastapi.responses import PlainTextResponse

from models import Candidate
from novvus_sdk import NovvusModule, requires, current_context

class HireBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    notes: str = ""

async def export_candidates_csv(session: AsyncSession) -> str:
    rows = (await session.execute(text(
        "SELECT id, name, email, phone, status, source, skills FROM mod_reclutamiento.candidate WHERE deleted_at IS NULL ORDER BY name"
    ))).all()
    lines = ["id,name,email,phone,status,source,skills"]
    for r in rows:
        def esc(v):
            s = "" if v is None else str(v)
            if "," in s or '"' in s or "\n" in s:
                s = '"' + s.replace('"', '""') + '"'
            return s
        lines.append(",".join(esc(v) for v in r))
    return "\n".join(lines) + "\n"


async def dashboard(session: AsyncSession) -> dict[str, Any]:
    rows = (await session.execute(
        text("SELECT status, COUNT(*) FROM mod_reclutamiento.candidate WHERE deleted_at IS NULL GROUP BY status")
    )).all()
    by_status = {str(r[0]): int(r[1]) for r in rows}
    total = sum(by_status.values())
    interviews = await session.scalar(text("SELECT COUNT(*) FROM mod_reclutamiento.interview WHERE deleted_at IS NULL AND date BETWEEN now() AND now() + interval '7 days'")) or 0
    offers = (await session.execute(text("SELECT status, COUNT(*) FROM mod_reclutamiento.offer WHERE deleted_at IS NULL GROUP BY status"))).all()
    by_offer = {str(r[0]): int(r[1]) for r in offers}
    return {
        "generated_at": datetime.now(tz=UTC).isoformat(),
        "metrics": [
            {"label": "Candidatos totales", "value": total, "description": "Todos los candidatos registrados", "tone": "info"},
            {"label": "En entrevista", "value": by_status.get("interview", 0), "description": "Candidatos en etapa de entrevista", "tone": "info"},
            {"label": "Contratados", "value": by_status.get("hired", 0), "description": "Candidatos contratados", "tone": "success"},
            {"label": "Entrevistas (7d)", "value": int(interviews), "description": "Entrevistas programadas próximos 7 días", "tone": "info"},
            {"label": "Ofertas aceptadas", "value": by_offer.get("accepted", 0), "description": "Ofertas aceptadas", "tone": "success"},
        ],
        "recent": {"title": "Candidatos recientes", "description": "Últimos candidatos registrados", "path": "candidates", "empty": "Sin candidatos.", "items": []},
        "queues": [],
        "distribution": [{"label": k, "value": v, "tone": "info"} for k, v in sorted(by_status.items())],
    }


def register(module: NovvusModule) -> None:
    router = module.router
    SessionDep = Annotated[AsyncSession, Depends(module.session_dependency())]

    @router.get("/reports/dashboard")
    async def _dashboard(session: SessionDep) -> dict[str, Any]:
        return await dashboard(session)

    @router.get("/reports/export/candidates")
    async def _export(session: SessionDep):
        csv = await export_candidates_csv(session)
        return PlainTextResponse(csv, media_type="text/csv", headers={"Content-Disposition": "attachment; filename=candidates.csv"})

    @router.post("/candidates/{candidate_id}/hire")
    @requires("reclutamiento.candidates.write")
    async def hire_candidate(candidate_id: UUID, payload: HireBody, session: SessionDep) -> dict[str, Any]:
        candidate = await session.scalar(
            select(Candidate).where(Candidate.id == candidate_id, Candidate.deleted_at.is_(None))
        )
        if candidate is None:
            raise HTTPException(status_code=404, detail="candidate not found")

        candidate.status = "hired"
        if payload.notes:
            candidate.notes = (candidate.notes or "") + "\n" + payload.notes
        await session.flush()
        await session.refresh(candidate)

        # Create contact in CRM via module.call
        contact_id = None
        if module.kernel is not None:
            try:
                ctx = current_context()
                result = await module.call(
                    "POST",
                    "/api/crm/contacts/actions/register",
                    org_id=ctx.org_id,
                    json={
                        "name": candidate.name,
                        "kind": "other",
                        "email": candidate.email or "",
                        "phone": candidate.phone or "",
                        "mobile": candidate.mobile or "",
                        "job_title": "Contratado",
                        "notes": f"Contratado desde Reclutamiento (candidato {candidate.id})",
                    },
                )
                contact_id = result.get("record", {}).get("id") if isinstance(result, dict) else None
            except Exception as e:
                import logging
                logging.getLogger("reclutamiento").warning("Failed to create contact in CRM: %s", e)

        # Create onboarding project in Projects via module.call
        project_id = None
        if module.kernel is not None:
            try:
                ctx = current_context()
                result = await module.call(
                    "POST",
                    "/api/projects/projects/actions/register",
                    org_id=ctx.org_id,
                    json={
                        "name": f"Onboarding - {candidate.name}",
                        "code": f"ONB-{str(candidate.id).replace('-', '')[-12:].upper()}",
                        "description": f"Proyecto de onboarding para {candidate.name}",
                        "kind": "internal",
                        "priority": "medium",
                        "status": "draft",
                        "company_name": "",
                        "contact_name": candidate.name,
                        "contact_id": contact_id,
                    },
                )
                project_id = result.get("record", {}).get("id") if isinstance(result, dict) else None
            except Exception as e:
                import logging
                logging.getLogger("reclutamiento").warning("Failed to create project in Projects: %s", e)

        await module.emit(
            "reclutamiento.candidate.hired",
            {
                "candidate_id": str(candidate.id),
                "name": candidate.name,
                "email": candidate.email,
                "contact_id": contact_id,
                "project_id": project_id,
            },
        )
        return {"candidate_id": str(candidate.id), "contact_id": contact_id, "project_id": project_id, "status": "hired"}
