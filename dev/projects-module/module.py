"""Proyectos — NOVVUS module.

Project management (portfolio → projects → phases → processes → tasks) that
works on its own and integrates with the CRM through its public API and
events only. CRM data is referenced BY ID via the gateway — never its tables.
"""

import logging
from pathlib import Path
from uuid import UUID

import business
import errors
import portfolio
import processes
import views
from models import ALL_MODELS, Project, ProjectLink, ProjectStatus, Task
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from novvus_sdk import Event, NovvusModule

logger = logging.getLogger("novvus.projects")

module = NovvusModule(Path(__file__).with_name("novvus.toml"))

# Badges, counters, tabs, related panels and stage indicators (views.py) are
# layered on the models BEFORE registration: the SDK validates them then.
views.declare()
for model in ALL_MODELS:
    module.model(model)
business.register(module)
processes.register(module)
portfolio.register(module)


async def _contact_display_name(contact_id: str | None, org_id: UUID) -> str:
    """Resolve the contact's name through the CRM public API. Degrades to an
    empty string when the CRM is unreachable/disabled — never breaks."""
    if not contact_id:
        return ""
    try:
        # Offline mode (no kernel) reports no dependency statuses, and a
        # disabled CRM is not worth a gateway round-trip: nothing to resolve.
        if (await module.dependency_statuses()).get("crm") != "enabled":
            return ""
        contact = await module.call("GET", f"/api/crm/contacts/{contact_id}", org_id=org_id)
        return str(contact.get("name", ""))
    except Exception as error:
        logger.warning("CRM unavailable while resolving contact %s: %s", contact_id, error)
        return ""


def opportunity_project_code(opportunity_id: str) -> str:
    """Deterministic project code for a project born from an opportunity."""
    return f"OPP-{opportunity_id.replace('-', '')[:8].upper()}"


@module.on("crm.opportunity.won")
async def create_project_from_won_opportunity(event: Event, session: AsyncSession) -> None:
    """Automatic conversion, only when the organization opted in
    (`projects.create_on_won`); otherwise the CRM offers an explicit
    «Crear proyecto» action (docs/implementation/crm-projects-plan.md D5)."""
    config = await module.config(event.org_id)
    if not config.get("projects.create_on_won", False):
        logger.info("won opportunity ignored: projects.create_on_won is off for %s", event.org_id)
        return

    payload = event.payload
    opportunity_id = payload.get("opportunity_id")

    # Belt and braces on top of the SDK's event idempotency: one automatic
    # project per won opportunity, even across event re-emissions.
    if opportunity_id:
        existing = await session.scalar(
            select(Project).where(Project.opportunity_id == UUID(opportunity_id))
        )
        if existing is not None:
            logger.info("project for opportunity %s already exists", opportunity_id)
            return

    contact_name = await _contact_display_name(payload.get("contact_id"), event.org_id)

    project = Project(
        org_id=event.org_id,
        name=payload.get("name") or "Proyecto de oportunidad ganada",
        code=opportunity_project_code(opportunity_id) if opportunity_id else "",
        description=(
            f"Creado automáticamente al ganar la oportunidad por "
            f"{payload.get('amount', '?')} {payload.get('currency', '')}".strip()
        ),
        status=ProjectStatus.active,
        opportunity_id=UUID(opportunity_id) if opportunity_id else None,
        contact_id=UUID(payload["contact_id"]) if payload.get("contact_id") else None,
        company_id=UUID(payload["company_id"]) if payload.get("company_id") else None,
        contact_name=contact_name,
    )
    session.add(project)
    await session.flush()
    if opportunity_id:
        session.add(
            ProjectLink(
                org_id=event.org_id,
                project_id=project.id,
                opportunity_id=UUID(opportunity_id),
                opportunity_name=str(payload.get("name") or ""),
            )
        )

    session.add_all(
        Task(org_id=event.org_id, project_id=project.id, title=title, position=index)
        for index, title in enumerate(("Reunión de arranque", "Definir alcance", "Asignar equipo"))
    )
    await session.flush()

    await module.emit(
        "projects.project.created",
        {"project_id": str(project.id), "opportunity_id": opportunity_id},
        org_id=event.org_id,
    )


