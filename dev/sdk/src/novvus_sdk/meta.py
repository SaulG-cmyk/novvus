"""Model metadata export (docs/VIEWS.md).

Builds the meta document the platform shell uses to render generic views:
models, typed fields with capability flags, and the views declared through the
optional ``__novvus_views__`` class attribute. Validation is fail-fast: a
module with a broken declaration must not start.
"""

from __future__ import annotations

import enum
import re
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PgUUID

from novvus_sdk.models import NovvusModel

META_VERSION = 1

# Platform columns never exposed in the meta (docs/VIEWS.md §4). The raw
# `ext`/`custom` columns stay hidden too: their fields reach the meta merged
# by the kernel as `ext.{extender}.{field}` / `custom.{field}`.
HIDDEN_COLUMNS = frozenset({"org_id", "deleted_at", "ext", "custom"})
READONLY_COLUMNS = frozenset({"id", "created_at", "updated_at"})
GROUPABLE_TYPES = frozenset({"string", "boolean", "date", "relation"})
COMPARABLE_TYPES = frozenset({"integer", "decimal", "date", "datetime"})
TEXT_TYPES = frozenset({"string", "text"})

# The only flags a model may override per field in __novvus_views__["fields"].
FLAG_OVERRIDES = frozenset({"searchable", "sortable", "filterable", "groupable", "readonly"})

VIEW_KEYS = frozenset(
    {
        "label",
        "labels",
        "display",
        "fields",
        "list",
        "form",
        "kanban",
        "calendar",
        "attachments",
        "chatter",
        "track",
        "actions",
        "related",
        "viewer",
        "nav",
        "workbench",
        "editor",
        "journey",
        "process",
        "dashboard",
        "choices",
        "timeline",
        "map",
        "board",
    }
)
# §8p (SDK 0.2.20): a board page for a singleton model: an optional map on top (same contract as
# `map` without `record`) and 1..4 columns, each a related panel scoped to the single record.
BOARD_KEYS = frozenset({"title", "help", "map", "columns"})
BOARD_MAP_KEYS = frozenset({"path", "title", "help", "refresh_seconds"})
BOARD_COLUMNS_RANGE = (1, 4)
# §8k (SDK 0.2.16): a Gantt over two date fields, filled by a progress field, grouped by a field,
# with dependency arrows read from a declared model of the same module. Opaque for the kernel.
TIMELINE_KEYS = frozenset(
    {"start_field", "end_field", "title", "progress_field", "group_field", "dependencies"}
)
TIMELINE_DEPENDENCY_KEYS = frozenset(
    {"model", "predecessor_field", "successor_field", "kind_field"}
)
# §8j (SDK 0.2.16): `kanban.action` names a declared record action the board runs when a card is
# dropped on another column (body `{group_by: value}`) instead of patching the field, so the move
# goes through the module's business rule; `choices` gives Spanish labels to enum values
# (`{"status": {"active": "Activa"}}`) without renaming the values the API exchanges.
KANBAN_KEYS = frozenset({"group_by", "card", "action"})
# §8h (SDK 0.2.13): a workbench is the model's landing page instead of its list — file slots
# the user fills, the fields of the `run` action inline, one button, and the progress of the
# related run as tabs on top (one per step). Declarative and opaque for the kernel.
WORKBENCH_KEYS = frozenset(
    {"title", "help", "create", "slots", "assign", "run", "progress", "history"}
)
WORKBENCH_SLOT_KEYS = frozenset({"name", "label", "field", "accept", "required", "help"})
WORKBENCH_PROGRESS_KEYS = frozenset({"related", "steps", "tabs", "stage", "state", "summary"})
WORKBENCH_STEPS_KEYS = frozenset({"model", "field", "key", "order", "columns"})
# §8i (SDK 0.2.14): the record page is a document editor — the model's `viewer` on one
# side and, on the other, the cards of editable fields the module serves for that record
# (`GET /api/{module}/{path}/{id}/editor`), with the buttons the same answer declares
# (`POST …/editor/{action}`). The declaration only names the module route; the sections,
# values, state and actions come from the module at run time, so the shell never guesses
# business rules. Declarative and opaque for the kernel.
EDITOR_KEYS = frozenset({"path", "title", "help"})
# §8n (SDK 0.2.17): the record page is a journey — a sequence of full pages (prepare, assign,
# in the field, delivered…) the module serves for that record
# (`GET /api/{module}/{path}/{id}/journey`):
# sections of fields, files with their processing, summaries, galleries, a map slot, history… and
# the buttons of each page (`POST …/journey/{action}`). Declarative and opaque for the kernel: the
# shell renders pages and sends back values and uploaded file ids; the module owns every rule.
JOURNEY_KEYS = frozenset({"path", "title", "help"})
# §8o (SDK 0.2.19): a map of points and routes of a model. The module serves
# `GET /api/{module}/{path}` (the collection) and, with `record`, `GET …/{path}/{id}` (one
# record): points with tone, kind, link and icon, routes as a straight estimate (`from`/`to`)
# or along a polyline, legend, bounds and notice. The shell only draws (configurable tiles);
# it never geocodes nor computes routes. Opaque for the kernel.
MAP_KEYS = frozenset({"path", "title", "help", "refresh_seconds", "record"})
MAP_REFRESH_RANGE = (5, 3600)
_EDITOR_PATH = re.compile(r"^[a-z0-9][a-z0-9_-]*(/[a-z0-9][a-z0-9_-]*)*$")
# Navegación (docs/VIEWS.md §8e): dónde aparece el modelo en la navegación de la app. `group`
# agrupa varios modelos bajo un encabezado (p. ej. «Configuración»), `order` ordena dentro de
# su nivel y `hidden` lo quita de la navegación sin quitar sus vistas (siguen accesibles por
# URL, pestañas y relacionados). Los permisos de lectura siguen filtrando.
# `singleton` (SDK 0.2.12, docs/VIEWS.md §8g): the navigation entry opens the model's single
# record (settings-like models) instead of a one-row list.
# `icon` (SDK 0.2.18, docs/VIEWS.md §8e): slug del icono de la entrada; el catálogo lo resuelve la
# shell y uno desconocido cae en el icono de tabla. Minúsculas, dígitos y guiones.
NAV_KEYS = frozenset({"group", "order", "hidden", "singleton", "icon"})
_NAV_ICON = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
# Indicador de etapas del formulario (docs/VIEWS.md §8e): `field` es el campo cuyo valor sitúa
# al registro en una etapa; cada paso lista los `values` que lo representan. La shell pinta
# los pasos anteriores como cumplidos, el actual resaltado y los siguientes pendientes.
STAGE_KEYS = frozenset({"label", "values"})

