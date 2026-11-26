"""Projects data model. RLS, ids and timestamps come from the SDK.

Hierarchy: portfolio → project → phases → processes (with stages) → tasks and
subtasks. Cross-cutting: milestones, deliverables, dependencies, risks,
approvals, members, templates and links to CRM opportunities. Comments and
field history use Core's chatter/track. Schema history: 0001 initial, 0002 ext,
0003 custom, 0004 project management model.
"""

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from sqlalchemy import Enum as SAEnum
from sqlalchemy import ForeignKey, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from novvus_sdk import NovvusModel


class ProjectStatus(StrEnum):
    draft = "draft"
    active = "active"
    paused = "paused"
    completed = "completed"
    cancelled = "cancelled"
    archived = "archived"


class ProjectKind(StrEnum):
    internal = "internal"
    administrative = "administrative"
    technology = "technology"
    industrial = "industrial"
    service = "service"
    other = "other"


class Health(StrEnum):
    """Execution health, independent from progress and status."""

    on_track = "on_track"
    at_risk = "at_risk"
    delayed = "delayed"
    blocked = "blocked"


class Priority(StrEnum):
    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"


class ProgressStrategy(StrEnum):
    tasks = "tasks"  # completed tasks / total tasks
    weighted = "weighted"  # sum(weight x progress) / Σ(weight) over phases (or tasks)
    milestones = "milestones"  # reached milestones / total milestones


class PhaseStatus(StrEnum):
    pending = "pending"
    active = "active"
    done = "done"
    cancelled = "cancelled"


class ProcessStatus(StrEnum):
    pending = "pending"
    running = "running"
    done = "done"
    cancelled = "cancelled"


class StageStatus(StrEnum):
    pending = "pending"
    active = "active"
    done = "done"
    skipped = "skipped"


class TaskStatus(StrEnum):
    todo = "todo"
    doing = "doing"
    blocked = "blocked"
    review = "review"
    done = "done"
    cancelled = "cancelled"


class DependencyKind(StrEnum):
    finish_to_start = "finish_to_start"
    start_to_start = "start_to_start"
    finish_to_finish = "finish_to_finish"
    start_to_finish = "start_to_finish"


class MilestoneStatus(StrEnum):
    pending = "pending"
    reached = "reached"
    missed = "missed"
    cancelled = "cancelled"


class DeliverableStatus(StrEnum):
    pending = "pending"
    in_progress = "in_progress"
    submitted = "submitted"
    approved = "approved"
    rejected = "rejected"
    delivered = "delivered"


class RiskLevel(StrEnum):
    low = "low"
    medium = "medium"
    high = "high"


class RiskStatus(StrEnum):
    open = "open"  # potential
    mitigating = "mitigating"
    materialized = "materialized"  # became an issue
    closed = "closed"


