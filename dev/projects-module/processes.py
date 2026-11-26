"""Processes: configurable workflows inside a project with validated stage
transitions and the stage inspector (`views.process`, docs/VIEWS.md).

A process owns an ordered list of stages. Advancing closes the current stage
and activates the next one; the rule refuses to advance when the stage demands
an approval that is not granted, when it asks for evidence and none is given,
or when it is mandatory and someone tries to skip it without the permission to
decide approvals. Every move is written to `process_transitions` (append-only)
with `forced=True` when a stage was skipped. Starting, advancing and finishing
also keep the project's progress and health current (business.touch).
"""

from datetime import UTC, date, datetime
from typing import Annotated, Any
from uuid import UUID

import business
from fastapi import Depends, HTTPException
from models import (
    Approval,
    ApprovalStatus,
    ApprovalTarget,
    Process,
    ProcessStage,
    ProcessStatus,
    ProcessTransition,
    StageStatus,
    Task,
    TaskStatus,
)
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from novvus_sdk import NovvusModule, current_context, requires

INSPECTOR_KEYS = ("pending", "running", "done")


async def stages_of(session: AsyncSession, process_id: UUID) -> list[ProcessStage]:
    return list(
        (
            await session.scalars(
                select(ProcessStage)
                .where(ProcessStage.process_id == process_id, ProcessStage.deleted_at.is_(None))
                .order_by(ProcessStage.position, ProcessStage.created_at)
            )
        ).all()
    )


def current_of(stages: list[ProcessStage], process: Process) -> ProcessStage | None:
    return next((s for s in stages if s.id == process.current_stage_id), None)


def next_of(stages: list[ProcessStage], current: ProcessStage | None) -> ProcessStage | None:
    if current is None:
        return stages[0] if stages else None
    after = [
        s
        for s in stages
        if s.position > current.position
        or (s.position == current.position and s.created_at > current.created_at)
    ]
    return after[0] if after else None


async def approved(session: AsyncSession, stage: ProcessStage) -> bool:
    row = await session.scalar(
        select(Approval).where(
            Approval.target_kind == ApprovalTarget.stage,
            Approval.target_id == stage.id,
            Approval.status == ApprovalStatus.approved,
            Approval.deleted_at.is_(None),
        )
    )
    return row is not None


async def pending_approval(session: AsyncSession, stage: ProcessStage) -> Approval | None:
    return await session.scalar(
        select(Approval).where(
            Approval.target_kind == ApprovalTarget.stage,
            Approval.target_id == stage.id,
            Approval.status == ApprovalStatus.pending,
            Approval.deleted_at.is_(None),
        )
    )


async def open_tasks_of_stage(session: AsyncSession, stage: ProcessStage) -> int:
    return int(
        await session.scalar(
            select(func.count(Task.id)).where(
                Task.stage_id == stage.id,
                Task.status.in_(business.OPEN_TASK),
                Task.deleted_at.is_(None),
            )
        )
        or 0
    )


async def _log(
    session: AsyncSession,
    process: Process,
    from_stage: ProcessStage | None,
    to_stage: ProcessStage | None,
    note: str,
    forced: bool = False,
) -> None:
    context = current_context()
    session.add(
        ProcessTransition(
            org_id=context.org_id,
            process_id=process.id,
            from_stage_id=from_stage.id if from_stage else None,
            to_stage_id=to_stage.id if to_stage else None,
            user_id=context.user_id,
            forced=forced,
            note=note[:2000],
        )
    )


async def _enter(session: AsyncSession, process: Process, stage: ProcessStage | None) -> None:
    """Activate `stage`, or finish the process when there is no stage left."""
    now = datetime.now(tz=UTC)
    if stage is None:
        process.current_stage_id = None
        process.status = ProcessStatus.done
    else:
        stage.status = StageStatus.active
        stage.started_at = now
        process.current_stage_id = stage.id
        process.status = ProcessStatus.running
    await session.flush()


async def blockers(session: AsyncSession, stage: ProcessStage, note: str) -> list[str]:
    """Why the current stage cannot be closed yet (empty = it can)."""
    reasons: list[str] = []
    if stage.requires_approval and not await approved(session, stage):
        reasons.append("falta la aprobación de la etapa")
    if stage.required_evidence.strip() and not note.strip():
        reasons.append("indica la evidencia requerida: " + stage.required_evidence.strip()[:120])
    open_tasks = await open_tasks_of_stage(session, stage)
    if open_tasks:
        reasons.append(f"{open_tasks} actividades abiertas en la etapa")
    if stage.exit_conditions.strip() and not note.strip():
        reasons.append("confirma las condiciones de salida en la nota")
    return reasons


