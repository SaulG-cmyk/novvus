"""Commercial control centre (`views.dashboard`) and reports, all from real rows.

Every figure is computed from the organization's opportunities, leads and
activities under the caller's permissions (RLS + `crm.reports.read` for the
reports, `crm.opportunities.read` for the home panel). Formulas, documented
in modules/crm/README.md:

    open            = opportunities with is_won IS NULL (not deleted)
    pipeline value  = Σ amount of open opportunities (per currency)
    probability     = opportunity.probability if set, else its stage's probability
    weighted forecast = Σ amount x probability / 100 over open opportunities
    won / lost      = closed opportunities by is_won, inside the period (closed_at)
    conversion rate = won / (won + lost) in the period
    closing soon    = open with expected_close_date within the next N days (default 30)
    stalled         = open whose last activity (last_activity_at, else updated_at) is older
                      than `crm.rotting_days` (config, default 14)
    overdue activities = pending with due_date < now
    average duration = mean(closed_at - created_at) of the opportunities closed in the period
"""

from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Annotated, Any
from uuid import UUID

from fastapi import Depends, HTTPException
from models import (
    Activity,
    ActivityStatus,
    Lead,
    LeadStatus,
    LostReason,
    Opportunity,
    Pipeline,
    Stage,
)
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from novvus_sdk import NovvusModule, current_context, requires

DEFAULT_ROTTING_DAYS = 14
CLOSING_WINDOW_DAYS = 30


def _period(start: date | None, end: date | None) -> tuple[datetime, datetime]:
    """Inclusive calendar window as UTC timestamps; default = the last 90 days."""
    today = date.today()
    first = start or (today - timedelta(days=90))
    last = end or today
    if last < first:
        raise HTTPException(status_code=422, detail="end must not be before start")
    return (
        datetime.combine(first, datetime.min.time(), tzinfo=UTC),
        datetime.combine(last + timedelta(days=1), datetime.min.time(), tzinfo=UTC),
    )


def _money(value: Decimal | None) -> str:
    return str((value or Decimal("0")).quantize(Decimal("0.01")))


async def _rotting_days(module: NovvusModule, org_id: UUID) -> int:
    try:
        config = await module.config(org_id)
    except Exception:  # offline or kernel hiccup: the default is documented
        return DEFAULT_ROTTING_DAYS
    try:
        return max(1, int(config.get("crm.rotting_days", DEFAULT_ROTTING_DAYS)))
    except (TypeError, ValueError):
        return DEFAULT_ROTTING_DAYS


async def _open_rows(
    session: AsyncSession, owner: UUID | None = None, pipeline: UUID | None = None
) -> list[tuple[Opportunity, int]]:
    """Open opportunities with their effective probability."""
    query = (
        select(Opportunity, Stage.probability)
        .join(Stage, Stage.id == Opportunity.stage_id)
        .where(Opportunity.is_won.is_(None), Opportunity.deleted_at.is_(None))
    )
    if owner is not None:
        query = query.where(Opportunity.owner_user_id == owner)
    if pipeline is not None:
        query = query.where(Opportunity.pipeline_id == pipeline)
    rows = (await session.execute(query)).all()
    return [
        (row[0], row[0].probability if row[0].probability is not None else int(row[1] or 0))
        for row in rows
    ]


def weighted_forecast(rows: list[tuple[Opportunity, int]]) -> dict[str, Decimal]:
    totals: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    for opportunity, probability in rows:
        totals[opportunity.currency] += opportunity.amount * Decimal(probability) / Decimal(100)
    return dict(totals)


def pipeline_value(rows: list[tuple[Opportunity, int]]) -> dict[str, Decimal]:
    totals: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    for opportunity, _probability in rows:
        totals[opportunity.currency] += opportunity.amount
    return dict(totals)