class ApprovalStatus(StrEnum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"


class ApprovalTarget(StrEnum):
    deliverable = "deliverable"
    milestone = "milestone"
    stage = "stage"
    task = "task"


def _enum(enum_cls: type[StrEnum]) -> SAEnum:
    return SAEnum(enum_cls, native_enum=False, length=20)


def _fk(target: str, ondelete: str) -> Mapped[UUID | None]:
    return mapped_column(PgUUID(as_uuid=True), ForeignKey(target, ondelete=ondelete), nullable=True)


def _fk_required(target: str, ondelete: str) -> Mapped[UUID]:
    return mapped_column(PgUUID(as_uuid=True), ForeignKey(target, ondelete=ondelete))


_PROJECT_PERMS = {"read": "projects.projects.read", "write": "projects.projects.write"}
_TASK_PERMS = {"read": "projects.tasks.read", "write": "projects.tasks.write"}
_TEMPLATE_PERMS = {"read": "projects.templates.read", "write": "projects.templates.write"}


class Template(NovvusModel):
    """Reusable project template: phases, processes, tasks, milestones, dependencies."""

    __resource__ = "templates"
    __table_args__ = (UniqueConstraint("org_id", "name"),)
    __novvus_api__ = {"permissions": _TEMPLATE_PERMS}  # noqa: RUF012

    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(String(4000), default="")
    kind: Mapped[ProjectKind] = mapped_column(_enum(ProjectKind), default=ProjectKind.other)
    progress_strategy: Mapped[ProgressStrategy] = mapped_column(
        _enum(ProgressStrategy), default=ProgressStrategy.weighted
    )
    is_active: Mapped[bool] = mapped_column(default=True)

    __novvus_views__ = {  # noqa: RUF012
        "label": "Plantillas de proyecto",
        "display": "name",
        "nav": {"group": "Configuración", "order": 10},
        "labels": {
            "name": "Nombre",
            "description": "Descripción",
            "kind": "Tipo de proyecto",
            "progress_strategy": "Estrategia de avance",
            "is_active": "Activa",
        },
        "list": {
            "columns": ["name", "kind", "progress_strategy", "is_active"],
            "default_order": "name",
        },
        "form": {"layout": [["name", "kind"], ["progress_strategy", "is_active"], ["description"]]},
    }


class TemplatePhase(NovvusModel):
    __resource__ = "template_phases"
    __novvus_api__ = {"permissions": _TEMPLATE_PERMS}  # noqa: RUF012

    template_id: Mapped[UUID] = _fk_required("template.id", "CASCADE")
    name: Mapped[str] = mapped_column(String(200))
    position: Mapped[int] = mapped_column(default=0)
    weight: Mapped[Decimal] = mapped_column(Numeric(7, 2), default=Decimal("1"))
    duration_days: Mapped[int] = mapped_column(default=0)

    __novvus_views__ = {  # noqa: RUF012
        "label": "Fases de plantilla",
        "display": "name",
        "nav": {"hidden": True},
        "labels": {
            "template_id": "Plantilla",
            "name": "Nombre",
            "position": "Posición",
            "weight": "Peso",
            "duration_days": "Duración (días)",
        },
        "list": {
            "columns": ["position", "name", "weight", "duration_days"],
            "default_order": "position",
        },
        "form": {"layout": [["template_id", "name"], ["position", "weight", "duration_days"]]},
    }


class TemplateProcess(NovvusModel):
    __resource__ = "template_processes"
    __novvus_api__ = {"permissions": _TEMPLATE_PERMS}  # noqa: RUF012

    template_id: Mapped[UUID] = _fk_required("template.id", "CASCADE")
    template_phase_id: Mapped[UUID | None] = _fk("template_phase.id", "SET NULL")
    name: Mapped[str] = mapped_column(String(200))
    position: Mapped[int] = mapped_column(default=0)
    # Ordered stage names separated by newlines; each becomes a ProcessStage.
    stages: Mapped[str] = mapped_column(String(4000), default="")

    __novvus_views__ = {  # noqa: RUF012
        "label": "Procesos de plantilla",
        "display": "name",
        "nav": {"hidden": True},
        "labels": {
            "template_id": "Plantilla",
            "template_phase_id": "Fase",
            "name": "Nombre",
            "position": "Posición",
            "stages": "Etapas (una por línea)",
        },
        "list": {"columns": ["position", "name", "template_phase_id"], "default_order": "position"},
        "form": {
            "layout": [["template_id", "template_phase_id"], ["name", "position"], ["stages"]]
        },
    }


class TemplateTask(NovvusModel):
    __resource__ = "template_tasks"
    __novvus_api__ = {"permissions": _TEMPLATE_PERMS}  # noqa: RUF012

    template_id: Mapped[UUID] = _fk_required("template.id", "CASCADE")
    template_phase_id: Mapped[UUID | None] = _fk("template_phase.id", "SET NULL")
    template_process_id: Mapped[UUID | None] = _fk("template_process.id", "SET NULL")
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(String(4000), default="")
    position: Mapped[int] = mapped_column(default=0)
    offset_days: Mapped[int] = mapped_column(default=0)  # from project start
    duration_days: Mapped[int] = mapped_column(default=1)
    estimated_hours: Mapped[Decimal] = mapped_column(Numeric(8, 2), default=Decimal("0"))
    weight: Mapped[Decimal] = mapped_column(Numeric(7, 2), default=Decimal("1"))
    priority: Mapped[Priority] = mapped_column(_enum(Priority), default=Priority.medium)

    __novvus_views__ = {  # noqa: RUF012
        "label": "Actividades de plantilla",
        "display": "title",
        "nav": {"hidden": True},
        "labels": {
            "template_id": "Plantilla",
            "template_phase_id": "Fase",
            "template_process_id": "Proceso",
            "title": "Título",
            "description": "Descripción",
            "position": "Posición",
            "offset_days": "Inicio (días desde el arranque)",
            "duration_days": "Duración (días)",
            "estimated_hours": "Horas estimadas",
            "weight": "Peso",
            "priority": "Prioridad",
        },
        "list": {
            "columns": [
                "position",
                "title",
                "template_phase_id",
                "offset_days",
                "duration_days",
                "weight",
            ],
            "default_order": "position",
        },
        "form": {
            "layout": [
                ["template_id", "template_phase_id", "template_process_id"],
                ["title", "priority"],
                ["position", "offset_days", "duration_days"],
                ["estimated_hours", "weight"],
                ["description"],
            ],
        },
    }


class TemplateMilestone(NovvusModel):
    __resource__ = "template_milestones"
    __novvus_api__ = {"permissions": _TEMPLATE_PERMS}  # noqa: RUF012

    template_id: Mapped[UUID] = _fk_required("template.id", "CASCADE")
    template_phase_id: Mapped[UUID | None] = _fk("template_phase.id", "SET NULL")
    name: Mapped[str] = mapped_column(String(200))
    offset_days: Mapped[int] = mapped_column(default=0)
    weight: Mapped[Decimal] = mapped_column(Numeric(7, 2), default=Decimal("1"))

    __novvus_views__ = {  # noqa: RUF012
        "label": "Hitos de plantilla",
        "display": "name",
        "nav": {"hidden": True},
        "labels": {
            "template_id": "Plantilla",
            "template_phase_id": "Fase",
            "name": "Nombre",
            "offset_days": "Días desde el arranque",
            "weight": "Peso",
        },
        "list": {
            "columns": ["name", "template_phase_id", "offset_days", "weight"],
            "default_order": "offset_days",
        },
        "form": {
            "layout": [["template_id", "template_phase_id"], ["name", "offset_days", "weight"]]
        },
    }


class TemplateDependency(NovvusModel):
    __resource__ = "template_dependencies"
    __table_args__ = (UniqueConstraint("predecessor_id", "successor_id"),)
    __novvus_api__ = {"permissions": _TEMPLATE_PERMS}  # noqa: RUF012

    template_id: Mapped[UUID] = _fk_required("template.id", "CASCADE")
    predecessor_id: Mapped[UUID] = _fk_required("template_task.id", "CASCADE")
    successor_id: Mapped[UUID] = _fk_required("template_task.id", "CASCADE")
    kind: Mapped[DependencyKind] = mapped_column(
        _enum(DependencyKind), default=DependencyKind.finish_to_start
    )
    lag_days: Mapped[int] = mapped_column(default=0)

    __novvus_views__ = {  # noqa: RUF012
        "label": "Dependencias de plantilla",
        "display": "kind",
        "nav": {"hidden": True},
        "labels": {
            "template_id": "Plantilla",
            "predecessor_id": "Predecesora",
            "successor_id": "Sucesora",
            "kind": "Tipo",
            "lag_days": "Desfase (días)",
        },
        "list": {"columns": ["predecessor_id", "successor_id", "kind", "lag_days"]},
        "form": {
            "layout": [["template_id"], ["predecessor_id", "successor_id"], ["kind", "lag_days"]]
        },
    }


class Project(NovvusModel):
    __resource__ = "projects"
    # Uniqueness of `code` per organization is a partial unique index in 0004
    # (rows created before 0004 keep an empty code). Registration goes through the validated
    # «Nuevo proyecto» action (code checked, template instantiated) and deletion through
    # «Eliminar» (only drafts, cancelled or archived projects): business.py.
    __novvus_api__ = {"disabled": ["create", "delete"]}  # noqa: RUF012

    name: Mapped[str] = mapped_column(String(200))
    code: Mapped[str] = mapped_column(String(40))
    description: Mapped[str] = mapped_column(String(4000), default="")
    kind: Mapped[ProjectKind] = mapped_column(_enum(ProjectKind), default=ProjectKind.internal)
    status: Mapped[ProjectStatus] = mapped_column(_enum(ProjectStatus), default=ProjectStatus.draft)
    health: Mapped[Health] = mapped_column(_enum(Health), default=Health.on_track)
    priority: Mapped[Priority] = mapped_column(_enum(Priority), default=Priority.medium)
    owner_user_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    # References to CRM entities BY ID only — resolved via its public API.
    # `opportunity_id` is the originating opportunity; further links live in project_links.
    opportunity_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    contact_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    company_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    # Denormalized display names fetched from the CRM API when linked.
    contact_name: Mapped[str] = mapped_column(String(200), default="")
    company_name: Mapped[str] = mapped_column(String(200), default="")
    template_id: Mapped[UUID | None] = _fk("template.id", "SET NULL")
    start_date: Mapped[date | None] = mapped_column(nullable=True)
    due_date: Mapped[date | None] = mapped_column(nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(nullable=True)
    archived_at: Mapped[datetime | None] = mapped_column(nullable=True)
    budget: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), default="MXN")
    progress_strategy: Mapped[ProgressStrategy] = mapped_column(
        _enum(ProgressStrategy), default=ProgressStrategy.tasks
    )
    # Computed by the progress engine (0-100) — never edited by hand.
    progress: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("0"))
    # Baseline: expected progress today according to the plan (0-100), if a baseline exists.
    planned_progress: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)

    __novvus_views__ = {  # noqa: RUF012
        "label": "Proyectos",
        "display": "name",
        "attachments": True,
        "chatter": True,
        "track": ["status", "health", "owner_user_id", "due_date", "priority"],
        "fields": {
            "progress": {"readonly": True},
            "health": {"readonly": True},
            "completed_at": {"readonly": True},
            "archived_at": {"readonly": True},
            "contact_name": {"readonly": True},
            "company_name": {"readonly": True},
        },
        "labels": {
            "name": "Nombre",
            "code": "Código",
            "description": "Descripción",
            "kind": "Tipo",
            "status": "Estado",
            "health": "Salud",
            "priority": "Prioridad",
            "owner_user_id": "Responsable",
            "opportunity_id": "Oportunidad (CRM)",
            "contact_id": "Contacto (CRM)",
            "company_id": "Cliente (CRM)",
            "contact_name": "Contacto",
            "company_name": "Cliente",
            "template_id": "Plantilla",
            "start_date": "Inicio",
            "due_date": "Conclusión estimada",
            "completed_at": "Concluido el",
            "archived_at": "Archivado el",
            "budget": "Presupuesto",
            "currency": "Moneda",
            "progress_strategy": "Estrategia de avance",
            "progress": "Avance (%)",
            "planned_progress": "Avance planificado (%)",
        },
        "list": {
            "columns": [
                "code",
                "name",
                "company_name",
                "owner_user_id",
                "status",
                "health",
                "priority",
                "progress",
                "due_date",
            ],
            "default_order": "-created_at",
            "mono": ["code"],
        },
        "form": {
            "layout": [
                ["code", "name"],
                ["kind", "status", "health", "priority"],
                ["owner_user_id", "template_id"],
                ["company_name", "contact_name"],
                ["start_date", "due_date"],
                ["budget", "currency"],
                ["progress_strategy", "progress", "planned_progress"],
                ["description"],
            ],
        },
        "kanban": {"group_by": "status", "card": ["code", "name", "owner_user_id", "due_date"]},
    }


