"""Project rules: lifecycle, creation from templates, task transitions,
dependencies without cycles, milestones, deliverables, approvals, risks and
the progress/health recomputation after every change. All as actions of the
generic views; permissions are checked by the SDK before the handlers run."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

import progress as engine
from fastapi import HTTPException
from models import (
    Approval,
    ApprovalStatus,
    ApprovalTarget,
    Deliverable,
    DeliverableStatus,
    DependencyKind,
    Health,
    Milestone,
    MilestoneStatus,
    Phase,
    PhaseStatus,
    Priority,
    Process,
    ProcessStage,
    ProgressStrategy,
    Project,
    ProjectKind,
    ProjectLink,
    ProjectStatus,
    Risk,
    RiskLevel,
    RiskStatus,
    Task,
    TaskDependency,
    TaskStatus,
    Template,
    TemplateDependency,
    TemplateMilestone,
    TemplatePhase,
    TemplateProcess,
    TemplateTask,
)
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from novvus_sdk import NovvusModule

OPEN_TASK = (TaskStatus.todo, TaskStatus.doing, TaskStatus.blocked, TaskStatus.review)
# Valid task transitions (from → to); `blocked` is entered/left through block/unblock.
TRANSITIONS: dict[TaskStatus, set[TaskStatus]] = {
    TaskStatus.todo: {TaskStatus.doing, TaskStatus.cancelled, TaskStatus.done},
    TaskStatus.doing: {TaskStatus.review, TaskStatus.done, TaskStatus.todo, TaskStatus.cancelled},
    TaskStatus.review: {TaskStatus.done, TaskStatus.doing, TaskStatus.cancelled},
    TaskStatus.done: {TaskStatus.doing},
    TaskStatus.blocked: set(),
    TaskStatus.cancelled: {TaskStatus.todo},
}


def _uuid(value: Any, field: str) -> UUID | None:
    if value in (None, ""):
        return None
    try:
        return UUID(str(value))
    except ValueError as error:
        raise HTTPException(
            status_code=422, detail={field: "Debe ser un registro válido"}
        ) from error


def _number(
    value: Any, field: str, *, minimum: Decimal | None = None, maximum: Decimal | None = None
) -> Decimal:
    try:
        number = Decimal(str(value if value not in (None, "") else "0"))
    except InvalidOperation as error:
        raise HTTPException(status_code=422, detail={field: "Debe ser un número"}) from error
    if minimum is not None and number < minimum:
        raise HTTPException(status_code=422, detail={field: f"Mínimo {minimum}"})
    if maximum is not None and number > maximum:
        raise HTTPException(status_code=422, detail={field: f"Máximo {maximum}"})
    return number


def _date(value: Any, field: str) -> date | None:
    if value in (None, ""):
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError as error:
        raise HTTPException(status_code=422, detail={field: "Fecha inválida"}) from error


def _enum(enum_cls: type, value: Any, default: Any) -> Any:
    if value in (None, ""):
        return default
    try:
        return enum_cls(str(value))
    except ValueError as error:
        raise HTTPException(status_code=422, detail=f"invalid value {value!r}") from error


async def _one(session: AsyncSession, model: type, item_id: UUID | None, name: str) -> Any:
    if item_id is None:
        return None
    row = await session.scalar(select(model).where(model.id == item_id, model.deleted_at.is_(None)))
    if row is None:
        raise HTTPException(status_code=404, detail=f"{name} not found")
    return row


async def _project_of(session: AsyncSession, project_id: UUID) -> Project:
    project = await _one(session, Project, project_id, "project")
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    return project


# ---------------------------------------------------------------------------
# Recomputation
# ---------------------------------------------------------------------------


async def _task_rows(session: AsyncSession, project_id: UUID) -> list[engine.TaskRow]:
    tasks = (
        await session.scalars(
            select(Task).where(Task.project_id == project_id, Task.deleted_at.is_(None))
        )
    ).all()
    return [
        engine.TaskRow(
            id=t.id,
            parent_id=t.parent_id,
            phase_id=t.phase_id,
            status=t.status.value,
            progress=t.progress,
            weight=t.weight,
            due=t.due_date.date() if t.due_date else None,
            blocked=t.is_blocked,
        )
        for t in tasks
    ]


async def recompute(session: AsyncSession, project: Project) -> Project:
    """Progress by the project's strategy, phase progress, planned baseline and health."""
    rows = await _task_rows(session, project.id)
    roots = engine.build_tree(rows)
    leaf_tasks = engine.leaves(roots)
    phases = (
        await session.scalars(
            select(Phase).where(Phase.project_id == project.id, Phase.deleted_at.is_(None))
        )
    ).all()
    for phase in phases:
        value = engine.phase_progress(phase.id, leaf_tasks)
        phase.progress = value if value is not None else Decimal("0.00")
    milestones = (
        await session.scalars(
            select(Milestone).where(
                Milestone.project_id == project.id, Milestone.deleted_at.is_(None)
            )
        )
    ).all()
    risks = (
        await session.scalars(
            select(Risk).where(Risk.project_id == project.id, Risk.deleted_at.is_(None))
        )
    ).all()
    project.progress = engine.project_progress(
        project.progress_strategy.value,
        roots,
        {p.id: p.weight for p in phases},
        [m.status.value for m in milestones],
    )
    today = date.today()
    project.planned_progress = engine.planned_progress(project.start_date, project.due_date, today)
    project.health = Health(
        engine.health(
            project.status.value,
            project.due_date,
            today,
            roots,
            [(m.status.value, m.due_date) for m in milestones],
            [(r.status.value, r.score) for r in risks],
        )
    )
    await session.flush()
    return project


