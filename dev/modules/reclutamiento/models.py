"""Modelos de Reclutamiento. Las columnas de sistema vienen del SDK."""

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from sqlalchemy import Enum as SAEnum
from sqlalchemy import ForeignKey, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from novvus_sdk import NovvusModel

try:
    from novvus_sdk import VIEW_KEYS
except Exception:
    VIEW_KEYS = frozenset()

_CHOICES = "choices" in VIEW_KEYS
_DASHBOARD = "dashboard" in VIEW_KEYS


class JobStatus(StrEnum):
    draft = "draft"
    open = "open"
    closed = "closed"
    cancelled = "cancelled"


class EmploymentType(StrEnum):
    full_time = "full_time"
    part_time = "part_time"
    contract = "contract"
    internship = "internship"
    freelance = "freelance"


class CandidateStatus(StrEnum):
    new = "new"
    screening = "screening"
    interview = "interview"
    offer = "offer"
    hired = "hired"
    rejected = "rejected"
    withdrawn = "withdrawn"


class ApplicationStage(StrEnum):
    applied = "applied"
    screening = "screening"
    interview = "interview"
    technical = "technical"
    offer = "offer"
    hired = "hired"
    rejected = "rejected"


class InterviewResult(StrEnum):
    pending = "pending"
    passed = "passed"
    failed = "failed"
    no_show = "no_show"


class OfferStatus(StrEnum):
    draft = "draft"
    sent = "sent"
    accepted = "accepted"
    rejected = "rejected"
    expired = "expired"


def _enum(enum_cls: type[StrEnum]) -> SAEnum:
    return SAEnum(enum_cls, native_enum=False, length=20)


class JobPosition(NovvusModel):
    __resource__ = "job_positions"

    name: Mapped[str] = mapped_column(String(200))
    department: Mapped[str] = mapped_column(String(120), default="")
    description: Mapped[str] = mapped_column(String(4000), default="")
    requirements: Mapped[str] = mapped_column(String(4000), default="")
    status: Mapped[JobStatus] = mapped_column(_enum(JobStatus), default=JobStatus.draft)
    employment_type: Mapped[EmploymentType] = mapped_column(_enum(EmploymentType), default=EmploymentType.full_time)
    location: Mapped[str] = mapped_column(String(200), default="")
    salary_min: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"))
    salary_max: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"))
    currency: Mapped[str] = mapped_column(String(3), default="MXN")
    owner_user_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)

    __novvus_views__ = {
        "label": "Puestos",
        "display": "name",
        "attachments": True,
        "chatter": True,
        "track": ["status", "owner_user_id"],
        "labels": {
            "name": "Nombre del puesto",
            "department": "Departamento",
            "description": "Descripción",
            "requirements": "Requisitos",
            "status": "Estado",
            "employment_type": "Tipo de empleo",
            "location": "Ubicación",
            "salary_min": "Salario mínimo",
            "salary_max": "Salario máximo",
            "currency": "Moneda",
            "owner_user_id": "Responsable",
        },
        "list": {
            "columns": ["name", "department", "status", "employment_type", "location"],
            "default_order": "name",
        },
        "form": {
            "layout": [
                ["name", "department"],
                ["status", "employment_type"],
                ["location"],
                ["salary_min", "salary_max", "currency"],
                ["description"],
                ["requirements"],
                ["owner_user_id"],
            ],
        },
        **({"choices": {
            "status": {
                "draft": "Borrador",
                "open": "Abierto",
                "closed": "Cerrado",
                "cancelled": "Cancelado",
            },
            "employment_type": {
                "full_time": "Tiempo completo",
                "part_time": "Medio tiempo",
                "contract": "Contrato",
                "internship": "Prácticas",
                "freelance": "Freelance",
            },
        }} if _CHOICES else {}),
        "kanban": {"group_by": "status", "card": ["name", "department", "location"]},
    }


class Candidate(NovvusModel):
    __resource__ = "candidates"

    name: Mapped[str] = mapped_column(String(200))
    email: Mapped[str] = mapped_column(String(254), default="")
    phone: Mapped[str] = mapped_column(String(40), default="")
    mobile: Mapped[str] = mapped_column(String(40), default="")
    resume: Mapped[str] = mapped_column(String(4000), default="")
    skills: Mapped[str] = mapped_column(String(2000), default="")
    source: Mapped[str] = mapped_column(String(120), default="")
    status: Mapped[CandidateStatus] = mapped_column(_enum(CandidateStatus), default=CandidateStatus.new)
    notes: Mapped[str] = mapped_column(String(4000), default="")
    owner_user_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)

    __novvus_api__ = {"search": ["name", "email", "skills"]}

    __novvus_views__ = {
        "nav": {"icon": "user-plus"},
        "label": "Candidatos",
        "display": "name",
        "attachments": True,
        "chatter": True,
        "track": ["status", "owner_user_id"],
        "labels": {
            "name": "Nombre",
            "email": "Correo",
            "phone": "Teléfono",
            "mobile": "Móvil",
            "resume": "Currículum",
            "skills": "Habilidades",
            "source": "Fuente",
            "status": "Estado",
            "notes": "Notas",
            "owner_user_id": "Responsable",
        },
        "list": {
            "columns": ["name", "email", "status", "source", "phone"],
            "default_order": "name",
        },
        "form": {
            "layout": [
                ["name"],
                ["email", "phone", "mobile"],
                ["source", "status"],
                ["skills"],
                ["resume"],
                ["notes"],
                ["owner_user_id"],
            ],
        },
        **({"choices": {
            "status": {
                "new": "Nuevo",
                "screening": "Filtrado",
                "interview": "Entrevista",
                "offer": "Oferta",
                "hired": "Contratado",
                "rejected": "Rechazado",
                "withdrawn": "Retirado",
            }
        }} if _CHOICES else {}),
        **({"dashboard": {"path": "reports/dashboard", "title": "Panel de reclutamiento", "order": 10}} if _DASHBOARD else {}),
        "kanban": {"group_by": "status", "card": ["name", "email", "source"]},
    }


