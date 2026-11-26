"""Inventario — módulo NOVVUS."""

from pathlib import Path
from uuid import UUID
from datetime import datetime, UTC

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from novvus_sdk import NovvusModel, NovvusModule
from novvus_sdk.events import Event

from models import ALL_MODELS, Product, StockItem, StockMovement

module = NovvusModule(Path(__file__).with_name("novvus.toml"))

for model in ALL_MODELS:
    module.model(model)

try:
    import business
    business.register(module)
except ImportError:
    pass

@module.on("logistica.shipment.delivered")
async def on_shipment_delivered(event: Event, session: AsyncSession) -> None:
    # Placeholder: al entregar un envío, se podría descontar stock automáticamente.
    pass

@module.seed
async def seed(session: AsyncSession, org_id: UUID) -> None:
    from models import Product, StockItem
    p = Product(org_id=org_id, sku="PROD-001", name="Servicio de consultoría", unit="hr", price=1500, is_active=True)
    session.add(p)
    await session.flush()
    session.add(StockItem(org_id=org_id, product_id=p.id, quantity=10, min_stock=2, location="Almacén principal"))

app = module.create_app()