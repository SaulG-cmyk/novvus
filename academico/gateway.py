"""Pasarela académica: firma las peticiones internas y las envía al módulo.

En la plataforma real este papel lo hace el kernel (imagen comercial). Aquí se
implementa la parte mínima necesaria para que los módulos del SDK funcionen de
forma autocontenida en un ejercicio de Docker.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import time
from typing import Any

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

SECRET = os.environ["NOVVUS_INTERNAL_HMAC_SECRET"]
ORG = os.environ["NOVVUS_ORG_ID"]
USER = os.environ.get("NOVVUS_USER_ID", "")
PERMS = os.environ.get("NOVVUS_PERMS", "*")
ENTITLEMENT = "not_required"
FEATURES = ""

# Módulos del repo y sus recursos (tal como los expone el SDK).
MODULOS: dict[str, tuple[str, str]] = {
    "auditorias": ("http://auditorias:8100", "audits,audit_findings,audit_checklists,audit_reports"),
    # `processes` existe pero desactiva su API en el modelo; no se ofrece en la UI.
    "automatizacion": (
        "http://automatizacion:8100",
        "process_steps,process_executions,process_logs,notifications",
    ),
    "facturacion": ("http://facturacion:8100", "invoices,invoice_lines,payments"),
    "inventario": ("http://inventario:8100", "products,stock_items,stock_movements"),
    "logistica": ("http://logistica:8100", "shipments,delivery_orders,warehouses,carriers,vehicles"),
    "reclutamiento": (
        "http://reclutamiento:8100",
        "candidates,applications,interviews,offers,job_positions",
    ),
}

app = FastAPI(title="Novvus pasarela académica", version="1.0")


def _sign(canonical: str) -> str:
    return hmac.new(SECRET.encode(), canonical.encode(), hashlib.sha256).hexdigest()


def _signed_headers(method: str, path: str) -> dict[str, str]:
    ts = str(int(time.time()))
    signature = _sign(f"{USER}\n{ORG}\n{PERMS}\n{ts}\n{method}\n{path}")
    entitlement_sig = _sign(
        f"entitlement\n{ENTITLEMENT}\n{FEATURES}\n{ts}\n{method}\n{path}"
    )
    return {
        "x-novvus-user": USER,
        "x-novvus-org": ORG,
        "x-novvus-perms": PERMS,
        "x-novvus-timestamp": ts,
        "x-novvus-signature": signature,
        "x-novvus-locale": "es-MX",
        "x-novvus-entitlement": ENTITLEMENT,
        "x-novvus-features": FEATURES,
        "x-novvus-entitlement-signature": entitlement_sig,
    }


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "gateway"}


@app.get("/modulos")
async def modulos() -> dict[str, dict[str, Any]]:
    return {
        name: {"url": f"/api/{name}", "recursos": recursos.split(",")}
        for name, (_, recursos) in MODULOS.items()
    }


@app.api_route(
    "/api/{module}/{path:path}",
    methods=["GET", "POST", "PATCH", "DELETE", "PUT"],
)
async def proxy(module: str, path: str, request: Request) -> Response:
    if module not in MODULOS:
        return JSONResponse({"detail": f"módulo desconocido: {module}"}, status_code=404)

    base_url = MODULOS[module][0]
    target = f"{base_url}/api/{module}/{path}"
    headers = _signed_headers(request.method, f"/api/{module}/{path}")
    body = await request.body()

    async with httpx.AsyncClient(timeout=30.0) as client:
        upstream = await client.request(
            request.method,
            target,
            params=dict(request.query_params),
            content=body,
            headers=headers,
        )

    return Response(
        content=upstream.content,
        status_code=upstream.status_code,
        media_type=upstream.headers.get("content-type"),
    )
