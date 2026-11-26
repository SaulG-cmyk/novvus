"""Auto-generated CRUD REST API for registered models.

For a model ``Contact`` in module ``crm`` the SDK exposes, under
``/api/crm/contacts``: list (cursor pagination, filters, ordering), create,
get, patch and soft-delete — each guarded by the conventional permissions
``crm.contacts.read`` / ``crm.contacts.write``. Any generated endpoint can be
disabled or overridden per model via ``__novvus_api__``.

NOTE: this module must NOT use ``from __future__ import annotations``: the
generated endpoints annotate their body parameter with dynamically-created
Pydantic classes held in local variables, which FastAPI can only see when
annotations are evaluated eagerly.
"""

import base64
import binascii
import csv
import io
import json
from collections.abc import AsyncIterator, Callable
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, ConfigDict, create_model
from sqlalchemy import Select, and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from novvus_sdk.chatter import ChatterHelper
from novvus_sdk.context import current_context
from novvus_sdk.custom_fields import (
    CustomFieldsRegistry,
    filter_custom_for_read,
    validate_custom_payload,
)
from novvus_sdk.extensions import (
    ExtensionsRegistry,
    filter_ext_for_read,
    validate_ext_payload,
)
from novvus_sdk.filters import parse_filter
from novvus_sdk.i18n import Translator
from novvus_sdk.meta import field_specs
from novvus_sdk.models import NovvusModel
from novvus_sdk.security import enforce

DEFAULT_LIMIT = 50
MAX_LIMIT = 200
# Row cap for exports (docs/VIEWS.md §6); read at request time so deployments
# and tests can tune it. Per-model override: __novvus_api__["export_max_rows"].
EXPORT_MAX_ROWS = 100_000

XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


# ---------------------------------------------------------------------------
# Pydantic schema generation from the SQLAlchemy model
# ---------------------------------------------------------------------------


def _python_type(column: Any) -> type:
    try:
        return column.type.python_type  # type: ignore[no-any-return]
    except NotImplementedError:
        return str


def build_schemas(
    model: type[NovvusModel],
) -> tuple[type[BaseModel], type[BaseModel], type[BaseModel]]:
    """(ReadSchema, CreateSchema, UpdateSchema) for a model."""
    read_fields: dict[str, Any] = {}
    create_fields: dict[str, Any] = {}
    update_fields: dict[str, Any] = {}

    for column in model.__table__.columns:
        name = column.key
        py_type = _python_type(column)
        read_fields[name] = (py_type | None if column.nullable else py_type, None)
        if name in NovvusModel.SYSTEM_COLUMNS:
            continue
        if column.nullable or column.default is not None or column.server_default is not None:
            create_fields[name] = (py_type | None, None)
        else:
            create_fields[name] = (py_type, ...)
        update_fields[name] = (py_type | None, None)

    # Cross-module extension data (docs/EXTENSIONS.md §5) and per-org custom
    # fields (docs/CUSTOM_FIELDS.md §7): writable through dedicated payload
    # keys, validated against the org's definitions.
    create_fields["ext"] = (dict | None, None)
    update_fields["ext"] = (dict | None, None)
    create_fields["custom"] = (dict | None, None)
    update_fields["custom"] = (dict | None, None)

    # extra="forbid" rejects unknown fields — in particular a client-supplied
    # org_id can never sneak into the payload (docs/MULTITENANCY.md §5).
    strict = ConfigDict(extra="forbid")
    lax = ConfigDict(from_attributes=True)
    read = create_model(f"{model.__name__}Read", __config__=lax, **read_fields)
    create = create_model(f"{model.__name__}Create", __config__=strict, **create_fields)
    update = create_model(f"{model.__name__}Update", __config__=strict, **update_fields)
    return read, create, update


# ---------------------------------------------------------------------------
# Cursor (keyset) pagination
# ---------------------------------------------------------------------------


