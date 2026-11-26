"""Readable answers for database integrity errors on the generic CRUD.

The auto-API trusts the schema: a unique constraint the module did not
pre-validate (template names, members, links, participants, dependencies)
would surface as a 500. Every `IntegrityError` becomes a 409 with the field
that clashed. The tenant session has already rolled back when this runs.
"""

from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError

CONSTRAINTS: dict[str, tuple[str, str]] = {
    "template_org_id_name_key": ("name", "Ya existe una plantilla con este nombre"),
    "ux_project_org_code": ("code", "Ya existe un proyecto con este código"),
    "project_member_project_id_user_id_key": ("user_id", "Esa persona ya forma parte del equipo"),
    "project_link_project_id_opportunity_id_key": (
        "opportunity_id",
        "El proyecto ya está vinculado con esa oportunidad",
    ),
    "task_participant_task_id_user_id_key": ("user_id", "Esa persona ya participa en la actividad"),
    "task_dependency_predecessor_id_successor_id_key": (
        "predecessor_id",
        "Esa dependencia ya existe",
    ),
    "template_dependency_predecessor_id_successor_id_key": (
        "predecessor_id",
        "Esa dependencia ya existe",
    ),
}


def describe(error: IntegrityError) -> dict[str, Any]:
    original = getattr(error, "orig", None)
    diag = getattr(original, "diag", None)
    constraint = str(getattr(diag, "constraint_name", "") or "")
    sqlstate = str(getattr(original, "sqlstate", "") or getattr(diag, "sqlstate", "") or "")
    if constraint in CONSTRAINTS:
        field, message = CONSTRAINTS[constraint]
        return {"detail": {field: message}}
    if sqlstate == "23503":
        return {"detail": "El registro referido no existe o ya fue eliminado"}
    if sqlstate == "23505":
        return {"detail": "Ya existe un registro con estos datos"}
    return {"detail": "La operación viola una restricción de integridad"}


def install(app: FastAPI) -> None:
    @app.exception_handler(IntegrityError)
    async def integrity_error(_request: Request, error: IntegrityError) -> JSONResponse:
        return JSONResponse(status_code=409, content=describe(error))