@module.seed
async def seed(session: AsyncSession, org_id: UUID) -> None:
    """Demo data: a reusable template and one project instantiated from it with real progress.
    Idempotent per organization (keyed by the template name)."""
    from datetime import date, timedelta

    from models import (
        Phase,
        PhaseStatus,
        ProgressStrategy,
        Task,
        TaskStatus,
        Template,
        TemplateDependency,
        TemplateMilestone,
        TemplatePhase,
        TemplateProcess,
        TemplateTask,
    )

    existing = await session.scalar(
        select(Template).where(
            Template.name == "Implementación estándar", Template.deleted_at.is_(None)
        )
    )
    if existing is not None:
        return
    template = Template(
        org_id=org_id,
        name="Implementación estándar",
        description="Arranque, diseño, ejecución con control de calidad y cierre.",
        progress_strategy=ProgressStrategy.weighted,
    )
    session.add(template)
    await session.flush()
    phases = []
    for position, (name, weight, days) in enumerate(
        (("Arranque", "1", 5), ("Diseño", "2", 15), ("Ejecución", "4", 30), ("Cierre", "1", 5))
    ):
        phase = TemplatePhase(
            org_id=org_id,
            template_id=template.id,
            name=name,
            position=position,
            weight=weight,
            duration_days=days,
        )
        session.add(phase)
        phases.append(phase)
    await session.flush()
    process = TemplateProcess(
        org_id=org_id,
        template_id=template.id,
        template_phase_id=phases[2].id,
        name="Control de ejecución",
        position=0,
        stages="Recepción\nEjecución\nControl de calidad\nEntrega",
    )
    session.add(process)
    await session.flush()
    tasks = []
    for position, (title, phase_index, offset, duration, weight, in_process) in enumerate(
        (
            ("Reunión de arranque", 0, 0, 1, "1", False),
            ("Definir alcance", 0, 1, 4, "2", False),
            ("Diseño de solución", 1, 5, 10, "3", False),
            ("Validar diseño con el cliente", 1, 15, 5, "1", False),
            ("Configurar entornos", 2, 20, 10, "3", True),
            ("Capacitar al equipo", 2, 30, 10, "2", True),
            ("Pruebas de aceptación", 2, 40, 10, "3", True),
            ("Go-live y entrega", 3, 50, 5, "2", False),
        )
    ):
        task = TemplateTask(
            org_id=org_id,
            template_id=template.id,
            template_phase_id=phases[phase_index].id,
            template_process_id=process.id if in_process else None,
            title=title,
            position=position,
            offset_days=offset,
            duration_days=duration,
            weight=weight,
        )
        session.add(task)
        tasks.append(task)
    await session.flush()
    session.add_all(
        TemplateDependency(
            org_id=org_id,
            template_id=template.id,
            predecessor_id=tasks[i].id,
            successor_id=tasks[i + 1].id,
        )
        for i in range(len(tasks) - 1)
    )
    session.add_all(
        (
            TemplateMilestone(
                org_id=org_id,
                template_id=template.id,
                template_phase_id=phases[1].id,
                name="Diseño aprobado",
                offset_days=20,
            ),
            TemplateMilestone(
                org_id=org_id,
                template_id=template.id,
                template_phase_id=phases[3].id,
                name="Go-live",
                offset_days=55,
            ),
        )
    )
    await session.flush()

    from business import instantiate_template, recompute

    project = Project(
        org_id=org_id,
        name="Implementación interna NOVVUS",
        code="INT-0001",
        status=ProjectStatus.active,
        description="Proyecto de ejemplo creado por el seed desde la plantilla estándar.",
        template_id=template.id,
        start_date=date.today() - timedelta(days=10),
        due_date=date.today() + timedelta(days=50),
        progress_strategy=ProgressStrategy.weighted,
    )
    session.add(project)
    await session.flush()
    await instantiate_template(session, org_id, project, template, project.start_date)
    done = (
        await session.scalars(
            select(Task)
            .where(Task.project_id == project.id, Task.deleted_at.is_(None))
            .order_by(Task.position)
            .limit(2)
        )
    ).all()
    for task in done:
        task.status = TaskStatus.done
        task.progress = 100
    phases_rows = (await session.scalars(select(Phase).where(Phase.project_id == project.id))).all()
    for phase in phases_rows:
        if phase.name == "Arranque":
            phase.status = PhaseStatus.done
    await session.flush()
    await recompute(session, project)


app = module.create_app()
errors.install(app)  # unique/foreign-key violations answer 409 with the field, never 500