def _encode_cursor(order_value: Any, item_id: UUID) -> str:
    if isinstance(order_value, datetime):
        serialized: Any = {"t": "dt", "v": order_value.isoformat()}
    elif isinstance(order_value, date):
        serialized = {"t": "d", "v": order_value.isoformat()}
    elif isinstance(order_value, UUID):
        serialized = {"t": "uuid", "v": str(order_value)}
    elif isinstance(order_value, Decimal):
        serialized = {"t": "dec", "v": str(order_value)}
    else:
        serialized = {"t": "raw", "v": order_value}
    payload = json.dumps({"o": serialized, "id": str(item_id)})
    return base64.urlsafe_b64encode(payload.encode()).decode()


def _decode_cursor(cursor: str) -> tuple[Any, UUID]:
    try:
        payload = json.loads(base64.urlsafe_b64decode(cursor.encode()))
        order = payload["o"]
        value: Any = order["v"]
        if order["t"] == "dt":
            value = datetime.fromisoformat(value)
        elif order["t"] == "d":
            value = date.fromisoformat(value)
        elif order["t"] == "uuid":
            value = UUID(value)
        elif order["t"] == "dec":
            value = Decimal(value)
        return value, UUID(payload["id"])
    except (ValueError, KeyError, binascii.Error) as exc:
        raise HTTPException(status_code=422, detail="invalid cursor") from exc


# ---------------------------------------------------------------------------
# Router generation
# ---------------------------------------------------------------------------


