"""Module runtime: NovvusModule ties manifest, models, auto-API, events and
kernel handshake into one FastAPI application (`novvus run` serves it)."""

from __future__ import annotations

import logging
import os
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import replace
from pathlib import Path
from typing import Any
from uuid import UUID

from fastapi import APIRouter, FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from novvus_sdk.autoapi import build_router
from novvus_sdk.chatter import ChatterHelper
from novvus_sdk.context import RequestContext, current_context, reset_context, set_context
from novvus_sdk.contract import PLATFORM_API
from novvus_sdk.custom_fields import CustomFieldsRegistry
from novvus_sdk.db import Database
from novvus_sdk.entitlement import Entitlement
from novvus_sdk.entitlement import from_kernel as entitlement_from_kernel
from novvus_sdk.events import (
    PROCESSED_EVENTS_DDL,
    Event,
    EventHandler,
    EventRegistry,
    mark_processed,
)
from novvus_sdk.extensions import ExtensionsRegistry
from novvus_sdk.facades import IdentityFacade, PermissionsFacade
from novvus_sdk.files import FilesHelper
from novvus_sdk.i18n import Translator
from novvus_sdk.kernel import KernelClient
from novvus_sdk.manifest import Manifest, find_manifest
from novvus_sdk.meta import build_module_meta, validate_views
from novvus_sdk.models import NovvusModel
from novvus_sdk.security import verify_request

# How long the kernel's answer about the entitlement is reused.
ENTITLEMENT_TTL_SECONDS = 15.0

SeedFunction = Callable[[AsyncSession, UUID], Awaitable[None]]
# A cron/hook handler receives a tenant-scoped session for the current org.
CronHandler = Callable[[AsyncSession], Awaitable[None]]
HookHandler = Callable[[AsyncSession], Awaitable[None]]
# Record-level authorization (docs/FILES.md §8.5, docs/VIEWS.md §9): given the
# caller's context, may it `read`/`write` THIS record of the model?
RecordAccessHandler = Callable[[AsyncSession, RequestContext, UUID, str], Awaitable[bool]]
# Optional list scope for the same models: a SQLAlchemy clause (or None) that
# restricts the generic list/export to the records the caller may read.
RecordScopeHandler = Callable[[AsyncSession, RequestContext], Awaitable[Any]]
# Record actions (docs/VIEWS.md §8b): the module's business logic behind a declared action
# button. It receives the caller's context, the target row and the (already validated) form
# body; it returns a JSON-serialisable result.
ActionHandler = Callable[[AsyncSession, RequestContext, Any, dict[str, Any]], Awaitable[Any]]


class CronTrigger(BaseModel):
    """Body the kernel scheduler POSTs to `/_novvus/cron`."""

    name: str
    org_id: UUID


class RecordAccessQuery(BaseModel):
    """Body the kernel POSTs to `/_novvus/record-access` before serving an
    attachment (or chatter) of a record whose model declares `record_access`
    (docs/FILES.md §8.5). The caller's identity travels in the signed headers."""

    model: str
    record_id: UUID
    action: str  # read | write


