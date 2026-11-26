"""Sanctioned facades over kernel services (ADR-001, fase 0).

Modules never reach the raw kernel client or the DB engine: identity lookups
and permission queries go through these thin, offline-tolerant wrappers
exposed as ``module.identity`` and ``module.permissions``. Offline mode (no
kernel handshake — local dev and tests) degrades to "nothing known".
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import UUID

from novvus_sdk.context import current_context

if TYPE_CHECKING:
    from novvus_sdk.app import NovvusModule


class IdentityFacade:
    """Read-only view of platform users and organizations."""

    def __init__(self, module: NovvusModule) -> None:
        self._module = module

    async def user(self, user_id: UUID, org_id: UUID | None = None) -> dict[str, Any] | None:
        """``{"id", "email", "display_name"}`` of a user as seen from `org_id`
        (defaults to the current request's org). None when the kernel does
        not know the user, or in offline mode."""
        kernel = self._module._kernel
        if kernel is None:
            return None
        org = org_id or current_context().org_id
        return await kernel.get_identity_user(user_id, org)

    async def users(
        self, permission: str | None = None, org_id: UUID | None = None
    ) -> list[dict[str, Any]]:
        """Active members of `org_id` (defaults to the current request's org)
        as ``[{"id", "email", "display_name"}, …]`` sorted by display name.
        With `permission`, only the members whose effective permissions grant
        that key (wildcards honored): the sanctioned way for a module to offer
        a person as the target of an assignment. Empty in offline mode and on
        a kernel older than 0.3.44."""
        kernel = self._module._kernel
        if kernel is None:
            return []
        org = org_id or current_context().org_id
        return await kernel.get_identity_users(org, permission)

    async def org(self, org_id: UUID | None = None) -> dict[str, Any] | None:
        """``{"id", "name", "slug"}`` of an organization (defaults to the
        current request's org). None when unknown, or in offline mode."""
        kernel = self._module._kernel
        if kernel is None:
            return None
        org = org_id or current_context().org_id
        return await kernel.get_identity_org(org)


class PermissionsFacade:
    """Permission checks against the gateway-asserted context and the kernel."""

    def __init__(self, module: NovvusModule) -> None:
        self._module = module

    def check(self, key: str) -> bool:
        """Whether the caller of the current request holds `key` (wildcard
        grants honored). False outside a gateway-authenticated request."""
        try:
            context = current_context()
        except RuntimeError:
            return False
        return context.is_allowed(key)

    async def effective(self, user_id: UUID, org_id: UUID | None = None) -> frozenset[str]:
        """Every permission key `user_id` effectively holds in `org_id`
        (defaults to the current request's org). Empty in offline mode."""
        kernel = self._module._kernel
        if kernel is None:
            return frozenset()
        org = org_id or current_context().org_id
        return await kernel.get_effective_permissions(user_id, org)
