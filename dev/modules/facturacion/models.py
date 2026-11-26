"""Modelos de Facturación y Cobranza."""

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


class InvoiceStatus(StrEnum):
    draft = "draft"
    sent = "sent"
    paid = "paid"
    overdue = "overdue"
    cancelled = "cancelled"


class PaymentMethod(StrEnum):
    cash = "cash"
    transfer = "transfer"
    card = "card"
    check = "check"
    other = "other"


def _enum(enum_cls: type[StrEnum]) -> SAEnum:
    return SAEnum(enum_cls, native_enum=False, length=20)


class Invoice(NovvusModel):
    __resource__ = "invoices"

    number: Mapped[str] = mapped_column(String(40), default="")
    customer_name: Mapped[str] = mapped_column(String(200), default="")
    company_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    contact_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    status: Mapped[InvoiceStatus] = mapped_column(_enum(InvoiceStatus), default=InvoiceStatus.draft)
    issue_date: Mapped[date | None] = mapped_column(nullable=True)
    due_date: Mapped[date | None] = mapped_column(nullable=True)
    currency: Mapped[str] = mapped_column(String(3), default="MXN")
    subtotal: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    tax: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    total: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    paid_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    notes: Mapped[str] = mapped_column(String(4000), default="")
    owner_user_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)

    __novvus_views__ = {
        "nav": {"icon": "receipt"},
        "label": "Facturas",
        "display": "number",
        "attachments": True,
        "chatter": True,
        "track": ["status", "company_id"],
        "labels": {
            "number": "Número",
            "customer_name": "Cliente",
            "company_id": "Empresa",
            "contact_id": "Contacto",
            "status": "Estado",
            "issue_date": "Fecha de emisión",
            "due_date": "Fecha de vencimiento",
            "currency": "Moneda",
            "subtotal": "Subtotal",
            "tax": "Impuesto",
            "total": "Total",
            "paid_amount": "Pagado",
            "notes": "Notas",
            "owner_user_id": "Responsable",
        },
        **({"choices": {
            "status": {
                "draft": "Borrador",
                "sent": "Enviada",
                "paid": "Pagada",
                "overdue": "Vencida",
                "cancelled": "Cancelada",
            }
        }} if _CHOICES else {}),
        **({"dashboard": {"path": "reports/dashboard", "title": "Panel de facturación", "order": 10}} if _DASHBOARD else {}),
        "list": {"columns": ["number", "customer_name", "status", "total", "currency", "due_date"], "default_order": "-issue_date"},
        "form": {"layout": [["number", "status"], ["customer_name", "company_id"], ["contact_id"], ["issue_date", "due_date"], ["currency"], ["subtotal", "tax", "total"], ["paid_amount"], ["notes"], ["owner_user_id"]]},
        "kanban": {"group_by": "status", "card": ["number", "total"]},
        "calendar": {"date_field": "due_date", "title": "number"},
    }


class InvoiceLine(NovvusModel):
    __resource__ = "invoice_lines"

    invoice_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), ForeignKey("invoice.id", ondelete="CASCADE"))
    invoice_number: Mapped[str] = mapped_column(String(40), default="")
    description: Mapped[str] = mapped_column(String(400))
    quantity: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("1"))
    unit_price: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    tax_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("0"))
    line_total: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))

    __novvus_views__ = {
        "label": "Líneas de factura",
        "display": "description",
        "attachments": False,
        "chatter": False,
        "labels": {
            "invoice_id": "Factura",
            "invoice_number": "Folio",
            "description": "Descripción",
            "quantity": "Cantidad",
            "unit_price": "Precio unitario",
            "tax_rate": "Impuesto (%)",
            "line_total": "Total",
        },
        "list": {"columns": ["invoice_number", "description", "quantity", "unit_price", "line_total"], "default_order": "invoice_number"},
        "form": {"layout": [["invoice_id"], ["description", "quantity"], ["unit_price", "tax_rate", "line_total"]]},
    }


class Payment(NovvusModel):
    __resource__ = "payments"

    invoice_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), ForeignKey("invoice.id", ondelete="CASCADE"))
    invoice_number: Mapped[str] = mapped_column(String(40), default="")
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    payment_date: Mapped[date | None] = mapped_column(nullable=True)
    method: Mapped[PaymentMethod] = mapped_column(_enum(PaymentMethod), default=PaymentMethod.transfer)
    reference: Mapped[str] = mapped_column(String(120), default="")
    notes: Mapped[str] = mapped_column(String(4000), default="")

    __novvus_views__ = {
        "label": "Pagos",
        "display": "reference",
        "attachments": True,
        "chatter": True,
        "track": ["method"],
        "labels": {
            "invoice_id": "Factura",
            "invoice_number": "Folio",
            "amount": "Monto",
            "payment_date": "Fecha de pago",
            "method": "Método",
            "reference": "Referencia",
            "notes": "Notas",
        },
        **({"choices": {
            "method": {
                "cash": "Efectivo",
                "transfer": "Transferencia",
                "card": "Tarjeta",
                "check": "Cheque",
                "other": "Otro",
            }
        }} if _CHOICES else {}),
        "list": {"columns": ["invoice_number", "amount", "method", "payment_date", "reference"], "default_order": "-payment_date"},
        "form": {"layout": [["invoice_id"], ["amount", "method"], ["payment_date", "reference"], ["notes"]]},
    }


ALL_MODELS = [Invoice, InvoiceLine, Payment]