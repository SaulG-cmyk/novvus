"""JSON filter DSL (docs/VIEWS.md §5).

Parses the ``?filter=`` query param, validates it against the model's field
specs and translates it to SQLAlchemy column expressions. Closed operator
whitelist; only ``filterable`` fields; never raw SQL or string interpolation.
Every rejection is a 422 carrying the path of the failing node.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, NoReturn, cast
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import Boolean, Date, DateTime, Integer, Numeric, and_, or_
from sqlalchemy import cast as sql_cast
from sqlalchemy.sql import ColumnElement

from novvus_sdk.meta import COMPARABLE_TYPES, TEXT_TYPES
from novvus_sdk.models import NovvusModel

MAX_DEPTH = 5
MAX_CONDITIONS = 50
MAX_IN_VALUES = 100

BASE_OPS = {"eq", "ne", "in", "is_null"}
COMPARISON_OPS = {"gt", "gte", "lt", "lte", "between"}
TEXT_OPS = {"contains", "ilike"}

LIKE_ESCAPE = "\\"


def _fail(path: str, message: str) -> NoReturn:
    raise HTTPException(status_code=422, detail={"message": message, "path": path})


def _escape_like(value: str) -> str:
    return (
        value.replace(LIKE_ESCAPE, LIKE_ESCAPE + LIKE_ESCAPE)
        .replace("%", LIKE_ESCAPE + "%")
        .replace("_", LIKE_ESCAPE + "_")
    )


def _coerce_scalar(field_type: str, value: Any, path: str) -> Any:
    """Validate/convert one JSON value against the field's meta type."""
    if value is None:
        _fail(path, "null value: use the is_null operator")
    if field_type == "boolean":
        if isinstance(value, bool):
            return value
        _fail(path, "expected a boolean")
    if field_type == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            _fail(path, "expected an integer")
        return value
    if field_type == "decimal":
        if isinstance(value, bool) or not isinstance(value, (int, float, str)):
            _fail(path, "expected a number")
        try:
            return Decimal(str(value))
        except InvalidOperation:
            _fail(path, "expected a number")
    if field_type == "date":
        if not isinstance(value, str):
            _fail(path, "expected an ISO date string")
        try:
            return date.fromisoformat(value)
        except ValueError:
            _fail(path, "expected an ISO date string")
    if field_type == "datetime":
        if not isinstance(value, str):
            _fail(path, "expected an ISO datetime string")
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            _fail(path, "expected an ISO datetime string")
    if field_type in {"uuid", "relation"}:
        if not isinstance(value, str):
            _fail(path, "expected a UUID string")
        try:
            return UUID(value)
        except ValueError:
            _fail(path, "expected a UUID string")
    if field_type in TEXT_TYPES:
        if not isinstance(value, str):
            _fail(path, "expected a string")
        return value
    _fail(path, f"field type {field_type!r} does not support filtering")


def _allowed_ops(field_type: str) -> set[str]:
    ops = set(BASE_OPS)
    if field_type in COMPARABLE_TYPES:
        ops |= COMPARISON_OPS
    if field_type in TEXT_TYPES:
        ops |= TEXT_OPS
    return ops


def _jsonb_cast(text_expr: Any, field_type: str) -> ColumnElement[Any]:
    """Cast a `->>` text expression to its declared meta type. Absent keys
    become SQL NULL, so is_null works."""
    if field_type == "integer":
        return sql_cast(text_expr, Integer)
    if field_type == "decimal":
        return sql_cast(text_expr, Numeric)
    if field_type == "boolean":
        return sql_cast(text_expr, Boolean)
    if field_type == "date":
        return sql_cast(text_expr, Date)
    if field_type == "datetime":
        return sql_cast(text_expr, DateTime(timezone=True))
    return cast("ColumnElement[Any]", text_expr)


def _resolve_field(
    field: str,
    path: str,
    model: type[NovvusModel],
    specs: dict[str, dict[str, Any]],
    ext_defs: dict[str, dict[str, Any]] | None,
    custom_defs: dict[str, dict[str, Any]] | None,
) -> tuple[str, ColumnElement[Any]]:
    """(meta type, SQL column) for a regular column, an `ext.{extender}.{name}`
    extension field or a `custom.{name}` per-org custom field."""
    if field.startswith("ext."):
        parts = field.split(".", 2)
        if len(parts) != 3 or not all(parts):
            _fail(path, f"extension field {field!r} must be ext.{{extender}}.{{name}}")
        _, extender, name = parts
        decl = (ext_defs or {}).get(extender, {}).get(name)
        if decl is None:
            _fail(path, f"unknown or disabled extension field {field!r}")
        field_type = str(decl.get("type", "string"))
        return field_type, _jsonb_cast(model.ext[extender][name].astext, field_type)

    if field.startswith("custom."):
        name = field.removeprefix("custom.")
        decl = (custom_defs or {}).get(name)
        if decl is None or not name:
            _fail(path, f"unknown or inactive custom field {field!r}")
        field_type = str(decl.get("type", "string"))
        return field_type, _jsonb_cast(model.custom[name].astext, field_type)

    spec = specs.get(field)
    if spec is None or not spec["filterable"]:
        _fail(path, f"unknown or non-filterable field {field!r}")
    return spec["type"], getattr(model, field)


