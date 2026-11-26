"""Readable answers for database integrity errors on the generic CRUD.

The auto-API trusts the schema: a unique constraint that the module did not
pre-validate (products by SKU, tags, pipelines, lost reasons, tax rates) would
surface as a 500. Here every `IntegrityError` becomes a 409 with the field
that clashed, so the shell shows a message instead of a generic failure. The
tenant session has already rolled back when the handler runs.
"""

from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError

# constraint name → (field, message)
CONSTRAINTS: dict[str, tuple[str, str]] = {
    "product_org_id_sku_key": ("sku", "Ya existe un producto con esta clave (SKU)"),
    "tag_org_id_name_key": ("name", "Ya existe una etiqueta con este nombre"),
    "lost_reason_org_id_name_key": ("name", "Ya existe un motivo de pérdida con este nombre"),
    "tax_rate_org_id_name_key": ("name", "Ya existe un impuesto con este nombre"),
    "quote_org_id_number_version_key": (
        "number",
        "Ya existe una cotización con este número y versión",
    ),
    "contact_company_contact_id_company_id_key": (
        "company_id",
        "El contacto ya está vinculado con esa empresa",
    ),
    "contact_tag_contact_id_tag_id_key": ("tag_id", "El contacto ya tiene esa etiqueta"),
    "opportunity_tag_opportunity_id_tag_id_key": ("tag_id", "La oportunidad ya tiene esa etiqueta"),
    "company_tag_company_id_tag_id_key": ("tag_id", "La empresa ya tiene esa etiqueta"),
}


def describe(error: IntegrityError) -> dict[str, Any]:
    """`{"detail": {field: message}}` for a known constraint, a generic duplicate otherwise."""
    original = getattr(error, "orig", None)
    diag = getattr(original, "diag", None)
    constraint = str(getattr(diag, "constraint_name", "") or "")
    sqlstate = str(getattr(original, "sqlstate", "") or getattr(diag, "sqlstate", "") or "")
    if constraint in CONSTRAINTS:
        field, message = CONSTRAINTS[constraint]
        return {"detail": {field: message}}
    if sqlstate == "23503":  # foreign key
        return {"detail": "El registro referido no existe o ya fue eliminado"}
    if sqlstate == "23505":
        return {"detail": "Ya existe un registro con estos datos"}
    return {"detail": "La operación viola una restricción de integridad"}


def install(app: FastAPI) -> None:
    @app.exception_handler(IntegrityError)
    async def integrity_error(_request: Request, error: IntegrityError) -> JSONResponse:
        return JSONResponse(status_code=409, content=describe(error))
