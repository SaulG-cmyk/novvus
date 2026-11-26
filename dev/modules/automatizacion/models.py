"""Modelos de Automatización de Procesos."""

from datetime import datetime
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

_DASHBOARD = "dashboard" in VIEW_KEYS
_CHOICES = "choices" in VIEW_KEYS


class ProcessStatus(StrEnum):
    active = "active"
    paused = "paused"
    draft = "draft"
    archived = "archived"


class TriggerType(StrEnum):
    manual = "manual"
    scheduled = "scheduled"
    event = "event"
    webhook = "webhook"


class StepStatus(StrEnum):
    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"
    skipped = "skipped"


class ExecutionStatus(StrEnum):
    running = "running"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


def _enum(enum_cls: type[StrEnum]) -> SAEnum:
    return SAEnum(enum_cls, native_enum=False, length=20)


class Process(NovvusModel):
    __resource__ = "processes"
    __novvus_api__ = {"disabled": {"list", "get", "create", "update", "delete"}}

    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(String(4000), default="")
    status: Mapped[ProcessStatus] = mapped_column(_enum(ProcessStatus), default=ProcessStatus.draft)
    trigger_type: Mapped[TriggerType] = mapped_column(_enum(TriggerType), default=TriggerType.manual)
    trigger_config: Mapped[str] = mapped_column(String(2000), default="")  # JSON config for schedule/event
    owner_user_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)

    __novvus_views__ = {
        "nav": {"icon": "bot"},
        "label": "Procesos",
        "display": "name",
        "attachments": True,
        "chatter": True,
        "track": ["status", "trigger_type"],
        "labels": {
            "name": "Nombre",
            "description": "Descripción",
            "status": "Estado",
            "trigger_type": "Tipo de disparador",
            "trigger_config": "Configuración del disparador",
            "owner_user_id": "Responsable",
        },
        "list": {"columns": ["name", "status", "trigger_type"], "default_order": "name"},
        "form": {"layout": [["name", "status"], ["trigger_type"], ["trigger_config"], ["description"], ["owner_user_id"]]},
        **({"choices": {
            "status": {
                "active": "Activo",
                "paused": "Pausado",
                "draft": "Borrador",
                "archived": "Archivado",
            },
            "trigger_type": {
                "manual": "Manual",
                "scheduled": "Programado",
                "event": "Por evento",
                "webhook": "Webhook",
            },
        }} if _CHOICES else {}),
        "kanban": {"group_by": "status", "card": ["name", "trigger_type"]},
        **({"dashboard": {
            "path": "reports/dashboard",
            "title": "Bandeja unificada de trabajo",
            "order": 10,
        }} if _DASHBOARD else {}),
    }


class ProcessStep(NovvusModel):
    __resource__ = "process_steps"

    process_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), ForeignKey("process.id", ondelete="CASCADE"))
    process_name: Mapped[str] = mapped_column(String(200), default="")
    name: Mapped[str] = mapped_column(String(200))
    position: Mapped[int] = mapped_column(default=0)
    action_type: Mapped[str] = mapped_column(String(60), default="")  # e.g. "send_email", "create_record", "webhook"
    action_config: Mapped[str] = mapped_column(String(4000), default="")  # JSON
    is_active: Mapped[bool] = mapped_column(default=True)

    __novvus_views__ = {
        "label": "Pasos",
        "display": "name",
        "attachments": False,
        "chatter": False,
        "labels": {
            "process_id": "Proceso",
            "process_name": "Proceso",
            "name": "Nombre",
            "position": "Posición",
            "action_type": "Tipo de acción",
            "action_config": "Configuración",
            "is_active": "Activo",
        },
        "list": {"columns": ["process_name", "name", "position", "action_type", "is_active"], "default_order": "position"},
        "form": {"layout": [["process_id"], ["name", "position"], ["action_type"], ["action_config"], ["is_active"]]},
    }


class ProcessExecution(NovvusModel):
    __resource__ = "process_executions"

    process_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), ForeignKey("process.id", ondelete="CASCADE"))
    process_name: Mapped[str] = mapped_column(String(200), default="")
    status: Mapped[ExecutionStatus] = mapped_column(_enum(ExecutionStatus), default=ExecutionStatus.running)
    started_at: Mapped[datetime | None] = mapped_column(nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(nullable=True)
    result: Mapped[str] = mapped_column(String(4000), default="")
    error: Mapped[str] = mapped_column(String(4000), default="")
    triggered_by: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)

    __novvus_views__ = {
        "label": "Ejecuciones",
        "display": "id",
        "attachments": False,
        "chatter": False,
        "labels": {
            "process_id": "Proceso",
            "process_name": "Proceso",
            "status": "Estado",
            "started_at": "Inicio",
            "finished_at": "Fin",
            "result": "Resultado",
            "error": "Error",
            "triggered_by": "Disparado por",
        },
        "list": {"columns": ["process_name", "status", "started_at", "finished_at"], "default_order": "-started_at"},
        "form": {"layout": [["process_id", "status"], ["started_at", "finished_at"], ["result"], ["error"], ["triggered_by"]]},
        **({"choices": {
            "status": {
                "running": "En ejecución",
                "completed": "Completada",
                "failed": "Fallida",
                "cancelled": "Cancelada",
            }
        }} if _CHOICES else {}),
        "kanban": {"group_by": "status", "card": ["process_name", "started_at"]},
    }


class ProcessLog(NovvusModel):
    __resource__ = "process_logs"

    execution_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), ForeignKey("process_execution.id", ondelete="CASCADE"))
    step_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), ForeignKey("process_step.id", ondelete="SET NULL"), nullable=True)
    level: Mapped[str] = mapped_column(String(10), default="info")
    message: Mapped[str] = mapped_column(String(4000), default="")
    logged_at: Mapped[datetime | None] = mapped_column(nullable=True)
    process_name: Mapped[str] = mapped_column(String(200), default="")

    __novvus_views__ = {
        "label": "Logs",
        "display": "message",
        "attachments": False,
        "chatter": False,
        "labels": {
            "process_name": "Proceso",
            "execution_id": "Ejecución",
            "step_id": "Paso",
            "level": "Nivel",
            "message": "Mensaje",
            "logged_at": "Fecha",
        },
        "list": {"columns": ["process_name", "level", "message", "logged_at"], "default_order": "-logged_at"},
        "form": {"layout": [["execution_id", "step_id"], ["level", "logged_at"], ["message"]]},
    }


class Notification(NovvusModel):
    __resource__ = "notifications"

    user_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    title: Mapped[str] = mapped_column(String(200))
    message: Mapped[str] = mapped_column(String(4000), default="")
    kind: Mapped[str] = mapped_column(String(40), default="info")  # info, success, warning, danger
    is_read: Mapped[bool] = mapped_column(default=False)
    link: Mapped[str] = mapped_column(String(500), default="")

    __novvus_views__ = {
        "label": "Notificaciones",
        "display": "title",
        "attachments": False,
        "chatter": False,
        "labels": {
            "user_id": "Usuario",
            "title": "Título",
            "message": "Mensaje",
            "kind": "Tipo",
            "is_read": "Leída",
            "link": "Enlace",
        },
        "list": {"columns": ["title", "kind", "is_read", "created_at"], "default_order": "-created_at"},
        "form": {"layout": [["title", "kind"], ["message"], ["user_id", "is_read"], ["link"]]},
    }


ALL_MODELS = [Process, ProcessStep, ProcessExecution, ProcessLog, Notification]