async def _recompute_task_parents(session: AsyncSession, task: Task) -> None:
    """A parent's own `progress` mirrors its subtasks so lists and cards show the roll-up."""
    rows = await _task_rows(session, task.project_id)
    roots = engine.build_tree(rows)
    by_id = {r.id: r for r in engine._all(roots)}
    tasks = {
        t.id: t
        for t in (
            await session.scalars(
                select(Task).where(Task.project_id == task.project_id, Task.deleted_at.is_(None))
            )
        ).all()
    }
    node = by_id.get(task.parent_id) if task.parent_id else None
    while node is not None:
        parent = tasks[node.id]
        parent.progress = int(engine.task_progress(node))
        node = by_id.get(node.parent_id) if node.parent_id else None
    await session.flush()


async def touch(session: AsyncSession, project_id: UUID, task: Task | None = None) -> Project:
    if task is not None:
        await _recompute_task_parents(session, task)
    return await recompute(session, await _project_of(session, project_id))


# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------


async def instantiate_template(
    session: AsyncSession, org_id: UUID, project: Project, template: Template, start: date
) -> dict[str, int]:
    """New, independent rows for every template element (ids never shared)."""
    phases = (
        await session.scalars(
            select(TemplatePhase)
            .where(TemplatePhase.template_id == template.id, TemplatePhase.deleted_at.is_(None))
            .order_by(TemplatePhase.position)
        )
    ).all()
    phase_map: dict[UUID, Phase] = {}
    cursor = start
    for tp in phases:
        phase = Phase(
            org_id=org_id,
            project_id=project.id,
            name=tp.name,
            position=tp.position,
            weight=tp.weight,
            start_date=cursor,
            due_date=cursor + timedelta(days=max(tp.duration_days, 0))
            if tp.duration_days
            else None,
        )
        if tp.duration_days:
            cursor = cursor + timedelta(days=tp.duration_days)
        session.add(phase)
        phase_map[tp.id] = phase
    await session.flush()

    processes = (
        await session.scalars(
            select(TemplateProcess)
            .where(TemplateProcess.template_id == template.id, TemplateProcess.deleted_at.is_(None))
            .order_by(TemplateProcess.position)
        )
    ).all()
    process_map: dict[UUID, Process] = {}
    for tp in processes:
        process = Process(
            org_id=org_id,
            project_id=project.id,
            name=tp.name,
            position=tp.position,
            phase_id=phase_map[tp.template_phase_id].id
            if tp.template_phase_id in phase_map
            else None,
        )
        session.add(process)
        await session.flush()
        for position, name in enumerate(
            line.strip() for line in tp.stages.splitlines() if line.strip()
        ):
            session.add(
                ProcessStage(org_id=org_id, process_id=process.id, name=name, position=position)
            )
        process_map[tp.id] = process
    await session.flush()

    tasks = (
        await session.scalars(
            select(TemplateTask)
            .where(TemplateTask.template_id == template.id, TemplateTask.deleted_at.is_(None))
            .order_by(TemplateTask.position)
        )
    ).all()
    task_map: dict[UUID, Task] = {}
    for tt in tasks:
        task_start = start + timedelta(days=tt.offset_days)
        task = Task(
            org_id=org_id,
            project_id=project.id,
            title=tt.title,
            description=tt.description,
            position=tt.position,
            phase_id=phase_map[tt.template_phase_id].id
            if tt.template_phase_id in phase_map
            else None,
            process_id=process_map[tt.template_process_id].id
            if tt.template_process_id in process_map
            else None,
            start_date=task_start,
            due_date=datetime.combine(
                task_start + timedelta(days=max(tt.duration_days, 1)), datetime.min.time()
            ),
            estimated_hours=tt.estimated_hours,
            weight=tt.weight,
            priority=tt.priority,
        )
        session.add(task)
        task_map[tt.id] = task
    await session.flush()

    dependencies = (
        await session.scalars(
            select(TemplateDependency).where(
                TemplateDependency.template_id == template.id,
                TemplateDependency.deleted_at.is_(None),
            )
        )
    ).all()
    for td in dependencies:
        if td.predecessor_id in task_map and td.successor_id in task_map:
            session.add(
                TaskDependency(
                    org_id=org_id,
                    project_id=project.id,
                    predecessor_id=task_map[td.predecessor_id].id,
                    successor_id=task_map[td.successor_id].id,
                    kind=td.kind,
                    lag_days=td.lag_days,
                )
            )
    milestones = (
        await session.scalars(
            select(TemplateMilestone).where(
                TemplateMilestone.template_id == template.id, TemplateMilestone.deleted_at.is_(None)
            )
        )
    ).all()
    for tm in milestones:
        session.add(
            Milestone(
                org_id=org_id,
                project_id=project.id,
                name=tm.name,
                weight=tm.weight,
                phase_id=phase_map[tm.template_phase_id].id
                if tm.template_phase_id in phase_map
                else None,
                due_date=start + timedelta(days=tm.offset_days),
            )
        )
    await session.flush()
    return {
        "phases": len(phases),
        "processes": len(processes),
        "tasks": len(tasks),
        "milestones": len(milestones),
        "dependencies": len(dependencies),
    }