class ProjectMember(NovvusModel):
    __resource__ = "project_members"
    __table_args__ = (UniqueConstraint("project_id", "user_id"),)
    __novvus_api__ = {"permissions": _PROJECT_PERMS}  # noqa: RUF012

    project_id: Mapped[UUID] = _fk_required("project.id", "CASCADE")
    user_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True))
    role: Mapped[str] = mapped_column(String(120), default="")

    __novvus_views__ = {  # noqa: RUF012
        "label": "Equipo",
        "display": "role",
        "nav": {"hidden": True},
        "labels": {"project_id": "Proyecto", "user_id": "Usuario", "role": "Rol"},
        "list": {"columns": ["user_id", "role"]},
        "form": {"layout": [["project_id"], ["user_id", "role"]]},
    }


class ProjectLink(NovvusModel):
    """M2M project ↔ CRM opportunity (ids only; names come from the CRM API)."""

    __resource__ = "project_links"
    __table_args__ = (UniqueConstraint("project_id", "opportunity_id"),)
    __novvus_api__ = {"permissions": _PROJECT_PERMS}  # noqa: RUF012

    project_id: Mapped[UUID] = _fk_required("project.id", "CASCADE")
    opportunity_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True))
    opportunity_name: Mapped[str] = mapped_column(String(200), default="")

    __novvus_views__ = {  # noqa: RUF012
        "label": "Oportunidades vinculadas",
        "display": "opportunity_name",
        "nav": {"hidden": True},
        "labels": {
            "project_id": "Proyecto",
            "opportunity_id": "Oportunidad (CRM)",
            "opportunity_name": "Oportunidad",
        },
        "list": {"columns": ["opportunity_name", "opportunity_id", "created_at"]},
        "form": {"layout": [["project_id"], ["opportunity_id", "opportunity_name"]]},
    }