def build_router(
    module_id: str,
    model: type[NovvusModel],
    session_dependency: Callable[[], AsyncIterator[AsyncSession]],
    translator: Translator | None = None,
    extensions: ExtensionsRegistry | None = None,
    custom_fields: CustomFieldsRegistry | None = None,
    chatter: ChatterHelper | None = None,
    record_access: Callable[..., Any] | None = None,
    record_scope: Callable[..., Any] | None = None,
    actions: dict[str, Callable[..., Any]] | None = None,
    action_validators: dict[str, Callable[..., Any]] | None = None,
    action_options: dict[str, Callable[..., Any]] | None = None,
) -> APIRouter:
    resource = model.resource_name()
    api_config: dict[str, Any] = getattr(model, "__novvus_api__", {})
    disabled: set[str] = set(api_config.get("disabled", ()))
    perms: dict[str, str] = api_config.get("permissions", {})
    read_perm = perms.get("read", f"{module_id}.{resource}.read")
    write_perm = perms.get("write", f"{module_id}.{resource}.write")

    read_schema, create_schema, update_schema = build_schemas(model)
    router = APIRouter(prefix=f"/api/{module_id}/{resource}", tags=[resource])
    columns = {c.key: c for c in model.__table__.columns}

    # Field specs (docs/VIEWS.md §4) drive search, the filter DSL and grouping.
    specs = field_specs(module_id, model)
    search_fields: list[str] = [name for name, spec in specs.items() if spec["searchable"]]
    # Fields whose changes post a system chatter message (docs/CHATTER.md §6).
    track_fields: list[str] = list(
        (getattr(model, "__novvus_views__", None) or {}).get("track", [])
    )

    def base_query() -> Select[Any]:
        return select(model).where(model.deleted_at.is_(None))

    async def scoped_query(session: AsyncSession) -> Select[Any]:
        """Base query narrowed to the caller's record scope (docs/FILES.md §8.5)."""
        query = base_query()
        if record_scope is not None:
            clause = await record_scope(session, current_context())
            if clause is not None:
                query = query.where(clause)
        return query

    async def check_record(session: AsyncSession, item_id: UUID, action: str) -> None:
        """Record-level authorization; denial answers 404 so ids leak nothing."""
        if record_access is None:
            return
        if not await record_access(session, current_context(), item_id, action):
            raise HTTPException(status_code=404, detail=f"{resource} item not found")

    async def model_ext_defs() -> dict[str, dict[str, Any]]:
        """Org-enabled extension definitions for THIS model (may be empty)."""
        if extensions is None:
            return {}
        org_defs = await extensions.for_org(current_context().org_id)
        return org_defs.get(resource, {})

    async def model_custom_defs() -> dict[str, dict[str, Any]]:
        """Active custom-field definitions of the org for THIS model."""
        if custom_fields is None:
            return {}
        org_defs = await custom_fields.for_org(current_context().org_id)
        return org_defs.get(resource, {})

    def serialized(
        row: NovvusModel, ext_defs: dict[str, Any], custom_defs: dict[str, Any]
    ) -> dict[str, Any]:
        out: dict[str, Any] = read_schema.model_validate(row).model_dump(mode="json")
        out["ext"] = filter_ext_for_read(ext_defs, out.get("ext"))
        out["custom"] = filter_custom_for_read(custom_defs, out.get("custom"))
        return out

    def searched_and_filtered(
        query: Select[Any],
        q: str | None,
        filter: str | None,
        ext_defs: dict[str, Any] | None = None,
        custom_defs: dict[str, Any] | None = None,
    ) -> Select[Any]:
        """The ONE place where ?q= and the filter DSL hit a query: list, group
        and export share it by contract (docs/VIEWS.md §9)."""
        if q and search_fields:
            needle = f"%{q}%"
            query = query.where(
                or_(*[getattr(model, field).ilike(needle) for field in search_fields])
            )
        if filter:
            query = query.where(
                parse_filter(filter, model, specs, ext_defs=ext_defs, custom_defs=custom_defs)
            )
        return query

    async def get_item(session: AsyncSession, item_id: UUID) -> NovvusModel:
        row = await session.scalar(base_query().where(model.id == item_id))
        if row is None:
            raise HTTPException(status_code=404, detail=f"{resource} item not found")
        return row  # type: ignore[no-any-return]

    if "list" not in disabled:

        @router.get("", response_model=None)
        async def list_items(  # type: ignore[unused-ignore]
            request: Request,
            limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
            cursor: str | None = None,
            offset: int = Query(0, ge=0),
            with_total: bool = False,
            order_by: str = "-id",
            q: str | None = None,
            filter: str | None = None,
            session: AsyncSession = Depends(session_dependency),
        ) -> dict[str, Any]:
            enforce(read_perm)
            if cursor and offset:
                raise HTTPException(
                    status_code=422, detail="cursor and offset are mutually exclusive"
                )

            descending = order_by.startswith("-")
            order_field = order_by.lstrip("-")
            if order_field not in columns:
                raise HTTPException(status_code=422, detail=f"unknown order field {order_field!r}")
            order_col = getattr(model, order_field)
            id_col = model.id

            ext_defs = await model_ext_defs()
            custom_defs = await model_custom_defs()
            query = searched_and_filtered(
                await scoped_query(session), q, filter, ext_defs, custom_defs
            )

            # Equality filters: any query param matching a column name.
            reserved = {"limit", "cursor", "offset", "with_total", "order_by", "q", "filter"}
            for key, raw in request.query_params.items():
                if key in reserved or key not in columns:
                    continue
                column = getattr(model, key)
                try:
                    value = _coerce(columns[key], raw)
                except ValueError as exc:
                    raise HTTPException(
                        status_code=422, detail=f"invalid value for filter {key!r}"
                    ) from exc
                query = query.where(column == value)

            # Numeric pagination (docs/VIEWS.md §6): the total counts exactly the
            # rows this caller can list (scope, search, filter and flat filters
            # applied), before any cursor or offset narrows the page.
            total: int | None = None
            if with_total:
                total = (
                    await session.execute(
                        select(func.count()).select_from(query.order_by(None).subquery())
                    )
                ).scalar_one()

            if cursor:
                last_value, last_id = _decode_cursor(cursor)
                if descending:
                    query = query.where(
                        or_(
                            order_col < last_value,
                            and_(order_col == last_value, id_col < last_id),
                        )
                    )
                else:
                    query = query.where(
                        or_(
                            order_col > last_value,
                            and_(order_col == last_value, id_col > last_id),
                        )
                    )

            if descending:
                query = query.order_by(order_col.desc(), id_col.desc())
            else:
                query = query.order_by(order_col.asc(), id_col.asc())

            rows = (await session.scalars(query.offset(offset).limit(limit + 1))).all()
            has_more = len(rows) > limit
            rows = rows[:limit]
            next_cursor = None
            if has_more and rows:
                last = rows[-1]
                next_cursor = _encode_cursor(getattr(last, order_field), last.id)
            body: dict[str, Any] = {
                "items": [serialized(r, ext_defs, custom_defs) for r in rows],
                "next_cursor": next_cursor,
            }
            if with_total:
                body["total"] = total
            return body

    if "list" not in disabled:
        # NOTE: registered before GET /{item_id} so the literal path wins.
        @router.get("/group", response_model=None)
        async def group_items(
            by: str,
            q: str | None = None,
            filter: str | None = None,
            session: AsyncSession = Depends(session_dependency),
        ) -> dict[str, Any]:
            enforce(read_perm)

            custom_defs = await model_custom_defs()
            choices: list[dict[str, Any]] = []
            if by.startswith("custom."):
                # Group by a custom field (docs/CUSTOM_FIELDS.md §7): allowed
                # only for bounded value sets, like the merged meta declares.
                decl = custom_defs.get(by.removeprefix("custom."))
                config = (decl or {}).get("config") or {}
                groupable = decl is not None and (
                    decl.get("type") == "boolean" or bool(config.get("choices"))
                )
                if not groupable:
                    raise HTTPException(
                        status_code=422, detail=f"field {by!r} is unknown or not groupable"
                    )
                group_col = model.custom[by.removeprefix("custom.")].astext
                choices = config.get("choices") or []
            else:
                spec = specs.get(by)
                if spec is None or not spec["groupable"]:
                    raise HTTPException(
                        status_code=422, detail=f"field {by!r} is unknown or not groupable"
                    )
                group_col = getattr(model, by)
                choices = spec["choices"] or []

            # Same record scope as list/export (docs/FILES.md §8.5): counts
            # must never reveal rows the caller cannot list.
            grouped = select(group_col, func.count()).where(model.deleted_at.is_(None))
            if record_scope is not None:
                clause = await record_scope(session, current_context())
                if clause is not None:
                    grouped = grouped.where(clause)
            query = searched_and_filtered(
                grouped.group_by(group_col).order_by(func.count().desc(), group_col.asc()),
                q,
                filter,
                await model_ext_defs(),
                custom_defs,
            )

            choice_labels = {c["value"]: c["label"] for c in choices}
            groups = []
            for value, count in (await session.execute(query)).all():
                serialized = _json_value(value)
                label = None if value is None else choice_labels.get(serialized, str(serialized))
                groups.append({"value": serialized, "label": label, "count": count})
            return {"groups": groups}

        @router.get("/export", response_model=None)
        async def export_items(
            format: str = "csv",
            q: str | None = None,
            filter: str | None = None,
            order_by: str = "-id",
            session: AsyncSession = Depends(session_dependency),
        ) -> Response:
            enforce(read_perm)

            if format not in {"csv", "xlsx"}:
                raise HTTPException(status_code=422, detail=f"unknown export format {format!r}")
            order_field = order_by.lstrip("-")
            if order_field not in columns:
                raise HTTPException(status_code=422, detail=f"unknown order field {order_field!r}")

            ext_defs = await model_ext_defs()
            custom_defs = await model_custom_defs()
            max_rows = int(api_config.get("export_max_rows", EXPORT_MAX_ROWS))
            count_query = searched_and_filtered(
                select(func.count()).select_from(model).where(model.deleted_at.is_(None)),
                q,
                filter,
                ext_defs,
                custom_defs,
            )
            total = (await session.execute(count_query)).scalar_one()
            if total > max_rows:
                raise HTTPException(
                    status_code=422,
                    detail=f"export of {total} rows exceeds the limit of {max_rows}; "
                    "narrow the filter",
                )

            order_col = getattr(model, order_field)
            query = searched_and_filtered(
                await scoped_query(session), q, filter, ext_defs, custom_defs
            ).order_by(
                order_col.desc() if order_by.startswith("-") else order_col.asc(), model.id.asc()
            )

            locale = current_context().locale
            headers = [
                translator.gettext(spec["label"], locale) if translator else spec["label"]
                for spec in specs.values()
            ]
            field_names = list(specs.keys())
            # Extension and custom columns close the sheet (EXTENSIONS.md §5,
            # CUSTOM_FIELDS.md §7).
            ext_columns: list[tuple[str, str]] = [
                (extender, name)
                for extender, fields in sorted(ext_defs.items())
                for name in sorted(fields)
            ]
            headers.extend(
                str(ext_defs[extender][name].get("label", name)) for extender, name in ext_columns
            )
            custom_columns: list[str] = sorted(custom_defs)
            headers.extend(str(custom_defs[name].get("label", name)) for name in custom_columns)

            def cell(row: NovvusModel, name: str) -> Any:
                value = _json_value(getattr(row, name))
                return "" if value is None else value

            def ext_cell(row: NovvusModel, extender: str, name: str) -> Any:
                stored = getattr(row, "ext", None) or {}
                value = stored.get(extender, {}).get(name)
                return "" if value is None else value

            def custom_cell(row: NovvusModel, name: str) -> Any:
                stored = getattr(row, "custom", None) or {}
                value = stored.get(name)
                return "" if value is None else value

            disposition = {"Content-Disposition": f'attachment; filename="{resource}.{format}"'}

            if format == "csv":

                async def csv_stream() -> AsyncIterator[str]:
                    buffer = io.StringIO()
                    writer = csv.writer(buffer)
                    writer.writerow(headers)
                    yield buffer.getvalue()
                    async for row in await session.stream_scalars(query):
                        buffer.seek(0)
                        buffer.truncate()
                        writer.writerow(
                            [cell(row, name) for name in field_names]
                            + [ext_cell(row, extender, name) for extender, name in ext_columns]
                            + [custom_cell(row, name) for name in custom_columns]
                        )
                        yield buffer.getvalue()

                return StreamingResponse(
                    csv_stream(), media_type="text/csv; charset=utf-8", headers=disposition
                )

            # XLSX: write-only workbook keeps per-row memory flat; the file
            # itself is assembled at the end (openpyxl has no async streaming).
            from openpyxl import Workbook

            workbook = Workbook(write_only=True)
            sheet = workbook.create_sheet(title=resource[:31])
            sheet.append(headers)
            async for row in await session.stream_scalars(query):
                sheet.append(
                    [cell(row, name) for name in field_names]
                    + [ext_cell(row, extender, name) for extender, name in ext_columns]
                    + [custom_cell(row, name) for name in custom_columns]
                )
            output = io.BytesIO()
            workbook.save(output)
            return Response(
                content=output.getvalue(), media_type=XLSX_MEDIA_TYPE, headers=disposition
            )

    if "create" not in disabled:

        @router.post("", status_code=201, response_model=None)
        async def create_item(
            payload: create_schema,  # type: ignore[valid-type]
            session: AsyncSession = Depends(session_dependency),
        ) -> dict[str, Any]:
            enforce(write_perm)
            context = current_context()
            values = payload.model_dump(exclude_unset=True)  # type: ignore[attr-defined]
            ext_defs = await model_ext_defs()
            custom_defs = await model_custom_defs()
            ext_payload = values.pop("ext", None)
            values["ext"] = validate_ext_payload(ext_defs, ext_payload, None, creating=True)
            custom_payload = values.pop("custom", None)
            values["custom"] = validate_custom_payload(
                custom_defs, custom_payload, None, creating=True
            )
            instance = model(**values, org_id=context.org_id)
            session.add(instance)
            await session.flush()
            await session.refresh(instance)
            return serialized(instance, ext_defs, custom_defs)

    if "get" not in disabled:

        @router.get("/{item_id}", response_model=None)
        async def get_one(
            item_id: UUID,
            session: AsyncSession = Depends(session_dependency),
        ) -> dict[str, Any]:
            enforce(read_perm)
            row = await get_item(session, item_id)
            await check_record(session, item_id, "read")
            return serialized(row, await model_ext_defs(), await model_custom_defs())

    if "update" not in disabled:

        @router.patch("/{item_id}", response_model=None)
        async def update_item(
            item_id: UUID,
            payload: update_schema,  # type: ignore[valid-type]
            session: AsyncSession = Depends(session_dependency),
        ) -> dict[str, Any]:
            enforce(write_perm)
            row = await get_item(session, item_id)
            await check_record(session, item_id, "write")
            values = payload.model_dump(exclude_unset=True)  # type: ignore[attr-defined]
            ext_defs = await model_ext_defs()
            custom_defs = await model_custom_defs()
            if "ext" in values:
                ext_payload = values.pop("ext")
                values["ext"] = validate_ext_payload(ext_defs, ext_payload, row.ext, creating=False)
            if "custom" in values:
                custom_payload = values.pop("custom")
                values["custom"] = validate_custom_payload(
                    custom_defs, custom_payload, row.custom, creating=False
                )
            # Tracked-field changes post system chatter messages afterwards
            # (docs/CHATTER.md §6); capture the old values before applying.
            changes: list[tuple[str, Any, Any]] = [
                (field, _json_value(getattr(row, field)), _json_value(values[field]))
                for field in track_fields
                if field in values and getattr(row, field) != values[field]
            ]
            for key, value in values.items():
                setattr(row, key, value)
            await session.flush()
            await session.refresh(row)
            if changes and chatter is not None:
                await chatter.track_changes(resource, item_id, changes)
            return serialized(row, ext_defs, custom_defs)

    if "delete" not in disabled:

        @router.delete("/{item_id}", status_code=204)
        async def delete_item(
            item_id: UUID,
            session: AsyncSession = Depends(session_dependency),
        ) -> None:
            enforce(write_perm)
            row = await get_item(session, item_id)
            await check_record(session, item_id, "write")
            row.deleted_at = datetime.now(tz=UTC)
            await session.flush()

    # Record actions (docs/VIEWS.md §8b) and collection actions (§8f): declared in the meta,
    # implemented
    # by the module. The permission is checked here (never trusted from the client), a record action
    # needs a record readable by the caller, and the body is validated against the declared fields
    # before the handler runs. `…/validate` (§8f) runs the module's read-only validator and returns
    # `{"errors": {field: message}}` so the shell can show problems next to the fields while typing.
    model_views = getattr(model, "__novvus_views__", {}) or {}
    declared_actions: dict[str, dict[str, Any]] = {
        a["name"]: a for a in model_views.get("actions", []) or []
    }

    async def _action_body(
        request: Request, spec: dict[str, Any], *, partial: bool
    ) -> dict[str, Any]:
        raw = await request.body()
        try:
            body = json.loads(raw) if raw else {}
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="body must be a JSON object") from exc
        if not isinstance(body, dict):
            raise HTTPException(status_code=422, detail="body must be a JSON object")
        return _validate_action_body(spec, body, partial=partial)

    def _lookup(
        name: str, *, collection: bool, validator: bool = False, options: bool = False
    ) -> tuple[dict[str, Any], Callable[..., Any]]:
        spec = declared_actions.get(name)
        table = (
            (action_options or {})
            if options
            else (action_validators or {})
            if validator
            else (actions or {})
        )
        fn = table.get(name)
        if (
            spec is None
            or fn is None
            or (spec.get("scope", "record") == "collection") != collection
        ):
            raise HTTPException(status_code=404, detail=f"action {name!r} not found")
        enforce(spec.get("permission") or write_perm)
        return spec, fn

    if declared_actions and "get" not in disabled:

        @router.post("/{item_id}/actions/{name}", response_model=None)
        async def run_action(
            item_id: UUID,
            name: str,
            request: Request,
            session: AsyncSession = Depends(session_dependency),
        ) -> Any:
            spec, handler = _lookup(name, collection=False)
            row = await get_item(session, item_id)
            await check_record(session, item_id, "read")
            cleaned = await _action_body(request, spec, partial=False)
            result = await handler(session, current_context(), row, cleaned)
            await session.flush()
            return result if result is not None else {"ok": True}

        @router.post("/{item_id}/actions/{name}/validate", response_model=None)
        async def validate_action(
            item_id: UUID,
            name: str,
            request: Request,
            session: AsyncSession = Depends(session_dependency),
        ) -> Any:
            spec, validator = _lookup(name, collection=False, validator=True)
            row = await get_item(session, item_id)
            await check_record(session, item_id, "read")
            cleaned = await _action_body(request, spec, partial=True)
            errors = await validator(session, current_context(), row, cleaned)
            return {"errors": dict(errors or {})}

        @router.post("/{item_id}/actions/{name}/options", response_model=None)
        async def options_action(
            item_id: UUID,
            name: str,
            request: Request,
            session: AsyncSession = Depends(session_dependency),
        ) -> Any:
            # §8g: choices that depend on the record and on the values typed so far (read-only)
            spec, provider = _lookup(name, collection=False, options=True)
            row = await get_item(session, item_id)
            await check_record(session, item_id, "read")
            cleaned = await _action_body(request, spec, partial=True)
            provided = await provider(session, current_context(), row, cleaned)
            return {"options": _clean_options(spec, provided)}

    if any(a.get("scope") == "collection" for a in declared_actions.values()):

        @router.post("/actions/{name}", response_model=None)
        async def run_collection_action(
            name: str,
            request: Request,
            session: AsyncSession = Depends(session_dependency),
        ) -> Any:
            spec, handler = _lookup(name, collection=True)
            cleaned = await _action_body(request, spec, partial=False)
            result = await handler(session, current_context(), None, cleaned)
            await session.flush()
            return result if result is not None else {"ok": True}

        @router.post("/actions/{name}/validate", response_model=None)
        async def validate_collection_action(
            name: str,
            request: Request,
            session: AsyncSession = Depends(session_dependency),
        ) -> Any:
            spec, validator = _lookup(name, collection=True, validator=True)
            cleaned = await _action_body(request, spec, partial=True)
            errors = await validator(session, current_context(), None, cleaned)
            return {"errors": dict(errors or {})}

        @router.post("/actions/{name}/options", response_model=None)
        async def options_collection_action(
            name: str,
            request: Request,
            session: AsyncSession = Depends(session_dependency),
        ) -> Any:
            spec, provider = _lookup(name, collection=True, options=True)
            cleaned = await _action_body(request, spec, partial=True)
            provided = await provider(session, current_context(), None, cleaned)
            return {"options": _clean_options(spec, provided)}

    return router


