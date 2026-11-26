"""HTTP client for the kernel: handshake, event emission and module
registration/lifecycle helpers used by the CLI."""

from __future__ import annotations

from typing import Any
from uuid import UUID

import httpx
from pydantic import BaseModel

SERVICE_TOKEN_HEADER = "x-novvus-service-token"


class HandshakeResult(BaseModel):
    module_id: str
    status: str
    internal_hmac_secret: str
    database_url: str
    schema_name: str

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> HandshakeResult:
        return cls(
            module_id=payload["module_id"],
            status=payload["status"],
            internal_hmac_secret=payload["internal_hmac_secret"],
            database_url=payload["database_url"],
            schema_name=payload["schema"],
        )


class KernelClient:
    """Async client a module runtime uses to talk to the kernel."""

    def __init__(self, kernel_url: str, service_token: str) -> None:
        self.kernel_url = kernel_url.rstrip("/")
        self._client = httpx.AsyncClient(
            base_url=self.kernel_url,
            headers={SERVICE_TOKEN_HEADER: service_token},
            timeout=15.0,
        )

    async def handshake(
        self, module_id: str, base_url: str, meta: dict[str, Any] | None = None
    ) -> HandshakeResult:
        body: dict[str, Any] = {"module_id": module_id, "base_url": base_url}
        if meta is not None:
            # Model metadata for the generic views (docs/VIEWS.md §7.1); an
            # invalid document rejects the whole handshake.
            body["meta"] = meta
        response = await self._client.post("/api/core/modules/handshake", json=body)
        response.raise_for_status()
        return HandshakeResult.from_payload(response.json())

    async def emit(
        self, org_id: UUID, event_type: str, payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        response = await self._client.post(
            "/api/core/events",
            json={"org_id": str(org_id), "event_type": event_type, "payload": payload or {}},
        )
        response.raise_for_status()
        result: dict[str, Any] = response.json()
        return result

    async def entitlement(self) -> dict[str, Any] | None:
        """What THIS module may do right now (ADR-001 Fase G5): ``state``,
        ``read_only`` and granted ``features``. For code that runs outside a
        request (cron, event handlers, startup). ``None`` from a kernel that
        predates licensing."""
        response = await self._client.get("/api/core/modules/entitlement")
        if response.status_code == 404:
            return None
        response.raise_for_status()
        result: dict[str, Any] = response.json()
        return result

    async def module_statuses(self) -> dict[str, str]:
        """id → lifecycle status of every platform module (service auth)."""
        response = await self._client.get("/api/core/modules/status")
        response.raise_for_status()
        result: dict[str, str] = response.json()
        return result

    async def get_config(self, org_id: UUID) -> dict[str, Any]:
        """Effective per-org config for the calling module (service auth)."""
        response = await self._client.get(
            "/api/core/config", headers={"x-novvus-org": str(org_id)}
        )
        response.raise_for_status()
        result: dict[str, Any] = response.json()
        return result

    async def set_config(self, org_id: UUID, values: dict[str, Any]) -> dict[str, Any]:
        """Write config values for the calling module's own namespace."""
        response = await self._client.put(
            "/api/core/config",
            headers={"x-novvus-org": str(org_id)},
            json={"values": values},
        )
        response.raise_for_status()
        result: dict[str, Any] = response.json()
        return result

    async def get_extensions(self, org_id: UUID | None = None) -> list[dict[str, Any]]:
        """Extension sets targeting the calling module (docs/EXTENSIONS.md §5);
        with org_id, only extenders enabled for that org."""
        params = {"org_id": str(org_id)} if org_id else {}
        response = await self._client.get("/api/core/extensions", params=params)
        response.raise_for_status()
        result: list[dict[str, Any]] = response.json()
        return result

    async def post_chatter_message(
        self,
        org_id: UUID,
        module_id: str,
        model: str,
        record_id: UUID,
        body: str,
        kind: str = "system",
        meta: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Post a message on one of this module's own records
        (docs/CHATTER.md §6; service auth)."""
        response = await self._client.post(
            f"/api/core/chatter/{module_id}/{model}/{record_id}/messages",
            headers={"x-novvus-org": str(org_id)},
            json={"kind": kind, "body": body, "meta": meta or {}},
        )
        response.raise_for_status()
        result: dict[str, Any] = response.json()
        return result

    async def get_custom_fields(self, org_id: UUID) -> list[dict[str, Any]]:
        """Active custom-field definitions of `org_id` targeting the calling
        module (docs/CUSTOM_FIELDS.md §7)."""
        response = await self._client.get(
            "/api/core/custom-fields/service", params={"org_id": str(org_id)}
        )
        response.raise_for_status()
        result: list[dict[str, Any]] = response.json()
        return result

    # -- identity (ADR-001 facades: module.identity / module.permissions) -----

    async def get_identity_user(self, user_id: UUID, org_id: UUID) -> dict[str, Any] | None:
        """Public profile (`id`, `email`, `display_name`) of a user as seen
        from `org_id` (service auth); None when the kernel does not know
        the user (404)."""
        response = await self._client.get(
            f"/api/core/identity/users/{user_id}",
            headers={"x-novvus-org": str(org_id)},
        )
        if response.status_code == 404:
            return None
        response.raise_for_status()
        result: dict[str, Any] = response.json()
        return result

    async def get_identity_users(
        self, org_id: UUID, permission: str | None = None
    ) -> list[dict[str, Any]]:
        """Active members of `org_id` (`id`, `email`, `display_name`), optionally
        only those whose effective permissions grant `permission` (service auth;
        Core >= 0.3.44). A kernel without the route (404) yields an empty list."""
        params = {"permission": permission} if permission else None
        response = await self._client.get(
            "/api/core/identity/users",
            params=params,
            headers={"x-novvus-org": str(org_id)},
        )
        if response.status_code == 404:
            return []
        response.raise_for_status()
        payload: dict[str, Any] = response.json()
        users = payload.get("users", [])
        return [dict(user) for user in users if isinstance(user, dict)]

    async def get_identity_org(self, org_id: UUID) -> dict[str, Any] | None:
        """`id`, `name`, `slug` of an organization (service auth); None on 404."""
        response = await self._client.get(
            f"/api/core/identity/orgs/{org_id}",
            headers={"x-novvus-org": str(org_id)},
        )
        if response.status_code == 404:
            return None
        response.raise_for_status()
        result: dict[str, Any] = response.json()
        return result

    async def get_effective_permissions(self, user_id: UUID, org_id: UUID) -> frozenset[str]:
        """Every permission key `user_id` effectively holds in `org_id`
        (roles expanded by the kernel; service auth)."""
        response = await self._client.get(
            f"/api/core/identity/permissions/{user_id}",
            headers={"x-novvus-org": str(org_id)},
        )
        response.raise_for_status()
        result: dict[str, Any] = response.json()
        return frozenset(str(key) for key in result.get("permissions", []))

    # -- attachments (docs/FILES.md §6) ---------------------------------------

    async def upload_file(
        self,
        org_id: UUID,
        module_id: str,
        model: str,
        record_id: UUID,
        filename: str,
        content: bytes,
    ) -> dict[str, Any]:
        """Attach a file to one of this module's own records (service auth)."""
        response = await self._client.post(
            "/api/core/files",
            headers={"x-novvus-org": str(org_id)},
            data={"module_id": module_id, "model": model, "record_id": str(record_id)},
            files={"file": (filename, content)},
        )
        response.raise_for_status()
        result: dict[str, Any] = response.json()
        return result

    async def list_files(
        self, org_id: UUID, module_id: str, model: str, record_id: UUID
    ) -> list[dict[str, Any]]:
        response = await self._client.get(
            "/api/core/files",
            headers={"x-novvus-org": str(org_id)},
            params={"module_id": module_id, "model": model, "record_id": str(record_id)},
        )
        response.raise_for_status()
        result: list[dict[str, Any]] = response.json()
        return result

    async def download_file(self, org_id: UUID, attachment_id: UUID) -> bytes:
        response = await self._client.get(
            f"/api/core/files/{attachment_id}",
            headers={"x-novvus-org": str(org_id)},
        )
        response.raise_for_status()
        return response.content

    async def delete_file(self, org_id: UUID, attachment_id: UUID) -> None:
        response = await self._client.delete(
            f"/api/core/files/{attachment_id}",
            headers={"x-novvus-org": str(org_id)},
        )
        response.raise_for_status()

    async def call_module(
        self,
        method: str,
        path: str,
        org_id: UUID,
        json: dict[str, Any] | None = None,
    ) -> httpx.Response:
        """Module→module call through the gateway (docs/MODULE_CONTRACT.md §4):
        service token + explicit tenant; the gateway injects the caller's
        declared service_permissions."""
        return await self._client.request(
            method,
            path,
            json=json,
            headers={"x-novvus-org": str(org_id)},
        )

    async def close(self) -> None:
        await self._client.aclose()


class AdminClient:
    """Sync client for CLI operations that act as a platform administrator."""

    def __init__(self, kernel_url: str, access_token: str) -> None:
        self._client = httpx.Client(
            base_url=kernel_url.rstrip("/"),
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=30.0,
        )

    def register_module(
        self, manifest_toml: str, migrations: list[dict[str, str]]
    ) -> dict[str, Any]:
        response = self._client.post(
            "/api/core/modules",
            json={"manifest_toml": manifest_toml, "migrations": migrations},
        )
        response.raise_for_status()
        result: dict[str, Any] = response.json()
        return result

    def lifecycle(self, module_id: str, action: str) -> dict[str, Any]:
        response = self._client.post(f"/api/core/modules/{module_id}/{action}", json={})
        response.raise_for_status()
        result: dict[str, Any] = response.json() if response.content else {}
        return result

    def close(self) -> None:
        self._client.close()