# Record actions (docs/VIEWS.md §8b): declarative buttons on the record form that call a
# module handler (`@module.action(Model, name)`) through
# `POST /api/{module}/{resource}/{id}/actions/{name}`.
ACTION_KEYS = frozenset(
    {
        "name",
        "label",
        "permission",
        "confirm",
        "fields",
        "variant",
        "success",
        "description",
        "scope",
        "help",
        "validate",
        "secondary",
        "prefill",
        "presentation",
        "after",
    }
)
# §8m (SDK 0.2.17): an action may open as a full page instead of a dialog (`presentation:
# "page"`): its fields are grouped in cards (`group`), `file`/`files` fields upload to the
# record's Files after the handler answers `{record}`, and `after` names a record action the
# shell runs once the uploads are done (e.g. "process the files just uploaded").
ACTION_PRESENTATIONS = frozenset({"dialog", "page"})
# §8l (SDK 0.2.17): `prefill` = the shell opens the dialog of a RECORD action with each field whose
# name matches a field of the record set to the record value (the handler still receives only
# what the user submits); `datetime` fields are edited as a local date and time and sent as ISO.
# §8g (SDK 0.2.12): `secondary` = the shell groups the action under a "Más" menu instead of a
# first-level button, so the primary actions of a record stay evident.
# §8f (SDK 0.2.11): `scope` = record (default, button on the record form) | collection (button on
# the list, no record); `help` = short help shown on demand instead of a leading paragraph;
# `validate` = the shell may
# call `POST …/actions/{name}/validate` while the user types and show the returned field errors.
ACTION_SCOPES = frozenset({"record", "collection"})
ACTION_FIELD_KEYS = frozenset(
    {
        "name",
        "label",
        "type",
        "required",
        "choices",
        "placeholder",
        "default",
        "help",
        "options",
        "group",
        "accept",
        "multiple",
    }
)
# §8g (SDK 0.2.12): a `choice` field with `options: True` takes its choices from the module at
# run time (`@module.action_options`, `POST …/actions/{name}/options` with the values typed so
# far), so the list may depend on the record and on the other fields (e.g. the entity to correct
# and then its editable fields with their current values). Static `choices` become optional.
ACTION_FIELD_TYPES = frozenset(
    {"string", "text", "number", "boolean", "choice", "date", "datetime", "file", "files"}
)
# A choice is a string or {value, label} plus optional `description` (one line under the label) and
# `details` ({label: value} shown under the field once the choice is selected, e.g. a certificate).
ACTION_CHOICE_KEYS = frozenset({"value", "label", "description", "details"})
ACTION_VARIANTS = frozenset({"default", "primary", "destructive"})
ACTION_SUCCESS = frozenset({"reload", "show", "download", "open"})
# Related rows (docs/VIEWS.md §8b): rows of another model of the same module whose `field`
# references this record.
# `filter` (SDK 0.2.12, §8g): a filter-DSL node the shell ANDs with `field = record`.
RELATED_KEYS = frozenset({"model", "field", "label", "columns", "order", "limit", "filter"})
# Pestañas del formulario (docs/VIEWS.md §8c): cada pestaña agrupa filas del layout, paneles
# relacionados (por modelo), anexos y/o el hilo; el visor (si se declara) acompaña al formulario.
TAB_KEYS = frozenset({"label", "rows", "sections", "related", "attachments", "chatter"})
# Visor de documentos relacionados: filas de `model` cuyo `field` apunta al registro, con un
# archivo de Files en `file_field`; la shell muestra el más reciente según `order`.
VIEWER_KEYS = frozenset({"model", "field", "file_field", "label_field", "order", "label", "filter"})
BADGE_TONES = frozenset({"neutral", "info", "success", "warning", "danger"})

DEFAULT_LIST_COLUMNS = 6
_SLUG = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")


def _views_config(model: type[NovvusModel]) -> dict[str, Any]:
    return getattr(model, "__novvus_views__", {}) or {}


def _meta_type(column: Any) -> str:
    if column.foreign_keys:
        return "relation"
    column_type = column.type
    if isinstance(column_type, sa.Enum):
        return "string"
    if isinstance(column_type, sa.Text):
        return "text"
    if isinstance(column_type, sa.String):
        return "string"
    if isinstance(column_type, sa.Boolean):
        return "boolean"
    if isinstance(column_type, sa.DateTime):
        return "datetime"
    if isinstance(column_type, sa.Date):
        return "date"
    if isinstance(column_type, sa.Integer):
        return "integer"
    if isinstance(column_type, sa.Numeric):
        return "decimal"
    if isinstance(column_type, (PgUUID, sa.Uuid)):
        return "uuid"
    if isinstance(column_type, sa.JSON):
        return "json"
    try:
        python_type = column_type.python_type
    except NotImplementedError:
        return "string"
    return {bool: "boolean", int: "integer", float: "decimal", str: "string"}.get(
        python_type, "string"
    )


def _relation_target(module_id: str, column: Any) -> str | None:
    if not column.foreign_keys:
        return None
    target_table = next(iter(column.foreign_keys)).column.table
    # Resolve the mapped class so __resource__ overrides are honored
    # (table "company" → resource "companies", not "companys").
    for mapper in NovvusModel.registry.mappers:
        if mapper.local_table is target_table:
            return f"{module_id}.{mapper.class_.resource_name()}"
    name = target_table.name
    return f"{module_id}.{name if name.endswith('s') else f'{name}s'}"


def _choices(column: Any) -> list[dict[str, Any]] | None:
    if not isinstance(column.type, sa.Enum):
        return None
    enum_class = column.type.enum_class
    if enum_class is not None and issubclass(enum_class, enum.Enum):
        return [{"value": member.value, "label": member.value} for member in enum_class]
    return [{"value": value, "label": value} for value in column.type.enums]


def _labelled_choices(
    choices: list[dict[str, Any]] | None, labels: dict[str, str] | None
) -> list[dict[str, Any]] | None:
    """§8j: apply the model's `choices` labels to the enum options (values untouched)."""
    if choices is None or not labels:
        return choices
    return [{**choice, "label": labels.get(choice["value"], choice["label"])} for choice in choices]


def _scalar_default(column: Any) -> Any:
    default = column.default
    if default is None or not getattr(default, "is_scalar", False):
        return None
    value = default.arg
    return value if isinstance(value, (str, int, float, bool)) else None


