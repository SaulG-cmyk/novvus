"""Modelos de Logística y Entregas."""

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

_DASHBOARD = "dashboard" in VIEW_KEYS

try:
    from novvus_sdk import VIEW_KEYS
except Exception:
    VIEW_KEYS = frozenset()

_CHOICES = "choices" in VIEW_KEYS


class ShipmentStatus(StrEnum):
    draft = "draft"
    planned = "planned"
    in_transit = "in_transit"
    delivered = "delivered"
    cancelled = "cancelled"
    returned = "returned"


class DeliveryStatus(StrEnum):
    pending = "pending"
    picked = "picked"
    in_transit = "in_transit"
    delivered = "delivered"
    failed = "failed"


class VehicleStatus(StrEnum):
    available = "available"
    in_use = "in_use"
    maintenance = "maintenance"
    inactive = "inactive"


def _enum(enum_cls: type[StrEnum]) -> SAEnum:
    return SAEnum(enum_cls, native_enum=False, length=20)


class Warehouse(NovvusModel):
    __resource__ = "warehouses"

    name: Mapped[str] = mapped_column(String(200))
    code: Mapped[str] = mapped_column(String(40), default="")
    address: Mapped[str] = mapped_column(String(400), default="")
    city: Mapped[str] = mapped_column(String(120), default="")
    region: Mapped[str] = mapped_column(String(120), default="")
    country: Mapped[str] = mapped_column(String(2), default="")
    is_active: Mapped[bool] = mapped_column(default=True)
    owner_user_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)

    __novvus_views__ = {
        "label": "Almacenes",
        "display": "name",
        "attachments": True,
        "chatter": True,
        "track": ["is_active", "owner_user_id"],
        "labels": {
            "name": "Nombre",
            "code": "Código",
            "address": "Dirección",
            "city": "Ciudad",
            "region": "Estado/Región",
            "country": "País",
            "is_active": "Activo",
            "owner_user_id": "Responsable",
        },
        "list": {"columns": ["name", "code", "city", "is_active"], "default_order": "name"},
        "form": {"layout": [["name", "code"], ["address"], ["city", "region", "country"], ["is_active", "owner_user_id"]]},
    }


class Carrier(NovvusModel):
    __resource__ = "carriers"

    name: Mapped[str] = mapped_column(String(200))
    contact_name: Mapped[str] = mapped_column(String(200), default="")
    phone: Mapped[str] = mapped_column(String(40), default="")
    email: Mapped[str] = mapped_column(String(254), default="")
    website: Mapped[str] = mapped_column(String(300), default="")
    is_active: Mapped[bool] = mapped_column(default=True)

    __novvus_views__ = {
        "label": "Transportistas",
        "display": "name",
        "attachments": True,
        "chatter": True,
        "labels": {
            "name": "Nombre",
            "contact_name": "Contacto",
            "phone": "Teléfono",
            "email": "Correo",
            "website": "Sitio web",
            "is_active": "Activo",
        },
        "list": {"columns": ["name", "contact_name", "phone", "is_active"], "default_order": "name"},
        "form": {"layout": [["name"], ["contact_name", "phone", "email"], ["website", "is_active"]]},
    }


class Vehicle(NovvusModel):
    __resource__ = "vehicles"

    name: Mapped[str] = mapped_column(String(200))
    plate: Mapped[str] = mapped_column(String(20), default="")
    capacity: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"))
    status: Mapped[VehicleStatus] = mapped_column(_enum(VehicleStatus), default=VehicleStatus.available)
    carrier_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), ForeignKey("carrier.id", ondelete="SET NULL"), nullable=True)
    owner_user_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)

    __novvus_views__ = {
        "label": "Vehículos",
        "display": "name",
        "attachments": True,
        "chatter": True,
        "track": ["status", "carrier_id"],
        "labels": {
            "name": "Nombre",
            "plate": "Placa",
            "capacity": "Capacidad",
            "status": "Estado",
            "carrier_id": "Transportista",
            "owner_user_id": "Responsable",
        },
        "list": {"columns": ["name", "plate", "status", "capacity", "carrier_id"], "default_order": "name"},
        "form": {"layout": [["name", "plate"], ["status", "capacity"], ["carrier_id"], ["owner_user_id"]]},
        **({"choices": {
            "status": {
                "available": "Disponible",
                "in_use": "En uso",
                "maintenance": "Mantenimiento",
                "inactive": "Inactivo",
            }
        }} if _CHOICES else {}),
        "kanban": {"group_by": "status", "card": ["name", "plate"]},
    }


