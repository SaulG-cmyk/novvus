"""Base-module side of cross-module extensions (docs/EXTENSIONS.md §5).

The kernel holds the catalog; this helper caches the per-org view with a
short TTL (there is no push invalidation — see DECISIONS.md) and validates
`ext` payloads against it. Definitions are normalized as::

    {model_resource: {extender_id: {field_name: declaration_dict}}}
"""

from __future__ import annotations

import logging
import re
import time
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Any
from uuid import UUID

from fastapi import HTTPException

if TYPE_CHECKING:
    from novvus_sdk.app import NovvusModule

# Cache TTL for per-org definitions (seconds).
DEFINITIONS_TTL = 60.0

ExtDefinitions = dict[str, dict[str, dict[str, dict[str, Any]]]]


def _normalize(sets: list[dict[str, Any]]) -> ExtDefinitions:
    normalized: ExtDefinitions = {}
    for entry in sets:
        model = str(entry.get("target_model", ""))
        extender = str(entry.get("extender_id", ""))
        for decl in entry.get("fields") or []:
            normalized.setdefault(model, {}).setdefault(extender, {})[str(decl["name"])] = decl
    return normalized


class ExtensionsRegistry:
    """Per-org cache of the extension definitions targeting this module."""

    def __init__(self, module: NovvusModule) -> None:
        self._module = module
        self._cache: dict[UUID, tuple[float, ExtDefinitions]] = {}

    async def for_org(self, org_id: UUID) -> ExtDefinitions:
        # Testing/dev hook: bypasses the kernel entirely when set.
        override = self._module.ext_definitions_override
        if override is not None:
            return override
        if self._module._kernel is None:
            return {}
        cached = self._cache.get(org_id)
        now = time.monotonic()
        if cached and now - cached[0] < DEFINITIONS_TTL:
            return cached[1]
        try:
            sets = await self._module._kernel.get_extensions(org_id)
        except Exception:  # degrade, never take the API down
            logging.getLogger("novvus").warning(
                "could not refresh extension definitions; serving stale/empty"
            )
            return cached[1] if cached else {}
        definitions = _normalize(sets)
        self._cache[org_id] = (now, definitions)
        return definitions


def _fail(message: str) -> HTTPException:
    return HTTPException(status_code=422, detail=message)


def _coerce(decl: dict[str, Any], value: Any) -> Any:
    """Validate one ext value against its declaration; returns the stored form."""
    field_type = decl.get("type", "string")
    name = decl.get("name", "?")
    config = decl.get("config") or {}

    if field_type == "boolean":
        if not isinstance(value, bool):
            raise _fail(f"ext field {name!r} expects a boolean")
        return value
    if field_type == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            raise _fail(f"ext field {name!r} expects an integer")
        return value
    if field_type == "decimal":
        if isinstance(value, bool) or not isinstance(value, (int, float, str)):
            raise _fail(f"ext field {name!r} expects a number")
        try:
            Decimal(str(value))
        except InvalidOperation as exc:
            raise _fail(f"ext field {name!r} expects a number") from exc
        return str(value)
    if field_type == "date":
        if not isinstance(value, str):
            raise _fail(f"ext field {name!r} expects an ISO date string")
        try:
            date.fromisoformat(value)
        except ValueError as exc:
            raise _fail(f"ext field {name!r} expects an ISO date string") from exc
        return value
    if field_type == "datetime":
        if not isinstance(value, str):
            raise _fail(f"ext field {name!r} expects an ISO datetime string")
        try:
            datetime.fromisoformat(value)
        except ValueError as exc:
            raise _fail(f"ext field {name!r} expects an ISO datetime string") from exc
        return value

    # string / text
    if not isinstance(value, str):
        raise _fail(f"ext field {name!r} expects a string")
    max_length = config.get("max_length")
    if isinstance(max_length, int) and len(value) > max_length:
        raise _fail(f"ext field {name!r} exceeds max_length {max_length}")
    pattern = config.get("pattern")
    if isinstance(pattern, str) and not re.fullmatch(pattern, value):
        raise _fail(f"ext field {name!r} does not match its pattern")
    choices = config.get("choices")
    if isinstance(choices, list) and choices:
        allowed = {str(c.get("value")) for c in choices if isinstance(c, dict)}
        if value not in allowed:
            raise _fail(f"ext field {name!r} must be one of {sorted(allowed)}")
    return value


def validate_ext_payload(
    model_defs: dict[str, dict[str, dict[str, Any]]],
    payload: Any,
    current: dict[str, Any] | None,
    creating: bool,
) -> dict[str, Any]:
    """Validate an incoming `ext` payload for one model and return the merged
    stored value. `model_defs` is the org-enabled view; unknown extenders or
    fields are rejected outright."""
    if payload is None:
        payload = {}
    if not isinstance(payload, dict):
        raise _fail("ext must be an object of {extender: {field: value}}")

    merged: dict[str, Any] = {k: dict(v) for k, v in (current or {}).items() if isinstance(v, dict)}
    for extender, fields in payload.items():
        defs = model_defs.get(extender)
        if defs is None:
            raise _fail(f"unknown or disabled extender {extender!r}")
        if not isinstance(fields, dict):
            raise _fail(f"ext[{extender!r}] must be an object of {{field: value}}")
        bucket = merged.setdefault(extender, {})
        for name, value in fields.items():
            decl = defs.get(name)
            if decl is None:
                raise _fail(f"extender {extender!r} does not declare ext field {name!r}")
            if value is None:
                bucket.pop(name, None)
            else:
                bucket[name] = _coerce(decl, value)

    # Required fields of enabled extenders must be present after the merge.
    if creating:
        for extender, defs in model_defs.items():
            for name, decl in defs.items():
                if decl.get("required") and merged.get(extender, {}).get(name) is None:
                    raise _fail(f"ext field {extender}.{name} is required")
    return merged


def filter_ext_for_read(
    model_defs: dict[str, dict[str, dict[str, Any]]], stored: Any
) -> dict[str, Any]:
    """Only namespaces of extenders enabled for the org leave the API."""
    if not isinstance(stored, dict):
        return {}
    return {extender: values for extender, values in stored.items() if extender in model_defs}