def field_specs(module_id: str, model: type[NovvusModel]) -> dict[str, dict[str, Any]]:
    """Ordered field spec per column (docs/VIEWS.md §4), overrides applied."""
    views = _views_config(model)
    labels: dict[str, str] = views.get("labels", {})
    api_config: dict[str, Any] = getattr(model, "__novvus_api__", {})
    explicit_search: list[str] | None = api_config.get("search")
    declared_labels = views.get("choices")
    choice_labels: dict[str, Any] = declared_labels if isinstance(declared_labels, dict) else {}

    specs: dict[str, dict[str, Any]] = {}
    for column in model.__table__.columns:
        name = column.key
        if name in HIDDEN_COLUMNS:
            continue
        meta_type = _meta_type(column)
        readonly = name in READONLY_COLUMNS
        if explicit_search is not None:
            searchable = name in explicit_search
        else:
            # Enum columns map to "string" but ILIKE does not apply to them.
            searchable = (
                meta_type in TEXT_TYPES
                and not isinstance(column.type, sa.Enum)
                and name not in NovvusModel.SYSTEM_COLUMNS
            )
        spec: dict[str, Any] = {
            "name": name,
            "type": meta_type,
            "label": labels.get(name, name.replace("_", " ").capitalize()),
            "required": (
                not column.nullable
                and column.default is None
                and column.server_default is None
                and not readonly
            ),
            "readonly": readonly,
            "default": _scalar_default(column),
            "choices": _labelled_choices(_choices(column), choice_labels.get(name)),
            "relation": _relation_target(module_id, column),
            "searchable": searchable,
            "sortable": meta_type != "json",
            "filterable": meta_type != "json",
            "groupable": meta_type in GROUPABLE_TYPES and name != "id",
        }
        for flag, value in views.get("fields", {}).get(name, {}).items():
            if flag in FLAG_OVERRIDES:
                spec[flag] = bool(value)
        specs[name] = spec
    return specs