def register(module: NovvusModule) -> None:
    @module.action(Process, "start")
    async def start(
        session: AsyncSession, ctx: Any, process: Process, body: dict[str, Any]
    ) -> dict[str, Any]:
        if process.status != ProcessStatus.pending:
            raise HTTPException(status_code=409, detail="only a pending process starts")
        stages = await stages_of(session, process.id)
        if not stages:
            raise HTTPException(status_code=422, detail="add at least one stage before starting")
        first = stages[0]
        if process.start_date is None:
            process.start_date = date.today()
        await _enter(session, process, first)
        await _log(session, process, None, first, str(body.get("note") or ""))
        await business.touch(session, process.project_id)
        return {"message": module._("Proceso iniciado en «{stage}»").format(stage=first.name)}

    @module.action(Process, "advance")
    async def advance(
        session: AsyncSession, ctx: Any, process: Process, body: dict[str, Any]
    ) -> dict[str, Any]:
        if process.status != ProcessStatus.running:
            raise HTTPException(status_code=409, detail="the process is not running")
        stages = await stages_of(session, process.id)
        current = current_of(stages, process)
        if current is None:
            raise HTTPException(status_code=409, detail="the process has no active stage")
        note = str(body.get("note") or "")
        reasons = await blockers(session, current, note)
        if reasons:
            raise HTTPException(status_code=409, detail="; ".join(reasons))
        current.status = StageStatus.done
        current.finished_at = datetime.now(tz=UTC)
        following = next_of(stages, current)
        await _enter(session, process, following)
        await _log(session, process, current, following, note)
        await business.touch(session, process.project_id)
        if following is None:
            return {"message": module._("Proceso terminado")}
        return {"message": module._("Etapa «{stage}» en curso").format(stage=following.name)}

    @module.action_validator(Process, "advance")
    async def advance_validate(
        session: AsyncSession, ctx: Any, process: Process, body: dict[str, Any]
    ) -> dict[str, str]:
        if process.status != ProcessStatus.running:
            return {"note": "El proceso no está en ejecución"}
        stages = await stages_of(session, process.id)
        current = current_of(stages, process)
        if current is None:
            return {}
        reasons = await blockers(session, current, str(body.get("note") or ""))
        return {"note": "; ".join(reasons)} if reasons else {}

    @module.action(Process, "skip")
    async def skip(
        session: AsyncSession, ctx: Any, process: Process, body: dict[str, Any]
    ) -> dict[str, Any]:
        """Explicit authorization: the permission to decide approvals and a written reason."""
        if process.status != ProcessStatus.running:
            raise HTTPException(status_code=409, detail="the process is not running")
        note = str(body.get("note") or "").strip()
        if not note:
            raise HTTPException(
                status_code=422, detail={"note": "Indica por qué se omite la etapa"}
            )
        stages = await stages_of(session, process.id)
        current = current_of(stages, process)
        if current is None:
            raise HTTPException(status_code=409, detail="the process has no active stage")
        current.status = StageStatus.skipped
        current.finished_at = datetime.now(tz=UTC)
        following = next_of(stages, current)
        await _enter(session, process, following)
        await _log(session, process, current, following, note, forced=True)
        await business.touch(session, process.project_id)
        return {
            "message": module._("Etapa «{stage}» omitida con autorización").format(
                stage=current.name
            )
        }

    @module.action(Process, "request_approval")
    async def request_approval(
        session: AsyncSession, ctx: Any, process: Process, body: dict[str, Any]
    ) -> dict[str, Any]:
        stages = await stages_of(session, process.id)
        current = current_of(stages, process)
        if current is None:
            raise HTTPException(status_code=409, detail="the process has no active stage")
        if not current.requires_approval:
            raise HTTPException(status_code=409, detail="this stage does not require an approval")
        if await approved(session, current):
            raise HTTPException(status_code=409, detail="the stage is already approved")
        if await pending_approval(session, current) is not None:
            raise HTTPException(status_code=409, detail="an approval is already pending")
        approver = body.get("approver_user_id")
        session.add(
            Approval(
                org_id=ctx.org_id,
                project_id=process.project_id,
                target_kind=ApprovalTarget.stage,
                target_id=current.id,
                target_label=f"{process.name} · {current.name}"[:200],
                requested_by_user_id=ctx.user_id,
                approver_user_id=UUID(str(approver)) if approver else None,
            )
        )
        await session.flush()
        return {
            "message": module._("Aprobación solicitada para «{stage}»").format(stage=current.name)
        }

    @module.action(Process, "cancel")
    async def cancel(
        session: AsyncSession, ctx: Any, process: Process, body: dict[str, Any]
    ) -> dict[str, Any]:
        if process.status == ProcessStatus.done:
            raise HTTPException(status_code=409, detail="a finished process is not cancelled")
        stages = await stages_of(session, process.id)
        current = current_of(stages, process)
        process.status = ProcessStatus.cancelled
        process.current_stage_id = None
        await _log(session, process, current, None, str(body.get("note") or "cancelado"))
        await session.flush()
        return {"message": module._("Proceso cancelado")}

    # ---- stage inspector (views.process) ---------------------------------------
    session_dep = module.session_dependency()
    SessionDep = Annotated[AsyncSession, Depends(session_dep)]

    @module.router.get("/processes/{process_id}/process")
    @requires("projects.projects.read")
    async def inspector(
        process_id: UUID, session: SessionDep, stage: str | None = None
    ) -> dict[str, Any]:
        process = await session.scalar(
            select(Process).where(Process.id == process_id, Process.deleted_at.is_(None))
        )
        if process is None:
            raise HTTPException(status_code=404, detail="process not found")
        return await inspect(session, process)