class Phase(NovvusModel):
    __resource__ = "phases"
    __novvus_api__ = {"permissions": _PROJECT_PERMS}  # noqa: RUF012

    project_id: Mapped[UUID] = _fk_required("project.id", "CASCADE")
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(String(4000), default="")
    position: Mapped[int] = mapped_column(default=0)
    status: Mapped[PhaseStatus] = mapped_column(_enum(PhaseStatus), default=PhaseStatus.pending)
    owner_user_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    start_date: Mapped[date | None] = mapped_column(nullable=True)
    due_date: Mapped[date | None] = mapped_column(nullable=True)
    weight: Mapped[Decimal] = mapped_column(Numeric(7, 2), default=Decimal("1"))
    progress: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("0"))

    __novvus_views__ = {  # noqa: RUF012
        "label": "Fases",
        "display": "name",
        "chatter": True,
        "track": ["status", "owner_user_id", "due_date"],
        "fields": {"progress": {"readonly": True}},
        "labels": {
            "project_id": "Proyecto",
            "name": "Nombre",
            "description": "Descripción",
            "position": "Posición",
            "status": "Estado",
            "owner_user_id": "Responsable",
            "start_date": "Inicio",
            "due_date": "Fin",
            "weight": "Peso",
            "progress": "Avance (%)",
        },
        "list": {
            "columns": [
                "position",
                "name",
                "project_id",
                "status",
                "owner_user_id",
                "due_date",
                "progress",
            ],
            "default_order": "position",
        },
        "form": {
            "layout": [
                ["project_id", "name"],
                ["position", "status", "owner_user_id"],
                ["start_date", "due_date", "weight", "progress"],
                ["description"],
            ],
        },
    }