# ---------------------------------------------------------------------------
# Option providers
# ---------------------------------------------------------------------------


async def template_options(session: AsyncSession) -> list[dict[str, Any]]:
    rows = (
        await session.scalars(
            select(Template)
            .where(Template.is_active.is_(True), Template.deleted_at.is_(None))
            .order_by(Template.name)
        )
    ).all()
    return [{"value": "", "label": "Sin plantilla"}] + [
        {"value": str(t.id), "label": t.name, "description": t.description[:120]} for t in rows
    ]


async def task_options(
    session: AsyncSession, project_id: UUID, exclude: UUID | None = None
) -> list[dict[str, Any]]:
    rows = (
        await session.scalars(
            select(Task)
            .where(Task.project_id == project_id, Task.deleted_at.is_(None))
            .order_by(Task.position, Task.title)
        )
    ).all()
    return [
        {"value": str(t.id), "label": t.title, "description": t.status.value}
        for t in rows
        if t.id != exclude
    ]


async def code_taken(session: AsyncSession, code: str, exclude: UUID | None = None) -> bool:
    query = select(func.count(Project.id)).where(
        func.lower(Project.code) == code.strip().lower(), Project.deleted_at.is_(None)
    )
    if exclude is not None:
        query = query.where(Project.id != exclude)
    return bool(await session.scalar(query))


# ---------------------------------------------------------------------------
# Dependencies
# ---------------------------------------------------------------------------


async def dependency_edges(session: AsyncSession, project_id: UUID) -> dict[UUID, set[UUID]]:
    rows = (
        await session.scalars(
            select(TaskDependency).where(
                TaskDependency.project_id == project_id, TaskDependency.deleted_at.is_(None)
            )
        )
    ).all()
    edges: dict[UUID, set[UUID]] = {}
    for d in rows:
        edges.setdefault(d.predecessor_id, set()).add(d.successor_id)
    return edges


async def unmet_predecessors(session: AsyncSession, task: Task, target: TaskStatus) -> list[str]:
    """Titles of predecessors that forbid the move: FS/SF block starting, FF blocks finishing,
    SS requires started."""
    rows = (
        await session.execute(
            select(TaskDependency, Task)
            .join(Task, Task.id == TaskDependency.predecessor_id)
            .where(
                TaskDependency.successor_id == task.id,
                TaskDependency.deleted_at.is_(None),
                Task.deleted_at.is_(None),
            )
        )
    ).all()
    blocking: list[str] = []
    starting = target in (TaskStatus.doing, TaskStatus.review, TaskStatus.done)
    finishing = target == TaskStatus.done
    for dependency, predecessor in rows:
        done = predecessor.status == TaskStatus.done
        started = predecessor.status in (TaskStatus.doing, TaskStatus.review, TaskStatus.done)
        # What each kind demands of the predecessor before the successor starts or finishes.
        unmet = {
            DependencyKind.finish_to_start: starting and not done,
            DependencyKind.start_to_start: starting and not started,
            DependencyKind.finish_to_finish: finishing and not done,
            DependencyKind.start_to_finish: finishing and not started,
        }
        if unmet.get(dependency.kind, False):
            blocking.append(predecessor.title)
    return blocking


# ---------------------------------------------------------------------------
# Actions
# ---------------------------------------------------------------------------


