"""Per-request context: identity, tenant and permissions asserted by the
kernel gateway via signed internal headers (docs/SECURITY.md §4)."""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass, field
from uuid import UUID

from novvus_sdk.entitlement import Entitlement

# Platform default locale (docs/I18N.md). es-MX is the source language.
DEFAULT_LOCALE = "es-MX"


@dataclass(frozen=True)
class RequestContext:
    """What the gateway asserted about the caller of the current request."""

    org_id: UUID
    user_id: UUID | None  # None for kernel-originated calls (event delivery)
    permissions: frozenset[str] = field(default_factory=frozenset)
    # Preferred locale of the caller; drives _() translations. Not security
    # sensitive, so it is read from a header without being part of the HMAC.
    locale: str = DEFAULT_LOCALE
    # License entitlement of the module (ADR-001 Fase G5), asserted by the
    # gateway on every request. `unknown` on kernels that predate licensing.
    entitlement: Entitlement = field(default_factory=Entitlement)

    def is_allowed(self, required: str) -> bool:
        return any(_grant_matches(granted, required) for granted in self.permissions)


def _grant_matches(granted: str, required: str) -> bool:
    """Wildcard-aware permission matching, identical to the kernel's rules."""
    if granted == "*" or granted == required:
        return True
    if granted.endswith(".*"):
        prefix = granted[:-2]
        return required.startswith(prefix + ".")
    return False


_current: ContextVar[RequestContext | None] = ContextVar("novvus_request_context", default=None)


def current_context() -> RequestContext:
    context = _current.get()
    if context is None:
        raise RuntimeError(
            "no NOVVUS request context; this code must run inside a gateway-authenticated request"
        )
    return context


def set_context(context: RequestContext | None) -> object:
    return _current.set(context)


def reset_context(token: object) -> None:
    _current.reset(token)  # type: ignore[arg-type]