def _validate_action_body(
    spec: dict[str, Any], body: dict[str, Any], *, partial: bool = False
) -> dict[str, Any]:
    """Keep only the declared fields, coerce simple types and enforce `required`/`choices`.
    `partial=True` (validation while typing, §8f) skips `required` and drops invalid values."""
    fields = spec.get("fields", []) or []
    out: dict[str, Any] = {}
    for f in fields:
        fname, ftype = f["name"], f.get("type", "string")
        if ftype in ("file", "files"):
            # §8m: the binaries never travel in the body — the shell uploads them to Files once
            # the handler has answered `{record}`; `required` is enforced by the shell
            out[fname] = None
            continue
        value = body.get(fname, f.get("default"))
        if ftype == "choice" and f.get("multiple"):
            # §8m: a multi-select choice carries a list of values (a lone string counts as one)
            values = value if isinstance(value, list) else ([] if value in (None, "") else [value])
            values = [str(v) for v in values if v not in (None, "")]
            if not values:
                if f.get("required") and not partial:
                    raise HTTPException(status_code=422, detail=f"field {fname!r} is required")
                out[fname] = []
                continue
            if not f.get("options"):
                allowed = [c["value"] if isinstance(c, dict) else c for c in f.get("choices", [])]
                bad = [v for v in values if v not in allowed]
                if bad:
                    if partial:
                        values = [v for v in values if v in allowed]
                    else:
                        raise HTTPException(
                            status_code=422, detail=f"field {fname!r}: not an allowed choice"
                        )
            out[fname] = values
            continue
        if value in (None, ""):
            if f.get("required") and not partial:
                raise HTTPException(status_code=422, detail=f"field {fname!r} is required")
            out[fname] = None
            continue
        try:
            if ftype == "date":
                value = date.fromisoformat(str(value)[:10]).isoformat()
            elif ftype == "datetime":
                # ISO 8601 (the shell sends UTC with a trailing Z); a naive value stays naive
                value = datetime.fromisoformat(str(value).replace("Z", "+00:00")).isoformat()
            elif ftype == "number":
                value = float(value)
            elif ftype == "boolean":
                if not isinstance(value, bool):
                    value = str(value).lower() in {"true", "1", "yes", "on"}
            elif ftype in {"string", "text", "choice"}:
                value = str(value)
        except (TypeError, ValueError) as exc:
            if partial:
                out[fname] = None
                continue
            raise HTTPException(
                status_code=422, detail=f"field {fname!r}: invalid {ftype}"
            ) from exc
        if ftype == "choice" and not f.get("options"):
            # a field with run-time `options` (§8g) is checked by the module itself
            allowed = [c["value"] if isinstance(c, dict) else c for c in f.get("choices", [])]
            if value not in allowed:
                if partial:
                    out[fname] = None
                    continue
                raise HTTPException(
                    status_code=422, detail=f"field {fname!r}: not an allowed choice"
                )
        out[fname] = value
    return out