def _default_views(specs: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """A model without __novvus_views__ is still navigable (docs/VIEWS.md §3)."""
    business = [name for name, spec in specs.items() if not spec["readonly"]]
    return {
        "list": {"columns": business[:DEFAULT_LIST_COLUMNS], "default_order": "-created_at"},
        "form": {"layout": [[name] for name in business]},
    }


def build_views(specs: dict[str, dict[str, Any]], model: type[NovvusModel]) -> dict[str, Any]:
    declared = _views_config(model)
    defaults = _default_views(specs)
    views: dict[str, Any] = {
        "list": declared.get("list", defaults["list"]),
        "form": declared.get("form", defaults["form"]),
    }
    views["list"].setdefault("default_order", "-created_at")
    if "kanban" in declared:
        views["kanban"] = declared["kanban"]
    if "calendar" in declared:
        views["calendar"] = declared["calendar"]
    if "timeline" in declared:
        views["timeline"] = dict(declared["timeline"])
    if "actions" in declared:
        views["actions"] = [dict(a) for a in declared["actions"]]
    if "related" in declared:
        views["related"] = [dict(r) for r in declared["related"]]
    if "viewer" in declared:
        views["viewer"] = dict(declared["viewer"])
    if "nav" in declared:
        views["nav"] = dict(declared["nav"])
    if "workbench" in declared:
        views["workbench"] = dict(declared["workbench"])
    if "editor" in declared:
        views["editor"] = dict(declared["editor"])
    if "journey" in declared:
        views["journey"] = dict(declared["journey"])
    if "map" in declared:
        views["map"] = dict(declared["map"])
    if "board" in declared:
        views["board"] = dict(declared["board"])
    if "process" in declared:
        views["process"] = dict(declared["process"])
    if "dashboard" in declared:
        views["dashboard"] = dict(declared["dashboard"])
    return views


def validate_views(module_id: str, model: type[NovvusModel]) -> None:
    """Fail-fast validation of __novvus_views__ at model registration."""
    declared = _views_config(model)
    name = model.__name__

    unknown_keys = set(declared) - VIEW_KEYS
    if unknown_keys:
        raise ValueError(f"{name}.__novvus_views__: unknown keys {sorted(unknown_keys)}")

    specs = field_specs(module_id, model)

    def check(field: str, where: str) -> None:
        if field not in specs:
            raise ValueError(f"{name}.__novvus_views__ {where}: unknown field {field!r}")

    for field in declared.get("labels", {}):
        check(field, "labels")
    for field in declared.get("fields", {}):
        check(field, "fields")
    if "display" in declared:
        check(declared["display"], "display")
    for field in declared.get("track", []):
        check(field, "track")

    list_view = declared.get("list", {})
    for field in list_view.get("columns", []):
        check(field, "list.columns")
    order = list_view.get("default_order")
    if order:
        check(order.lstrip("-"), "list.default_order")

    for row in declared.get("form", {}).get("layout", []):
        for field in row:
            check(field, "form.layout")
    tabs = declared.get("form", {}).get("tabs")
    if tabs is not None:
        if not isinstance(tabs, list) or not tabs:
            raise ValueError(f"{name}.__novvus_views__ form.tabs: must be a non-empty list")
        for tab in tabs:
            bad_shape = not isinstance(tab, dict) or bool(set(tab) - TAB_KEYS)
            if bad_shape or not isinstance(tab.get("label"), str) or not tab["label"]:
                raise ValueError(
                    f"{name}.__novvus_views__ form.tabs: each tab needs a label "
                    f"and only {sorted(TAB_KEYS)}"
                )
            for row in tab.get("rows", []) or []:
                for field in row:
                    check(field, "form.tabs.rows")
            sections = tab.get("sections", [])
            if not isinstance(sections, list):
                raise ValueError(f"{name}.__novvus_views__ form.tabs.sections: must be a list")
            for section in sections:
                if (
                    not isinstance(section, dict)
                    or set(section) - {"label", "rows"}
                    or not isinstance(section.get("label"), str)
                    or not section["label"]
                    or not isinstance(section.get("rows"), list)
                    or not section["rows"]
                ):
                    raise ValueError(
                        f"{name}.__novvus_views__ form.tabs.sections: "
                        "needs label and non-empty rows"
                    )
                for row in section["rows"]:
                    if (
                        not isinstance(row, list)
                        or not 1 <= len(row) <= 2
                        or any(not isinstance(f, str) for f in row)
                    ):
                        raise ValueError(
                            f"{name}.__novvus_views__ form.tabs.sections.rows: "
                            "needs one or two field names"
                        )
                    for field in row:
                        check(field, "form.tabs.sections.rows")
            for rel in tab.get("related", []) or []:
                if not isinstance(rel, str) or not rel:
                    raise ValueError(
                        f"{name}.__novvus_views__ form.tabs.related: model names must be strings"
                    )
    stages = declared.get("form", {}).get("stages")
    if stages is not None:
        bad = not isinstance(stages, dict) or set(stages) - {"field", "steps"}
        if bad or not isinstance(stages.get("field"), str) or not stages.get("steps"):
            raise ValueError(
                f"{name}.__novvus_views__ form.stages: needs field and a non-empty steps list"
            )
        check(stages["field"], "form.stages.field")
        for step in stages["steps"]:
            bad_step = not isinstance(step, dict) or bool(set(step) - STAGE_KEYS)
            values = step.get("values") if isinstance(step, dict) else None
            if (
                bad_step
                or not isinstance(step.get("label"), str)
                or not step["label"]
                or not isinstance(values, list)
                or not values
                or any(not isinstance(v, str) for v in values)
            ):
                raise ValueError(
                    f"{name}.__novvus_views__ form.stages.steps: each step needs a label "
                    "and a non-empty list of string values"
                )
    process = declared.get("process")
    if process is not None:
        if (
            not isinstance(process, dict)
            or set(process) - {"path", "summary"}
            or not isinstance(process.get("path"), str)
            or not re.fullmatch(r"[a-z][a-z0-9_-]*(?:/[a-z][a-z0-9_-]*)*", process["path"])
            or not stages
        ):
            raise ValueError(
                f"{name}.__novvus_views__ process: needs a module-relative path and form.stages"
            )
        keys = [step["values"][0] for step in stages["steps"]]
        if len(set(keys)) != len(keys) or process.get("summary") not in keys:
            raise ValueError(
                f"{name}.__novvus_views__ process: summary must identify one unique stage"
            )
    dashboard = declared.get("dashboard")
    if dashboard is not None and (
        not isinstance(dashboard, dict)
        or set(dashboard) - {"path", "title", "order"}
        or not isinstance(dashboard.get("path"), str)
        or not re.fullmatch(r"[a-z][a-z0-9_-]*(?:/[a-z][a-z0-9_-]*)*", dashboard["path"])
        or not isinstance(dashboard.get("title"), str)
        or not dashboard["title"].strip()
        or type(dashboard.get("order", 0)) is not int
    ):
        raise ValueError(
            f"{name}.__novvus_views__ dashboard: "
            "needs a module-relative path, title and integer order"
        )
    nav = declared.get("nav")
    if nav is not None:
        if not isinstance(nav, dict) or set(nav) - NAV_KEYS:
            raise ValueError(
                f"{name}.__novvus_views__ nav: unknown keys or not a mapping "
                f"(allowed: {sorted(NAV_KEYS)})"
            )
        if (
            "group" in nav
            and nav["group"] is not None
            and (not isinstance(nav["group"], str) or not nav["group"])
        ):
            raise ValueError(f"{name}.__novvus_views__ nav.group: must be a non-empty string")
        if "order" in nav and not isinstance(nav["order"], int):
            raise ValueError(f"{name}.__novvus_views__ nav.order: must be an integer")
        if "hidden" in nav and not isinstance(nav["hidden"], bool):
            raise ValueError(f"{name}.__novvus_views__ nav.hidden: must be a boolean")
        if "singleton" in nav and not isinstance(nav["singleton"], bool):
            raise ValueError(f"{name}.__novvus_views__ nav.singleton: must be a boolean")
        if "icon" in nav and not (isinstance(nav["icon"], str) and _NAV_ICON.match(nav["icon"])):
            raise ValueError(
                f"{name}.__novvus_views__ nav.icon: must be a lowercase slug"
            )
    # list.filter (§8g): a filter-DSL node the shell applies to every query of the list (rows,
    # counters, groups, export); validated against the columns at query time like any filter.
    base_filter = declared.get("list", {}).get("filter")
    if base_filter is not None and not (isinstance(base_filter, dict) and base_filter):
        raise ValueError(f"{name}.__novvus_views__ list.filter: must be a non-empty mapping")
    for key in ("mono",):
        for field in declared.get("list", {}).get(key, []) or []:
            check(field, f"list.{key}")
    # list.counters (docs/VIEWS.md §8c): chips with per-value counts; the
    # shell asks GET /group for each, so every field must be groupable.
    counters = declared.get("list", {}).get("counters")
    if counters is not None:
        if not isinstance(counters, list) or not all(isinstance(f, str) for f in counters):
            raise ValueError(
                f"{name}.__novvus_views__ list.counters: must be a list of field names"
            )
        if len(set(counters)) != len(counters):
            raise ValueError(f"{name}.__novvus_views__ list.counters: fields must not repeat")
        for field in counters:
            check(field, "list.counters")
            if not specs[field]["groupable"]:
                raise ValueError(
                    f"{name}.__novvus_views__ list.counters: {field!r} is not groupable"
                )
    badges = declared.get("list", {}).get("badges")
    if badges is not None:
        if not isinstance(badges, dict):
            raise ValueError(
                f"{name}.__novvus_views__ list.badges: must be a mapping field -> {{value: tone}}"
            )
        for field, tones in badges.items():
            check(field, "list.badges")
            if not isinstance(tones, dict) or any(t not in BADGE_TONES for t in tones.values()):
                raise ValueError(
                    f"{name}.__novvus_views__ list.badges.{field}: "
                    f"tones must be one of {sorted(BADGE_TONES)}"
                )
    viewer = declared.get("viewer")
    if viewer is not None:
        if not isinstance(viewer, dict) or set(viewer) - VIEWER_KEYS:
            raise ValueError(f"{name}.__novvus_views__ viewer: unknown keys or not a mapping")
        for key in ("model", "field", "file_field"):
            if not isinstance(viewer.get(key), str) or not viewer[key]:
                raise ValueError(f"{name}.__novvus_views__ viewer: {key} is required")
        # `filter` (SDK 0.2.10): a filter-DSL node (docs/VIEWS.md §5) the shell ANDs with
        # `field = record` when listing the viewer rows, e.g. only documents of one kind.
        # Validated against the viewer model's columns at query time (422 like any list).
        if "filter" in viewer and not (isinstance(viewer["filter"], dict) and viewer["filter"]):
            raise ValueError(f"{name}.__novvus_views__ viewer: filter must be a non-empty mapping")

    kanban = declared.get("kanban")
    if kanban is not None:
        if not isinstance(kanban, dict) or set(kanban) - KANBAN_KEYS:
            raise ValueError(
                f"{name}.__novvus_views__ kanban: unknown keys or not a mapping "
                f"(allowed: {sorted(KANBAN_KEYS)})"
            )
        group_by = kanban.get("group_by")
        if not group_by:
            raise ValueError(f"{name}.__novvus_views__ kanban: group_by is required")
        check(group_by, "kanban.group_by")
        if not specs[group_by]["groupable"]:
            raise ValueError(
                f"{name}.__novvus_views__ kanban.group_by: {group_by!r} is not groupable"
            )
        for field in kanban.get("card", []):
            check(field, "kanban.card")
        # §8j: the drop runs a declared record action that takes the grouped field as input.
        action_name = kanban.get("action")
        if action_name is not None:
            matching = [
                a
                for a in declared.get("actions", []) or []
                if isinstance(a, dict) and a.get("name") == action_name
            ]
            if (
                not isinstance(action_name, str)
                or not matching
                or matching[0].get("scope", "record") != "record"
                or not any(
                    isinstance(f, dict) and f.get("name") == group_by
                    for f in matching[0].get("fields", []) or []
                )
            ):
                raise ValueError(
                    f"{name}.__novvus_views__ kanban.action: must name a declared record "
                    f"action with a field named {group_by!r}"
                )
    choice_labels = declared.get("choices")
    if choice_labels is not None:
        if not isinstance(choice_labels, dict):
            raise ValueError(
                f"{name}.__novvus_views__ choices: must be a mapping field -> {{value: label}}"
            )
        for field, labels_map in choice_labels.items():
            check(field, "choices")
            known = {c["value"] for c in specs[field]["choices"] or []}
            if not known:
                raise ValueError(f"{name}.__novvus_views__ choices.{field}: field has no choices")
            if (
                not isinstance(labels_map, dict)
                or set(labels_map) - known
                or any(not isinstance(v, str) or not v for v in labels_map.values())
            ):
                raise ValueError(
                    f"{name}.__novvus_views__ choices.{field}: labels must map known values "
                    "to non-empty strings"
                )

    timeline = declared.get("timeline")
    if timeline is not None:
        _validate_timeline(name, timeline, specs)

    calendar = declared.get("calendar")
    if calendar is not None:
        date_field = calendar.get("date_field")
        if not date_field:
            raise ValueError(f"{name}.__novvus_views__ calendar: date_field is required")
        check(date_field, "calendar.date_field")
        if specs[date_field]["type"] not in {"date", "datetime"}:
            raise ValueError(
                f"{name}.__novvus_views__ calendar.date_field: {date_field!r} is not a date"
            )
        if calendar.get("title"):
            check(calendar["title"], "calendar.title")

    actions = declared.get("actions")
    if actions is not None:
        if not isinstance(actions, list):
            raise ValueError(f"{name}.__novvus_views__ actions: must be a list")
        seen: set[str] = set()
        for a in actions:
            if not isinstance(a, dict):
                raise ValueError(f"{name}.__novvus_views__ actions: each action must be a mapping")
            unknown = set(a) - ACTION_KEYS
            if unknown:
                raise ValueError(f"{name}.__novvus_views__ actions: unknown keys {sorted(unknown)}")
            aname = a.get("name")
            if not isinstance(aname, str) or not _SLUG.match(aname):
                raise ValueError(
                    f"{name}.__novvus_views__ actions: name must be a slug ([a-z0-9_-])"
                )
            if aname in seen:
                raise ValueError(f"{name}.__novvus_views__ actions: duplicated action {aname!r}")
            seen.add(aname)
            if not isinstance(a.get("label"), str) or not a["label"]:
                raise ValueError(f"{name}.__novvus_views__ actions.{aname}: label is required")
            perm = a.get("permission")
            where = f"{name}.__novvus_views__ actions.{aname}"
            if perm is not None and (
                not isinstance(perm, str) or not perm.startswith(f"{module_id}.")
            ):
                raise ValueError(f"{where}: permission must be {module_id}.<resource>.<action>")
            if a.get("variant", "default") not in ACTION_VARIANTS:
                raise ValueError(f"{where}: variant must be one of {sorted(ACTION_VARIANTS)}")
            if a.get("success", "reload") not in ACTION_SUCCESS:
                raise ValueError(f"{where}: success must be one of {sorted(ACTION_SUCCESS)}")
            if a.get("scope", "record") not in ACTION_SCOPES:
                raise ValueError(f"{where}: scope must be one of {sorted(ACTION_SCOPES)}")
            if "help" in a and (not isinstance(a["help"], str) or not a["help"]):
                raise ValueError(f"{where}: help must be a non-empty string")
            if "validate" in a and not isinstance(a["validate"], bool):
                raise ValueError(f"{where}: validate must be a boolean")
            if "secondary" in a and not isinstance(a["secondary"], bool):
                raise ValueError(f"{where}: secondary must be a boolean")
            if "prefill" in a and not isinstance(a["prefill"], bool):
                raise ValueError(f"{where}: prefill must be a boolean")
            if a.get("prefill") and a.get("scope", "record") != "record":
                raise ValueError(f"{where}: prefill needs a record action")
            presentation = a.get("presentation", "dialog")
            if presentation not in ACTION_PRESENTATIONS:
                raise ValueError(
                    f"{where}: presentation must be one of {sorted(ACTION_PRESENTATIONS)}"
                )
            if "after" in a:
                after = a["after"]
                if presentation != "page":
                    raise ValueError(f"{where}: after needs presentation 'page'")
                ok_after = (
                    isinstance(after, str)
                    and after != aname
                    and any(
                        isinstance(x, dict)
                        and x.get("name") == after
                        and x.get("scope", "record") == "record"
                        and not (x.get("fields") and any(
                            f.get("required") for f in x["fields"] if isinstance(f, dict)
                        ))
                        for x in actions
                    )
                )
                if not ok_after:
                    raise ValueError(
                        f"{where}: after must name another record action of this model "
                        "without required fields"
                    )
            for f in a.get("fields", []) or []:
                valid_shape = (
                    isinstance(f, dict)
                    and not (set(f) - ACTION_FIELD_KEYS)
                    and isinstance(f.get("name"), str)
                    and _SLUG.match(f["name"]) is not None
                )
                if not valid_shape:
                    raise ValueError(f"{where}: invalid field definition")
                if f.get("type", "string") not in ACTION_FIELD_TYPES:
                    raise ValueError(
                        f"{where}.{f['name']}: type must be one of {sorted(ACTION_FIELD_TYPES)}"
                    )
                if "options" in f and not isinstance(f["options"], bool):
                    raise ValueError(f"{where}.{f['name']}: options must be a boolean")
                if f.get("options") and f.get("type", "string") != "choice":
                    raise ValueError(f"{where}.{f['name']}: options needs type choice")
                ftype = f.get("type", "string")
                if ftype in ("file", "files") and presentation != "page":
                    raise ValueError(
                        f"{where}.{f['name']}: file fields need presentation 'page'"
                    )
                if "accept" in f:
                    accept = f["accept"]
                    if ftype not in ("file", "files"):
                        raise ValueError(f"{where}.{f['name']}: accept needs a file field")
                    if not isinstance(accept, list) or not accept or any(
                        not isinstance(x, str) or not x for x in accept
                    ):
                        raise ValueError(
                            f"{where}.{f['name']}: accept must be a non-empty list of "
                            "extensions or MIME patterns"
                        )
                if "multiple" in f:
                    if not isinstance(f["multiple"], bool):
                        raise ValueError(f"{where}.{f['name']}: multiple must be a boolean")
                    if ftype != "choice":
                        raise ValueError(f"{where}.{f['name']}: multiple needs type choice")
                if "group" in f and (not isinstance(f["group"], str) or not f["group"]):
                    raise ValueError(f"{where}.{f['name']}: group must be a non-empty string")
                if f.get("type") == "choice" and not f.get("choices") and not f.get("options"):
                    raise ValueError(f"{where}.{f['name']}: choice fields need choices")
                if "help" in f and (not isinstance(f["help"], str) or not f["help"]):
                    raise ValueError(f"{where}.{f['name']}: help must be a non-empty string")
                for c in f.get("choices", []) or []:
                    if isinstance(c, str):
                        continue
                    ok = (
                        isinstance(c, dict)
                        and not (set(c) - ACTION_CHOICE_KEYS)
                        and isinstance(c.get("value"), str)
                        and isinstance(c.get("label"), str)
                        and ("description" not in c or isinstance(c["description"], str))
                        and (
                            "details" not in c
                            or (
                                isinstance(c["details"], dict)
                                and all(
                                    isinstance(k, str) and isinstance(v, str)
                                    for k, v in c["details"].items()
                                )
                            )
                        )
                    )
                    if not ok:
                        raise ValueError(
                            f"{where}.{f['name']}: choices must be strings or "
                            "{value, label[, description, details]}"
                        )
    workbench = declared.get("workbench")
    if workbench is not None:
        _validate_workbench(name, workbench, specs, declared)
    editor = declared.get("editor")
    if editor is not None:
        _validate_editor(name, editor, declared)
    journey = declared.get("journey")
    if journey is not None:
        _validate_journey(name, journey)
    map_view = declared.get("map")
    if map_view is not None:
        _validate_map(name, map_view)
    board = declared.get("board")
    if board is not None:
        _validate_board(name, board, declared)
    related = declared.get("related")
    if related is not None:
        if not isinstance(related, list):
            raise ValueError(f"{name}.__novvus_views__ related: must be a list")
        for r in related:
            _validate_related_entry(r, f"{name}.__novvus_views__ related")


def _validate_related_entry(r: Any, where: str) -> None:
    """One `{model, field, label, columns, order, limit, filter}` panel (§8c/§8g); the board
    columns (§8p) use the same shape."""
    if not isinstance(r, dict) or set(r) - RELATED_KEYS:
        raise ValueError(f"{where}: unknown keys or not a mapping")
    model_ok = isinstance(r.get("model"), str) and r["model"]
    field_ok = isinstance(r.get("field"), str) and r["field"]
    if not model_ok or not field_ok:
        raise ValueError(f"{where}: model and field are required")
    if "limit" in r and (not isinstance(r["limit"], int) or not 1 <= r["limit"] <= 200):
        raise ValueError(f"{where}: limit must be 1..200")
    if "filter" in r and not (isinstance(r["filter"], dict) and r["filter"]):
        raise ValueError(f"{where}: filter must be a non-empty mapping")


def _validate_board(name: str, board: Any, declared: dict[str, Any]) -> None:
    """§8p: the board is the landing page of a `nav.singleton` model: an optional map on top
    (`path`, `title`, `help`, `refresh_seconds`; the module serves `GET /{path}`) and 1..4
    columns, each a related panel scoped to the single record (`field = record`)."""
    where = f"{name}.__novvus_views__ board"
    if not isinstance(board, dict) or set(board) - BOARD_KEYS:
        raise ValueError(f"{where}: unknown keys or not a mapping (allowed: {sorted(BOARD_KEYS)})")
    nav = declared.get("nav")
    if not (isinstance(nav, dict) and nav.get("singleton") is True):
        raise ValueError(
            f"{where}: requires nav.singleton = True (the columns are scoped to the single record)"
        )
    for key in ("title", "help"):
        if key in board and (not isinstance(board[key], str) or not board[key]):
            raise ValueError(f"{where}: {key} must be a non-empty string")
    if "map" in board:
        bm = board["map"]
        if not isinstance(bm, dict) or set(bm) - BOARD_MAP_KEYS:
            raise ValueError(
                f"{where}.map: unknown keys or not a mapping (allowed: {sorted(BOARD_MAP_KEYS)})"
            )
        _validate_map(name, bm)
    columns = board.get("columns")
    low, high = BOARD_COLUMNS_RANGE
    if not isinstance(columns, list) or not low <= len(columns) <= high:
        raise ValueError(f"{where}: columns must be a list of {low}..{high} related panels")
    for c in columns:
        _validate_related_entry(c, f"{where}.columns")


def _validate_timeline(name: str, timeline: Any, specs: dict[str, dict[str, Any]]) -> None:
    where = f"{name}.__novvus_views__ timeline"
    if not isinstance(timeline, dict) or set(timeline) - TIMELINE_KEYS:
        raise ValueError(
            f"{where}: unknown keys or not a mapping (allowed: {sorted(TIMELINE_KEYS)})"
        )
    for key in ("start_field", "end_field"):
        field = timeline.get(key)
        if not isinstance(field, str) or field not in specs:
            raise ValueError(f"{where}: {key} must name a field of the model")
        if specs[field]["type"] not in {"date", "datetime"}:
            raise ValueError(f"{where}: {key} {field!r} is not a date")
    for key, allowed in (
        ("title", None),
        ("progress_field", {"integer", "decimal"}),
        ("group_field", {"string", "relation", "boolean"}),
    ):
        field = timeline.get(key)
        if field is None:
            continue
        if not isinstance(field, str) or field not in specs:
            raise ValueError(f"{where}: {key} must name a field of the model")
        if allowed is not None and specs[field]["type"] not in allowed:
            raise ValueError(f"{where}: {key} {field!r} must be one of {sorted(allowed)}")
    dependencies = timeline.get("dependencies")
    if dependencies is not None:
        if not isinstance(dependencies, dict) or set(dependencies) - TIMELINE_DEPENDENCY_KEYS:
            raise ValueError(f"{where}.dependencies: unknown keys or not a mapping")
        for key in ("model", "predecessor_field", "successor_field"):
            if not isinstance(dependencies.get(key), str) or not dependencies[key]:
                raise ValueError(f"{where}.dependencies: {key} is required")
        kind_field = dependencies.get("kind_field")
        if kind_field is not None and (not isinstance(kind_field, str) or not kind_field):
            raise ValueError(f"{where}.dependencies: kind_field must be a field name")


def _validate_editor(name: str, editor: Any, declared: dict[str, Any]) -> None:
    """§8i: the editor names the module route that serves (and receives) the editable
    sections of a record; the document beside them is the model's `viewer`."""
    where = f"{name}.__novvus_views__ editor"
    if not isinstance(editor, dict) or set(editor) - EDITOR_KEYS:
        raise ValueError(
            f"{where}: unknown keys or not a mapping (allowed: {sorted(EDITOR_KEYS)})"
        )
    path = editor.get("path")
    if not isinstance(path, str) or not _EDITOR_PATH.match(path):
        raise ValueError(
            f"{where}: path must be a route relative to the module "
            "(slug segments separated by '/', no scheme, dots or query)"
        )
    for key in ("title", "help"):
        if key in editor and (not isinstance(editor[key], str) or not editor[key]):
            raise ValueError(f"{where}: {key} must be a non-empty string")
    if not isinstance(declared.get("viewer"), dict):
        raise ValueError(
            f"{where}: the editor needs the model's views.viewer "
            "(the document shown beside the fields)"
        )


def _validate_journey(name: str, journey: Any) -> None:
    """§8n: the journey names the module route that serves the pages of a record and
    receives the values and uploaded files of each page."""
    where = f"{name}.__novvus_views__ journey"
    if not isinstance(journey, dict) or set(journey) - JOURNEY_KEYS:
        raise ValueError(
            f"{where}: unknown keys or not a mapping (allowed: {sorted(JOURNEY_KEYS)})"
        )
    path = journey.get("path")
    if not isinstance(path, str) or not _EDITOR_PATH.match(path):
        raise ValueError(
            f"{where}: path must be a route relative to the module "
            "(slug segments separated by '/', no scheme, dots or query)"
        )
    for key in ("title", "help"):
        if key in journey and (not isinstance(journey[key], str) or not journey[key]):
            raise ValueError(f"{where}: {key} must be a non-empty string")


def _validate_map(name: str, map_view: Any) -> None:
    """§8o: the map names the module route that serves the points and routes of the
    collection (and of one record with `record`); the shell draws, the module computes."""
    where = f"{name}.__novvus_views__ map"
    if not isinstance(map_view, dict) or set(map_view) - MAP_KEYS:
        raise ValueError(f"{where}: unknown keys or not a mapping (allowed: {sorted(MAP_KEYS)})")
    path = map_view.get("path")
    if not isinstance(path, str) or not _EDITOR_PATH.match(path):
        raise ValueError(
            f"{where}: path must be a route relative to the module "
            "(slug segments separated by '/', no scheme, dots or query)"
        )
    for key in ("title", "help"):
        if key in map_view and (not isinstance(map_view[key], str) or not map_view[key]):
            raise ValueError(f"{where}: {key} must be a non-empty string")
    if "refresh_seconds" in map_view:
        seconds = map_view["refresh_seconds"]
        low, high = MAP_REFRESH_RANGE
        if isinstance(seconds, bool) or not isinstance(seconds, int) or not low <= seconds <= high:
            raise ValueError(
                f"{where}: refresh_seconds must be an integer between {low} and {high}"
            )
    if "record" in map_view and not isinstance(map_view["record"], bool):
        raise ValueError(f"{where}: record must be a boolean")


def _validate_workbench(
    name: str, wb: Any, specs: dict[str, dict[str, Any]], declared: dict[str, Any]
) -> None:
    """§8h: the workbench names actions declared on the same model (`create` of scope
    collection; `assign` and `run` of scope record), file slots stored in uuid fields of the
    record, and (optionally) the progress of a related run shown as tabs."""
    where = f"{name}.__novvus_views__ workbench"
    if not isinstance(wb, dict) or set(wb) - WORKBENCH_KEYS:
        raise ValueError(
            f"{where}: unknown keys or not a mapping (allowed: {sorted(WORKBENCH_KEYS)})"
        )
    if not isinstance(wb.get("title"), str) or not wb["title"]:
        raise ValueError(f"{where}: title is required")
    if "help" in wb and (not isinstance(wb["help"], str) or not wb["help"]):
        raise ValueError(f"{where}: help must be a non-empty string")
    if "history" in wb and not isinstance(wb["history"], bool):
        raise ValueError(f"{where}: history must be a boolean")
    actions = {a.get("name"): a for a in declared.get("actions", []) or [] if isinstance(a, dict)}
    for key, scope in (("create", "collection"), ("assign", "record"), ("run", "record")):
        aname = wb.get(key)
        if not isinstance(aname, str) or aname not in actions:
            raise ValueError(f"{where}: {key} must name an action declared in views.actions")
        if actions[aname].get("scope", "record") != scope:
            raise ValueError(f"{where}: {key} must be an action of scope {scope!r}")
    if actions[wb["create"]].get("fields") or actions[wb["create"]].get("confirm"):
        raise ValueError(
            f"{where}: the create action runs without a dialog (no fields, no confirm)"
        )
    slots = wb.get("slots")
    if not isinstance(slots, list) or not slots:
        raise ValueError(f"{where}: slots must be a non-empty list")
    seen: set[str] = set()
    for slot in slots:
        ok = isinstance(slot, dict) and not (set(slot) - WORKBENCH_SLOT_KEYS)
        if not ok or not isinstance(slot.get("name"), str) or not _SLUG.match(slot["name"]):
            raise ValueError(
                f"{where}.slots: each slot needs a slug name and only {sorted(WORKBENCH_SLOT_KEYS)}"
            )
        if slot["name"] in seen:
            raise ValueError(f"{where}.slots: duplicated slot {slot['name']!r}")
        seen.add(slot["name"])
        if not isinstance(slot.get("label"), str) or not slot["label"]:
            raise ValueError(f"{where}.slots.{slot['name']}: label is required")
        field = slot.get("field")
        if not isinstance(field, str) or field not in specs:
            raise ValueError(f"{where}.slots.{slot['name']}: field must name a column of the model")
        if specs[field]["type"] != "uuid":
            raise ValueError(
                f"{where}.slots.{slot['name']}: field {field!r} must be a uuid column (Files id)"
            )
        accept = slot.get("accept", [])
        if not isinstance(accept, list) or any(not isinstance(a, str) or not a for a in accept):
            raise ValueError(
                f"{where}.slots.{slot['name']}: "
                "accept must be a list of extensions or MIME patterns"
            )
        if "required" in slot and not isinstance(slot["required"], bool):
            raise ValueError(f"{where}.slots.{slot['name']}: required must be a boolean")
        if "help" in slot and (not isinstance(slot["help"], str) or not slot["help"]):
            raise ValueError(f"{where}.slots.{slot['name']}: help must be a non-empty string")
    # the shell posts the whole slot state (`{slot: file id | null}`) to `assign`: the SDK only lets
    # declared fields through, so the action declares one optional string field per slot
    assign_fields = {
        f.get("name"): f
        for f in actions[wb["assign"]].get("fields", []) or []
        if isinstance(f, dict)
    }
    if set(assign_fields) != seen or any(
        f.get("type", "string") != "string" or f.get("required") for f in assign_fields.values()
    ):
        raise ValueError(
            f"{where}: the assign action must declare exactly one optional string field "
            f"per slot ({sorted(seen)})"
        )
    progress = wb.get("progress")
    if progress is None:
        return
    pwhere = f"{where}.progress"
    if not isinstance(progress, dict) or set(progress) - WORKBENCH_PROGRESS_KEYS:
        raise ValueError(
            f"{pwhere}: unknown keys or not a mapping (allowed: {sorted(WORKBENCH_PROGRESS_KEYS)})"
        )
    related_models = {
        r.get("model") for r in declared.get("related", []) or [] if isinstance(r, dict)
    }
    if not isinstance(progress.get("related"), str) or progress["related"] not in related_models:
        raise ValueError(f"{pwhere}: related must name a model declared in views.related")
    steps = progress.get("steps")
    if not isinstance(steps, dict) or set(steps) - WORKBENCH_STEPS_KEYS:
        raise ValueError(
            f"{pwhere}.steps: needs model and field (allowed: {sorted(WORKBENCH_STEPS_KEYS)})"
        )
    for key in ("model", "field"):
        if not isinstance(steps.get(key), str) or not steps[key]:
            raise ValueError(f"{pwhere}.steps: {key} is required")
    for key in ("key", "order"):
        if key in steps and (not isinstance(steps[key], str) or not steps[key]):
            raise ValueError(f"{pwhere}.steps: {key} must be a non-empty string")
    columns = steps.get("columns", [])
    if not isinstance(columns, list) or any(not isinstance(c, str) for c in columns):
        raise ValueError(
            f"{pwhere}.steps: columns must be a list of field names of the steps model"
        )
    for key in ("stage", "state"):
        if not isinstance(progress.get(key), str) or not progress[key]:
            raise ValueError(f"{pwhere}: {key} is required (field of the related run)")
    tabs = progress.get("tabs")
    if not isinstance(tabs, list) or not tabs:
        raise ValueError(f"{pwhere}: tabs must be a non-empty list")
    for tab in tabs:
        bad = not isinstance(tab, dict) or bool(set(tab) - STAGE_KEYS)
        values = tab.get("values") if isinstance(tab, dict) else None
        if (
            bad
            or not isinstance(tab.get("label"), str)
            or not tab["label"]
            or not isinstance(values, list)
            or not values
            or any(not isinstance(v, str) for v in values)
        ):
            raise ValueError(
                f"{pwhere}.tabs: each tab needs a label and a non-empty list of step keys"
            )
    summary = progress.get("summary", [])
    if not isinstance(summary, list) or any(not isinstance(c, str) for c in summary):
        raise ValueError(f"{pwhere}: summary must be a list of field names of the related run")


def build_model_meta(module_id: str, model: type[NovvusModel]) -> dict[str, Any]:
    specs = field_specs(module_id, model)
    declared = _views_config(model)
    resource = model.resource_name()
    api_config: dict[str, Any] = getattr(model, "__novvus_api__", {})
    disabled: set[str] = set(api_config.get("disabled", ()))
    perms: dict[str, str] = api_config.get("permissions", {})

    display = declared.get("display", "name" if "name" in specs else "id")
    return {
        "name": resource,
        "label": declared.get("label", resource.replace("_", " ").capitalize()),
        "display": display,
        "permissions": {
            "read": perms.get("read", f"{module_id}.{resource}.read"),
            "write": perms.get("write", f"{module_id}.{resource}.write"),
        },
        "fields": list(specs.values()),
        "views": build_views(specs, model),
        "capabilities": {
            "create": "create" not in disabled,
            "update": "update" not in disabled,
            "delete": "delete" not in disabled,
            "export": "list" not in disabled,
            # Attachment panel (docs/FILES.md §6): opt-in per model.
            "attachments": bool(declared.get("attachments", False)),
            # Record collaboration thread (docs/CHATTER.md §6): opt-in.
            "chatter": bool(declared.get("chatter", False)),
            # Record-level authorization (docs/FILES.md §8.5): the kernel asks the
            # module (`POST /_novvus/record-access`) before serving attachments or
            # chatter of a record of this model.
            "record_access": bool(getattr(model, "__novvus_record_access__", False)),
        },
    }


def _navigable(model: type[NovvusModel]) -> bool:
    """Models with the list endpoint disabled (pure join tables, internal
    resources) have no generic surface — they stay out of the meta."""
    api_config: dict[str, Any] = getattr(model, "__novvus_api__", {})
    return "list" not in set(api_config.get("disabled", ()))


def build_module_meta(
    module_id: str, module_version: str, models: list[type[NovvusModel]]
) -> dict[str, Any]:
    return {
        "meta_version": META_VERSION,
        "module": module_id,
        "module_version": module_version,
        "models": [build_model_meta(module_id, model) for model in models if _navigable(model)],
    }