def _per_currency(totals: dict[str, Decimal]) -> str:
    if not totals:
        return "0.00"
    return " · ".join(f"{_money(value)} {currency}" for currency, value in sorted(totals.items()))


async def overview(module: NovvusModule, session: AsyncSession) -> dict[str, Any]:
    """`views.dashboard` payload (docs/VIEWS.md): metrics, recent, queues, distribution."""
    context = current_context()
    now = datetime.now(tz=UTC)
    rotting = await _rotting_days(module, context.org_id)
    open_rows = await _open_rows(session)
    forecast = weighted_forecast(open_rows)
    value = pipeline_value(open_rows)

    period_start, period_end = _period(None, None)
    closed = (
        await session.execute(
            select(Opportunity.is_won, func.count(), func.coalesce(func.sum(Opportunity.amount), 0))
            .where(
                Opportunity.is_won.is_not(None),
                Opportunity.closed_at >= period_start,
                Opportunity.closed_at < period_end,
                Opportunity.deleted_at.is_(None),
            )
            .group_by(Opportunity.is_won)
        )
    ).all()
    won = next(((c, a) for w, c, a in closed if w), (0, Decimal("0")))
    lost = next(((c, a) for w, c, a in closed if not w), (0, Decimal("0")))
    decided = won[0] + lost[0]
    conversion = round(won[0] / decided * 100, 1) if decided else None

    soon_limit = (now + timedelta(days=CLOSING_WINDOW_DAYS)).date()
    closing_soon = sorted(
        (
            o
            for o, _p in open_rows
            if o.expected_close_date is not None and o.expected_close_date <= soon_limit
        ),
        key=lambda o: (o.expected_close_date, o.name),
    )
    stale_before = now - timedelta(days=rotting)

    def _naive(value: datetime | None) -> datetime | None:
        if value is None:
            return None
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)

    stalled = sorted(
        (
            o
            for o, _p in open_rows
            if (_naive(o.last_activity_at) or _naive(o.updated_at) or now) < stale_before
        ),
        key=lambda o: _naive(o.last_activity_at) or _naive(o.updated_at) or now,
    )

    pending_activities = (
        await session.scalars(
            select(Activity)
            .where(Activity.status == ActivityStatus.pending, Activity.deleted_at.is_(None))
            .order_by(Activity.due_date.asc().nulls_last(), Activity.created_at.asc())
        )
    ).all()
    overdue = [a for a in pending_activities if a.due_date is not None and _naive(a.due_date) < now]

    stage_rows = (
        await session.execute(
            select(
                Stage.name, Stage.position, Stage.is_won, Stage.is_lost, func.count(Opportunity.id)
            )
            .join(Opportunity, Opportunity.stage_id == Stage.id)
            .where(
                Opportunity.deleted_at.is_(None),
                Opportunity.is_won.is_(None),
                Stage.deleted_at.is_(None),
            )
            .group_by(Stage.id, Stage.name, Stage.position, Stage.is_won, Stage.is_lost)
            .order_by(Stage.position)
        )
    ).all()
    new_leads = await session.scalar(
        select(func.count(Lead.id)).where(
            Lead.status.in_((LeadStatus.new, LeadStatus.contacted)), Lead.deleted_at.is_(None)
        )
    )

    def metric(label: str, value: Any, description: str, tone: str = "neutral") -> dict[str, Any]:
        return {"label": label, "value": value, "description": description, "tone": tone}

    def item(o: Opportunity, label: str, tone: str, subtitle: str | None = None) -> dict[str, Any]:
        return {
            "id": str(o.id),
            "title": o.name,
            "subtitle": subtitle or f"{_money(o.amount)} {o.currency}",
            "path": f"opportunities/{o.id}",
            "status": {"label": label, "tone": tone},
            "updated_at": (_naive(o.updated_at) or now).isoformat(),
        }

    return {
        "generated_at": now.isoformat(),
        "metrics": [
            metric(
                "Oportunidades abiertas",
                len(open_rows),
                f"Valor del pipeline: {_per_currency(value)}",
                "info",
            ),
            metric(
                "Pronóstico ponderado",
                _per_currency(forecast),
                "Σ valor x probabilidad de las abiertas",
                "info",
            ),
            metric("Ganadas (90 días)", won[0], f"{_money(won[1])} en ventas cerradas", "success"),
            metric("Perdidas (90 días)", lost[0], f"{_money(lost[1])} perdidos", "danger"),
            metric(
                "Tasa de conversión",
                f"{conversion} %" if conversion is not None else "—",
                "Ganadas entre las decididas en 90 días",
                "success" if (conversion or 0) >= 50 else "warning",
            ),
            metric(
                "Actividades pendientes",
                len(pending_activities),
                f"{len(overdue)} vencidas",
                "danger" if overdue else "neutral",
            ),
            metric(
                "Prospectos por atender",
                int(new_leads or 0),
                "Nuevos o contactados sin calificar",
                "warning" if new_leads else "neutral",
            ),
        ],
        "recent": {
            "title": "Oportunidades próximas a cerrar",
            "description": f"Cierre estimado en los próximos {CLOSING_WINDOW_DAYS} días",
            "path": "opportunities",
            "empty": "Ninguna oportunidad abierta cierra en el periodo.",
            "items": [
                item(
                    o,
                    f"Cierra {o.expected_close_date.isoformat()}",
                    "warning" if o.expected_close_date < now.date() else "info",
                )
                for o in closing_soon[:8]
            ],
        },
        "queues": [
            {
                "title": "Oportunidades estancadas",
                "description": f"Sin actividad en más de {rotting} días",
                "tone": "danger",
                "empty": "Ninguna oportunidad abierta está estancada.",
                "total": len(stalled),
                "items": [item(o, "Estancada", "danger") for o in stalled[:5]],
            },
            {
                "title": "Actividades vencidas",
                "description": "Pendientes cuya fecha ya pasó, las más antiguas primero",
                "tone": "warning",
                "empty": "No hay actividades vencidas.",
                "total": len(overdue),
                "items": [
                    {
                        "id": str(a.id),
                        "title": a.title,
                        "subtitle": f"Vencía {a.due_date.date().isoformat()}",
                        "path": f"activities/{a.id}",
                        "status": {"label": "Vencida", "tone": "warning"},
                        "updated_at": (_naive(a.updated_at) or now).isoformat(),
                    }
                    for a in overdue[:5]
                ],
            },
        ],
        "distribution": [
            {"label": name, "value": count, "tone": "info"}
            for name, _pos, _w, _l, count in stage_rows
        ],
    }