class NovvusModule:
    """Declarative entry point of a business module.

    Usage (module.py at the module root, next to novvus.toml)::

        module = NovvusModule()

        @module.model
        class Contact(NovvusModel):
            name: Mapped[str]

        @module.on("crm.opportunity.won")
        async def on_won(event, session): ...

        @module.seed
        async def seed(session, org_id): ...

        app = module.create_app()
    """

    def __init__(self, manifest_path: str | Path | None = None) -> None:
        path = Path(manifest_path) if manifest_path else find_manifest()
        self.manifest: Manifest = Manifest.load(path)
        self.root = path.parent
        self.id = self.manifest.module.id
        self.schema = f"mod_{self.id}"

        self.models: list[type[NovvusModel]] = []
        self.events = EventRegistry()
        self.router = APIRouter()
        self._seed_fn: SeedFunction | None = None
        # Automation (docs/MODULE_CONTRACT.md §10): scheduled jobs and
        # per-org lifecycle hooks, both invoked by the kernel.
        self._cron_handlers: dict[str, CronHandler] = {}
        self._hook_handlers: dict[str, HookHandler] = {}
        # Record-level authorization per model resource (docs/FILES.md §8.5).
        self._record_access: dict[str, RecordAccessHandler] = {}
        self._record_scope: dict[str, RecordScopeHandler] = {}
        # Record actions per model resource and action name (docs/VIEWS.md §10).
        self._actions: dict[str, dict[str, ActionHandler]] = {}
        self._action_validators: dict[str, dict[str, ActionHandler]] = {}
        self._action_options: dict[str, dict[str, ActionHandler]] = {}
        self._cron_names = {job.name for job in self.manifest.cron}
        # Translation catalogs shipped under the module's i18n/ directory
        # (docs/I18N.md); es-MX is the source language.
        self.translator = Translator.load(self.root / "i18n")
        # Attachment helper (docs/FILES.md §6): kernel APIs, own models only.
        self.files = FilesHelper(self)
        # Cross-module extension definitions targeting THIS module
        # (docs/EXTENSIONS.md §5), cached per org. The override is a
        # testing/dev hook that bypasses the kernel.
        self.ext_definitions_override: dict[str, Any] | None = None
        self.extensions = ExtensionsRegistry(self)
        # Per-org custom fields (docs/CUSTOM_FIELDS.md §7); same testing hook.
        self.custom_definitions_override: dict[str, Any] | None = None
        self.custom_fields = CustomFieldsRegistry(self)
        # Record collaboration (docs/CHATTER.md §6): system messages + tracking.
        self.chatter = ChatterHelper(self)
        # Sanctioned facades over kernel services (ADR-001): identity
        # lookups and permission queries never touch the kernel client.
        self.identity = IdentityFacade(self)
        self.permissions = PermissionsFacade(self)

        # Filled during startup (handshake or offline env config). Private
        # on purpose: modules never reach the DB engine, the kernel client
        # or the internal secret — only the facades and helpers above.
        self._db: Database | None = None
        self._hmac_secret: str | None = None
        self._kernel: KernelClient | None = None
        # License entitlement asked to the kernel when a request carries none
        # (event deliveries, cron, a stripped header): (monotonic time, value).
        self._entitlement_cache: tuple[float, Entitlement] | None = None
        # None = not asked yet; False = a kernel that predates licensing.
        self._licensing_kernel: bool | None = None
        self._deps_cache: dict[str, str] | None = None
        self._deps_cached_at: float = 0.0

    # ------------------------------------------------------------------
    # Declaration API
    # ------------------------------------------------------------------

    def model(self, cls: type[NovvusModel]) -> type[NovvusModel]:
        """Register a model: table + RLS in migrations, CRUD in the API."""
        if not issubclass(cls, NovvusModel):
            raise TypeError(f"{cls.__name__} must inherit from NovvusModel")
        # Fail fast on a broken __novvus_views__ declaration (docs/VIEWS.md §3).
        validate_views(self.id, cls)
        self.models.append(cls)
        return cls

    def gettext(self, message: str, locale: str | None = None) -> str:
        """Translate a source (es-MX) string using this module's catalogs and
        the current request locale. Alias: `module._`."""
        return self.translator.gettext(message, locale)

    # gettext-style short alias.
    _ = gettext

    def on(self, event_type: str) -> Callable[[EventHandler], EventHandler]:
        """Subscribe a handler; the type must be declared in [events] listens."""
        if event_type not in self.manifest.events.listens:
            raise ValueError(
                f"event {event_type!r} is not declared in [events] listens of novvus.toml"
            )
        return self.events.on(event_type)

    def seed(self, fn: SeedFunction) -> SeedFunction:
        self._seed_fn = fn
        return fn

    def record_access(
        self, model: type[NovvusModel]
    ) -> Callable[[RecordAccessHandler], RecordAccessHandler]:
        """Declare record-level authorization for `model` (docs/FILES.md §8.5).

        The handler receives a tenant session, the caller's context, the record id
        and the action (`read` | `write`) and returns whether the caller may touch
        THAT record. The kernel asks it before serving attachments of the model;
        the generic `get`/`patch`/`delete` endpoints apply it too, answering 404
        on denial (no existence leak). Permissions by organization are still
        required: this hook only narrows them.
        """

        def decorator(fn: RecordAccessHandler) -> RecordAccessHandler:
            self._record_access[model.resource_name()] = fn
            model.__novvus_record_access__ = True
            return fn

        return decorator

    def record_scope(
        self, model: type[NovvusModel]
    ) -> Callable[[RecordScopeHandler], RecordScopeHandler]:
        """Declare the list scope of a record-access model: the handler returns a
        SQLAlchemy clause (or None for everything) restricting the generic
        list/export to what the caller may read."""

        def decorator(fn: RecordScopeHandler) -> RecordScopeHandler:
            self._record_scope[model.resource_name()] = fn
            return fn

        return decorator

    def action(
        self, model: type[NovvusModel], name: str
    ) -> Callable[[ActionHandler], ActionHandler]:
        """Bind the handler of a record action declared in ``__novvus_views__["actions"]``.

        The generic API mounts ``POST /api/{module}/{resource}/{id}/actions/{name}``: the
        caller must hold the action's ``permission`` (or the model's write permission), the
        record must be visible to it (``record_access``), and only then the handler runs
        inside the tenant session. An action declared with ``"scope": "collection"`` (§8f) is
        mounted at ``POST /api/{module}/{resource}/actions/{name}`` and the handler receives
        ``None`` as the record."""
        views = getattr(model, "__novvus_views__", {}) or {}
        declared = {a["name"] for a in views.get("actions", []) or []}
        if name not in declared:
            raise ValueError(
                f"{model.__name__}: action {name!r} is not declared in __novvus_views__['actions']"
            )

        def decorator(fn: ActionHandler) -> ActionHandler:
            self._actions.setdefault(model.resource_name(), {})[name] = fn
            return fn

        return decorator

    def action_validator(
        self, model: type[NovvusModel], name: str
    ) -> Callable[[ActionHandler], ActionHandler]:
        """Bind the read-only validator of an action declared with ``"validate": True`` (§8f).

        Mounted at ``POST …/{id}/actions/{name}/validate`` (record) or
        ``POST …/actions/{name}/validate`` (collection): same permission as the action, body
        validated leniently (no ``required``), and the callable returns ``{field: message}`` for
        the problems the shell shows next to the fields. It must
        not write."""
        views = getattr(model, "__novvus_views__", {}) or {}
        spec = next((a for a in views.get("actions", []) or [] if a.get("name") == name), None)
        if spec is None:
            raise ValueError(
                f"{model.__name__}: action {name!r} is not declared in __novvus_views__['actions']"
            )
        if not spec.get("validate"):
            raise ValueError(f"{model.__name__}: action {name!r} does not declare validate=True")

        def decorator(fn: ActionHandler) -> ActionHandler:
            self._action_validators.setdefault(model.resource_name(), {})[name] = fn
            return fn

        return decorator

    def action_options(
        self, model: type[NovvusModel], name: str
    ) -> Callable[[ActionHandler], ActionHandler]:
        """Bind the options provider of an action with at least one field declared with
        ``"options": True`` (§8g).

        Mounted at ``POST …/{id}/actions/{name}/options`` (record) or
        ``POST …/actions/{name}/options`` (collection): same permission as the action,
        body = the values typed so far (lenient), and
        the callable returns ``{field: [choices]}`` where each choice is a string or
        ``{value, label[, description, details]}``. It must not write."""
        views = getattr(model, "__novvus_views__", {}) or {}
        spec = next((a for a in views.get("actions", []) or [] if a.get("name") == name), None)
        if spec is None:
            raise ValueError(
                f"{model.__name__}: action {name!r} is not declared in __novvus_views__['actions']"
            )
        if not any(f.get("options") for f in spec.get("fields", []) or []):
            raise ValueError(f"{model.__name__}: action {name!r} has no field with options=True")

        def decorator(fn: ActionHandler) -> ActionHandler:
            self._action_options.setdefault(model.resource_name(), {})[name] = fn
            return fn

        return decorator

    def action_handlers(self, resource: str) -> dict[str, ActionHandler]:
        return self._actions.get(resource, {})

    def action_option_handlers(self, resource: str) -> dict[str, ActionHandler]:
        return self._action_options.get(resource, {})

    def action_validators(self, resource: str) -> dict[str, ActionHandler]:
        return self._action_validators.get(resource, {})

    def record_access_handler(self, resource: str) -> RecordAccessHandler | None:
        return self._record_access.get(resource)

    def record_scope_handler(self, resource: str) -> RecordScopeHandler | None:
        return self._record_scope.get(resource)

    def cron(self, name: str) -> Callable[[CronHandler], CronHandler]:
        """Bind a handler to a scheduled job declared in [[cron]]. The kernel
        invokes it every `interval_seconds` for each org where the module is
        enabled; the handler runs inside that org's tenant session."""
        if name not in self._cron_names:
            raise ValueError(f"cron {name!r} is not declared in [[cron]] of novvus.toml")

        def decorator(fn: CronHandler) -> CronHandler:
            self._cron_handlers[name] = fn
            return fn

        return decorator

    def _lifecycle_hook(self, hook: str) -> Callable[[HookHandler], HookHandler]:
        def decorator(fn: HookHandler) -> HookHandler:
            self._hook_handlers[hook] = fn
            return fn

        return decorator

    def on_install(self, fn: HookHandler) -> HookHandler:
        """Run when an organization installs this module (per-org setup)."""
        return self._lifecycle_hook("on_install")(fn)

    def on_enable(self, fn: HookHandler) -> HookHandler:
        """Run when an organization enables this module."""
        return self._lifecycle_hook("on_enable")(fn)

    def on_disable(self, fn: HookHandler) -> HookHandler:
        """Run when an organization disables this module."""
        return self._lifecycle_hook("on_disable")(fn)

    def on_uninstall(self, fn: HookHandler) -> HookHandler:
        """Run when an organization uninstalls this module (per-org teardown)."""
        return self._lifecycle_hook("on_uninstall")(fn)

    async def call(
        self,
        method: str,
        path: str,
        org_id: UUID | None = None,
        json: dict[str, Any] | None = None,
    ) -> Any:
        """Call another module's public API through the gateway (never its
        tables). Requires the target permission in [dependencies]
        service_permissions. Raises RuntimeError in offline mode."""
        if self._kernel is None:
            raise RuntimeError("module-to-module calls require a kernel connection")
        org = org_id or current_context().org_id
        response = await self._kernel.call_module(method, path, org, json=json)
        response.raise_for_status()
        return response.json() if response.content else None

    async def dependency_statuses(self) -> dict[str, str]:
        """Lifecycle status of this module's declared dependencies, cached
        briefly. Empty dict in offline mode (nothing to report)."""
        if self._kernel is None or not self.manifest.dependencies.modules:
            return {}
        now = time.monotonic()
        if self._deps_cache is not None and now - self._deps_cached_at < 10:
            return self._deps_cache
        statuses = await self._kernel.module_statuses()
        wanted = {
            spec.split("<")[0].split(">")[0].split("=")[0].split("^")[0].split("~")[0].strip()
            for spec in self.manifest.dependencies.modules
        }
        self._deps_cache = {dep: statuses.get(dep, "missing") for dep in wanted}
        self._deps_cached_at = now
        return self._deps_cache

    async def emit(
        self, event_type: str, payload: dict[str, Any] | None = None, org_id: UUID | None = None
    ) -> dict[str, Any]:
        """Publish an event through the kernel bus (must be declared in emits).

        In offline mode (no kernel handshake — local dev and tests) the event
        is skipped with a warning instead of failing the business operation.
        """
        if event_type not in self.manifest.events.emits:
            raise ValueError(f"event {event_type!r} is not declared in [events] emits")
        org = org_id or current_context().org_id
        if self._kernel is None:
            logging.getLogger("novvus").warning(
                "offline mode: event %s for org %s was not published", event_type, org
            )
            return {"skipped": True, "event_type": event_type}
        return await self._kernel.emit(org, event_type, payload)

    def _config_defaults(self) -> dict[str, Any]:
        """Schema defaults, used offline and as the base for effective config."""
        return {field.key: field.default for field in self.manifest.config}

    def instance_config(self) -> dict[str, Any]:
        """Instance-level configuration of this module: the `[[config]]`
        defaults declared in novvus.toml, the baseline every org starts
        from. Per-org effective values come from `config()`."""
        return self._config_defaults()

    async def config(self, org_id: UUID | None = None) -> dict[str, Any]:
        """Effective per-org configuration for this module (MODULE_CONTRACT.md
        §9): schema defaults merged with the org's stored values. In offline
        mode (no kernel) only the schema defaults are returned."""
        org = org_id or current_context().org_id
        if self._kernel is None:
            return self._config_defaults()
        return await self._kernel.get_config(org)

    async def set_config(
        self, values: dict[str, Any], org_id: UUID | None = None
    ) -> dict[str, Any]:
        """Write configuration values in this module's own namespace for `org_id`.
        Raises RuntimeError in offline mode."""
        org = org_id or current_context().org_id
        if self._kernel is None:
            raise RuntimeError("writing module config requires a kernel connection")
        return await self._kernel.set_config(org, values)

    # ------------------------------------------------------------------
    # Runtime
    # ------------------------------------------------------------------

    async def kernel_entitlement(self) -> Entitlement:
        """What the KERNEL says this module may do (service token channel),
        cached for a few seconds. Offline (no kernel): ``unknown``. A kernel
        that predates licensing: ``unknown``, nothing refused. A licensing
        kernel that cannot be reached: fail closed (no feature)."""
        if self._kernel is None or self._licensing_kernel is False:
            return Entitlement()
        now = time.monotonic()
        if self._entitlement_cache and now - self._entitlement_cache[0] < ENTITLEMENT_TTL_SECONDS:
            return self._entitlement_cache[1]
        try:
            document = await self._kernel.entitlement()
        except Exception:
            return Entitlement(strict=True)
        if document is None and self._licensing_kernel is None:
            self._licensing_kernel = False
            return Entitlement()
        self._licensing_kernel = True
        value = entitlement_from_kernel(document) if document else Entitlement(strict=True)
        self._entitlement_cache = (now, value)
        return value

    async def startup(self) -> None:
        """Connect to the platform: handshake with the kernel, or offline env
        config (NOVVUS_DATABASE_URL + NOVVUS_INTERNAL_HMAC_SECRET) for tests
        and local development without a kernel."""
        offline_db = os.environ.get("NOVVUS_DATABASE_URL")
        offline_secret = os.environ.get("NOVVUS_INTERNAL_HMAC_SECRET")
        service_token = os.environ.get("NOVVUS_SERVICE_TOKEN")

        if service_token:
            kernel_url = os.environ.get("NOVVUS_KERNEL_URL", "http://127.0.0.1:8000")
            port = int(
                os.environ.get("NOVVUS_MODULE_PORT", str(self.manifest.runtime.port or 8100))
            )
            base_url = os.environ.get("NOVVUS_MODULE_BASE_URL", f"http://127.0.0.1:{port}")
            self._kernel = KernelClient(kernel_url, service_token)
            meta = build_module_meta(self.id, self.manifest.module.version, self.models)
            result = await self._kernel.handshake(self.id, base_url, meta=meta)
            self._hmac_secret = result.internal_hmac_secret
            self._db = Database(result.database_url, self.schema)
        elif offline_db and offline_secret:
            self._hmac_secret = offline_secret
            self._db = Database(offline_db, self.schema)
        else:
            raise RuntimeError(
                "set NOVVUS_SERVICE_TOKEN (kernel handshake) or "
                "NOVVUS_DATABASE_URL + NOVVUS_INTERNAL_HMAC_SECRET (offline mode)"
            )

    async def shutdown(self) -> None:
        if self._db is not None:
            await self._db.dispose()
        if self._kernel is not None:
            await self._kernel.close()

    def session_dependency(self) -> Callable[[], AsyncIterator[AsyncSession]]:
        """FastAPI dependency yielding a tenant-scoped session. Also available
        to custom endpoints: `session = Depends(module.session_dependency())`."""

        async def dependency() -> AsyncIterator[AsyncSession]:
            context = current_context()
            assert self._db is not None, "module runtime not started"
            async with self._db.tenant_session(context.org_id) as session:
                yield session

        return dependency

    def create_app(self) -> FastAPI:
        @asynccontextmanager
        async def lifespan(_: FastAPI) -> AsyncIterator[None]:
            await self.startup()
            yield
            await self.shutdown()

        app = FastAPI(
            title=self.manifest.module.name,
            version=self.manifest.module.version,
            lifespan=lifespan,
        )

        # Every request except the healthcheck must carry valid signed
        # internal headers: only the kernel can originate traffic.
        @app.middleware("http")
        async def _internal_auth(request: Request, call_next: Any) -> Response:
            if request.url.path == self.manifest.runtime.healthcheck:
                return await call_next(request)  # type: ignore[no-any-return]
            if self._hmac_secret is None:
                return JSONResponse({"detail": "module runtime not ready"}, status_code=503)
            try:
                context = verify_request(request, self._hmac_secret)
            except HTTPException as exc:
                return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
            if context.entitlement.state == "unknown":
                # No (signed) entitlement on this request: the kernel is asked
                # over the module's own authenticated channel. Never guessed.
                context = replace(context, entitlement=await self.kernel_entitlement())
            token = set_context(context)
            try:
                return await call_next(request)  # type: ignore[no-any-return]
            finally:
                reset_context(token)

        session_dep = self.session_dependency()
        for model in self.models:
            app.include_router(
                build_router(
                    self.id,
                    model,
                    session_dep,
                    translator=self.translator,
                    extensions=self.extensions,
                    custom_fields=self.custom_fields,
                    chatter=self.chatter,
                    record_access=self._record_access.get(model.resource_name()),
                    record_scope=self._record_scope.get(model.resource_name()),
                    actions=self._actions.get(model.resource_name()),
                    action_validators=self._action_validators.get(model.resource_name()),
                    action_options=self._action_options.get(model.resource_name()),
                )
            )
        app.include_router(self.router, prefix=f"/api/{self.id}")

        @app.get(self.manifest.runtime.healthcheck)
        async def health() -> dict[str, Any]:
            # Explicit degraded state: still serving, but a declared
            # dependency is not enabled (docs/MODULE_CONTRACT.md §2.1).
            degraded: dict[str, str] = {}
            try:
                statuses = await self.dependency_statuses()
                degraded = {dep: s for dep, s in statuses.items() if s != "enabled"}
            except Exception:
                logging.getLogger("novvus").warning("could not check dependency statuses")
            return {
                "status": "degraded" if degraded else "ok",
                "module": self.id,
                "version": self.manifest.module.version,
                "platform_api": PLATFORM_API,
                "degraded_dependencies": degraded,
            }

        @app.get("/_novvus/meta")
        async def module_meta() -> dict[str, Any]:
            # Introspection of the meta document (docs/VIEWS.md §4); the
            # authoritative copy travels to the kernel in the handshake.
            # `platform_api` is introspection-only: the handshake validator
            # rejects unknown keys (kernel meta.rs, deny_unknown_fields).
            meta = build_module_meta(self.id, self.manifest.module.version, self.models)
            return {**meta, "platform_api": PLATFORM_API}

        @app.post("/_novvus/events")
        async def receive_event(event: Event) -> dict[str, Any]:
            handlers = self.events.handlers_for(event.event_type)
            if not handlers:
                return {"status": "ignored"}
            assert self._db is not None
            async with self._db.tenant_session(event.org_id) as session:
                first_time = await mark_processed(session, event.id)
                if not first_time:
                    return {"status": "duplicate"}
                for handler in handlers:
                    await handler(event, session)
            return {"status": "processed"}

        @app.post("/_novvus/cron")
        async def receive_cron(trigger: CronTrigger) -> dict[str, Any]:
            handler = self._cron_handlers.get(trigger.name)
            if handler is None:
                return {"status": "ignored"}
            assert self._db is not None
            async with self._db.tenant_session(trigger.org_id) as session:
                await handler(session)
            return {"status": "ran"}

        @app.post("/_novvus/record-access")
        async def record_access_query(query: RecordAccessQuery) -> dict[str, Any]:
            # Fail closed: unknown model, unknown action or handler error → denied.
            handler = self._record_access.get(query.model)
            if handler is None or query.action not in ("read", "write"):
                return {"allowed": False}
            context = current_context()
            assert self._db is not None
            try:
                async with self._db.tenant_session(context.org_id) as session:
                    allowed = bool(await handler(session, context, query.record_id, query.action))
            except Exception:
                logging.getLogger("novvus").exception(
                    "record_access handler failed for %s", query.model
                )
                allowed = False
            return {"allowed": allowed}

        @app.post("/_novvus/hooks/{hook}")
        async def receive_hook(hook: str) -> dict[str, Any]:
            handler = self._hook_handlers.get(hook)
            if handler is None:
                return {"status": "ignored"}
            context = current_context()
            assert self._db is not None
            async with self._db.tenant_session(context.org_id) as session:
                await handler(session)
            return {"status": "ran"}

        return app

    # Exposed for the CLI (`novvus seed`).
    @property
    def seed_function(self) -> SeedFunction | None:
        return self._seed_fn

    @property
    def processed_events_ddl(self) -> str:
        return PROCESSED_EVENTS_DDL
