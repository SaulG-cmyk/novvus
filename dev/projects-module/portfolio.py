"""Portfolio (`views.dashboard` of projects) and reports, all from real rows.

Formulas (modules/projects/README.md):

    active / paused / completed = projects by status (not deleted)
    delayed / at risk / blocked = active or paused projects by health
    global progress  = Σ(progress x weight) / Σ(weight) over active and paused projects, where the
                       weight is the budget when every such project has one, else 1 (plain mean)
    upcoming milestones = pending milestones of active projects due within the next 30 days
    overdue tasks   = open tasks (todo/doing/blocked/review) of active projects past their due date
    workload        = open tasks per assignee, with the overdue ones
Filters of the reports: status, kind, owner_user_id, company_id.
"""

from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Annotated, Any
from uuid import UUID

from fastapi import Depends, HTTPException
from models import (
    Health,
    Milestone,
    MilestoneStatus,
    Project,
    ProjectKind,
    ProjectStatus,
    Task,
    TaskStatus,
)
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from novvus_sdk import NovvusModule, requires

OPEN = (TaskStatus.todo, TaskStatus.doing, TaskStatus.blocked, TaskStatus.review)
LIVE = (ProjectStatus.active, ProjectStatus.paused)
UPCOMING_DAYS = 30
STATUS_LABELS = {
    "draft": ("Borrador", "neutral"),
    "active": ("Activo", "info"),
    "paused": ("Pausado", "warning"),
    "completed": ("Concluido", "success"),
    "cancelled": ("Cancelado", "danger"),
    "archived": ("Archivado", "neutral"),
}
HEALTH_LABELS = {
    "on_track": ("En tiempo", "success"),
    "at_risk": ("En riesgo", "warning"),
    "delayed": ("Retrasado", "danger"),
    "blocked": ("Bloqueado", "danger"),
}


def _pct(value: Decimal) -> str:
    return str(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def global_progress(rows: list[tuple[Decimal, Decimal | None]]) -> Decimal:
    """`rows` = (progress, budget). Budget-weighted when every project has a budget, else a mean."""
    if not rows:
        return Decimal("0.00")
    if all(budget is not None and budget > 0 for _p, budget in rows):
        total = sum((budget for _p, budget in rows), Decimal("0"))  # type: ignore[misc]
        return (sum((p * b for p, b in rows), Decimal("0")) / total).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )  # type: ignore[operator]
    return (sum((p for p, _b in rows), Decimal("0")) / len(rows)).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


async def _projects(
    session: AsyncSession,
    status: ProjectStatus | None = None,
    kind: ProjectKind | None = None,
    owner: UUID | None = None,
    company: UUID | None = None,
) -> list[Project]:
    query = select(Project).where(Project.deleted_at.is_(None))
    if status is not None:
        query = query.where(Project.status == status)
    if kind is not None:
        query = query.where(Project.kind == kind)
    if owner is not None:
        query = query.where(Project.owner_user_id == owner)
    if company is not None:
        query = query.where(Project.company_id == company)
    return list(
        (
            await session.scalars(query.order_by(Project.due_date.asc().nulls_last(), Project.name))
        ).all()
    )