class Shipment(NovvusModel):
    __resource__ = "shipments"

    reference: Mapped[str] = mapped_column(String(60), default="")
    origin_warehouse_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), ForeignKey("warehouse.id", ondelete="SET NULL"), nullable=True)
    destination_address: Mapped[str] = mapped_column(String(400), default="")
    carrier_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), ForeignKey("carrier.id", ondelete="SET NULL"), nullable=True)
    vehicle_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), ForeignKey("vehicle.id", ondelete="SET NULL"), nullable=True)
    status: Mapped[ShipmentStatus] = mapped_column(_enum(ShipmentStatus), default=ShipmentStatus.draft)
    tracking_number: Mapped[str] = mapped_column(String(120), default="")
    scheduled_date: Mapped[datetime | None] = mapped_column(nullable=True)
    delivered_date: Mapped[datetime | None] = mapped_column(nullable=True)
    notes: Mapped[str] = mapped_column(String(4000), default="")
    owner_user_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)

    __novvus_views__ = {
        "nav": {"icon": "truck"},
        "label": "Envíos",
        "display": "reference",
        "attachments": True,
        "chatter": True,
        "track": ["status", "carrier_id", "vehicle_id"],
        "labels": {
            "reference": "Referencia",
            "origin_warehouse_id": "Almacén origen",
            "destination_address": "Dirección destino",
            "carrier_id": "Transportista",
            "vehicle_id": "Vehículo",
            "status": "Estado",
            "tracking_number": "Número de rastreo",
            "scheduled_date": "Fecha programada",
            "delivered_date": "Fecha de entrega",
            "notes": "Notas",
            "owner_user_id": "Responsable",
        },
        "list": {"columns": ["reference", "status", "carrier_id", "tracking_number", "scheduled_date"], "default_order": "-scheduled_date"},
        "form": {"layout": [["reference", "status"], ["origin_warehouse_id", "destination_address"], ["carrier_id", "vehicle_id"], ["tracking_number"], ["scheduled_date", "delivered_date"], ["notes"], ["owner_user_id"]]},
        **({"choices": {
            "status": {
                "draft": "Borrador",
                "planned": "Planeado",
                "in_transit": "En tránsito",
                "delivered": "Entregado",
                "cancelled": "Cancelado",
                "returned": "Devuelto",
            }
        }} if _CHOICES else {}),
        **({"dashboard": {"path": "reports/dashboard", "title": "Panel de logística", "order": 10}} if _DASHBOARD else {}),
        "kanban": {"group_by": "status", "card": ["reference", "tracking_number"]},
        "calendar": {"date_field": "scheduled_date", "title": "reference"},
    }


class DeliveryOrder(NovvusModel):
    __resource__ = "delivery_orders"

    shipment_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), ForeignKey("shipment.id", ondelete="CASCADE"))
    product_description: Mapped[str] = mapped_column(String(400), default="")
    quantity: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"))
    unit: Mapped[str] = mapped_column(String(20), default="pz")
    status: Mapped[DeliveryStatus] = mapped_column(_enum(DeliveryStatus), default=DeliveryStatus.pending)
    notes: Mapped[str] = mapped_column(String(4000), default="")

    __novvus_views__ = {
        "label": "Órdenes de entrega",
        "display": "product_description",
        "attachments": True,
        "chatter": True,
        "track": ["status"],
        "labels": {
            "shipment_id": "Envío",
            "product_description": "Producto/Descripción",
            "quantity": "Cantidad",
            "unit": "Unidad",
            "status": "Estado",
            "notes": "Notas",
        },
        "list": {"columns": ["shipment_id", "product_description", "quantity", "status"], "default_order": "shipment_id"},
        "form": {"layout": [["shipment_id"], ["product_description", "quantity", "unit"], ["status"], ["notes"]]},
        **({"choices": {
            "status": {
                "pending": "Pendiente",
                "picked": "Recogido",
                "in_transit": "En tránsito",
                "delivered": "Entregado",
                "failed": "Fallido",
            }
        }} if _CHOICES else {}),
        "kanban": {"group_by": "status", "card": ["product_description", "quantity"]},
    }


# Shipment primero: es el modelo operativo y el que abre la tarjeta del módulo.
ALL_MODELS = [Shipment, DeliveryOrder, Warehouse, Carrier, Vehicle]
