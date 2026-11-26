"""Business rules for Facturación."""

from typing import Annotated, Any
from uuid import UUID
from datetime import datetime, UTC

from fastapi import Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select, text, func
from sqlalchemy.ext.asyncio import AsyncSession

from models import Invoice, InvoiceStatus
from novvus_sdk import NovvusModule, requires, current_context
from fastapi.responses import PlainTextResponse


class PaymentBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    amount: float
    method: str = "transfer"
    reference: str = ""
    notes: str = ""


async def dashboard(session: AsyncSession) -> dict[str, Any]:
    rows = (await session.execute(text("SELECT status, COUNT(*), COALESCE(SUM(total),0), COALESCE(SUM(paid_amount),0) FROM mod_facturacion.invoice WHERE deleted_at IS NULL GROUP BY status"))).all()
    by_status = {str(r[0]): {"count": int(r[1]), "total": float(r[2]), "paid": float(r[3])} for r in rows}
    total_invoices = sum(v["count"] for v in by_status.values())
    total_amount = sum(v["total"] for v in by_status.values())
    total_paid = sum(v["paid"] for v in by_status.values())
    pending = total_amount - total_paid
    overdue = by_status.get("overdue", {}).get("count", 0)
    return {
        "generated_at": datetime.now(tz=UTC).isoformat(),
        "metrics": [
            {"label": "Facturas totales", "value": total_invoices, "description": "Todas las facturas", "tone": "info"},
            {"label": "Monto total", "value": f"{total_amount:,.2f}", "description": "Suma de todas las facturas", "tone": "info"},
            {"label": "Cobrado", "value": f"{total_paid:,.2f}", "description": "Pagos recibidos", "tone": "success"},
            {"label": "Pendiente de cobro", "value": f"{pending:,.2f}", "description": "Saldo por cobrar", "tone": "warning" if pending > 0 else "success"},
            {"label": "Vencidas", "value": overdue, "description": "Facturas vencidas sin pagar", "tone": "danger" if overdue else "neutral"},
            {"label": "Pagadas", "value": by_status.get("paid", {}).get("count", 0), "description": "Facturas pagadas", "tone": "success"},
        ],
        "recent": {"title": "Facturas recientes", "description": "Últimas facturas emitidas", "path": "invoices", "empty": "Sin facturas.", "items": []},
        "queues": [],
        "distribution": [{"label": k, "value": v["count"], "tone": "info"} for k, v in sorted(by_status.items())],
    }


async def register_payment(session: AsyncSession, invoice_id: UUID, amount: float, method: str = "transfer", reference: str = "", notes: str = "") -> dict[str, Any]:
    from models import Invoice, Payment
    from decimal import Decimal
    inv = await session.scalar(select(Invoice).where(Invoice.id == invoice_id, Invoice.deleted_at.is_(None)))
    if inv is None:
        raise HTTPException(status_code=404, detail="invoice not found")
    pay = Payment(
        org_id=inv.org_id, invoice_id=inv.id, amount=Decimal(str(amount)),
        payment_date=datetime.now(tz=UTC).date(), method=method, reference=reference, notes=notes,
    )
    session.add(pay)
    inv.paid_amount = (inv.paid_amount or Decimal("0")) + Decimal(str(amount))
    if inv.paid_amount >= inv.total and inv.total > 0:
        inv.status = "paid"
    await session.flush()
    await session.refresh(inv)
    return {"invoice_id": str(inv.id), "paid_amount": str(inv.paid_amount), "status": inv.status, "payment_id": str(pay.id)}


async def export_invoices_csv(session: AsyncSession) -> str:
    rows = (await session.execute(text(
        "SELECT id, number, status, company_id, total, currency, issue_date, due_date, paid_amount FROM mod_facturacion.invoice WHERE deleted_at IS NULL ORDER BY issue_date DESC NULLS LAST"
    ))).all()
    lines = ["id,number,status,company_id,total,currency,issue_date,due_date,paid_amount"]
    for r in rows:
        def esc(v):
            s = "" if v is None else str(v)
            if "," in s or '"' in s or "\n" in s:
                s = '"' + s.replace('"', '""') + '"'
            return s
        lines.append(",".join(esc(v) for v in r))
    return "\n".join(lines) + "\n"


def register(module: NovvusModule) -> None:
    router = module.router
    SessionDep = Annotated[AsyncSession, Depends(module.session_dependency())]

    @router.get("/reports/dashboard")
    async def _dashboard(session: SessionDep) -> dict[str, Any]:
        return await dashboard(session)

    @router.get("/reports/export/invoices")
    async def _export(session: SessionDep):
        csv = await export_invoices_csv(session)
        return PlainTextResponse(csv, media_type="text/csv", headers={"Content-Disposition": "attachment; filename=invoices.csv"})

    @router.post("/invoices/{invoice_id}/register_payment")
    @requires("facturacion.payments.write")
    async def _pay(invoice_id: UUID, payload: PaymentBody, session: SessionDep) -> dict[str, Any]:
        return await register_payment(session, invoice_id, payload.amount, payload.method, payload.reference, payload.notes)