async def overview(session: AsyncSession) -> dict[str, Any]:
    now = datetime.now(tz=UTC)
    today = now.date()
    projects = await _projects(session)
    by_status: dict[str, int] = defaultdict(int)
    by_health: dict[str, int] = defaultdict(int)
    live: list[Project] = []
    for project in projects:
        by_status[project.status.value] += 1
        if project.status in LIVE:
            live.append(project)
            by_health[project.health.value] += 1
    live_ids = [p.id for p in live]
    progress = global_progress([(p.progress, p.budget) for p in live])

    milestones: list[Milestone] = []
    overdue: list[Task] = []
    if live_ids:
        milestones = list(
            (
                await session.scalars(
                    select(Milestone)
                    .where(
                        Milestone.project_id.in_(live_ids),
                        Milestone.status == MilestoneStatus.pending,
                        Milestone.due_date.is_not(None),
                        Milestone.due_date <= today + timedelta(days=UPCOMING_DAYS),
                        Milestone.deleted_at.is_(None),
                    )
                    .order_by(Milestone.due_date)
                )
            ).all()
        )
        tasks = (
            await session.scalars(
                select(Task)
                .where(
                    Task.project_id.in_(live_ids),
                    Task.status.in_(OPEN),
                    Task.due_date.is_not(None),
                    Task.deleted_at.is_(None),
                )
                .order_by(Task.due_date)
            )
        ).all()
        overdue = [t for t in tasks if _aware(t.due_date) < now]  # type: ignore[operator]
    names = {p.id: p for p in projects}

    def metric(label: str, value: Any, description: str, tone: str = "neutral") -> dict[str, Any]:
        return {"label": label, "value": value, "description": description, "tone": tone}

    def item(project: Project) -> dict[str, Any]:
        health_label, health_tone = HEALTH_LABELS[project.health.value]
        return {
            "id": str(project.id),
            "title": f"{project.code} · {project.name}" if project.code else project.name,
            "subtitle": f"Avance {_pct(project.progress)} %"
            + (f" · entrega {project.due_date.isoformat()}" if project.due_date else ""),
            "path": f"projects/{project.id}",
            "status": {"label": health_label, "tone": health_tone},
            "updated_at": (_aware(project.updated_at) or now).isoformat(),
        }

    attention = sorted(
        (p for p in live if p.health != Health.on_track),
        key=lambda p: (
            {"blocked": 0, "delayed": 1, "at_risk": 2}.get(p.health.value, 3),
            p.due_date or date.max,
        ),
    )
    return {
        "generated_at": now.isoformat(),
        "metrics": [
            metric(
                "Proyectos activos", by_status["active"], f"{by_status['paused']} pausados", "info"
            ),
            metric(
                "Concluidos",
                by_status["completed"],
                f"{by_status['archived']} archivados",
                "success",
            ),
            metric(
                "Retrasados",
                by_health["delayed"],
                "Activos o pausados con fechas vencidas",
                "danger" if by_health["delayed"] else "neutral",
            ),
            metric(
                "En riesgo",
                by_health["at_risk"] + by_health["blocked"],
                f"{by_health['blocked']} bloqueados",
                "warning" if (by_health["at_risk"] + by_health["blocked"]) else "neutral",
            ),
            metric(
                "Avance global",
                f"{_pct(progress)} %",
                "Media de los proyectos en curso (ponderada por presupuesto si todos lo tienen)",
                "info",
            ),
            metric(
                "Hitos próximos",
                len(milestones),
                f"Pendientes en {UPCOMING_DAYS} días",
                "warning" if milestones else "neutral",
            ),
            metric(
                "Actividades vencidas",
                len(overdue),
                "Abiertas con fecha límite pasada",
                "danger" if overdue else "neutral",
            ),
        ],
        "recent": {
            "title": "Proyectos en curso",
            "description": "Por fecha de entrega",
            "path": "projects",
            "empty": "No hay proyectos activos ni pausados.",
            "items": [item(p) for p in live[:8]],
        },
        "queues": [
            {
                "title": "Requieren atención",
                "description": "Bloqueados, retrasados y en riesgo",
                "tone": "danger",
                "empty": "Todos los proyectos en curso están en tiempo.",
                "total": len(attention),
                "items": [item(p) for p in attention[:5]],
            },
            {
                "title": "Próximos hitos",
                "description": f"Pendientes en los próximos {UPCOMING_DAYS} días",
                "tone": "warning",
                "empty": "Ningún hito vence pronto.",
                "total": len(milestones),
                "items": [
                    {
                        "id": str(m.id),
                        "title": m.name,
                        "subtitle": f"{names[m.project_id].name} · {m.due_date.isoformat()}"
                        if m.project_id in names
                        else (m.due_date.isoformat() if m.due_date else ""),
                        "path": f"milestones/{m.id}",
                        "status": {
                            "label": "Vencido" if m.due_date and m.due_date < today else "Próximo",
                            "tone": "danger" if m.due_date and m.due_date < today else "warning",
                        },
                        "updated_at": (_aware(m.updated_at) or now).isoformat(),
                    }
                    for m in milestones[:5]
                ],
            },
            {
                "title": "Actividades vencidas",
                "description": "Las más antiguas primero",
                "tone": "danger",
                "empty": "No hay actividades vencidas.",
                "total": len(overdue),
                "items": [
                    {
                        "id": str(t.id),
                        "title": t.title,
                        "subtitle": f"{names[t.project_id].name} · vencía {t.due_date.date()}"
                        if t.project_id in names
                        else t.due_date.date().isoformat(),
                        "path": f"tasks/{t.id}",
                        "status": {"label": "Vencida", "tone": "danger"},
                        "updated_at": (_aware(t.updated_at) or now).isoformat(),
                    }
                    for t in overdue[:5]
                ],
            },
        ],
        "distribution": [
            {"label": STATUS_LABELS[key][0], "value": by_status[key], "tone": STATUS_LABELS[key][1]}
            for key in ("draft", "active", "paused", "completed", "cancelled", "archived")
            if by_status[key]
        ],
    }


