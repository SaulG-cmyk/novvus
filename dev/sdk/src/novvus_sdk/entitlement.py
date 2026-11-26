"""License entitlement of the module, as the kernel tells it (ADR-001 Fase G5).

The kernel decides; the SDK only exposes the decision so that every module
uses the same API instead of growing its own:

* ``current_entitlement()`` — state, read-only flag and GRANTED features of
  the running request.
* ``@requires_feature("exports")`` / ``enforce_feature("exports")`` — 403
  when the license of the installation does not grant that capability.

``[entitlement] features`` of the manifest is the CATALOG of capabilities a
module can license separately; what is granted comes from the license, never
from the manifest. A module that requires no entitlement is granted its whole
catalog.

Trust boundary (docs/SECURITY.md §4.1). The headers are TRANSPORT, not a trust
root: the authority is the license the kernel verified.

* A client cannot inject them: the gateway builds the internal request from
  scratch and no client ``X-Novvus-*`` header crosses it.
* A request that did not come through the gateway carries no valid internal
  signature and is refused (401) before any header is read.
* ``x-novvus-entitlement`` / ``x-novvus-features`` travel with their own
  signature (``x-novvus-entitlement-signature``: same secret, timestamp,
  method and path as the request). Present and not verifying = 401: they can
  neither be edited nor moved to another request.
* When they are absent the SDK asks the kernel itself over the module's
  authenticated channel (service token). Only a kernel that predates licensing
  (no such endpoint) yields ``unknown``, which refuses nothing because
  licensing did not exist there; a licensing kernel that cannot be reached
  fails CLOSED (no feature).

When the entitlement is not in force the module is READ-ONLY: the gateway
answers 423 to mutations before they reach the module and the database role
of the runtime cannot write. A module cannot lift that from the inside.
"""

from __future__ import annotations

import hashlib
import hmac
import inspect
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from functools import wraps
from typing import Any, TypeVar

from fastapi import HTTPException

HDR_ENTITLEMENT = "x-novvus-entitlement"
HDR_FEATURES = "x-novvus-features"
HDR_ENTITLEMENT_SIGNATURE = "x-novvus-entitlement-signature"

#: States a kernel reports. ``unknown`` = a kernel that predates licensing.
STATES = frozenset({"not_required", "licensed", "grace", "restricted", "unknown"})


@dataclass(frozen=True)
class Entitlement:
    """What this installation may do with the module right now."""

    state: str = "unknown"
    features: frozenset[str] = field(default_factory=frozenset)
    #: ``unknown`` because a LICENSING kernel could not be asked: fail closed.
    strict: bool = False

    @property
    def read_only(self) -> bool:
        return self.state == "restricted"

    def has_feature(self, name: str) -> bool:
        """Whether capability ``name`` of the manifest catalog is granted."""
        if self.state == "unknown":
            return not self.strict
        return name in self.features


def sign_entitlement(
    secret: str, state: str, features: str, timestamp: int, method: str, path: str
) -> str:
    """Signature of the entitlement headers of one request (kernel-compatible)."""
    canonical = f"entitlement\n{state}\n{features}\n{timestamp}\n{method}\n{path}"
    return hmac.new(secret.encode(), canonical.encode(), hashlib.sha256).hexdigest()


def from_request(
    headers: Mapping[str, str], secret: str, timestamp: int, method: str, path: str
) -> Entitlement:
    """The entitlement the gateway asserted on this ALREADY AUTHENTICATED
    request. Absent headers = ``unknown`` (the caller then asks the kernel);
    headers that do not verify = 401."""
    state = headers.get(HDR_ENTITLEMENT)
    if state is None:
        if headers.get(HDR_FEATURES) is not None:
            raise HTTPException(status_code=401, detail="invalid entitlement headers")
        return Entitlement()
    raw = headers.get(HDR_FEATURES) or ""
    signature = headers.get(HDR_ENTITLEMENT_SIGNATURE) or ""
    expected = sign_entitlement(secret, state, raw, timestamp, method, path)
    if not hmac.compare_digest(expected, signature) or state not in STATES:
        raise HTTPException(status_code=401, detail="invalid entitlement signature")
    return Entitlement(state=state, features=frozenset(f for f in raw.split(",") if f))


def from_kernel(document: Mapping[str, Any] | None) -> Entitlement:
    """The entitlement returned by ``GET /api/core/modules/entitlement``
    (``None`` from a kernel that does not know the endpoint)."""
    if document is None:
        return Entitlement()
    if document.get("state") not in STATES:
        return Entitlement(strict=True)
    return Entitlement(
        state=str(document["state"]),
        features=frozenset(str(f) for f in document.get("features") or []),
    )


def current_entitlement() -> Entitlement:
    """Entitlement of the running request."""
    from novvus_sdk.context import current_context

    return current_context().entitlement


def enforce_feature(name: str) -> None:
    """Raise 403 unless the license grants capability ``name``."""
    if not current_entitlement().has_feature(name):
        raise HTTPException(status_code=403, detail=f"feature not entitled: {name}")


F = TypeVar("F", bound=Callable[..., Awaitable[Any]])


def requires_feature(name: str) -> Callable[[F], F]:
    """Decorator for endpoint handlers: the capability must be licensed."""

    def decorator(func: F) -> F:
        if not inspect.iscoroutinefunction(func):
            raise TypeError("@requires_feature only supports async endpoint functions")

        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            enforce_feature(name)
            return await func(*args, **kwargs)

        return wrapper  # type: ignore[return-value]

    return decorator
