"""CRM data model. Every class inherits NovvusModel: UUIDv7 id, org_id with
RLS, timestamps and soft delete come from the SDK.

Schema history: 0001 initial, 0002 ext, 0003 custom, 0004 commercial model
(companies, contacts, leads, opportunities, activities extended; products,
tax rates, lost reasons, quotes and quote lines; stage log; M2M tables).
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


# Lowercase member names so SQLAlchemy's Enum (which stores member names)
# persists the same strings the API exchanges.
class LeadSource(StrEnum):
    manual = "manual"
    form = "form"
    referral = "referral"
    website = "website"
    event = "event"
    partner = "partner"
    campaign = "campaign"
    other = "other"


class LeadStatus(StrEnum):
    new = "new"
    contacted = "contacted"
    qualified = "qualified"
    unqualified = "unqualified"
    lost = "lost"
    converted = "converted"


class Priority(StrEnum):
    low = "low"
    medium = "medium"
    high = "high"


class ActivityType(StrEnum):
    call = "call"
    meeting = "meeting"
    email = "email"
    task = "task"
    followup = "followup"
    reminder = "reminder"


class ActivityStatus(StrEnum):
    pending = "pending"
    done = "done"
    cancelled = "cancelled"


class CompanyStatus(StrEnum):
    prospect = "prospect"
    active = "active"
    inactive = "inactive"
    lost = "lost"


class CompanyKind(StrEnum):
    customer = "customer"
    prospect = "prospect"
    partner = "partner"
    supplier = "supplier"
    other = "other"


class ContactKind(StrEnum):
    decision_maker = "decision_maker"
    influencer = "influencer"
    user = "user"
    technical = "technical"
    administrative = "administrative"
    other = "other"


class ContactStatus(StrEnum):
    active = "active"
    inactive = "inactive"


class QuoteStatus(StrEnum):
    draft = "draft"
    sent = "sent"
    accepted = "accepted"
    rejected = "rejected"
    expired = "expired"


def _enum(enum_cls: type[StrEnum]) -> SAEnum:
    return SAEnum(enum_cls, native_enum=False, length=20)


def _uuid_fk(target: str, ondelete: str) -> Mapped[UUID | None]:
    return mapped_column(PgUUID(as_uuid=True), ForeignKey(target, ondelete=ondelete), nullable=True)


class Company(NovvusModel):
    __resource__ = "companies"
    # Registration goes through the validated «Nueva empresa» action (directory.py): duplicates
    # by name, fiscal id or e-mail are refused in the server. Edits stay generic.
    __novvus_api__ = {"disabled": ["create"]}  # noqa: RUF012

    name: Mapped[str] = mapped_column(String(200))
    legal_name: Mapped[str] = mapped_column(String(300), default="")
    # Fiscal identifier and its kind (RFC, NIT, CUIT, VAT…): the kind is free text
    # per organization/country; validation rules live in country extensions.
    tax_id: Mapped[str] = mapped_column(String(60), default="")
    tax_id_kind: Mapped[str] = mapped_column(String(40), default="")
    website: Mapped[str] = mapped_column(String(300), default="")
    industry: Mapped[str] = mapped_column(String(120), default="")
    phone: Mapped[str] = mapped_column(String(40), default="")
    email: Mapped[str] = mapped_column(String(254), default="")
    address: Mapped[str] = mapped_column(String(400), default="")
    city: Mapped[str] = mapped_column(String(120), default="")
    region: Mapped[str] = mapped_column(String(120), default="")
    postal_code: Mapped[str] = mapped_column(String(20), default="")
    country: Mapped[str] = mapped_column(String(2), default="")  # ISO 3166-1 alpha-2
    kind: Mapped[CompanyKind] = mapped_column(_enum(CompanyKind), default=CompanyKind.prospect)
    status: Mapped[CompanyStatus] = mapped_column(
        _enum(CompanyStatus), default=CompanyStatus.prospect
    )
    owner_user_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    notes: Mapped[str] = mapped_column(String(4000), default="")

    __novvus_views__ = {  # noqa: RUF012
        "label": "Empresas",
        "display": "name",
        "attachments": True,
        "chatter": True,
        "track": ["status", "owner_user_id", "kind"],
        "labels": {
            "name": "Nombre comercial",
            "legal_name": "Razón social",
            "tax_id": "Identificación fiscal",
            "tax_id_kind": "Tipo de identificación",
            "website": "Sitio web",
            "industry": "Industria",
            "phone": "Teléfono",
            "email": "Correo",
            "address": "Dirección",
            "city": "Ciudad",
            "region": "Estado o región",
            "postal_code": "Código postal",
            "country": "País",
            "kind": "Tipo",
            "status": "Estado comercial",
            "owner_user_id": "Responsable interno",
            "notes": "Notas",
        },
        "list": {
            "columns": ["name", "industry", "status", "kind", "phone", "email"],
            "default_order": "name",
        },
        "form": {
            "layout": [
                ["name", "legal_name"],
                ["tax_id_kind", "tax_id"],
                ["industry", "kind", "status"],
                ["phone", "email", "website"],
                ["address"],
                ["city", "region", "postal_code", "country"],
                ["owner_user_id"],
                ["notes"],
            ],
        },
        "kanban": {"group_by": "status", "card": ["name", "industry", "phone"]},
    }


class Contact(NovvusModel):
    __resource__ = "contacts"
    # Registration goes through the validated «Nuevo contacto» action (directory.py).
    __novvus_api__ = {"disabled": ["create"]}  # noqa: RUF012

    name: Mapped[str] = mapped_column(String(200))
    email: Mapped[str] = mapped_column(String(254), default="")
    email_secondary: Mapped[str] = mapped_column(String(254), default="")
    phone: Mapped[str] = mapped_column(String(40), default="")
    mobile: Mapped[str] = mapped_column(String(40), default="")
    job_title: Mapped[str] = mapped_column(String(120), default="")
    department: Mapped[str] = mapped_column(String(120), default="")
    responsibilities: Mapped[str] = mapped_column(String(2000), default="")
    kind: Mapped[ContactKind] = mapped_column(_enum(ContactKind), default=ContactKind.other)
    status: Mapped[ContactStatus] = mapped_column(
        _enum(ContactStatus), default=ContactStatus.active
    )
    # Primary company; further companies through contact_companies (M2M).
    company_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("company.id", ondelete="SET NULL"), nullable=True
    )
    owner_user_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    notes: Mapped[str] = mapped_column(String(4000), default="")

    __novvus_views__ = {  # noqa: RUF012
        "label": "Contactos",
        "display": "name",
        "attachments": True,
        "chatter": True,
        "track": ["job_title", "company_id", "status", "kind"],
        "labels": {
            "name": "Nombre",
            "email": "Correo",
            "email_secondary": "Correo secundario",
            "phone": "Teléfono",
            "mobile": "Móvil",
            "job_title": "Puesto",
            "department": "Departamento",
            "responsibilities": "Responsabilidades",
            "kind": "Clasificación",
            "status": "Estado",
            "company_id": "Empresa",
            "owner_user_id": "Responsable interno",
            "notes": "Notas",
        },
        "list": {
            "columns": ["name", "company_id", "job_title", "email", "phone", "kind", "status"],
            "default_order": "name",
        },
        "form": {
            "layout": [
                ["name", "company_id"],
                ["email", "email_secondary"],
                ["phone", "mobile"],
                ["job_title", "department"],
                ["kind", "status", "owner_user_id"],
                ["responsibilities"],
                ["notes"],
            ],
        },
    }


class ContactCompany(NovvusModel):
    """M2M contact↔company for people who act for several organizations."""

    __resource__ = "contact_companies"
    __table_args__ = (UniqueConstraint("contact_id", "company_id"),)
    __novvus_api__ = {  # noqa: RUF012
        "permissions": {"read": "crm.contacts.read", "write": "crm.contacts.write"}
    }

    contact_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("contact.id", ondelete="CASCADE")
    )
    company_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("company.id", ondelete="CASCADE")
    )
    role: Mapped[str] = mapped_column(String(120), default="")
    is_primary: Mapped[bool] = mapped_column(default=False)

    __novvus_views__ = {  # noqa: RUF012
        "label": "Empresas del contacto",
        "display": "role",
        "nav": {"hidden": True},
        "labels": {
            "contact_id": "Contacto",
            "company_id": "Empresa",
            "role": "Rol en la empresa",
            "is_primary": "Principal",
        },
        "list": {"columns": ["contact_id", "company_id", "role", "is_primary"]},
        "form": {"layout": [["contact_id", "company_id"], ["role", "is_primary"]]},
    }


class Tag(NovvusModel):
    __resource__ = "tags"
    __table_args__ = (UniqueConstraint("org_id", "name"),)

    name: Mapped[str] = mapped_column(String(60))
    color: Mapped[str] = mapped_column(String(9), default="#888888")

    __novvus_views__ = {  # noqa: RUF012
        "label": "Etiquetas",
        "display": "name",
        "nav": {"group": "Configuración", "order": 30},
        "labels": {"name": "Nombre", "color": "Color"},
        "list": {"columns": ["name", "color"], "default_order": "name"},
        "form": {"layout": [["name", "color"]]},
    }


class Pipeline(NovvusModel):
    __resource__ = "pipelines"
    __novvus_api__ = {  # noqa: RUF012 — SDK config, not mutable state
        "permissions": {"read": "crm.pipelines.read", "write": "crm.pipelines.manage"}
    }

    name: Mapped[str] = mapped_column(String(120))
    is_default: Mapped[bool] = mapped_column(default=False)

    __novvus_views__ = {  # noqa: RUF012
        "label": "Pipelines",
        "display": "name",
        "nav": {"group": "Configuración", "order": 10},
        "labels": {"name": "Nombre", "is_default": "Predeterminado"},
        "list": {"columns": ["name", "is_default"], "default_order": "name"},
        "form": {"layout": [["name", "is_default"]]},
    }


class Stage(NovvusModel):
    __resource__ = "stages"
    __novvus_api__ = {  # noqa: RUF012
        "permissions": {"read": "crm.pipelines.read", "write": "crm.pipelines.manage"}
    }

    pipeline_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("pipeline.id", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(String(120))
    position: Mapped[int] = mapped_column(default=0)
    probability: Mapped[int] = mapped_column(default=0)  # 0-100 (%)
    is_won: Mapped[bool] = mapped_column(default=False)
    is_lost: Mapped[bool] = mapped_column(default=False)

    __novvus_views__ = {  # noqa: RUF012
        "label": "Etapas",
        "display": "name",
        "nav": {"group": "Configuración", "order": 20},
        "labels": {
            "pipeline_id": "Pipeline",
            "name": "Nombre",
            "position": "Posición",
            "probability": "Probabilidad (%)",
            "is_won": "Etapa ganada",
            "is_lost": "Etapa perdida",
        },
        "list": {
            "columns": ["pipeline_id", "position", "name", "probability", "is_won", "is_lost"],
            "default_order": "position",
        },
        "form": {
            "layout": [["pipeline_id", "name"], ["position", "probability"], ["is_won", "is_lost"]]
        },
    }


class LostReason(NovvusModel):
    __resource__ = "lost_reasons"
    __table_args__ = (UniqueConstraint("org_id", "name"),)
    __novvus_api__ = {  # noqa: RUF012
        "permissions": {"read": "crm.opportunities.read", "write": "crm.pipelines.manage"}
    }

    name: Mapped[str] = mapped_column(String(120))
    is_active: Mapped[bool] = mapped_column(default=True)

    __novvus_views__ = {  # noqa: RUF012
        "label": "Motivos de pérdida",
        "display": "name",
        "nav": {"group": "Configuración", "order": 40},
        "labels": {"name": "Motivo", "is_active": "Activo"},
        "list": {"columns": ["name", "is_active"], "default_order": "name"},
        "form": {"layout": [["name", "is_active"]]},
    }


class TaxRate(NovvusModel):
    """Configurable tax per organization (no country rule is assumed)."""

    __resource__ = "tax_rates"
    __table_args__ = (UniqueConstraint("org_id", "name"),)
    __novvus_api__ = {  # noqa: RUF012
        "permissions": {"read": "crm.products.read", "write": "crm.products.write"}
    }

    name: Mapped[str] = mapped_column(String(120))
    rate: Mapped[Decimal] = mapped_column(Numeric(7, 4), default=Decimal("0"))  # percent
    country: Mapped[str] = mapped_column(String(2), default="")
    is_default: Mapped[bool] = mapped_column(default=False)
    is_active: Mapped[bool] = mapped_column(default=True)

    __novvus_views__ = {  # noqa: RUF012
        "label": "Impuestos",
        "display": "name",
        "nav": {"group": "Configuración", "order": 60},
        "labels": {
            "name": "Nombre",
            "rate": "Tasa (%)",
            "country": "País",
            "is_default": "Predeterminado",
            "is_active": "Activo",
        },
        "list": {
            "columns": ["name", "rate", "country", "is_default", "is_active"],
            "default_order": "name",
        },
        "form": {"layout": [["name", "rate"], ["country", "is_default", "is_active"]]},
    }


class Product(NovvusModel):
    """Products and services the organization sells (CRM catalog)."""

    __resource__ = "products"
    __table_args__ = (UniqueConstraint("org_id", "sku"),)

    sku: Mapped[str] = mapped_column(String(60))
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(String(2000), default="")
    unit: Mapped[str] = mapped_column(String(40), default="pieza")
    list_price: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    currency: Mapped[str] = mapped_column(String(3), default="MXN")
    tax_rate_id: Mapped[UUID | None] = _uuid_fk("tax_rate.id", "SET NULL")
    is_active: Mapped[bool] = mapped_column(default=True)

    __novvus_views__ = {  # noqa: RUF012
        "label": "Productos y servicios",
        "display": "name",
        "nav": {"group": "Configuración", "order": 50},
        "track": ["list_price", "is_active"],
        "labels": {
            "sku": "Clave (SKU)",
            "name": "Nombre",
            "description": "Descripción",
            "unit": "Unidad",
            "list_price": "Precio de lista",
            "currency": "Moneda",
            "tax_rate_id": "Impuesto",
            "is_active": "Activo",
        },
        "list": {
            "columns": ["sku", "name", "unit", "list_price", "currency", "is_active"],
            "default_order": "name",
            "mono": ["sku"],
        },
        "form": {
            "layout": [
                ["sku", "name"],
                ["unit", "list_price", "currency"],
                ["tax_rate_id", "is_active"],
                ["description"],
            ],
        },
    }


class Opportunity(NovvusModel):
    __resource__ = "opportunities"

    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(String(4000), default="")
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    currency: Mapped[str] = mapped_column(String(3), default="MXN")
    pipeline_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("pipeline.id", ondelete="CASCADE")
    )
    stage_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("stage.id", ondelete="RESTRICT")
    )
    # None = use the stage's configured probability; set = explicit override (0-100).
    probability: Mapped[int | None] = mapped_column(nullable=True)
    expected_close_date: Mapped[date | None] = mapped_column(nullable=True)
    owner_user_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    contact_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("contact.id", ondelete="SET NULL"), nullable=True
    )
    company_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("company.id", ondelete="SET NULL"), nullable=True
    )
    priority: Mapped[Priority] = mapped_column(_enum(Priority), default=Priority.medium)
    # None while open; set (with closed_at) when moved to a won/lost stage.
    is_won: Mapped[bool | None] = mapped_column(nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(nullable=True)
    lost_reason_id: Mapped[UUID | None] = _uuid_fk("lost_reason.id", "SET NULL")
    lost_notes: Mapped[str] = mapped_column(String(2000), default="")
    # Last activity (created or completed) touching the opportunity: stalled detection.
    last_activity_at: Mapped[datetime | None] = mapped_column(nullable=True)

    __novvus_views__ = {  # noqa: RUF012
        "label": "Oportunidades",
        "display": "name",
        "attachments": True,
        "chatter": True,
        "track": ["amount", "stage_id", "owner_user_id", "expected_close_date", "probability"],
        "labels": {
            "name": "Nombre",
            "description": "Descripción",
            "amount": "Valor estimado",
            "currency": "Moneda",
            "pipeline_id": "Pipeline",
            "stage_id": "Etapa",
            "probability": "Probabilidad (%)",
            "expected_close_date": "Cierre estimado",
            "owner_user_id": "Responsable comercial",
            "contact_id": "Contacto",
            "company_id": "Empresa",
            "priority": "Prioridad",
            "is_won": "Ganada",
            "closed_at": "Cerrada el",
            "lost_reason_id": "Motivo de pérdida",
            "lost_notes": "Detalle de la pérdida",
            "last_activity_at": "Última actividad",
        },
        "list": {
            "columns": [
                "name",
                "company_id",
                "stage_id",
                "amount",
                "currency",
                "probability",
                "expected_close_date",
                "owner_user_id",
                "priority",
            ],
            "default_order": "-created_at",
        },
        "form": {
            "layout": [
                ["name", "company_id", "contact_id"],
                ["pipeline_id", "stage_id", "priority"],
                ["amount", "currency", "probability", "expected_close_date"],
                ["owner_user_id"],
                ["description"],
            ],
        },
        "kanban": {
            "group_by": "stage_id",
            "card": ["name", "company_id", "amount", "expected_close_date"],
        },
    }


class OpportunityLine(NovvusModel):
    """Products or services attached to an opportunity (estimated scope)."""

    __resource__ = "opportunity_lines"
    __novvus_api__ = {  # noqa: RUF012
        "permissions": {"read": "crm.opportunities.read", "write": "crm.opportunities.write"}
    }

    opportunity_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("opportunity.id", ondelete="CASCADE")
    )
    product_id: Mapped[UUID | None] = _uuid_fk("product.id", "SET NULL")
    description: Mapped[str] = mapped_column(String(500), default="")
    quantity: Mapped[Decimal] = mapped_column(Numeric(12, 3), default=Decimal("1"))
    unit_price: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))

    __novvus_views__ = {  # noqa: RUF012
        "label": "Productos de la oportunidad",
        "display": "description",
        "nav": {"hidden": True},
        "labels": {
            "opportunity_id": "Oportunidad",
            "product_id": "Producto",
            "description": "Descripción",
            "quantity": "Cantidad",
            "unit_price": "Precio unitario",
        },
        "list": {"columns": ["product_id", "description", "quantity", "unit_price"]},
        "form": {
            "layout": [
                ["opportunity_id", "product_id"],
                ["description"],
                ["quantity", "unit_price"],
            ]
        },
    }


class OpportunityStageLog(NovvusModel):
    """Append-only history of stage transitions (who, when, from, to)."""

    __resource__ = "opportunity_stage_logs"
    __novvus_api__ = {  # noqa: RUF012
        "permissions": {"read": "crm.opportunities.read", "write": "crm.opportunities.write"},
        "disabled": ["create", "update", "delete"],
    }

    opportunity_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("opportunity.id", ondelete="CASCADE")
    )
    from_stage_id: Mapped[UUID | None] = _uuid_fk("stage.id", "SET NULL")
    to_stage_id: Mapped[UUID | None] = _uuid_fk("stage.id", "SET NULL")
    user_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    note: Mapped[str] = mapped_column(String(1000), default="")

    __novvus_views__ = {  # noqa: RUF012
        "label": "Historial de etapas",
        "display": "note",
        "nav": {"hidden": True},
        "labels": {
            "opportunity_id": "Oportunidad",
            "from_stage_id": "De la etapa",
            "to_stage_id": "A la etapa",
            "user_id": "Usuario",
            "note": "Nota",
        },
        "list": {
            "columns": ["created_at", "from_stage_id", "to_stage_id", "user_id", "note"],
            "default_order": "-created_at",
        },
    }


class Lead(NovvusModel):
    __resource__ = "leads"
    # Creation goes through the custom endpoint so crm.lead.created is emitted.
    __novvus_api__ = {"disabled": ["create"]}  # noqa: RUF012

    title: Mapped[str] = mapped_column(String(200), default="")
    source: Mapped[LeadSource] = mapped_column(_enum(LeadSource), default=LeadSource.manual)
    status: Mapped[LeadStatus] = mapped_column(_enum(LeadStatus), default=LeadStatus.new)
    # Captured identity for prospects not yet in the directory (manual capture).
    person_name: Mapped[str] = mapped_column(String(200), default="")
    company_name: Mapped[str] = mapped_column(String(200), default="")
    email: Mapped[str] = mapped_column(String(254), default="")
    phone: Mapped[str] = mapped_column(String(40), default="")
    contact_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("contact.id", ondelete="SET NULL"), nullable=True
    )
    company_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("company.id", ondelete="SET NULL"), nullable=True
    )
    owner_user_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    need: Mapped[str] = mapped_column(String(2000), default="")
    estimated_value: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    currency: Mapped[str] = mapped_column(String(3), default="MXN")
    next_activity_at: Mapped[datetime | None] = mapped_column(nullable=True)
    notes: Mapped[str] = mapped_column(String(4000), default="")
    # Conversion is auditable: the lead is never deleted, it points at the
    # opportunity it became (docs: MODULE_CONTRACT; regla de negocio Fase 3).
    converted_opportunity_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("opportunity.id", ondelete="SET NULL"), nullable=True
    )

    __novvus_views__ = {  # noqa: RUF012
        "label": "Prospectos",
        "display": "title",
        "attachments": True,
        "chatter": True,
        "track": ["status", "owner_user_id", "estimated_value"],
        "labels": {
            "title": "Título",
            "source": "Fuente",
            "status": "Calificación",
            "person_name": "Nombre de la persona",
            "company_name": "Empresa (texto)",
            "email": "Correo",
            "phone": "Teléfono",
            "contact_id": "Contacto",
            "company_id": "Empresa",
            "owner_user_id": "Propietario",
            "need": "Necesidad identificada",
            "estimated_value": "Valor potencial",
            "currency": "Moneda",
            "next_activity_at": "Próxima actividad",
            "notes": "Notas",
            "converted_opportunity_id": "Oportunidad resultante",
        },
        "list": {
            "columns": [
                "title",
                "person_name",
                "company_name",
                "source",
                "status",
                "owner_user_id",
                "estimated_value",
                "next_activity_at",
            ],
            "default_order": "-created_at",
        },
        "form": {
            "layout": [
                ["title", "source", "status"],
                ["person_name", "company_name"],
                ["email", "phone"],
                ["contact_id", "company_id"],
                ["owner_user_id", "estimated_value", "currency"],
                ["next_activity_at"],
                ["need"],
                ["notes"],
            ],
        },
        "kanban": {"group_by": "status", "card": ["title", "person_name", "company_name"]},
    }


class Activity(NovvusModel):
    __resource__ = "activities"

    type: Mapped[ActivityType] = mapped_column(_enum(ActivityType), default=ActivityType.task)
    title: Mapped[str] = mapped_column(String(200))
    notes: Mapped[str] = mapped_column(String(4000), default="")
    due_date: Mapped[datetime | None] = mapped_column(nullable=True)
    status: Mapped[ActivityStatus] = mapped_column(
        _enum(ActivityStatus), default=ActivityStatus.pending
    )
    priority: Mapped[Priority] = mapped_column(_enum(Priority), default=Priority.medium)
    completed_at: Mapped[datetime | None] = mapped_column(nullable=True)
    outcome: Mapped[str] = mapped_column(String(2000), default="")
    lead_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("lead.id", ondelete="CASCADE"), nullable=True
    )
    opportunity_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("opportunity.id", ondelete="CASCADE"), nullable=True
    )
    company_id: Mapped[UUID | None] = _uuid_fk("company.id", "SET NULL")
    contact_id: Mapped[UUID | None] = _uuid_fk("contact.id", "SET NULL")
    assigned_user_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)

    __novvus_views__ = {  # noqa: RUF012
        "label": "Actividades",
        "display": "title",
        "chatter": True,
        "track": ["status", "assigned_user_id", "due_date"],
        "labels": {
            "type": "Tipo",
            "title": "Título",
            "notes": "Notas",
            "due_date": "Vencimiento",
            "status": "Estado",
            "priority": "Prioridad",
            "completed_at": "Completada el",
            "outcome": "Resultado",
            "lead_id": "Prospecto",
            "opportunity_id": "Oportunidad",
            "company_id": "Empresa",
            "contact_id": "Contacto",
            "assigned_user_id": "Responsable",
        },
        "list": {
            "columns": [
                "title",
                "type",
                "status",
                "priority",
                "due_date",
                "assigned_user_id",
                "company_id",
                "opportunity_id",
            ],
            "default_order": "due_date",
        },
        "form": {
            "layout": [
                ["title", "type", "status", "priority"],
                ["due_date", "assigned_user_id"],
                ["company_id", "contact_id"],
                ["lead_id", "opportunity_id"],
                ["notes"],
                ["outcome"],
            ],
        },
        "kanban": {"group_by": "status", "card": ["title", "type", "due_date"]},
        "calendar": {"date_field": "due_date", "title": "title"},
    }


class Quote(NovvusModel):
    """Commercial quote. Totals are computed by the server (business.py) from
    its lines; every revision is a new row chained through `previous_id`."""

    __resource__ = "quotes"
    __table_args__ = (UniqueConstraint("org_id", "number", "version"),)
    # Only drafts are deleted, through the «Eliminar borrador» action (quotes.py): a sent or
    # decided quote is commercial history.
    __novvus_api__ = {"disabled": ["delete"]}  # noqa: RUF012

    number: Mapped[str] = mapped_column(String(40))
    version: Mapped[int] = mapped_column(default=1)
    previous_id: Mapped[UUID | None] = _uuid_fk("quote.id", "SET NULL")
    title: Mapped[str] = mapped_column(String(200), default="")
    status: Mapped[QuoteStatus] = mapped_column(_enum(QuoteStatus), default=QuoteStatus.draft)
    company_id: Mapped[UUID | None] = _uuid_fk("company.id", "SET NULL")
    contact_id: Mapped[UUID | None] = _uuid_fk("contact.id", "SET NULL")
    opportunity_id: Mapped[UUID | None] = _uuid_fk("opportunity.id", "SET NULL")
    owner_user_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), default="MXN")
    issued_at: Mapped[date | None] = mapped_column(nullable=True)
    valid_until: Mapped[date | None] = mapped_column(nullable=True)
    # Whole-quote discount applied after line discounts (percent, 0-100).
    discount_percent: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("0"))
    subtotal: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    discount_total: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    tax_total: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    total: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    notes: Mapped[str] = mapped_column(String(4000), default="")
    terms: Mapped[str] = mapped_column(String(4000), default="")
    sent_at: Mapped[datetime | None] = mapped_column(nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(nullable=True)
    decision_notes: Mapped[str] = mapped_column(String(2000), default="")

    __novvus_views__ = {  # noqa: RUF012
        "label": "Cotizaciones",
        "display": "number",
        "attachments": True,
        "chatter": True,
        "track": ["status", "total", "valid_until"],
        "fields": {
            "subtotal": {"readonly": True},
            "discount_total": {"readonly": True},
            "tax_total": {"readonly": True},
            "total": {"readonly": True},
            "version": {"readonly": True},
            "previous_id": {"readonly": True},
            "sent_at": {"readonly": True},
            "decided_at": {"readonly": True},
        },
        "labels": {
            "number": "Número",
            "version": "Versión",
            "previous_id": "Versión anterior",
            "title": "Título",
            "status": "Estado",
            "company_id": "Cliente",
            "contact_id": "Contacto",
            "opportunity_id": "Oportunidad",
            "owner_user_id": "Responsable",
            "currency": "Moneda",
            "issued_at": "Fecha de emisión",
            "valid_until": "Vigencia hasta",
            "discount_percent": "Descuento global (%)",
            "subtotal": "Subtotal",
            "discount_total": "Descuentos",
            "tax_total": "Impuestos",
            "total": "Total",
            "notes": "Notas",
            "terms": "Términos y condiciones",
            "sent_at": "Enviada el",
            "decided_at": "Decidida el",
            "decision_notes": "Notas de la decisión",
        },
        "list": {
            "columns": [
                "number",
                "version",
                "title",
                "company_id",
                "status",
                "total",
                "currency",
                "valid_until",
                "owner_user_id",
            ],
            "default_order": "-created_at",
            "mono": ["number"],
        },
        "form": {
            "layout": [
                ["number", "version", "status"],
                ["title"],
                ["company_id", "contact_id", "opportunity_id"],
                ["owner_user_id", "currency"],
                ["issued_at", "valid_until", "discount_percent"],
                ["subtotal", "discount_total", "tax_total", "total"],
                ["notes"],
                ["terms"],
            ],
        },
        "kanban": {"group_by": "status", "card": ["number", "title", "company_id", "total"]},
    }


class QuoteLine(NovvusModel):
    """A quote line; amounts are recomputed by the server whenever lines change."""

    __resource__ = "quote_lines"
    # Lines enter through the quote's actions (quotes.py) so totals are always recomputed.
    __novvus_api__ = {  # noqa: RUF012
        "permissions": {"read": "crm.quotes.read", "write": "crm.quotes.write"},
        "disabled": ["create", "update", "delete"],
    }

    quote_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("quote.id", ondelete="CASCADE")
    )
    position: Mapped[int] = mapped_column(default=0)
    product_id: Mapped[UUID | None] = _uuid_fk("product.id", "SET NULL")
    description: Mapped[str] = mapped_column(String(500), default="")
    quantity: Mapped[Decimal] = mapped_column(Numeric(12, 3), default=Decimal("1"))
    unit_price: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    discount_percent: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("0"))
    tax_rate_id: Mapped[UUID | None] = _uuid_fk("tax_rate.id", "SET NULL")
    # Snapshot of the applied rate so a later catalog change never rewrites history.
    tax_rate: Mapped[Decimal] = mapped_column(Numeric(7, 4), default=Decimal("0"))
    line_subtotal: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    line_tax: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    line_total: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))

    __novvus_views__ = {  # noqa: RUF012
        "label": "Conceptos de la cotización",
        "display": "description",
        "nav": {"hidden": True},
        "fields": {
            "tax_rate": {"readonly": True},
            "line_subtotal": {"readonly": True},
            "line_tax": {"readonly": True},
            "line_total": {"readonly": True},
        },
        "labels": {
            "quote_id": "Cotización",
            "position": "Posición",
            "product_id": "Producto",
            "description": "Descripción",
            "quantity": "Cantidad",
            "unit_price": "Precio unitario",
            "discount_percent": "Descuento (%)",
            "tax_rate_id": "Impuesto",
            "tax_rate": "Tasa aplicada (%)",
            "line_subtotal": "Subtotal",
            "line_tax": "Impuesto",
            "line_total": "Total",
        },
        "list": {
            "columns": [
                "position",
                "product_id",
                "description",
                "quantity",
                "unit_price",
                "discount_percent",
                "line_total",
            ],
            "default_order": "position",
        },
        "form": {
            "layout": [
                ["quote_id", "position", "product_id"],
                ["description"],
                ["quantity", "unit_price", "discount_percent", "tax_rate_id"],
                ["line_subtotal", "line_tax", "line_total"],
            ],
        },
    }


class ContactTag(NovvusModel):
    """M2M contact↔tag. Managed via /contacts/{id}/tags, not the auto-API."""

    __resource__ = "contact_tags"
    __table_args__ = (UniqueConstraint("contact_id", "tag_id"),)
    __novvus_api__ = {"disabled": ["list", "create", "get", "update", "delete"]}  # noqa: RUF012

    contact_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("contact.id", ondelete="CASCADE")
    )
    tag_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("tag.id", ondelete="CASCADE")
    )


class OpportunityTag(NovvusModel):
    """M2M opportunity↔tag. Managed via /opportunities/{id}/tags."""

    __resource__ = "opportunity_tags"
    __table_args__ = (UniqueConstraint("opportunity_id", "tag_id"),)
    __novvus_api__ = {"disabled": ["list", "create", "get", "update", "delete"]}  # noqa: RUF012

    opportunity_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("opportunity.id", ondelete="CASCADE")
    )
    tag_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("tag.id", ondelete="CASCADE")
    )


class CompanyTag(NovvusModel):
    """M2M company↔tag. Managed via /companies/{id}/tags."""

    __resource__ = "company_tags"
    __table_args__ = (UniqueConstraint("company_id", "tag_id"),)
    __novvus_api__ = {"disabled": ["list", "create", "get", "update", "delete"]}  # noqa: RUF012

    company_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("company.id", ondelete="CASCADE")
    )
    tag_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("tag.id", ondelete="CASCADE")
    )


# Registration order matters: referenced tables first (initial migration
# emits CREATE TABLE in this order).
ALL_MODELS: list[type[NovvusModel]] = [
    Company,
    Contact,
    ContactCompany,
    Tag,
    Pipeline,
    Stage,
    LostReason,
    TaxRate,
    Product,
    Opportunity,
    OpportunityLine,
    OpportunityStageLog,
    Lead,
    Activity,
    Quote,
    QuoteLine,
    ContactTag,
    OpportunityTag,
    CompanyTag,
]
