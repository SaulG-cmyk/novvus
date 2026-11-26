"""Logística — módulo NOVVUS."""

from pathlib import Path
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from novvus_sdk import NovvusModel, NovvusModule
from novvus_sdk.events import Event

from models import ALL_MODELS, Shipment, Warehouse

module = NovvusModule(Path(__file__).with_name("novvus.toml"))

for model in ALL_MODELS:
    module.model(model)

try:
    import business
    business.register(module)
except ImportError:
    pass

@module.on("crm.quote.accepted")
async def create_shipment_on_quote_accepted(event: Event, session: AsyncSession) -> None:
    payload = event.payload or {}
    quote_id = payload.get("quote_id")
    company_id = payload.get("company_id")
    total = payload.get("total")
    currency = payload.get("currency", "MXN")

    # Get default warehouse (first active)
    warehouse = await session.scalar(
        select(Warehouse).where(Warehouse.deleted_at.is_(None)).limit(1)
    )
    if warehouse is None:
        return

    # Idempotencia: un mismo evento/quote no debe generar envíos duplicados.
    if quote_id:
        already = await session.scalar(
            select(Shipment.id).where(
                Shipment.deleted_at.is_(None),
                Shipment.notes.like(f"%{quote_id}%"),
            ).limit(1)
        )
        if already is not None:
            return

    # Referencia estable y sin colisiones: últimos 8 caracteres hex del UUID.
    compact = (quote_id or "").replace("-", "")
    reference = f"ENV-{compact[-8:].upper()}" if compact else "ENV-AUTO"

    # Create shipment
    shipment = Shipment(
        org_id=event.org_id,
        reference=reference,
        origin_warehouse_id=warehouse.id,
        destination_address="Por definir",
        status="draft",
        notes=f"Generado automáticamente por cotización aceptada {quote_id}",
        owner_user_id=None,
    )
    session.add(shipment)
    await session.flush()
    await module.emit("logistica.shipment.created", {"shipment_id": str(shipment.id), "quote_id": quote_id})

@module.seed
async def seed(session: AsyncSession, org_id: UUID) -> None:
    from models import Warehouse, Carrier
    session.add_all([
        Warehouse(org_id=org_id, name="Almacén principal", city="Ciudad de México", is_active=True),
        Carrier(org_id=org_id, name="Transportes Rápidos", contact_name="Juan", phone="555-1234", is_active=True),
    ])

app = module.create_app()
