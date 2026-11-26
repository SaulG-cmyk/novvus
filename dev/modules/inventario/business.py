"""Business rules for Inventario."""

from typing import Annotated, Any
from uuid import UUID
from datetime import datetime, UTC

from fastapi import Depends, HTTPException
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from models import Product
from novvus_sdk import NovvusModule, requires, current_context
from fastapi.responses import PlainTextResponse


async def dashboard(session: AsyncSession) -> dict[str, Any]:
    products = await session.scalar(text("SELECT COUNT(*) FROM mod_inventario.product WHERE deleted_at IS NULL")) or 0
    low = await session.scalar(text("SELECT COUNT(*) FROM mod_inventario.stock_item WHERE deleted_at IS NULL AND quantity <= min_stock")) or 0
    movements = await session.scalar(text("SELECT COUNT(*) FROM mod_inventario.stock_movement WHERE deleted_at IS NULL")) or 0
    in_moves = await session.scalar(text("SELECT COALESCE(SUM(quantity),0) FROM mod_inventario.stock_movement WHERE deleted_at IS NULL AND movement_type='in'")) or 0
    out_moves = await session.scalar(text("SELECT COALESCE(SUM(quantity),0) FROM mod_inventario.stock_movement WHERE deleted_at IS NULL AND movement_type='out'")) or 0
    return {
        "generated_at": datetime.now(tz=UTC).isoformat(),
        "metrics": [
            {"label": "Productos", "value": int(products), "description": "Productos registrados", "tone": "info"},
            {"label": "Stock bajo", "value": int(low), "description": "Productos por debajo del mínimo", "tone": "danger" if low else "success"},
            {"label": "Movimientos", "value": int(movements), "description": "Movimientos registrados", "tone": "info"},
            {"label": "Entradas", "value": str(in_moves), "description": "Unidades ingresadas", "tone": "success"},
            {"label": "Salidas", "value": str(out_moves), "description": "Unidades retiradas", "tone": "warning"},
        ],
        "recent": {"title": "Productos", "description": "Productos registrados", "path": "products", "empty": "Sin productos.", "items": []},
        "queues": [],
        "distribution": [],
    }


async def export_products_csv(session: AsyncSession) -> str:
    rows = (await session.execute(text("SELECT id, sku, name, unit, price, is_active FROM mod_inventario.product WHERE deleted_at IS NULL ORDER BY name"))).all()
    lines = ["id,sku,name,unit,price,is_active"]
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

    @router.get("/reports/export/products")
    async def _export(session: SessionDep):
        csv = await export_products_csv(session)
        return PlainTextResponse(csv, media_type="text/csv", headers={"Content-Disposition": "attachment; filename=products.csv"})