def register(module: NovvusModule) -> None:
    # ---- projects ------------------------------------------------------------
    @module.action(Project, "register")
    async def register_project(
        session: AsyncSession, ctx: Any, _record: Any, body: dict[str, Any]
    ) -> dict[str, Any]:
        code = str(body.get("code") or "").strip()
        if not code:
            raise HTTPException(status_code=422, detail={"code": "Indica un código"})
        if await code_taken(session, code):
            raise HTTPException(
                status_code=422, detail={"code": f"Ya existe un proyecto con el código {code}"}
            )
        template = await _one(
            session, Template, _uuid(body.get("template_id"), "template_id"), "template"
        )
        start = _date(body.get("start_date"), "start_date")
        due = _date(body.get("due_date"), "due_date")
        if start and due and due < start:
            raise HTTPException(
                status_code=422,
                detail={"due_date": "La conclusión no puede ser anterior al inicio"},
            )
        budget = body.get("budget")
        project = Project(
            org_id=ctx.org_id,
            name=str(body.get("name") or "").strip() or code,
            code=code,
            description=str(body.get("description") or "").strip(),
            kind=_enum(
                ProjectKind, body.get("kind"), template.kind if template else ProjectKind.internal
            ),
            status=ProjectStatus.draft,
            priority=_enum(Priority, body.get("priority"), Priority.medium),
            owner_user_id=ctx.user_id,
            template_id=template.id if template else None,
            start_date=start,
            due_date=due,
            budget=_number(budget, "budget", minimum=Decimal("0"))
            if budget not in (None, "")
            else None,
            currency=str(body.get("currency") or "MXN").upper()[:3],
            progress_strategy=_enum(
                ProgressStrategy,
                body.get("progress_strategy"),
                template.progress_strategy if template else ProgressStrategy.tasks,
            ),
            company_id=_uuid(body.get("company_id"), "company_id"),
            opportunity_id=_uuid(body.get("opportunity_id"), "opportunity_id"),
            contact_id=_uuid(body.get("contact_id"), "contact_id"),
            company_name=str(body.get("company_name") or "").strip()[:200],
            contact_name=str(body.get("contact_name") or "").strip()[:200],
        )
        session.add(project)
        await session.flush()
        if project.opportunity_id is not None:
            # Many projects may serve one opportunity: the link table is the relation the CRM reads.
            session.add(
                ProjectLink(
                    org_id=ctx.org_id,
                    project_id=project.id,
                    opportunity_id=project.opportunity_id,
                    opportunity_name=str(body.get("opportunity_name") or "").strip()[:200],
                )
            )
            await session.flush()
        created: dict[str, int] = {}
        if template is not None:
            created = await instantiate_template(
                session, ctx.org_id, project, template, start or date.today()
            )
        await recompute(session, project)
        await module.emit(
            "projects.project.created",
            {
                "project_id": str(project.id),
                "opportunity_id": str(project.opportunity_id) if project.opportunity_id else None,
            },
        )
        message = module._("Proyecto {code} creado").format(code=code)
        if created:
            message += module._(
                " desde la plantilla: {tasks} actividades, {phases} fases, {milestones} hitos"
            ).format(**created)
        return {"message": message, "record": {"model": "projects", "id": str(project.id)}}

    @module.action_validator(Project, "register")
    async def register_project_validate(
        session: AsyncSession, ctx: Any, _record: Any, body: dict[str, Any]
    ) -> dict[str, str]:
        errors: dict[str, str] = {}
        code = str(body.get("code") or "").strip()
        if code and await code_taken(session, code):
            errors["code"] = f"Ya existe un proyecto con el código {code}"
        start, due = (
            _date(body.get("start_date"), "start_date"),
            _date(body.get("due_date"), "due_date"),
        )
        if start and due and due < start:
            errors["due_date"] = "La conclusión no puede ser anterior al inicio"
        return errors

    @module.action_options(Project, "register")
    async def register_project_options(
        session: AsyncSession, ctx: Any, _record: Any, body: dict[str, Any]
    ) -> dict[str, Any]:
        return {"template_id": await template_options(session)}

    async def _set_status(
        session: AsyncSession,
        project: Project,
        status: ProjectStatus,
        allowed: tuple[ProjectStatus, ...],
    ) -> Project:
        if project.status not in allowed:
            raise HTTPException(
                status_code=409,
                detail=f"a {project.status.value} project cannot become {status.value}",
            )
        project.status = status
        if status == ProjectStatus.completed:
            project.completed_at = datetime.now(tz=UTC)
        if status == ProjectStatus.archived:
            project.archived_at = datetime.now(tz=UTC)
        if status == ProjectStatus.active and project.start_date is None:
            project.start_date = date.today()
        return await recompute(session, project)

    @module.action(Project, "activate")
    async def activate(
        session: AsyncSession, ctx: Any, project: Project, body: dict[str, Any]
    ) -> dict[str, Any]:
        await _set_status(
            session, project, ProjectStatus.active, (ProjectStatus.draft, ProjectStatus.paused)
        )
        return {"message": module._("Proyecto en ejecución")}

    @module.action(Project, "pause")
    async def pause(
        session: AsyncSession, ctx: Any, project: Project, body: dict[str, Any]
    ) -> dict[str, Any]:
        await _set_status(session, project, ProjectStatus.paused, (ProjectStatus.active,))
        return {"message": module._("Proyecto pausado")}

    @module.action(Project, "complete")
    async def complete(
        session: AsyncSession, ctx: Any, project: Project, body: dict[str, Any]
    ) -> dict[str, Any]:
        open_count = await session.scalar(
            select(func.count(Task.id)).where(
                Task.project_id == project.id, Task.status.in_(OPEN_TASK), Task.deleted_at.is_(None)
            )
        )
        if open_count and not body.get("force"):
            raise HTTPException(
                status_code=409,
                detail=f"{open_count} open tasks; cancel them or confirm the forced closing",
            )
        await _set_status(
            session, project, ProjectStatus.completed, (ProjectStatus.active, ProjectStatus.paused)
        )
        await module.emit("projects.project.completed", {"project_id": str(project.id)})
        return {"message": module._("Proyecto concluido")}

    @module.action(Project, "cancel")
    async def cancel(
        session: AsyncSession, ctx: Any, project: Project, body: dict[str, Any]
    ) -> dict[str, Any]:
        await _set_status(
            session,
            project,
            ProjectStatus.cancelled,
            (ProjectStatus.draft, ProjectStatus.active, ProjectStatus.paused),
        )
        return {"message": module._("Proyecto cancelado")}

    @module.action(Project, "archive")
    async def archive(
        session: AsyncSession, ctx: Any, project: Project, body: dict[str, Any]
    ) -> dict[str, Any]:
        await _set_status(
            session,
            project,
            ProjectStatus.archived,
            (ProjectStatus.completed, ProjectStatus.cancelled),
        )
        return {"message": module._("Proyecto archivado")}

    @module.action(Project, "restore")
    async def restore(
        session: AsyncSession, ctx: Any, project: Project, body: dict[str, Any]
    ) -> dict[str, Any]:
        if project.status != ProjectStatus.archived:
            raise HTTPException(status_code=409, detail="only an archived project is restored")
        project.status = ProjectStatus.completed if project.completed_at else ProjectStatus.draft
        project.archived_at = None
        await recompute(session, project)
        return {"message": module._("Proyecto restaurado")}

    @module.action(Project, "remove")
    async def remove(
        session: AsyncSession, ctx: Any, project: Project, body: dict[str, Any]
    ) -> dict[str, Any]:
        """Controlled deletion: only drafts, cancelled or archived projects; linked rows go
        with it."""
        if project.status not in (
            ProjectStatus.draft,
            ProjectStatus.cancelled,
            ProjectStatus.archived,
        ):
            raise HTTPException(
                status_code=409, detail="cancel or archive the project before deleting it"
            )
        done_tasks = await session.scalar(
            select(func.count(Task.id)).where(
                Task.project_id == project.id,
                Task.status == TaskStatus.done,
                Task.deleted_at.is_(None),
            )
        )
        if done_tasks and not body.get("force"):
            raise HTTPException(
                status_code=409,
                detail=f"{done_tasks} completed tasks would be lost; confirm the forced deletion",
            )
        await session.delete(project)
        await session.flush()
        return {"message": module._("Proyecto eliminado"), "path": "projects"}

    @module.action(Project, "recompute")
    async def recompute_action(
        session: AsyncSession, ctx: Any, project: Project, body: dict[str, Any]
    ) -> dict[str, Any]:
        await recompute(session, project)
        return {
            "message": module._("Avance {progress} % · salud {health}").format(
                progress=project.progress, health=project.health.value
            )
        }

    @module.action(Project, "set_status")
    async def project_set_status(
        session: AsyncSession, ctx: Any, project: Project, body: dict[str, Any]
    ) -> dict[str, Any]:
        """Kanban drops on the portfolio board go through the lifecycle rules."""
        target = _enum(ProjectStatus, body.get("status"), project.status)
        if target == project.status:
            return {"message": module._("Sin cambios")}
        handlers = {
            ProjectStatus.active: activate,
            ProjectStatus.paused: pause,
            ProjectStatus.completed: complete,
            ProjectStatus.cancelled: cancel,
            ProjectStatus.archived: archive,
        }
        if target == ProjectStatus.draft:
            if project.status != ProjectStatus.archived:
                raise HTTPException(status_code=409, detail="a project does not go back to draft")
            return await restore(session, ctx, project, body)
        return await handlers[target](session, ctx, project, body)

    # ---- phases --------------------------------------------------------------
    @module.action(Phase, "reorder")
    async def reorder(
        session: AsyncSession, ctx: Any, phase: Phase, body: dict[str, Any]
    ) -> dict[str, Any]:
        position = int(_number(body.get("position"), "position", minimum=Decimal("0")))
        siblings = (
            await session.scalars(
                select(Phase)
                .where(
                    Phase.project_id == phase.project_id,
                    Phase.deleted_at.is_(None),
                    Phase.id != phase.id,
                )
                .order_by(Phase.position)
            )
        ).all()
        ordered = list(siblings)
        ordered.insert(min(position, len(ordered)), phase)
        for index, row in enumerate(ordered):
            row.position = index
        await session.flush()
        return {
            "message": module._("Fase en la posición {position}").format(position=phase.position)
        }

    @module.action(Phase, "set_status")
    async def phase_status(
        session: AsyncSession, ctx: Any, phase: Phase, body: dict[str, Any]
    ) -> dict[str, Any]:
        phase.status = _enum(PhaseStatus, body.get("status"), phase.status)
        await session.flush()
        await touch(session, phase.project_id)
        return {"message": module._("Fase {status}").format(status=phase.status.value)}

    # ---- tasks ---------------------------------------------------------------
    @module.action(Task, "set_status")
    async def task_status(
        session: AsyncSession, ctx: Any, task: Task, body: dict[str, Any]
    ) -> dict[str, Any]:
        target = _enum(TaskStatus, body.get("status"), task.status)
        if target == task.status:
            return {"message": module._("Sin cambios")}
        if task.is_blocked:
            raise HTTPException(status_code=409, detail="unblock the task first")
        if target not in TRANSITIONS.get(task.status, set()):
            raise HTTPException(
                status_code=409,
                detail=f"{task.status.value} → {target.value} is not a valid transition",
            )
        unmet = await unmet_predecessors(session, task, target)
        if unmet and not body.get("force"):
            raise HTTPException(status_code=409, detail="pending predecessors: " + ", ".join(unmet))
        task.status = target
        if target == TaskStatus.done:
            task.progress = 100
            task.completed_at = datetime.now(tz=UTC)
            await module.emit(
                "projects.task.completed",
                {"task_id": str(task.id), "project_id": str(task.project_id)},
            )
        elif target in (TaskStatus.todo, TaskStatus.cancelled):
            task.completed_at = None
            if target == TaskStatus.todo:
                task.progress = 0
        elif task.progress == 100:
            task.progress = 90
            task.completed_at = None
        await session.flush()
        await touch(session, task.project_id, task)
        return {"message": module._("Actividad {status}").format(status=target.value)}

    @module.action(Task, "set_progress")
    async def task_progress(
        session: AsyncSession, ctx: Any, task: Task, body: dict[str, Any]
    ) -> dict[str, Any]:
        children = await session.scalar(
            select(func.count(Task.id)).where(Task.parent_id == task.id, Task.deleted_at.is_(None))
        )
        if children:
            raise HTTPException(
                status_code=409, detail="the progress of a task with subtasks comes from them"
            )
        value = int(
            _number(body.get("progress"), "progress", minimum=Decimal("0"), maximum=Decimal("100"))
        )
        if task.status in (TaskStatus.done, TaskStatus.cancelled):
            raise HTTPException(status_code=409, detail="a finished task does not change progress")
        task.progress = value
        if value > 0 and task.status == TaskStatus.todo:
            task.status = TaskStatus.doing
        if "logged_hours" in body and body["logged_hours"] not in (None, ""):
            task.logged_hours = task.logged_hours + _number(
                body["logged_hours"], "logged_hours", minimum=Decimal("0")
            )
        await session.flush()
        await touch(session, task.project_id, task)
        return {"message": module._("Avance {progress} %").format(progress=value)}

    @module.action(Task, "block")
    async def block(
        session: AsyncSession, ctx: Any, task: Task, body: dict[str, Any]
    ) -> dict[str, Any]:
        reason = str(body.get("reason") or "").strip()
        if not reason:
            raise HTTPException(status_code=422, detail={"reason": "Indica la causa del bloqueo"})
        if task.status in (TaskStatus.done, TaskStatus.cancelled):
            raise HTTPException(status_code=409, detail="a finished task cannot be blocked")
        task.is_blocked = True
        task.blocked_reason = reason[:1000]
        task.status = TaskStatus.blocked
        await session.flush()
        await touch(session, task.project_id, task)
        return {"message": module._("Actividad bloqueada")}

    @module.action(Task, "unblock")
    async def unblock(
        session: AsyncSession, ctx: Any, task: Task, body: dict[str, Any]
    ) -> dict[str, Any]:
        if not task.is_blocked:
            raise HTTPException(status_code=409, detail="the task is not blocked")
        task.is_blocked = False
        task.blocked_reason = ""
        task.status = TaskStatus.doing if task.progress > 0 else TaskStatus.todo
        await session.flush()
        await touch(session, task.project_id, task)
        return {"message": module._("Actividad desbloqueada")}

    @module.action(Task, "assign")
    async def assign(
        session: AsyncSession, ctx: Any, task: Task, body: dict[str, Any]
    ) -> dict[str, Any]:
        user = _uuid(body.get("user_id"), "user_id")
        task.assigned_user_id = user if user is not None else ctx.user_id
        await session.flush()
        return {"message": module._("Responsable asignado")}

    @module.action(Task, "add_dependency")
    async def add_dependency(
        session: AsyncSession, ctx: Any, task: Task, body: dict[str, Any]
    ) -> dict[str, Any]:
        predecessor_id = _uuid(body.get("predecessor_id"), "predecessor_id")
        if predecessor_id is None:
            raise HTTPException(
                status_code=422, detail={"predecessor_id": "Elige la actividad predecesora"}
            )
        predecessor = await _one(session, Task, predecessor_id, "task")
        if predecessor.project_id != task.project_id:
            raise HTTPException(
                status_code=422, detail={"predecessor_id": "Debe ser del mismo proyecto"}
            )
        edges = await dependency_edges(session, task.project_id)
        if engine.would_cycle(edges, predecessor.id, task.id):
            raise HTTPException(
                status_code=422, detail={"predecessor_id": "Crearía un ciclo de dependencias"}
            )
        existing = await session.scalar(
            select(TaskDependency).where(
                TaskDependency.predecessor_id == predecessor.id,
                TaskDependency.successor_id == task.id,
            )
        )
        kind = _enum(DependencyKind, body.get("kind"), DependencyKind.finish_to_start)
        lag = int(_number(body.get("lag_days"), "lag_days"))
        if existing is None:
            session.add(
                TaskDependency(
                    org_id=ctx.org_id,
                    project_id=task.project_id,
                    predecessor_id=predecessor.id,
                    successor_id=task.id,
                    kind=kind,
                    lag_days=lag,
                )
            )
        else:
            existing.kind, existing.lag_days = kind, lag
        await session.flush()
        return {"message": module._("Depende de «{title}»").format(title=predecessor.title)}

    @module.action_options(Task, "add_dependency")
    async def add_dependency_options(
        session: AsyncSession, ctx: Any, task: Task, body: dict[str, Any]
    ) -> dict[str, Any]:
        return {"predecessor_id": await task_options(session, task.project_id, exclude=task.id)}

    @module.action_validator(Task, "add_dependency")
    async def add_dependency_validate(
        session: AsyncSession, ctx: Any, task: Task, body: dict[str, Any]
    ) -> dict[str, str]:
        predecessor_id = (
            _uuid(body.get("predecessor_id"), "predecessor_id")
            if body.get("predecessor_id")
            else None
        )
        if predecessor_id is None:
            return {}
        edges = await dependency_edges(session, task.project_id)
        if engine.would_cycle(edges, predecessor_id, task.id):
            return {"predecessor_id": "Crearía un ciclo de dependencias"}
        return {}

    @module.action(TaskDependency, "remove")
    async def remove_dependency(
        session: AsyncSession, ctx: Any, dependency: TaskDependency, body: dict[str, Any]
    ) -> dict[str, Any]:
        await session.delete(dependency)
        await session.flush()
        return {"message": module._("Dependencia quitada")}

    # ---- milestones, deliverables, approvals, risks ----------------------------
    @module.action(Milestone, "reach")
    async def reach(
        session: AsyncSession, ctx: Any, milestone: Milestone, body: dict[str, Any]
    ) -> dict[str, Any]:
        if milestone.status == MilestoneStatus.cancelled:
            raise HTTPException(status_code=409, detail="a cancelled milestone is not reached")
        milestone.status = MilestoneStatus.reached
        milestone.reached_at = datetime.now(tz=UTC)
        await session.flush()
        await touch(session, milestone.project_id)
        return {"message": module._("Hito alcanzado")}

    @module.action(Milestone, "miss")
    async def miss(
        session: AsyncSession, ctx: Any, milestone: Milestone, body: dict[str, Any]
    ) -> dict[str, Any]:
        milestone.status = MilestoneStatus.missed
        milestone.reached_at = None
        await session.flush()
        await touch(session, milestone.project_id)
        return {"message": module._("Hito incumplido")}

    @module.action(Milestone, "reopen")
    async def reopen_milestone(
        session: AsyncSession, ctx: Any, milestone: Milestone, body: dict[str, Any]
    ) -> dict[str, Any]:
        milestone.status = MilestoneStatus.pending
        milestone.reached_at = None
        await session.flush()
        await touch(session, milestone.project_id)
        return {"message": module._("Hito pendiente de nuevo")}

    async def _request_approval(
        session: AsyncSession,
        ctx: Any,
        project_id: UUID,
        kind: ApprovalTarget,
        target_id: UUID,
        label: str,
        approver: Any,
    ) -> Approval:
        pending = await session.scalar(
            select(Approval).where(
                Approval.target_kind == kind,
                Approval.target_id == target_id,
                Approval.status == ApprovalStatus.pending,
                Approval.deleted_at.is_(None),
            )
        )
        if pending is not None:
            raise HTTPException(status_code=409, detail="an approval is already pending")
        approval = Approval(
            org_id=ctx.org_id,
            project_id=project_id,
            target_kind=kind,
            target_id=target_id,
            target_label=label[:200],
            requested_by_user_id=ctx.user_id,
            approver_user_id=_uuid(approver, "approver_user_id"),
        )
        session.add(approval)
        await session.flush()
        return approval

    @module.action(Deliverable, "submit")
    async def submit(
        session: AsyncSession, ctx: Any, deliverable: Deliverable, body: dict[str, Any]
    ) -> dict[str, Any]:
        if deliverable.status not in (
            DeliverableStatus.pending,
            DeliverableStatus.in_progress,
            DeliverableStatus.rejected,
        ):
            raise HTTPException(
                status_code=409, detail="the deliverable is not in a state that can be submitted"
            )
        deliverable.status = DeliverableStatus.submitted
        await _request_approval(
            session,
            ctx,
            deliverable.project_id,
            ApprovalTarget.deliverable,
            deliverable.id,
            deliverable.name,
            body.get("approver_user_id"),
        )
        return {"message": module._("Entregable enviado a aprobación")}

    @module.action(Deliverable, "start")
    async def start_deliverable(
        session: AsyncSession, ctx: Any, deliverable: Deliverable, body: dict[str, Any]
    ) -> dict[str, Any]:
        if deliverable.status != DeliverableStatus.pending:
            raise HTTPException(status_code=409, detail="only a pending deliverable starts")
        deliverable.status = DeliverableStatus.in_progress
        await session.flush()
        return {"message": module._("Entregable en elaboración")}

    @module.action(Deliverable, "deliver")
    async def deliver(
        session: AsyncSession, ctx: Any, deliverable: Deliverable, body: dict[str, Any]
    ) -> dict[str, Any]:
        if deliverable.status != DeliverableStatus.approved:
            raise HTTPException(status_code=409, detail="only an approved deliverable is delivered")
        deliverable.status = DeliverableStatus.delivered
        deliverable.delivered_at = datetime.now(tz=UTC)
        await session.flush()
        return {"message": module._("Entregable entregado")}

    async def _decide(session: AsyncSession, approval: Approval, approved: bool, note: str) -> None:
        if approval.status != ApprovalStatus.pending:
            raise HTTPException(status_code=409, detail="the approval was already decided")
        approval.status = ApprovalStatus.approved if approved else ApprovalStatus.rejected
        approval.decided_at = datetime.now(tz=UTC)
        approval.note = note[:2000]
        if approval.target_kind == ApprovalTarget.deliverable:
            deliverable = await _one(session, Deliverable, approval.target_id, "deliverable")
            if deliverable is not None:
                deliverable.status = (
                    DeliverableStatus.approved if approved else DeliverableStatus.rejected
                )
        elif approval.target_kind == ApprovalTarget.milestone:
            milestone = await _one(session, Milestone, approval.target_id, "milestone")
            if milestone is not None and approved:
                milestone.status = MilestoneStatus.reached
                milestone.reached_at = datetime.now(tz=UTC)
        elif approval.target_kind == ApprovalTarget.task:
            task = await _one(session, Task, approval.target_id, "task")
            if task is not None:
                task.status = TaskStatus.done if approved else TaskStatus.doing
                if approved:
                    task.progress = 100
                    task.completed_at = datetime.now(tz=UTC)
        await session.flush()
        await touch(session, approval.project_id)

    @module.action(Approval, "approve")
    async def approve(
        session: AsyncSession, ctx: Any, approval: Approval, body: dict[str, Any]
    ) -> dict[str, Any]:
        await _decide(session, approval, True, str(body.get("note") or ""))
        return {"message": module._("Aprobado")}

    @module.action(Approval, "reject")
    async def reject(
        session: AsyncSession, ctx: Any, approval: Approval, body: dict[str, Any]
    ) -> dict[str, Any]:
        note = str(body.get("note") or "").strip()
        if not note:
            raise HTTPException(status_code=422, detail={"note": "Indica el motivo del rechazo"})
        await _decide(session, approval, False, note)
        return {"message": module._("Rechazado")}

    @module.action(Task, "request_approval")
    async def task_request_approval(
        session: AsyncSession, ctx: Any, task: Task, body: dict[str, Any]
    ) -> dict[str, Any]:
        if task.status not in (TaskStatus.doing, TaskStatus.review):
            raise HTTPException(
                status_code=409, detail="only a task in progress or in review asks for approval"
            )
        task.status = TaskStatus.review
        await _request_approval(
            session,
            ctx,
            task.project_id,
            ApprovalTarget.task,
            task.id,
            task.title,
            body.get("approver_user_id"),
        )
        return {"message": module._("Actividad en revisión; aprobación solicitada")}

    @module.action(Risk, "assess")
    async def assess(
        session: AsyncSession, ctx: Any, risk: Risk, body: dict[str, Any]
    ) -> dict[str, Any]:
        risk.probability = _enum(RiskLevel, body.get("probability"), risk.probability)
        risk.impact = _enum(RiskLevel, body.get("impact"), risk.impact)
        risk.score = engine.risk_score(risk.probability.value, risk.impact.value)
        if body.get("mitigation"):
            risk.mitigation = str(body["mitigation"])[:4000]
        if body.get("review_date"):
            risk.review_date = _date(body["review_date"], "review_date")
        if risk.status == RiskStatus.open and risk.mitigation:
            risk.status = RiskStatus.mitigating
        await session.flush()
        await touch(session, risk.project_id)
        return {"message": module._("Riesgo evaluado: puntuación {score}").format(score=risk.score)}

    @module.action(Risk, "set_status")
    async def risk_set_status(
        session: AsyncSession, ctx: Any, risk: Risk, body: dict[str, Any]
    ) -> dict[str, Any]:
        target = _enum(RiskStatus, body.get("status"), risk.status)
        if target == risk.status:
            return {"message": module._("Sin cambios")}
        if target == RiskStatus.materialized:
            return await materialize(session, ctx, risk, body)
        if target == RiskStatus.closed:
            return await close_risk(session, ctx, risk, body)
        if risk.status == RiskStatus.closed:
            raise HTTPException(status_code=409, detail="a closed risk is not reopened")
        risk.status = target
        await session.flush()
        await touch(session, risk.project_id)
        return {"message": module._("Riesgo {status}").format(status=target.value)}

    @module.action(Risk, "materialize")
    async def materialize(
        session: AsyncSession, ctx: Any, risk: Risk, body: dict[str, Any]
    ) -> dict[str, Any]:
        if risk.status == RiskStatus.closed:
            raise HTTPException(status_code=409, detail="a closed risk cannot materialize")
        risk.status = RiskStatus.materialized
        if body.get("description"):
            risk.description = (risk.description + "\n" if risk.description else "") + str(
                body["description"]
            )[:2000]
        await session.flush()
        await touch(session, risk.project_id)
        return {"message": module._("Riesgo materializado: ahora es un problema")}

    @module.action(Risk, "close")
    async def close_risk(
        session: AsyncSession, ctx: Any, risk: Risk, body: dict[str, Any]
    ) -> dict[str, Any]:
        risk.status = RiskStatus.closed
        await session.flush()
        await touch(session, risk.project_id)
        return {"message": module._("Riesgo cerrado")}