async def inspect(session: AsyncSession, process: Process) -> dict[str, Any]:
    """The contract of docs/VIEWS.md «Inspector de etapas»: the three status steps of the
    process carry the dynamic stages as panels, so the shell never guesses the workflow."""
    stages = await stages_of(session, process.id)
    current = current_of(stages, process)
    transitions = (
        await session.scalars(
            select(ProcessTransition)
            .where(
                ProcessTransition.process_id == process.id, ProcessTransition.deleted_at.is_(None)
            )
            .order_by(ProcessTransition.created_at)
        )
    ).all()
    by_id = {s.id: s for s in stages}
    status = process.status.value
    state = {"pending": "pending", "running": "running", "done": "done", "cancelled": "attention"}[
        status
    ]
    step_state = {
        "pending": "done" if status != "pending" else "running",
        "running": {
            "pending": "pending",
            "running": "running",
            "done": "done",
            "cancelled": "attention",
        }[status],
        "done": "done"
        if status == "done"
        else ("attention" if status == "cancelled" else "pending"),
    }
    status_labels = {
        "pending": "pendiente",
        "active": "activa",
        "done": "terminada",
        "skipped": "omitida",
    }
    stage_rows = {
        f"{position + 1}. {s.name}": " · ".join(
            part
            for part in (
                status_labels.get(s.status.value, s.status.value),
                "obligatoria" if s.is_mandatory else "opcional",
                "requiere aprobación" if s.requires_approval else "",
                f"plazo {s.due_date.isoformat()}" if s.due_date else "",
                f"inicio {s.started_at.date().isoformat()}" if s.started_at else "",
                f"fin {s.finished_at.date().isoformat()}" if s.finished_at else "",
            )
            if part
        )
        for position, s in enumerate(stages)
    }
    panels: list[dict[str, Any]] = [
        {"label": "Etapas", "kind": "fields", "value": stage_rows or {"—": "Sin etapas definidas"}}
    ]
    if current is not None:
        reasons = await blockers(session, current, "")
        panels.append(
            {
                "label": f"Etapa actual: {current.name}",
                "kind": "fields",
                "value": {
                    "Responsable": str(current.owner_user_id) if current.owner_user_id else "—",
                    "Condiciones de entrada": current.entry_conditions or "—",
                    "Condiciones de salida": current.exit_conditions or "—",
                    "Evidencias requeridas": current.required_evidence or "—",
                    "Aprobación": ("aprobada" if await approved(session, current) else "pendiente")
                    if current.requires_approval
                    else "no requerida",
                    "Actividades abiertas": str(await open_tasks_of_stage(session, current)),
                    "Plazo": current.due_date.isoformat() if current.due_date else "—",
                    "Para avanzar": "; ".join(
                        r
                        for r in reasons
                        if not r.startswith("indica la evidencia") and not r.startswith("confirma")
                    )
                    or "listo",
                },
            }
        )
    history = {
        f"{t.created_at.strftime('%d/%m %H:%M')} · "
        f"{by_id[t.from_stage_id].name if t.from_stage_id in by_id else 'inicio'} → "
        f"{by_id[t.to_stage_id].name if t.to_stage_id in by_id else 'fin'}": (
            ("forzada · " if t.forced else "") + (t.note or "—")
        )
        for t in transitions
    }
    panels.append(
        {"label": "Historial", "kind": "fields", "value": history or {"—": "Sin transiciones"}}
    )
    overdue = (
        current is not None and current.due_date is not None and current.due_date < date.today()
    )
    skipped = len([s for s in stages if s.status == StageStatus.skipped])
    return {
        "state": "attention" if overdue else state,
        "stage": status if status != "cancelled" else "running",
        "updated_at": (process.updated_at or datetime.now(tz=UTC)).isoformat(),
        "steps": [
            {
                "key": "pending",
                "state": step_state["pending"],
                "message": "Proceso definido" if stages else "Sin etapas",
                "started_at": process.created_at.isoformat() if process.created_at else None,
                "finished_at": transitions[0].created_at.isoformat()
                if transitions and status != "pending"
                else None,
            },
            {
                "key": "running",
                "state": step_state["running"],
                "message": f"Etapa «{current.name}»" + (" · plazo vencido" if overdue else "")
                if current
                else ("Cancelado" if status == "cancelled" else "—"),
                "started_at": process.start_date.isoformat() if process.start_date else None,
                "finished_at": None,
            },
            {
                "key": "done",
                "state": step_state["done"],
                "message": "Terminado"
                if status == "done"
                else ("Cancelado" if status == "cancelled" else "Pendiente"),
                "started_at": None,
                "finished_at": transitions[-1].created_at.isoformat()
                if status == "done" and transitions
                else None,
            },
        ],
        "panels": panels,
        "note": (f"{skipped} etapas omitidas con autorización" if skipped else None),
        "document": None,
    }


__all__ = ["INSPECTOR_KEYS", "TaskStatus", "inspect", "register", "stages_of"]
