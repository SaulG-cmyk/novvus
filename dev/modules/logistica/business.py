"""Business rules for Logística."""

from typing import Annotated, Any
from uuid import UUID

from fastapi import Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import Shipment, ShipmentStatus
from novvus_sdk import NovvusModule, requires, current_context
from sqlalchemy import text
from datetime import datetime, UTC
from fastapi.responses import PlainTextResponse

class DeliverBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    notes: str = ""

async def export_shipments_csv(session: AsyncSession) -> str:
    rows = (await session.execute(text(
        "SELECT id, reference, status, carrier_id, tracking_number, scheduled_date, delivered_date FROM mod_logistica.shipment WHERE deleted_at IS NULL ORDER BY scheduled_date DESC NULLS LAST"
    ))).all()
    lines = ["id,reference,status,carrier_id,tracking_number,scheduled_date,delivered_date"]
    for r in rows:
        def esc(v):
            s = "" if v is None else str(v)
            if "," in s or '"' in s or "\n" in s:
                s = '"' + s.replace('"', '""') + '"'
            return s
        lines.append(",".join(esc(v) for v in r))
    return "\n".join(lines) + "\n"


async def dashboard(session: AsyncSession) -> dict[str, Any]:
    from sqlalchemy import func
    rows = (await session.execute(
        text("SELECT status, COUNT(*) FROM mod_logistica.shipment WHERE deleted_at IS NULL GROUP BY status")
    )).all()
    by_status = {r[0]: int(r[1]) for r in rows}
    total = sum(by_status.values())
    pending = by_status.get("draft", 0) + by_status.get("planned", 0) + by_status.get("in_transit", 0)
    delivered = by_status.get("delivered", 0)
    return {
        "generated_at": datetime.now(tz=UTC).isoformat(),
        "metrics": [
            {"label": "Envíos totales", "value": total, "description": "Todos los envíos registrados", "tone": "info"},
            {"label": "Pendientes", "value": pending, "description": "Borrador / planeado / en tránsito", "tone": "warning" if pending else "success"},
            {"label": "Entregados", "value": delivered, "description": "Entregas completadas", "tone": "success"},
            {"label": "Cancelados", "value": by_status.get("cancelled", 0) + by_status.get("returned", 0), "description": "Cancelados o devueltos", "tone": "danger"},
        ],
        "recent": {"title": "Envíos recientes", "description": "Últimos envíos registrados", "path": "shipments", "empty": "Sin envíos.", "items": []},
        "queues": [],
        "distribution": [{"label": k, "value": v, "tone": "info"} for k, v in sorted(by_status.items())],
    }


def register(module: NovvusModule) -> None:
    router = module.router
    SessionDep = Annotated[AsyncSession, Depends(module.session_dependency())]

    @router.get("/reports/dashboard")
    async def _dashboard(session: SessionDep) -> dict[str, Any]:
        return await dashboard(session)

    @router.get("/reports/export/shipments")
    async def _export(session: SessionDep):
        csv = await export_shipments_csv(session)
        return PlainTextResponse(csv, media_type="text/csv", headers={"Content-Disposition": "attachment; filename=shipments.csv"})

    @router.post("/shipments/{shipment_id}/deliver")
    @requires("logistica.shipments.write")
    async def deliver_shipment(shipment_id: UUID, payload: DeliverBody, session: SessionDep) -> dict[str, Any]:
        shipment = await session.scalar(
            select(Shipment).where(Shipment.id == shipment_id, Shipment.deleted_at.is_(None))
        )
        if shipment is None:
            raise HTTPException(status_code=404, detail="shipment not found")

        shipment.status = "delivered"
        from datetime import datetime, UTC
        shipment.delivered_date = datetime.now(tz=UTC)
        if payload.notes:
            shipment.notes = (shipment.notes or "") + "\n" + payload.notes
        await session.flush()
        await session.refresh(shipment)

        # Create activity in CRM
        ctx = current_context()
        try:
            await module.call(
                "POST",
                "/api/crm/activities",
                org_id=ctx.org_id,
                json={
                    "type": "task",
                    "title": f"Entrega completada: {shipment.reference}",
                    "notes": f"El envío {shipment.reference} fue entregado. Tracking: {shipment.tracking_number}",
                    "status": "pending",
                    "priority": "medium",
                    "due_date": shipment.delivered_date.isoformat() if shipment.delivered_date else None,
                },
            )
        except Exception as e:
            import logging
            logging.getLogger("logistica").warning("Failed to create activity in CRM: %s", e)

        await module.emit(
            "logistica.shipment.delivered",
            {"shipment_id": str(shipment.id), "reference": shipment.reference},
        )
        return {"shipment_id": str(shipment.id), "status": "delivered"}