class Process(NovvusModel):
    """A workflow inside a project: ordered stages with validated transitions."""

    __resource__ = "processes"
    __novvus_api__ = {"permissions": _PROJECT_PERMS}  # noqa: RUF012

    project_id: Mapped[UUID] = _fk_required("project.id", "CASCADE")
    phase_id: Mapped[UUID | None] = _fk("phase.id", "SET NULL")
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(String(4000), default="")
    position: Mapped[int] = mapped_column(default=0)
    status: Mapped[ProcessStatus] = mapped_column(
        _enum(ProcessStatus), default=ProcessStatus.pending
    )
    owner_user_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    # The active stage; None before the process starts or after it finishes.
    current_stage_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    start_date: Mapped[date | None] = mapped_column(nullable=True)
    due_date: Mapped[date | None] = mapped_column(nullable=True)

    __novvus_views__ = {  # noqa: RUF012
        "label": "Procesos",
        "display": "name",
        "chatter": True,
        "track": ["status", "current_stage_id", "owner_user_id"],
        "fields": {"current_stage_id": {"readonly": True}},
        "labels": {
            "project_id": "Proyecto",
            "phase_id": "Fase",
            "name": "Nombre",
            "description": "Descripción",
            "position": "Posición",
            "status": "Estado",
            "owner_user_id": "Responsable",
            "current_stage_id": "Etapa actual",
            "start_date": "Inicio",
            "due_date": "Fin",
        },
        "list": {
            "columns": ["name", "project_id", "phase_id", "status", "owner_user_id", "due_date"],
            "default_order": "position",
        },
        "form": {
            "layout": [
                ["project_id", "phase_id"],
                ["name", "position", "status"],
                ["owner_user_id", "start_date", "due_date"],
                ["description"],
            ],
        },
    }