def register(module: NovvusModule) -> None:
    router = module.router
    SessionDep = Annotated[AsyncSession, Depends(module.session_dependency())]

    @router.get("/reports/portfolio")
    @requires("projects.projects.read")
    async def portfolio(
        session: SessionDep,
        status: str | None = None,
        kind: str | None = None,
        owner_user_id: UUID | None = None,
        company_id: UUID | None = None,
    ) -> dict[str, Any]:
        """Projects with their progress, planned baseline and health, filtered."""
        try:
            status_value = ProjectStatus(status) if status else None
            kind_value = ProjectKind(kind) if kind else None
        except ValueError as error:
            raise HTTPException(status_code=422, detail="unknown status or kind") from error
        rows = await _projects(session, status_value, kind_value, owner_user_id, company_id)
        ids = [p.id for p in rows]
        open_by_project: dict[UUID, int] = defaultdict(int)
        overdue_by_project: dict[UUID, int] = defaultdict(int)
        now = datetime.now(tz=UTC)
        if ids:
            tasks = (
                await session.scalars(
                    select(Task).where(
                        Task.project_id.in_(ids), Task.status.in_(OPEN), Task.deleted_at.is_(None)
                    )
                )
            ).all()
            for t in tasks:
                open_by_project[t.project_id] += 1
                if t.due_date is not None and _aware(t.due_date) < now:  # type: ignore[operator]
                    overdue_by_project[t.project_id] += 1
        live = [p for p in rows if p.status in LIVE]
        return {
            "count": len(rows),
            "global_progress": _pct(global_progress([(p.progress, p.budget) for p in live])),
            "by_status": {
                s.value: sum(1 for p in rows if p.status == s)
                for s in ProjectStatus
                if any(p.status == s for p in rows)
            },
            "by_health": {
                h.value: sum(1 for p in live if p.health == h)
                for h in Health
                if any(p.health == h for p in live)
            },
            "projects": [
                {
                    "id": str(p.id),
                    "code": p.code,
                    "name": p.name,
                    "kind": p.kind.value,
                    "status": p.status.value,
                    "health": p.health.value,
                    "owner_user_id": str(p.owner_user_id) if p.owner_user_id else None,
                    "company_id": str(p.company_id) if p.company_id else None,
                    "progress": _pct(p.progress),
                    "planned_progress": _pct(p.planned_progress)
                    if p.planned_progress is not None
                    else None,
                    "deviation": _pct(p.progress - p.planned_progress)
                    if p.planned_progress is not None
                    else None,
                    "due_date": p.due_date.isoformat() if p.due_date else None,
                    "open_tasks": open_by_project[p.id],
                    "overdue_tasks": overdue_by_project[p.id],
                }
                for p in rows
            ],
        }

    @router.get("/reports/workload")
    @requires("projects.projects.read")
    async def workload(session: SessionDep, project_id: UUID | None = None) -> dict[str, Any]:
        """Open tasks per assignee (and unassigned), with overdue counts and hours."""
        query = select(Task).where(Task.status.in_(OPEN), Task.deleted_at.is_(None))
        if project_id is not None:
            query = query.where(Task.project_id == project_id)
        tasks = (await session.scalars(query)).all()
        now = datetime.now(tz=UTC)
        buckets: dict[str, dict[str, Any]] = {}
        for t in tasks:
            key = str(t.assigned_user_id) if t.assigned_user_id else ""
            bucket = buckets.setdefault(
                key,
                {
                    "user_id": key or None,
                    "open": 0,
                    "overdue": 0,
                    "blocked": 0,
                    "estimated_hours": Decimal("0"),
                    "logged_hours": Decimal("0"),
                },
            )
            bucket["open"] += 1
            if t.is_blocked:
                bucket["blocked"] += 1
            if t.due_date is not None and _aware(t.due_date) < now:  # type: ignore[operator]
                bucket["overdue"] += 1
            bucket["estimated_hours"] += t.estimated_hours
            bucket["logged_hours"] += t.logged_hours
        return {
            "open": len(tasks),
            "by_user": [
                {
                    **b,
                    "estimated_hours": str(b["estimated_hours"]),
                    "logged_hours": str(b["logged_hours"]),
                }
                for b in sorted(
                    buckets.values(), key=lambda b: (-b["overdue"], -b["open"], b["user_id"] or "")
                )
            ],
        }

    @router.get("/reports/dashboard")
    @requires("projects.projects.read")
    async def dashboard(session: SessionDep) -> dict[str, Any]:
        return await overview(session)

    _ = func  # keep the import meaningful for future aggregates
