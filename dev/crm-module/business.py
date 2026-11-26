"""CRM business rules: custom endpoints beyond the auto-generated CRUD.

Registered on the module router (prefix /api/crm). Events are emitted after
the write is flushed; the kernel bus is the source of truth for delivery.
"""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Annotated, Any
from uuid import UUID

from fastapi import Depends, HTTPException
from models import (
    Contact,
    ContactTag,
    Lead,
    LeadSource,
    LeadStatus,
    Opportunity,
    OpportunityStageLog,
    OpportunityTag,
    Pipeline,
    Priority,
    Stage,
    Tag,
)
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from novvus_sdk import NovvusModule, current_context, requires


class LeadCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: LeadSource = LeadSource.manual
    contact_id: UUID | None = None
    company_id: UUID | None = None
    notes: str = ""


class ConvertLead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    amount: Decimal = Decimal("0")
    currency: str = "MXN"
    pipeline_id: UUID | None = None
    expected_close_date: date | None = None
    priority: Priority = Priority.medium


class MoveOpportunity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stage_id: UUID


async def change_stage(
    module: NovvusModule,
    session: AsyncSession,
    opportunity: Opportunity,
    stage: Stage,
    note: str = "",
) -> Opportunity:
    """The one place an opportunity changes stage (endpoint, kanban action, conversions):
    validates the pipeline, settles won/lost, appends the stage log and emits the events."""
    if stage.pipeline_id != opportunity.pipeline_id:
        raise HTTPException(status_code=422, detail="stage belongs to a different pipeline")
    context = current_context()
    previous_stage_id = opportunity.stage_id
    opportunity.stage_id = stage.id
    if stage.is_won:
        opportunity.is_won = True
        opportunity.closed_at = datetime.now(tz=UTC)
    elif stage.is_lost:
        opportunity.is_won = False
        opportunity.closed_at = datetime.now(tz=UTC)
    else:
        opportunity.is_won = None
        opportunity.closed_at = None
    if previous_stage_id != stage.id:
        session.add(
            OpportunityStageLog(
                org_id=context.org_id,
                opportunity_id=opportunity.id,
                from_stage_id=previous_stage_id,
                to_stage_id=stage.id,
                user_id=context.user_id,
                note=note[:1000],
            )
        )
    await session.flush()
    await session.refresh(opportunity)

    base_payload = {
        "opportunity_id": str(opportunity.id),
        "name": opportunity.name,
        "from_stage_id": str(previous_stage_id),
        "to_stage_id": str(stage.id),
        "amount": str(opportunity.amount),
        "currency": opportunity.currency,
        # References other modules resolve via the CRM's public API.
        "contact_id": str(opportunity.contact_id) if opportunity.contact_id else None,
        "company_id": str(opportunity.company_id) if opportunity.company_id else None,
    }
    await module.emit("crm.opportunity.stage_changed", base_payload)
    if stage.is_won:
        await module.emit("crm.opportunity.won", base_payload)
    elif stage.is_lost:
        await module.emit("crm.opportunity.lost", base_payload)
    return opportunity


async def _get_or_404(session: AsyncSession, model: type, item_id: UUID, name: str) -> Any:
    row = await session.scalar(select(model).where(model.id == item_id, model.deleted_at.is_(None)))
    if row is None:
        raise HTTPException(status_code=404, detail=f"{name} not found")
    return row