class ProcessStage(NovvusModel):
    __resource__ = "process_stages"
    __novvus_api__ = {"permissions": _PROJECT_PERMS}  # noqa: RUF012

    process_id: Mapped[UUID] = _fk_required("process.id", "CASCADE")
    name: Mapped[str] = mapped_column(String(200))
    position: Mapped[int] = mapped_column(default=0)
    status: Mapped[StageStatus] = mapped_column(_enum(StageStatus), default=StageStatus.pending)
    owner_user_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    is_mandatory: Mapped[bool] = mapped_column(default=True)
    requires_approval: Mapped[bool] = mapped_column(default=False)
    entry_conditions: Mapped[str] = mapped_column(String(2000), default="")
    exit_conditions: Mapped[str] = mapped_column(String(2000), default="")
    required_evidence: Mapped[str] = mapped_column(String(2000), default="")
    due_date: Mapped[date | None] = mapped_column(nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(nullable=True)

    __novvus_views__ = {  # noqa: RUF012
        "label": "Etapas de proceso",
        "display": "name",
        "nav": {"hidden": True},
        "fields": {"started_at": {"readonly": True}, "finished_at": {"readonly": True}},
        "labels": {
            "process_id": "Proceso",
            "name": "Nombre",
            "position": "Posición",
            "status": "Estado",
            "owner_user_id": "Responsable",
            "is_mandatory": "Obligatoria",
            "requires_approval": "Requiere aprobación",
            "entry_conditions": "Condiciones de entrada",
            "exit_conditions": "Condiciones de salida",
            "required_evidence": "Evidencias requeridas",
            "due_date": "Plazo",
            "started_at": "Iniciada el",
            "finished_at": "Terminada el",
        },
        "list": {
            "columns": [
                "position",
                "name",
                "status",
                "owner_user_id",
                "is_mandatory",
                "requires_approval",
                "due_date",
            ],
            "default_order": "position",
        },
        "form": {
            "layout": [
                ["process_id", "name", "position"],
                ["status", "owner_user_id", "due_date"],
                ["is_mandatory", "requires_approval"],
                ["entry_conditions"],
                ["exit_conditions"],
                ["required_evidence"],
                ["started_at", "finished_at"],
            ],
        },
    }


class ProcessTransition(NovvusModel):
    """Append-only history of process stage transitions."""

    __resource__ = "process_transitions"
    __novvus_api__ = {  # noqa: RUF012
        "permissions": _PROJECT_PERMS,
        "disabled": ["create", "update", "delete"],
    }

    process_id: Mapped[UUID] = _fk_required("process.id", "CASCADE")
    from_stage_id: Mapped[UUID | None] = _fk("process_stage.id", "SET NULL")
    to_stage_id: Mapped[UUID | None] = _fk("process_stage.id", "SET NULL")
    user_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    forced: Mapped[bool] = mapped_column(default=False)
    note: Mapped[str] = mapped_column(String(2000), default="")

    __novvus_views__ = {  # noqa: RUF012
        "label": "Historial de transiciones",
        "display": "note",
        "nav": {"hidden": True},
        "labels": {
            "process_id": "Proceso",
            "from_stage_id": "De la etapa",
            "to_stage_id": "A la etapa",
            "user_id": "Usuario",
            "forced": "Forzada",
            "note": "Nota",
        },
        "list": {
            "columns": ["created_at", "from_stage_id", "to_stage_id", "user_id", "forced", "note"],
            "default_order": "-created_at",
        },
    }


class Task(NovvusModel):
    __resource__ = "tasks"

    project_id: Mapped[UUID] = _fk_required("project.id", "CASCADE")
    phase_id: Mapped[UUID | None] = _fk("phase.id", "SET NULL")
    process_id: Mapped[UUID | None] = _fk("process.id", "SET NULL")
    stage_id: Mapped[UUID | None] = _fk("process_stage.id", "SET NULL")
    parent_id: Mapped[UUID | None] = _fk("task.id", "CASCADE")
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(String(4000), default="")
    status: Mapped[TaskStatus] = mapped_column(_enum(TaskStatus), default=TaskStatus.todo)
    priority: Mapped[Priority] = mapped_column(_enum(Priority), default=Priority.medium)
    assigned_user_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    position: Mapped[int] = mapped_column(default=0)
    start_date: Mapped[date | None] = mapped_column(nullable=True)
    due_date: Mapped[datetime | None] = mapped_column(nullable=True)
    estimated_hours: Mapped[Decimal] = mapped_column(Numeric(8, 2), default=Decimal("0"))
    logged_hours: Mapped[Decimal] = mapped_column(Numeric(8, 2), default=Decimal("0"))
    progress: Mapped[int] = mapped_column(default=0)  # 0-100, set by people or by subtasks
    weight: Mapped[Decimal] = mapped_column(Numeric(7, 2), default=Decimal("1"))
    is_blocked: Mapped[bool] = mapped_column(default=False)
    blocked_reason: Mapped[str] = mapped_column(String(1000), default="")
    completed_at: Mapped[datetime | None] = mapped_column(nullable=True)
    # Future link to work executed by a specialized module (e.g. an operations
    # module): {module, model, id} by reference only, never a table join.
    external_module: Mapped[str] = mapped_column(String(60), default="")
    external_model: Mapped[str] = mapped_column(String(60), default="")
    external_id: Mapped[str] = mapped_column(String(60), default="")

    __novvus_views__ = {  # noqa: RUF012
        "label": "Actividades",
        "display": "title",
        "attachments": True,
        "chatter": True,
        "track": ["status", "assigned_user_id", "due_date", "progress", "is_blocked"],
        "fields": {"completed_at": {"readonly": True}},
        "labels": {
            "project_id": "Proyecto",
            "phase_id": "Fase",
            "process_id": "Proceso",
            "stage_id": "Etapa del proceso",
            "parent_id": "Actividad superior",
            "title": "Título",
            "description": "Descripción",
            "status": "Estado",
            "priority": "Prioridad",
            "assigned_user_id": "Responsable",
            "position": "Posición",
            "start_date": "Inicio",
            "due_date": "Fecha límite",
            "estimated_hours": "Horas estimadas",
            "logged_hours": "Horas registradas",
            "progress": "Avance (%)",
            "weight": "Peso",
            "is_blocked": "Bloqueada",
            "blocked_reason": "Causa del bloqueo",
            "completed_at": "Completada el",
            "external_module": "Módulo externo",
            "external_model": "Modelo externo",
            "external_id": "Registro externo",
        },
        "list": {
            "columns": [
                "title",
                "project_id",
                "phase_id",
                "status",
                "priority",
                "assigned_user_id",
                "due_date",
                "progress",
                "is_blocked",
            ],
            "default_order": "due_date",
        },
        "form": {
            "layout": [
                ["title", "project_id"],
                ["phase_id", "process_id", "stage_id", "parent_id"],
                ["status", "priority", "assigned_user_id"],
                ["start_date", "due_date"],
                ["estimated_hours", "logged_hours", "progress", "weight"],
                ["is_blocked", "blocked_reason"],
                ["description"],
                ["external_module", "external_model", "external_id"],
            ],
        },
        "kanban": {
            "group_by": "status",
            "card": ["title", "assigned_user_id", "due_date", "progress"],
        },
        "calendar": {"date_field": "due_date", "title": "title"},
    }


class TaskParticipant(NovvusModel):
    __resource__ = "task_participants"
    __table_args__ = (UniqueConstraint("task_id", "user_id"),)
    __novvus_api__ = {"permissions": _TASK_PERMS}  # noqa: RUF012

    task_id: Mapped[UUID] = _fk_required("task.id", "CASCADE")
    user_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True))

    __novvus_views__ = {  # noqa: RUF012
        "label": "Participantes",
        "display": "user_id",
        "nav": {"hidden": True},
        "labels": {"task_id": "Actividad", "user_id": "Usuario"},
        "list": {"columns": ["user_id", "created_at"]},
        "form": {"layout": [["task_id", "user_id"]]},
    }