def register(module: NovvusModule) -> None:
    router = module.router
    SessionDep = Annotated[AsyncSession, Depends(module.session_dependency())]

    @router.get("/reports/dashboard")
    @requires("crm.opportunities.read")
    async def dashboard(session: SessionDep) -> dict[str, Any]:
        return await overview(module, session)

    @router.get("/reports/sales")
    @requires("crm.reports.read")
    async def sales(
        session: SessionDep,
        start: date | None = None,
        end: date | None = None,
        owner_user_id: UUID | None = None,
        pipeline_id: UUID | None = None,
    ) -> dict[str, Any]:
        """Won/lost by owner in the period, with average duration and loss reasons."""
        period_start, period_end = _period(start, end)
        query = select(Opportunity).where(
            Opportunity.is_won.is_not(None),
            Opportunity.closed_at >= period_start,
            Opportunity.closed_at < period_end,
            Opportunity.deleted_at.is_(None),
        )
        if owner_user_id is not None:
            query = query.where(Opportunity.owner_user_id == owner_user_id)
        if pipeline_id is not None:
            query = query.where(Opportunity.pipeline_id == pipeline_id)
        rows = (await session.scalars(query)).all()
        reasons = {
            r.id: r.name
            for r in (
                await session.scalars(select(LostReason).where(LostReason.deleted_at.is_(None)))
            ).all()
        }
        by_owner: dict[str, dict[str, Any]] = {}
        durations: list[float] = []
        lost_by_reason: dict[str, int] = defaultdict(int)
        won_total: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
        lost_total: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
        for o in rows:
            key = str(o.owner_user_id) if o.owner_user_id else ""
            bucket = by_owner.setdefault(
                key, {"owner_user_id": key or None, "won": 0, "lost": 0, "won_amount": Decimal("0")}
            )
            if o.is_won:
                bucket["won"] += 1
                bucket["won_amount"] += o.amount
                won_total[o.currency] += o.amount
            else:
                bucket["lost"] += 1
                lost_total[o.currency] += o.amount
                lost_by_reason[
                    reasons.get(o.lost_reason_id, "Sin motivo")
                    if o.lost_reason_id
                    else "Sin motivo"
                ] += 1
            if o.closed_at and o.created_at:
                closed = o.closed_at if o.closed_at.tzinfo else o.closed_at.replace(tzinfo=UTC)
                durations.append((closed - o.created_at).total_seconds() / 86400)
        won = sum(b["won"] for b in by_owner.values())
        lost = sum(b["lost"] for b in by_owner.values())
        return {
            "start": period_start.date().isoformat(),
            "end": (period_end - timedelta(days=1)).date().isoformat(),
            "won": won,
            "lost": lost,
            "conversion_rate": round(won / (won + lost), 4) if (won + lost) else 0.0,
            "won_amount": {c: _money(v) for c, v in won_total.items()},
            "lost_amount": {c: _money(v) for c, v in lost_total.items()},
            "average_duration_days": round(sum(durations) / len(durations), 1)
            if durations
            else None,
            "by_owner": [
                {**b, "won_amount": _money(b["won_amount"])}
                for b in sorted(
                    by_owner.values(), key=lambda b: (-b["won"], b["owner_user_id"] or "")
                )
            ],
            "lost_reasons": [
                {"reason": reason, "count": count}
                for reason, count in sorted(lost_by_reason.items(), key=lambda kv: (-kv[1], kv[0]))
            ],
        }

    @router.get("/reports/forecast")
    @requires("crm.reports.read")
    async def forecast(
        session: SessionDep, owner_user_id: UUID | None = None, pipeline_id: UUID | None = None
    ) -> dict[str, Any]:
        """Open pipeline by stage and owner with the weighted forecast."""
        rows = await _open_rows(session, owner_user_id, pipeline_id)
        stages = {
            s.id: s
            for s in (await session.scalars(select(Stage).where(Stage.deleted_at.is_(None)))).all()
        }
        by_stage: dict[UUID, dict[str, Any]] = {}
        by_owner: dict[str, dict[str, Any]] = {}
        for o, probability in rows:
            stage = stages.get(o.stage_id)
            bucket = by_stage.setdefault(
                o.stage_id,
                {
                    "stage_id": str(o.stage_id),
                    "stage": stage.name if stage else "",
                    "position": stage.position if stage else 0,
                    "count": 0,
                    "amount": Decimal("0"),
                    "weighted": Decimal("0"),
                },
            )
            bucket["count"] += 1
            bucket["amount"] += o.amount
            bucket["weighted"] += o.amount * Decimal(probability) / Decimal(100)
            key = str(o.owner_user_id) if o.owner_user_id else ""
            owner = by_owner.setdefault(
                key,
                {
                    "owner_user_id": key or None,
                    "count": 0,
                    "amount": Decimal("0"),
                    "weighted": Decimal("0"),
                },
            )
            owner["count"] += 1
            owner["amount"] += o.amount
            owner["weighted"] += o.amount * Decimal(probability) / Decimal(100)
        return {
            "open_count": len(rows),
            "pipeline_value": {c: _money(v) for c, v in pipeline_value(rows).items()},
            "weighted_forecast": {c: _money(v) for c, v in weighted_forecast(rows).items()},
            "by_stage": [
                {**b, "amount": _money(b["amount"]), "weighted": _money(b["weighted"])}
                for b in sorted(by_stage.values(), key=lambda b: b["position"])
            ],
            "by_owner": [
                {**b, "amount": _money(b["amount"]), "weighted": _money(b["weighted"])}
                for b in sorted(
                    by_owner.values(), key=lambda b: (-b["count"], b["owner_user_id"] or "")
                )
            ],
        }

    @router.get("/reports/activities")
    @requires("crm.reports.read")
    async def activities(session: SessionDep, owner_user_id: UUID | None = None) -> dict[str, Any]:
        """Pending and overdue activities by owner and type."""
        now = datetime.now(tz=UTC)
        query = select(Activity).where(
            Activity.status == ActivityStatus.pending, Activity.deleted_at.is_(None)
        )
        if owner_user_id is not None:
            query = query.where(Activity.assigned_user_id == owner_user_id)
        rows = (await session.scalars(query)).all()
        by_type: dict[str, dict[str, int]] = defaultdict(lambda: {"pending": 0, "overdue": 0})
        by_owner: dict[str, dict[str, Any]] = {}
        for a in rows:
            due = (
                a.due_date
                if a.due_date is None or a.due_date.tzinfo
                else a.due_date.replace(tzinfo=UTC)
            )
            overdue = due is not None and due < now
            by_type[a.type.value]["pending"] += 1
            key = str(a.assigned_user_id) if a.assigned_user_id else ""
            owner = by_owner.setdefault(
                key, {"owner_user_id": key or None, "pending": 0, "overdue": 0}
            )
            owner["pending"] += 1
            if overdue:
                by_type[a.type.value]["overdue"] += 1
                owner["overdue"] += 1
        return {
            "pending": len(rows),
            "overdue": sum(b["overdue"] for b in by_owner.values()),
            "by_type": [{"type": t, **counts} for t, counts in sorted(by_type.items())],
            "by_owner": sorted(by_owner.values(), key=lambda b: (-b["overdue"], -b["pending"])),
        }

    @router.get("/reports/pipelines")
    @requires("crm.reports.read")
    async def pipelines(session: SessionDep) -> list[dict[str, Any]]:
        """Filter options for the reports (pipelines of the organization)."""
        rows = (
            await session.scalars(
                select(Pipeline).where(Pipeline.deleted_at.is_(None)).order_by(Pipeline.name)
            )
        ).all()
        return [{"id": str(p.id), "name": p.name, "is_default": p.is_default} for p in rows]

    @router.get("/reports/export/{entity}")
    @requires("crm.reports.read")
    async def export(entity: str, session: SessionDep) -> Any:
        from fastapi.responses import PlainTextResponse
        import csv, io
        model_map = {
            "companies": (Company, ["id", "name", "kind", "status", "email", "phone", "city", "country"]),
            "contacts": (Contact, ["id", "name", "email", "phone", "job_title", "kind", "status"]),
            "leads": (Lead, ["id", "title", "status", "source", "estimated_value", "currency"]),
            "opportunities": (Opportunity, ["id", "name", "amount", "currency", "priority", "expected_close_date", "is_won"]),
            "activities": (Activity, ["id", "title", "type", "status", "priority", "due_date"]),
        }
        if entity not in model_map:
            raise HTTPException(status_code=404, detail="entity not found")
        model, cols = model_map[entity]
        rows = (await session.scalars(select(model).where(model.deleted_at.is_(None)))).all()
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(cols)
        for r in rows:
            w.writerow([getattr(r, c, "") for c in cols])
        return PlainTextResponse(buf.getvalue(), media_type="text/csv", headers={"Content-Disposition": f"attachment; filename={entity}.csv"})
