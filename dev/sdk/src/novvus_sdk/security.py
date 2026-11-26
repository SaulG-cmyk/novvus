"""Verification of gateway-signed internal headers and the @requires
permission decorator (docs/SECURITY.md §§4-5)."""

from __future__ import annotations

import hashlib
import hmac
import inspect
import time
from collections.abc import Awaitable, Callable
from functools import wraps
from typing import Any, TypeVar
from uuid import UUID

from fastapi import HTTPException, Request

from novvus_sdk.context import DEFAULT_LOCALE, RequestContext, current_context
from novvus_sdk.entitlement import from_request as entitlement_from_request

HDR_USER = "x-novvus-user"
HDR_ORG = "x-novvus-org"
HDR_PERMS = "x-novvus-perms"
HDR_TIMESTAMP = "x-novvus-timestamp"
HDR_SIGNATURE = "x-novvus-signature"
HDR_LOCALE = "x-novvus-locale"

MAX_SKEW_SECONDS = 60


def sign(
    secret: str, user: str, org: str, perms: str, timestamp: int, method: str, path: str
) -> str:
    canonical = f"{user}\n{org}\n{perms}\n{timestamp}\n{method}\n{path}"
    return hmac.new(secret.encode(), canonical.encode(), hashlib.sha256).hexdigest()


def verify_request(request: Request, secret: str) -> RequestContext:
    """Validate the internal headers of an incoming request or raise 401."""
    headers = request.headers
    signature = headers.get(HDR_SIGNATURE)
    timestamp_raw = headers.get(HDR_TIMESTAMP)
    org_raw = headers.get(HDR_ORG)
    if not signature or not timestamp_raw or org_raw is None:
        raise HTTPException(status_code=401, detail="missing internal headers")

    try:
        timestamp = int(timestamp_raw)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="invalid timestamp") from exc
    if abs(time.time() - timestamp) > MAX_SKEW_SECONDS:
        raise HTTPException(status_code=401, detail="stale internal signature")

    user_raw = headers.get(HDR_USER, "")
    perms_raw = headers.get(HDR_PERMS, "")
    expected = sign(
        secret, user_raw, org_raw, perms_raw, timestamp, request.method, request.url.path
    )
    if not hmac.compare_digest(expected, signature):
        raise HTTPException(status_code=401, detail="invalid internal signature")

    try:
        org_id = UUID(org_raw)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="invalid org id") from exc
    user_id = UUID(user_raw) if user_raw else None
    permissions = frozenset(p for p in perms_raw.split(",") if p)
    # Locale is informational (not part of the signature); default to es-MX.
    locale = headers.get(HDR_LOCALE) or DEFAULT_LOCALE
    return RequestContext(
        org_id=org_id,
        user_id=user_id,
        permissions=permissions,
        locale=locale,
        # Read only AFTER the identity signature verified, and verified itself.
        entitlement=entitlement_from_request(
            headers, secret, timestamp, request.method, request.url.path
        ),
    )


def enforce(required: str) -> None:
    """Raise 403 unless the current request holds the required permission."""
    context = current_context()
    if not context.is_allowed(required):
        raise HTTPException(status_code=403, detail=f"missing permission: {required}")


F = TypeVar("F", bound=Callable[..., Awaitable[Any]])


def requires(required: str) -> Callable[[F], F]:
    """Decorator for endpoint handlers: enforce a permission key.

    The key must be concrete (``crm.contacts.read``); grants may be
    wildcards, requirements never are.
    """

    def decorator(func: F) -> F:
        if not inspect.iscoroutinefunction(func):
            raise TypeError("@requires only supports async endpoint functions")

        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            enforce(required)
            return await func(*args, **kwargs)

        return wrapper  # type: ignore[return-value]

    return decorator
