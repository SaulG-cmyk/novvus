"""Modelos de Inventario."""

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from sqlalchemy import Enum as SAEnum
from sqlalchemy import ForeignKey, Numeric, String
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from novvus_sdk import NovvusModel

try:
    from novvus_sdk import VIEW_KEYS
except Exception:
    VIEW_KEYS = frozenset()

_CHOICES = "choices" in VIEW_KEYS
_DASHBOARD = "dashboard" in VIEW_KEYS


class MovementType(StrEnum):
    in_ = "in"
    out = "out"
    adjustment = "adjustment"


def _enum(enum_cls: type[StrEnum]) -> SAEnum:
    return SAEnum(enum_cls, native_enum=False, length=20)


class Product(NovvusModel):
    __resource__ = "products"

    sku: Mapped[str] = mapped_column(String(60), default="")
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(String(4000), default="")
    unit: Mapped[str] = mapped_column(String(20), default="pz")
    price: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    is_active: Mapped[bool] = mapped_column(default=True)
    owner_user_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)

    __novvus_views__ = {
        "nav": {"icon": "package"},
        "label": "Productos",
        "display": "name",
        "attachments": True,
        "chatter": True,
        "track": ["is_active"],
        "labels": {
            "sku": "SKU",
            "name": "Nombre",
            "description": "Descripción",
            "unit": "Unidad",
            "price": "Precio",
            "is_active": "Activo",
            "owner_user_id": "Responsable",
        },
        **({"dashboard": {"path": "reports/dashboard", "title": "Panel de inventario", "order": 10}} if _DASHBOARD else {}),
        "list": {"columns": ["sku", "name", "unit", "price", "is_active"], "default_order": "name"},
        "form": {"layout": [["sku", "name"], ["unit", "price"], ["description"], ["is_active", "owner_user_id"]]},
    }


class StockItem(NovvusModel):
    __resource__ = "stock_items"

    product_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    product_name: Mapped[str] = mapped_column(String(200), default="")
    warehouse_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    quantity: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"))
    min_stock: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"))
    location: Mapped[str] = mapped_column(String(120), default="")

    __novvus_views__ = {
        "label": "Stock",
        "display": "product_name",
        "attachments": False,
        "chatter": False,
        "labels": {
            "product_id": "Producto",
            "product_name": "Producto",
            "warehouse_id": "Almacén",
            "quantity": "Cantidad",
            "min_stock": "Stock mínimo",
            "location": "Ubicación",
        },
        "list": {"columns": ["product_name", "quantity", "min_stock", "location"], "default_order": "product_name"},
        "form": {"layout": [["product_id", "warehouse_id"], ["quantity", "min_stock"], ["location"]]},
    }


class StockMovement(NovvusModel):
    __resource__ = "stock_movements"

    product_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    product_name: Mapped[str] = mapped_column(String(200), default="")
    warehouse_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    movement_type: Mapped[MovementType] = mapped_column(_enum(MovementType), default=MovementType.in_)
    quantity: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"))
    reference: Mapped[str] = mapped_column(String(120), default="")
    notes: Mapped[str] = mapped_column(String(4000), default="")
    movement_date: Mapped[datetime | None] = mapped_column(nullable=True)

    __novvus_views__ = {
        "label": "Movimientos",
        "display": "reference",
        "attachments": False,
        "chatter": False,
        "track": ["movement_type"],
        "labels": {
            "product_id": "Producto",
            "product_name": "Producto",
            "warehouse_id": "Almacén",
            "movement_type": "Tipo",
            "quantity": "Cantidad",
            "reference": "Referencia",
            "notes": "Notas",
            "movement_date": "Fecha",
        },
        **({"choices": {
            "movement_type": {
                "in": "Entrada",
                "out": "Salida",
                "adjustment": "Ajuste",
            }
        }} if _CHOICES else {}),
        "list": {"columns": ["product_name", "movement_type", "quantity", "reference", "movement_date"], "default_order": "-movement_date"},
        "form": {"layout": [["product_id", "warehouse_id"], ["movement_type", "quantity"], ["reference", "movement_date"], ["notes"]]},
    }


ALL_MODELS = [Product, StockItem, StockMovement]