def _condition(
    node: dict[str, Any],
    path: str,
    model: type[NovvusModel],
    specs: dict[str, dict[str, Any]],
    ext_defs: dict[str, dict[str, Any]] | None,
    custom_defs: dict[str, dict[str, Any]] | None,
) -> ColumnElement[bool]:
    extra_keys = set(node) - {"field", "op", "value"}
    if extra_keys:
        _fail(path, f"unknown keys {sorted(extra_keys)}")
    field = node.get("field")
    op = node.get("op")
    if not isinstance(field, str) or not isinstance(op, str):
        _fail(path, "a condition requires string 'field' and 'op'")

    field_type, column = _resolve_field(field, path, model, specs, ext_defs, custom_defs)
    if op not in _allowed_ops(field_type):
        _fail(path, f"operator {op!r} is not allowed for type {field_type!r}")

    value = node.get("value")

    if op == "is_null":
        if not isinstance(value, bool):
            _fail(path, "is_null requires a boolean value")
        return column.is_(None) if value else column.is_not(None)
    if op == "in":
        if not isinstance(value, list) or not value:
            _fail(path, "in requires a non-empty array")
        if len(value) > MAX_IN_VALUES:
            _fail(path, f"in accepts at most {MAX_IN_VALUES} values")
        return column.in_(
            [_coerce_scalar(field_type, v, f"{path}.value[{i}]") for i, v in enumerate(value)]
        )
    if op == "between":
        if not isinstance(value, list) or len(value) != 2:
            _fail(path, "between requires an array of exactly two values")
        low = _coerce_scalar(field_type, value[0], f"{path}.value[0]")
        high = _coerce_scalar(field_type, value[1], f"{path}.value[1]")
        return column.between(low, high)
    if op == "contains":
        text = _coerce_scalar(field_type, value, f"{path}.value")
        return column.ilike(f"%{_escape_like(text)}%", escape=LIKE_ESCAPE)
    if op == "ilike":
        text = _coerce_scalar(field_type, value, f"{path}.value")
        return column.ilike(text, escape=LIKE_ESCAPE)

    coerced = _coerce_scalar(field_type, value, f"{path}.value")
    # SQLAlchemy comparison dunders are typed Any (object.__eq__ contract).
    comparison: Any
    if op == "eq":
        comparison = column == coerced
    elif op == "ne":
        comparison = column != coerced
    elif op == "gt":
        comparison = column > coerced
    elif op == "gte":
        comparison = column >= coerced
    elif op == "lt":
        comparison = column < coerced
    else:  # lte — the whitelist guarantees no other op reaches here
        comparison = column <= coerced
    return cast("ColumnElement[bool]", comparison)


def _walk(
    node: Any,
    path: str,
    depth: int,
    counter: list[int],
    model: type[NovvusModel],
    specs: dict[str, dict[str, Any]],
    ext_defs: dict[str, dict[str, Any]] | None,
    custom_defs: dict[str, dict[str, Any]] | None,
) -> ColumnElement[bool]:
    if depth > MAX_DEPTH:
        _fail(path, f"filter exceeds the maximum nesting depth of {MAX_DEPTH}")
    if not isinstance(node, dict):
        _fail(path, "expected an object")

    if "and" in node or "or" in node:
        if len(node) != 1:
            _fail(path, "a group must have exactly one key: 'and' or 'or'")
        connector, children = next(iter(node.items()))
        if not isinstance(children, list) or not children:
            _fail(path, f"'{connector}' requires a non-empty array")
        clauses = [
            _walk(child, f"{path}.{connector}[{i}]" if path else f"{connector}[{i}]",
                  depth + 1, counter, model, specs, ext_defs, custom_defs)
            for i, child in enumerate(children)
        ]
        return and_(*clauses) if connector == "and" else or_(*clauses)

    counter[0] += 1
    if counter[0] > MAX_CONDITIONS:
        _fail(path, f"filter exceeds the maximum of {MAX_CONDITIONS} conditions")
    return _condition(node, path or "$", model, specs, ext_defs, custom_defs)


def parse_filter(
    raw: str,
    model: type[NovvusModel],
    specs: dict[str, dict[str, Any]],
    ext_defs: dict[str, dict[str, Any]] | None = None,
    custom_defs: dict[str, dict[str, Any]] | None = None,
) -> ColumnElement[bool]:
    """Parse the ?filter= JSON into a SQLAlchemy boolean expression."""
    try:
        tree = json.loads(raw)
    except json.JSONDecodeError:
        _fail("$", "invalid JSON")
    return _walk(tree, "", 1, [0], model, specs, ext_defs, custom_defs)
