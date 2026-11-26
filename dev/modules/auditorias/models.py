"""Modelos de Auditorías."""

from datetime import date, datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy import Enum as SAEnum
from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from novvus_sdk import NovvusModel

try:
    from novvus_sdk import VIEW_KEYS
except Exception:
    VIEW_KEYS = frozenset()

_CHOICES = "choices" in VIEW_KEYS
_DASHBOARD = "dashboard" in VIEW_KEYS


class AuditType(StrEnum):
    internal = "internal"
    external = "external"
    compliance = "compliance"
    financial = "financial"
    operational = "operational"


class AuditStatus(StrEnum):
    planned = "planned"
    in_progress = "in_progress"
    completed = "completed"
    cancelled = "cancelled"


class FindingSeverity(StrEnum):
    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"


class FindingStatus(StrEnum):
    open = "open"
    in_progress = "in_progress"
    closed = "closed"
    accepted = "accepted"


class ChecklistResult(StrEnum):
    pass_ = "pass"
    fail = "fail"
    na = "na"
    pending = "pending"


def _enum(enum_cls: type[StrEnum]) -> SAEnum:
    return SAEnum(enum_cls, native_enum=False, length=20)


class Audit(NovvusModel):
    __resource__ = "audits"

    name: Mapped[str] = mapped_column(String(200))
    audit_type: Mapped[AuditType] = mapped_column(_enum(AuditType), default=AuditType.internal)
    status: Mapped[AuditStatus] = mapped_column(_enum(AuditStatus), default=AuditStatus.planned)
    scope: Mapped[str] = mapped_column(String(2000), default="")
    start_date: Mapped[date | None] = mapped_column(nullable=True)
    end_date: Mapped[date | None] = mapped_column(nullable=True)
    auditor_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    notes: Mapped[str] = mapped_column(String(4000), default="")
    owner_user_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)

    __novvus_views__ = {
        "nav": {"icon": "shield"},
        "label": "Auditorías",
        "display": "name",
        "attachments": True,
        "chatter": True,
        "track": ["status", "auditor_id"],
        "labels": {
            "name": "Nombre",
            "audit_type": "Tipo",
            "status": "Estado",
            "scope": "Alcance",
            "start_date": "Fecha inicio",
            "end_date": "Fecha fin",
            "auditor_id": "Auditor",
            "notes": "Notas",
            "owner_user_id": "Responsable",
        },
        "list": {"columns": ["name", "audit_type", "status", "start_date", "end_date"], "default_order": "-start_date"},
        "form": {"layout": [["name", "audit_type"], ["status"], ["scope"], ["start_date", "end_date"], ["auditor_id", "owner_user_id"], ["notes"]]},
        **({"choices": {
            "audit_type": {
                "internal": "Interna",
                "external": "Externa",
                "compliance": "Cumplimiento",
                "financial": "Financiera",
                "operational": "Operativa",
            },
            "status": {
                "planned": "Planeada",
                "in_progress": "En progreso",
                "completed": "Completada",
                "cancelled": "Cancelada",
            },
        }} if _CHOICES else {}),
        **({"dashboard": {"path": "reports/dashboard", "title": "Panel de auditorías", "order": 10}} if _DASHBOARD else {}),
        "kanban": {"group_by": "status", "card": ["name", "audit_type"]},
        "calendar": {"date_field": "start_date", "title": "name"},
    }


class AuditFinding(NovvusModel):
    __resource__ = "audit_findings"

    audit_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), ForeignKey("audit.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(String(4000), default="")
    severity: Mapped[FindingSeverity] = mapped_column(_enum(FindingSeverity), default=FindingSeverity.medium)
    status: Mapped[FindingStatus] = mapped_column(_enum(FindingStatus), default=FindingStatus.open)
    responsible_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    due_date: Mapped[date | None] = mapped_column(nullable=True)
    notes: Mapped[str] = mapped_column(String(4000), default="")

    __novvus_views__ = {
        "label": "Hallazgos",
        "display": "title",
        "attachments": True,
        "chatter": True,
        "track": ["status", "severity", "responsible_id"],
        "labels": {
            "audit_id": "Auditoría",
            "title": "Título",
            "description": "Descripción",
            "severity": "Severidad",
            "status": "Estado",
            "responsible_id": "Responsable",
            "due_date": "Fecha límite",
            "notes": "Notas",
        },
        "list": {"columns": ["audit_id", "title", "severity", "status", "due_date"], "default_order": "-due_date"},
        "form": {"layout": [["audit_id"], ["title"], ["severity", "status"], ["responsible_id", "due_date"], ["description"], ["notes"]]},
        **({"choices": {
            "severity": {
                "low": "Baja",
                "medium": "Media",
                "high": "Alta",
                "critical": "Crítica",
            },
            "status": {
                "open": "Abierto",
                "in_progress": "En progreso",
                "closed": "Cerrado",
                "accepted": "Aceptado",
            },
        }} if _CHOICES else {}),
        "kanban": {"group_by": "status", "card": ["title", "severity"]},
    }


class AuditChecklist(NovvusModel):
    __resource__ = "audit_checklists"

    audit_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), ForeignKey("audit.id", ondelete="CASCADE"))
    item: Mapped[str] = mapped_column(String(400))
    result: Mapped[ChecklistResult] = mapped_column(_enum(ChecklistResult), default=ChecklistResult.pending)
    notes: Mapped[str] = mapped_column(String(4000), default="")

    __novvus_views__ = {
        "label": "Listas de verificación",
        "display": "item",
        "attachments": False,
        "chatter": False,
        "labels": {
            "audit_id": "Auditoría",
            "item": "Ítem",
            "result": "Resultado",
            "notes": "Notas",
        },
        "list": {"columns": ["audit_id", "item", "result"], "default_order": "audit_id"},
        "form": {"layout": [["audit_id"], ["item"], ["result"], ["notes"]]},
        **({"choices": {
            "result": {
                "pass": "Aprobado",
                "fail": "Reprobado",
                "na": "No aplica",
                "pending": "Pendiente",
            }
        }} if _CHOICES else {}),
        "kanban": {"group_by": "result", "card": ["item"]},
    }


class AuditReport(NovvusModel):
    __resource__ = "audit_reports"

    audit_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), ForeignKey("audit.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(200))
    content: Mapped[str] = mapped_column(String(10000), default="")
    published_date: Mapped[datetime | None] = mapped_column(nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="draft")

    __novvus_views__ = {
        "label": "Informes",
        "display": "title",
        "attachments": True,
        "chatter": True,
        "track": ["status"],
        "labels": {
            "audit_id": "Auditoría",
            "title": "Título",
            "content": "Contenido",
            "published_date": "Fecha de publicación",
            "status": "Estado",
        },
        "list": {"columns": ["audit_id", "title", "status", "published_date"], "default_order": "-published_date"},
        "form": {"layout": [["audit_id"], ["title"], ["status", "published_date"], ["content"]]},
    }


ALL_MODELS = [Audit, AuditFinding, AuditChecklist, AuditReport]