def _clean_options(spec: dict[str, Any], provided: Any) -> dict[str, list[dict[str, Any]]]:
    """Keep only the declared `options` fields and normalize each choice to `{value, label, …}`."""
    wanted = {f["name"] for f in spec.get("fields", []) or [] if f.get("options")}
    out: dict[str, list[dict[str, Any]]] = {}
    for fname, choices in dict(provided or {}).items():
        if fname not in wanted:
            continue
        cleaned: list[dict[str, Any]] = []
        for c in choices or []:
            if isinstance(c, str):
                cleaned.append({"value": c, "label": c})
            elif isinstance(c, dict) and "value" in c:
                item: dict[str, Any] = {
                    "value": str(c["value"]),
                    "label": str(c.get("label") or c["value"]),
                }
                if c.get("description"):
                    item["description"] = str(c["description"])
                if isinstance(c.get("details"), dict):
                    item["details"] = {str(k): str(v) for k, v in c["details"].items()}
                cleaned.append(item)
        out[fname] = cleaned
    return out


def _json_value(value: Any) -> Any:
    """Serialize a group key for the JSON response."""
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, (UUID, Decimal)):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    return value


def _coerce(column: Any, raw: str) -> Any:
    py_type = _python_type(column)
    if py_type is bool:
        if raw.lower() in {"true", "1"}:
            return True
        if raw.lower() in {"false", "0"}:
            return False
        raise ValueError(raw)
    if py_type is UUID:
        return UUID(raw)
    if py_type is datetime:
        return datetime.fromisoformat(raw)
    if py_type is date:
        return date.fromisoformat(raw)
    if py_type is Decimal:
        return Decimal(raw)
    if isinstance(py_type, type) and issubclass(py_type, Enum):
        return py_type(raw)
    if py_type in (int, float):
        return py_type(raw)
    return raw
