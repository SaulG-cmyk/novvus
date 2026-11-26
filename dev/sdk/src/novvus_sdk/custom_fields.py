"""Base-module side of per-organization custom fields
(docs/CUSTOM_FIELDS.md §7).

Same shape as the extensions pipeline with a flat namespace: definitions come
from `core.custom_fields` through the kernel's service endpoint, cached per
org with a short TTL, and every `custom` payload is validated against them.
Definitions normalize as::

    {model_resource: {field_name: declaration_dict}}
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any
from uuid import UUID

from fastapi import HTTPException

from novvus_sdk.extensions import _coerce  # same v1 type catalog and constraints

if TYPE_CHECKING:
    from novvus_sdk.app import NovvusModule

DEFINITIONS_TTL = 60.0

CustomDefinitions = dict[str, dict[str, dict[str, Any]]]


def _normalize(rows: list[dict[str, Any]]) -> CustomDefinitions:
    normalized: CustomDefinitions = {}
    for row in rows:
        model = str(row.get("model", ""))
        decl = {
            "name": row.get("name"),
            "type": row.get("field_type", "string"),
            "label": row.get("label", ""),
            "required": bool(row.get("required", False)),
            "config": row.get("config") or {},
        }
        normalized.setdefault(model, {})[str(row["name"])] = decl
    return normalized


class CustomFieldsRegistry:
    """Per-org cache of the active custom-field definitions of this module."""

    def __init__(self, module: NovvusModule) -> None:
        self._module = module
        self._cache: dict[UUID, tuple[float, CustomDefinitions]] = {}

    async def for_org(self, org_id: UUID) -> CustomDefinitions:
        override = self._module.custom_definitions_override
        if override is not None:
            return override
        if self._module._kernel is None:
            return {}
        cached = self._cache.get(org_id)
        now = time.monotonic()
        if cached and now - cached[0] < DEFINITIONS_TTL:
            return cached[1]
        try:
            rows = await self._module._kernel.get_custom_fields(org_id)
        except Exception:  # degrade, never take the API down
            logging.getLogger("novvus").warning(
                "could not refresh custom-field definitions; serving stale/empty"
            )
            return cached[1] if cached else {}
        definitions = _normalize(rows)
        self._cache[org_id] = (now, definitions)
        return definitions


def _fail(message: str) -> HTTPException:
    return HTTPException(status_code=422, detail=message)


def validate_custom_payload(
    model_defs: dict[str, dict[str, Any]],
    payload: Any,
    current: dict[str, Any] | None,
    creating: bool,
) -> dict[str, Any]:
    """Validate an incoming `custom` payload and return the merged stored
    value. Includes the lazy sweep (docs/CUSTOM_FIELDS.md §6): stored keys
    without an ACTIVE definition are dropped on write — the kernel never runs
    SQL against module schemas to clean them."""
    if payload is None:
        payload = {}
    if not isinstance(payload, dict):
        raise _fail("custom must be an object of {field: value}")

    # Lazy sweep: start from the surviving keys only.
    merged: dict[str, Any] = {
        name: value for name, value in (current or {}).items() if name in model_defs
    }
    for name, value in payload.items():
        decl = model_defs.get(name)
        if decl is None:
            raise _fail(f"unknown or inactive custom field {name!r}")
        if value is None:
            merged.pop(name, None)
        else:
            merged[name] = _coerce(decl, value)

    if creating:
        for name, decl in model_defs.items():
            if decl.get("required") and merged.get(name) is None:
                raise _fail(f"custom field {name!r} is required")
    return merged


def filter_custom_for_read(
    model_defs: dict[str, dict[str, Any]], stored: Any
) -> dict[str, Any]:
    """Only keys with an active definition leave the API."""
    if not isinstance(stored, dict):
        return {}
    return {name: value for name, value in stored.items() if name in model_defs}
