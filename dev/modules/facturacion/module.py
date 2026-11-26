"""Facturación — módulo NOVVUS."""

from pathlib import Path
from uuid import UUID
from datetime import datetime, UTC

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from novvus_sdk import NovvusModel, NovvusModule
from novvus_sdk.events import Event

from models import ALL_MODELS, Invoice, InvoiceLine, Payment

module = NovvusModule(Path(__file__).with_name("novvus.toml"))

for model in ALL_MODELS:
    module.model(model)

try:
    import business
    business.register(module)
except ImportError:
    pass

@module.on("crm.quote.accepted")
async def on_quote_accepted(event: Event, session: AsyncSession) -> None:
    payload = event.payload or {}
    quote_id = payload.get("quote_id")
    company_id = payload.get("company_id")
    total = payload.get("total")
    currency = payload.get("currency", "MXN")
    # Idempotencia
    if quote_id:
        already = await session.scalar(
            select(Invoice.id).where(Invoice.deleted_at.is_(None), Invoice.notes.like(f"%{quote_id}%")).limit(1)
        )
        if already is not None:
            return
    inv = Invoice(
        org_id=event.org_id,
        number=f"FAC-{str(quote_id or '')[-8:].upper()}",
        company_id=company_id,
        status="draft",
        issue_date=datetime.now(tz=UTC).date(),
        currency=currency,
        subtotal=total or 0,
        tax=0,
        total=total or 0,
        paid_amount=0,
        notes=f"Generada automáticamente por cotización aceptada {quote_id}",
    )
    session.add(inv)
    await session.flush()
    await module.emit("facturacion.invoice.created", {"invoice_id": str(inv.id), "quote_id": quote_id})


@module.seed
async def seed(session: AsyncSession, org_id: UUID) -> None:
    from models import Invoice
    session.add(Invoice(org_id=org_id, number="FAC-DEMO-001", status="draft", currency="MXN", total=1000, subtotal=1000))


app = module.create_app()