def register(module: NovvusModule) -> None:
    router = module.router
    session_dep = module.session_dependency()
    SessionDep = Annotated[AsyncSession, Depends(session_dep)]

    # ------------------------------------------------------------------
    # Leads: creation (emits crm.lead.created) and conversion
    # ------------------------------------------------------------------

    @router.post("/leads", status_code=201)
    @requires("crm.leads.write")
    async def create_lead(payload: LeadCreate, session: SessionDep) -> dict[str, Any]:
        context = current_context()
        lead = Lead(org_id=context.org_id, **payload.model_dump())
        session.add(lead)
        await session.flush()
        await session.refresh(lead)
        await module.emit(
            "crm.lead.created",
            {"lead_id": str(lead.id), "source": lead.source.value},
        )
        return _serialize(lead)

    @router.post("/leads/{lead_id}/convert", status_code=201)
    @requires("crm.leads.write")
    async def convert_lead(
        lead_id: UUID, payload: ConvertLead, session: SessionDep
    ) -> dict[str, Any]:
        from directory import convert_lead as convert  # local: directory imports change_stage

        context = current_context()
        lead: Lead = await _get_or_404(session, Lead, lead_id, "lead")
        opportunity = await convert(
            module,
            session,
            lead,
            name=payload.name,
            amount=payload.amount,
            currency=payload.currency,
            pipeline_id=payload.pipeline_id,
            expected_close_date=payload.expected_close_date,
            priority=payload.priority,
            org_id=context.org_id,
            user_id=context.user_id,
        )
        return _serialize(opportunity)

    # ------------------------------------------------------------------
    # Opportunities: stage movement, won/lost
    # ------------------------------------------------------------------

    @router.post("/opportunities/{opportunity_id}/move")
    @requires("crm.opportunities.write")
    async def move_opportunity(
        opportunity_id: UUID, payload: MoveOpportunity, session: SessionDep
    ) -> dict[str, Any]:
        opportunity: Opportunity = await _get_or_404(
            session, Opportunity, opportunity_id, "opportunity"
        )
        stage: Stage = await _get_or_404(session, Stage, payload.stage_id, "stage")
        await change_stage(module, session, opportunity, stage)
        return _serialize(opportunity)

    # §8j: the kanban drops (and the «Mover de etapa» button) run this action.
    @module.action(Opportunity, "move")
    async def move_action(
        session: AsyncSession, ctx: Any, opportunity: Opportunity, body: dict[str, Any]
    ) -> dict[str, Any]:
        try:
            stage_id = UUID(str(body.get("stage_id") or ""))
        except ValueError as error:
            raise HTTPException(status_code=422, detail="stage_id must be a stage") from error
        stage: Stage = await _get_or_404(session, Stage, stage_id, "stage")
        await change_stage(module, session, opportunity, stage, note=str(body.get("note") or ""))
        return {"message": module._("Movida a {stage}").format(stage=stage.name)}

    @module.action_options(Opportunity, "move")
    async def move_options(
        session: AsyncSession, ctx: Any, opportunity: Opportunity, body: dict[str, Any]
    ) -> dict[str, Any]:
        rows = (
            await session.scalars(
                select(Stage)
                .where(Stage.pipeline_id == opportunity.pipeline_id, Stage.deleted_at.is_(None))
                .order_by(Stage.position)
            )
        ).all()
        return {
            "stage_id": [
                {
                    "value": str(stage.id),
                    "label": stage.name,
                    "description": f"{stage.probability} %"
                    + (" · ganada" if stage.is_won else " · perdida" if stage.is_lost else ""),
                }
                for stage in rows
            ]
        }

    # ------------------------------------------------------------------
    # Activities
    # ------------------------------------------------------------------

    @router.post("/activities/{activity_id}/complete")
    @requires("crm.activities.write")
    async def complete_activity(activity_id: UUID, session: SessionDep) -> dict[str, Any]:
        from models import Activity, ActivityStatus

        activity: Activity = await _get_or_404(session, Activity, activity_id, "activity")
        if activity.status == ActivityStatus.done:
            return _serialize(activity)
        activity.status = ActivityStatus.done
        activity.completed_at = datetime.now(tz=UTC)
        await session.flush()
        await session.refresh(activity)
        await module.emit(
            "crm.activity.completed",
            {"activity_id": str(activity.id), "type": activity.type.value},
        )
        return _serialize(activity)

    # ------------------------------------------------------------------
    # Tags (M2M helpers)
    # ------------------------------------------------------------------

    def _tag_endpoints(
        parent_name: str,
        parent_model: type,
        link_model: type,
        link_field: str,
        perm_read: str,
        perm_write: str,
    ) -> None:
        @router.get(f"/{parent_name}/{{item_id}}/tags")
        @requires(perm_read)
        async def list_tags(item_id: UUID, session: SessionDep) -> list[dict[str, Any]]:
            await _get_or_404(session, parent_model, item_id, parent_name)
            rows = (
                await session.scalars(
                    select(Tag)
                    .join(link_model, link_model.tag_id == Tag.id)
                    .where(getattr(link_model, link_field) == item_id, Tag.deleted_at.is_(None))
                    .order_by(Tag.name)
                )
            ).all()
            return [_serialize(t) for t in rows]

        @router.post(f"/{parent_name}/{{item_id}}/tags/{{tag_id}}", status_code=204)
        @requires(perm_write)
        async def add_tag(item_id: UUID, tag_id: UUID, session: SessionDep) -> None:
            context = current_context()
            await _get_or_404(session, parent_model, item_id, parent_name)
            await _get_or_404(session, Tag, tag_id, "tag")
            exists = await session.scalar(
                select(link_model).where(
                    getattr(link_model, link_field) == item_id, link_model.tag_id == tag_id
                )
            )
            if exists is None:
                session.add(
                    link_model(org_id=context.org_id, **{link_field: item_id, "tag_id": tag_id})
                )
                await session.flush()

        @router.delete(f"/{parent_name}/{{item_id}}/tags/{{tag_id}}", status_code=204)
        @requires(perm_write)
        async def remove_tag(item_id: UUID, tag_id: UUID, session: SessionDep) -> None:
            link = await session.scalar(
                select(link_model).where(
                    getattr(link_model, link_field) == item_id, link_model.tag_id == tag_id
                )
            )
            if link is not None:
                await session.delete(link)
                await session.flush()

    _tag_endpoints(
        "contacts", Contact, ContactTag, "contact_id", "crm.contacts.read", "crm.contacts.write"
    )
    _tag_endpoints(
        "opportunities",
        Opportunity,
        OpportunityTag,
        "opportunity_id",
        "crm.opportunities.read",
        "crm.opportunities.write",
    )

    # ------------------------------------------------------------------
    # Reports
    # ------------------------------------------------------------------

    @router.get("/reports/pipeline")
    @requires("crm.reports.read")
    async def pipeline_report(
        session: SessionDep, pipeline_id: UUID | None = None
    ) -> dict[str, Any]:
        if pipeline_id is not None:
            pipeline: Pipeline = await _get_or_404(session, Pipeline, pipeline_id, "pipeline")
        else:
            pipeline = await session.scalar(
                select(Pipeline).where(Pipeline.is_default, Pipeline.deleted_at.is_(None))
            )
            if pipeline is None:
                raise HTTPException(status_code=422, detail="no default pipeline")

        rows = (
            await session.execute(
                select(
                    Stage.id,
                    Stage.name,
                    Stage.position,
                    Stage.probability,
                    Stage.is_won,
                    Stage.is_lost,
                    func.count(Opportunity.id),
                    func.coalesce(func.sum(Opportunity.amount), 0),
                )
                .outerjoin(
                    Opportunity,
                    (Opportunity.stage_id == Stage.id) & Opportunity.deleted_at.is_(None),
                )
                .where(Stage.pipeline_id == pipeline.id, Stage.deleted_at.is_(None))
                .group_by(Stage.id)
                .order_by(Stage.position)
            )
        ).all()

        stages = [
            {
                "stage_id": str(row[0]),
                "name": row[1],
                "position": row[2],
                "probability": row[3],
                "is_won": row[4],
                "is_lost": row[5],
                "count": row[6],
                "total_amount": str(row[7]),
            }
            for row in rows
        ]
        return {
            "pipeline_id": str(pipeline.id),
            "pipeline_name": pipeline.name,
            "stages": stages,
            "open_count": sum(s["count"] for s in stages if not s["is_won"] and not s["is_lost"]),
            "won_count": sum(s["count"] for s in stages if s["is_won"]),
            "lost_count": sum(s["count"] for s in stages if s["is_lost"]),
        }

    @router.get("/reports/conversion")
    @requires("crm.reports.read")
    async def conversion_report(session: SessionDep, start: date, end: date) -> dict[str, Any]:
        # Inclusive calendar window: `end` is the LAST day counted. The column
        # is a UTC timestamp, so the upper bound is end + 1 day (exclusive) —
        # with an exclusive `end`, callers west of UTC lose the evening hours
        # of their last day (a lead created at 22:00 local is already
        # "tomorrow" in UTC and fell outside the window).
        if end < start:
            raise HTTPException(status_code=422, detail="end must not be before start")
        totals = (
            await session.execute(
                select(
                    func.count(Lead.id),
                    func.count(Lead.id).filter(Lead.status == LeadStatus.converted),
                    func.count(Lead.id).filter(Lead.status == LeadStatus.lost),
                ).where(
                    Lead.created_at >= start,
                    Lead.created_at < end + timedelta(days=1),
                    Lead.deleted_at.is_(None),
                )
            )
        ).one()
        total, converted, lost = totals
        return {
            "start": start.isoformat(),
            "end": end.isoformat(),
            "leads": total,
            "converted": converted,
            "lost": lost,
            "conversion_rate": round(converted / total, 4) if total else 0.0,
        }


def _serialize(instance: Any) -> dict[str, Any]:
    """JSON-safe dict of a model row (mirrors the auto-API read output)."""
    result: dict[str, Any] = {}
    for key, value in instance.as_dict().items():
        if isinstance(value, UUID | Decimal):
            result[key] = str(value)
        elif isinstance(value, datetime | date):
            result[key] = value.isoformat()
        elif hasattr(value, "value"):  # StrEnum
            result[key] = value.value
        else:
            result[key] = value
    return result