class TaskDependency(NovvusModel):
    """Dependency between two tasks of the same project. Cycles are rejected in
    business.py (the auto-API create is disabled)."""

    __resource__ = "task_dependencies"
    __table_args__ = (UniqueConstraint("predecessor_id", "successor_id"),)
    __novvus_api__ = {"permissions": _TASK_PERMS, "disabled": ["create", "update"]}  # noqa: RUF012

    project_id: Mapped[UUID] = _fk_required("project.id", "CASCADE")
    predecessor_id: Mapped[UUID] = _fk_required("task.id", "CASCADE")
    successor_id: Mapped[UUID] = _fk_required("task.id", "CASCADE")
    kind: Mapped[DependencyKind] = mapped_column(
        _enum(DependencyKind), default=DependencyKind.finish_to_start
    )
    lag_days: Mapped[int] = mapped_column(default=0)

    __novvus_views__ = {  # noqa: RUF012
        "label": "Dependencias",
        "display": "kind",
        "nav": {"hidden": True},
        "labels": {
            "project_id": "Proyecto",
            "predecessor_id": "Predecesora",
            "successor_id": "Sucesora",
            "kind": "Tipo",
            "lag_days": "Desfase (días)",
        },
        "list": {"columns": ["predecessor_id", "successor_id", "kind", "lag_days"]},
    }


class Milestone(NovvusModel):
    __resource__ = "milestones"
    __novvus_api__ = {"permissions": _PROJECT_PERMS}  # noqa: RUF012

    project_id: Mapped[UUID] = _fk_required("project.id", "CASCADE")
    phase_id: Mapped[UUID | None] = _fk("phase.id", "SET NULL")
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(String(4000), default="")
    due_date: Mapped[date | None] = mapped_column(nullable=True)
    owner_user_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    status: Mapped[MilestoneStatus] = mapped_column(
        _enum(MilestoneStatus), default=MilestoneStatus.pending
    )
    reached_at: Mapped[datetime | None] = mapped_column(nullable=True)
    weight: Mapped[Decimal] = mapped_column(Numeric(7, 2), default=Decimal("1"))

    __novvus_views__ = {  # noqa: RUF012
        "label": "Hitos",
        "display": "name",
        "chatter": True,
        "track": ["status", "due_date", "owner_user_id"],
        "fields": {"reached_at": {"readonly": True}},
        "labels": {
            "project_id": "Proyecto",
            "phase_id": "Fase",
            "name": "Nombre",
            "description": "Descripción",
            "due_date": "Fecha",
            "owner_user_id": "Responsable",
            "status": "Estado",
            "reached_at": "Alcanzado el",
            "weight": "Peso",
        },
        "list": {
            "columns": ["name", "project_id", "phase_id", "due_date", "owner_user_id", "status"],
            "default_order": "due_date",
        },
        "form": {
            "layout": [
                ["project_id", "phase_id"],
                ["name", "status"],
                ["due_date", "owner_user_id", "weight"],
                ["description"],
                ["reached_at"],
            ],
        },
        "calendar": {"date_field": "due_date", "title": "name"},
    }