class Application(NovvusModel):
    __resource__ = "applications"

    candidate_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), ForeignKey("candidate.id", ondelete="CASCADE"))
    job_position_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), ForeignKey("job_position.id", ondelete="CASCADE"))
    stage: Mapped[ApplicationStage] = mapped_column(_enum(ApplicationStage), default=ApplicationStage.applied)
    rating: Mapped[int] = mapped_column(default=0)
    notes: Mapped[str] = mapped_column(String(4000), default="")
    applied_date: Mapped[datetime | None] = mapped_column(nullable=True)
    owner_user_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)

    __novvus_views__ = {
        "label": "Aplicaciones",
        "display": "id",
        "attachments": True,
        "chatter": True,
        "track": ["stage", "rating"],
        "labels": {
            "candidate_id": "Candidato",
            "job_position_id": "Puesto",
            "stage": "Etapa",
            "rating": "Calificación",
            "notes": "Notas",
            "applied_date": "Fecha de aplicación",
            "owner_user_id": "Responsable",
        },
        "list": {
            "columns": ["candidate_id", "job_position_id", "stage", "rating", "applied_date"],
            "default_order": "-applied_date",
        },
        "form": {
            "layout": [
                ["candidate_id", "job_position_id"],
                ["stage", "rating"],
                ["applied_date"],
                ["notes"],
                ["owner_user_id"],
            ],
        },
        **({"choices": {
            "stage": {
                "applied": "Aplicado",
                "screening": "Filtrado",
                "interview": "Entrevista",
                "technical": "Técnica",
                "offer": "Oferta",
                "hired": "Contratado",
                "rejected": "Rechazado",
            }
        }} if _CHOICES else {}),
        "kanban": {"group_by": "stage", "card": ["candidate_id", "job_position_id", "rating"]},
    }


class Interview(NovvusModel):
    __resource__ = "interviews"

    application_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), ForeignKey("application.id", ondelete="CASCADE"))
    date: Mapped[datetime | None] = mapped_column(nullable=True)
    interviewer_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    notes: Mapped[str] = mapped_column(String(4000), default="")
    rating: Mapped[int] = mapped_column(default=0)
    result: Mapped[InterviewResult] = mapped_column(_enum(InterviewResult), default=InterviewResult.pending)

    __novvus_views__ = {
        "label": "Entrevistas",
        "display": "id",
        "attachments": True,
        "chatter": True,
        "track": ["result", "rating"],
        "labels": {
            "application_id": "Aplicación",
            "date": "Fecha",
            "interviewer_id": "Entrevistador",
            "notes": "Notas",
            "rating": "Calificación",
            "result": "Resultado",
        },
        "list": {
            "columns": ["application_id", "date", "interviewer_id", "result", "rating"],
            "default_order": "-date",
        },
        "form": {
            "layout": [
                ["application_id", "interviewer_id"],
                ["date", "result", "rating"],
                ["notes"],
            ],
        },
        **({"choices": {
            "result": {
                "pending": "Pendiente",
                "passed": "Aprobado",
                "failed": "Reprobado",
                "no_show": "No asistió",
            }
        }} if _CHOICES else {}),
        "kanban": {"group_by": "result", "card": ["application_id", "date", "rating"]},
        "calendar": {"date_field": "date", "title": "application_id"},
    }


class Offer(NovvusModel):
    __resource__ = "offers"

    application_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), ForeignKey("application.id", ondelete="CASCADE"))
    salary: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"))
    currency: Mapped[str] = mapped_column(String(3), default="MXN")
    start_date: Mapped[date | None] = mapped_column(nullable=True)
    status: Mapped[OfferStatus] = mapped_column(_enum(OfferStatus), default=OfferStatus.draft)
    notes: Mapped[str] = mapped_column(String(4000), default="")

    __novvus_views__ = {
        "label": "Ofertas",
        "display": "id",
        "attachments": True,
        "chatter": True,
        "track": ["status"],
        "labels": {
            "application_id": "Aplicación",
            "salary": "Salario",
            "currency": "Moneda",
            "start_date": "Fecha de inicio",
            "status": "Estado",
            "notes": "Notas",
        },
        **({"choices": {
            "status": {
                "draft": "Borrador",
                "sent": "Enviada",
                "accepted": "Aceptada",
                "rejected": "Rechazada",
                "expired": "Vencida",
            }
        }} if _CHOICES else {}),
        "list": {
            "columns": ["application_id", "salary", "currency", "status", "start_date"],
            "default_order": "-start_date",
        },
        "form": {
            "layout": [
                ["application_id"],
                ["salary", "currency", "start_date"],
                ["status"],
                ["notes"],
            ],
        },
    }


# Candidate primero: es el modelo operativo y el que abre la tarjeta del módulo.
ALL_MODELS = [Candidate, Application, Interview, Offer, JobPosition]