class Deliverable(NovvusModel):
    __resource__ = "deliverables"
    __novvus_api__ = {"permissions": _PROJECT_PERMS}  # noqa: RUF012

    project_id: Mapped[UUID] = _fk_required("project.id", "CASCADE")
    milestone_id: Mapped[UUID | None] = _fk("milestone.id", "SET NULL")
    task_id: Mapped[UUID | None] = _fk("task.id", "SET NULL")
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(String(4000), default="")
    status: Mapped[DeliverableStatus] = mapped_column(
        _enum(DeliverableStatus), default=DeliverableStatus.pending
    )
    owner_user_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    due_date: Mapped[date | None] = mapped_column(nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(nullable=True)

    __novvus_views__ = {  # noqa: RUF012
        "label": "Entregables",
        "display": "name",
        "attachments": True,
        "chatter": True,
        "track": ["status", "owner_user_id", "due_date"],
        "fields": {"delivered_at": {"readonly": True}},
        "labels": {
            "project_id": "Proyecto",
            "milestone_id": "Hito",
            "task_id": "Actividad",
            "name": "Nombre",
            "description": "Descripción",
            "status": "Estado",
            "owner_user_id": "Responsable",
            "due_date": "Fecha comprometida",
            "delivered_at": "Entregado el",
        },
        "list": {
            "columns": [
                "name",
                "project_id",
                "milestone_id",
                "status",
                "owner_user_id",
                "due_date",
            ],
            "default_order": "due_date",
        },
        "form": {
            "layout": [
                ["project_id", "milestone_id", "task_id"],
                ["name", "status"],
                ["owner_user_id", "due_date", "delivered_at"],
                ["description"],
            ],
        },
    }


class Risk(NovvusModel):
    __resource__ = "risks"
    __novvus_api__ = {"permissions": _PROJECT_PERMS}  # noqa: RUF012

    project_id: Mapped[UUID] = _fk_required("project.id", "CASCADE")
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(String(4000), default="")
    probability: Mapped[RiskLevel] = mapped_column(_enum(RiskLevel), default=RiskLevel.medium)
    impact: Mapped[RiskLevel] = mapped_column(_enum(RiskLevel), default=RiskLevel.medium)
    # 1..9 = probability x impact (low=1, medium=2, high=3); kept by business.py.
    score: Mapped[int] = mapped_column(default=4)
    owner_user_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    mitigation: Mapped[str] = mapped_column(String(4000), default="")
    status: Mapped[RiskStatus] = mapped_column(_enum(RiskStatus), default=RiskStatus.open)
    review_date: Mapped[date | None] = mapped_column(nullable=True)

    __novvus_views__ = {  # noqa: RUF012
        "label": "Riesgos",
        "display": "title",
        "chatter": True,
        "track": ["status", "probability", "impact", "owner_user_id"],
        "fields": {"score": {"readonly": True}},
        "labels": {
            "project_id": "Proyecto",
            "title": "Riesgo",
            "description": "Descripción",
            "probability": "Probabilidad",
            "impact": "Impacto",
            "score": "Puntuación",
            "owner_user_id": "Responsable",
            "mitigation": "Plan de mitigación",
            "status": "Estado",
            "review_date": "Próxima revisión",
        },
        "list": {
            "columns": [
                "title",
                "project_id",
                "probability",
                "impact",
                "score",
                "status",
                "owner_user_id",
                "review_date",
            ],
            "default_order": "-score",
        },
        "form": {
            "layout": [
                ["project_id", "title"],
                ["probability", "impact", "score", "status"],
                ["owner_user_id", "review_date"],
                ["description"],
                ["mitigation"],
            ],
        },
        "kanban": {"group_by": "status", "card": ["title", "probability", "impact"]},
    }


class Approval(NovvusModel):
    """Approval request on a deliverable, milestone, process stage or task."""

    __resource__ = "approvals"
    __novvus_api__ = {"permissions": _PROJECT_PERMS, "disabled": ["update"]}  # noqa: RUF012

    project_id: Mapped[UUID] = _fk_required("project.id", "CASCADE")
    target_kind: Mapped[ApprovalTarget] = mapped_column(_enum(ApprovalTarget))
    target_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True))
    target_label: Mapped[str] = mapped_column(String(200), default="")
    requested_by_user_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    approver_user_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    status: Mapped[ApprovalStatus] = mapped_column(
        _enum(ApprovalStatus), default=ApprovalStatus.pending
    )
    decided_at: Mapped[datetime | None] = mapped_column(nullable=True)
    note: Mapped[str] = mapped_column(String(2000), default="")

    __novvus_views__ = {  # noqa: RUF012
        "label": "Aprobaciones",
        "display": "target_label",
        "chatter": True,
        "track": ["status", "approver_user_id"],
        "fields": {"decided_at": {"readonly": True}, "status": {"readonly": True}},
        "labels": {
            "project_id": "Proyecto",
            "target_kind": "Qué se aprueba",
            "target_id": "Registro",
            "target_label": "Elemento",
            "requested_by_user_id": "Solicitada por",
            "approver_user_id": "Aprobador",
            "status": "Estado",
            "decided_at": "Decidida el",
            "note": "Nota",
        },
        "list": {
            "columns": [
                "target_label",
                "target_kind",
                "project_id",
                "approver_user_id",
                "status",
                "decided_at",
            ],
            "default_order": "-created_at",
        },
        "form": {
            "layout": [
                ["project_id", "target_kind", "target_id"],
                ["target_label", "approver_user_id"],
                ["status", "decided_at"],
                ["note"],
            ],
        },
    }


# Registration order matters: referenced tables first.
ALL_MODELS: list[type[NovvusModel]] = [
    Template,
    TemplatePhase,
    TemplateProcess,
    TemplateTask,
    TemplateMilestone,
    TemplateDependency,
    Project,
    ProjectMember,
    ProjectLink,
    Phase,
    Process,
    ProcessStage,
    ProcessTransition,
    Task,
    TaskParticipant,
    TaskDependency,
    Milestone,
    Deliverable,
    Risk,
    Approval,
]
