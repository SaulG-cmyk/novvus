"""Chatter helper for module code (docs/CHATTER.md §6).

Programmatic system messages on this module's own records, and the tracking
hook the auto-API uses for `track = [...]` fields. Best-effort by design: a
chatter outage must never break the business operation.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any
from uuid import UUID

from novvus_sdk.context import current_context

if TYPE_CHECKING:
    from novvus_sdk.app import NovvusModule


class ChatterHelper:
    def __init__(self, module: NovvusModule) -> None:
        self._module = module

    async def post(
        self,
        model: str,
        record_id: UUID,
        body: str,
        kind: str = "system",
        meta: dict[str, Any] | None = None,
        org_id: UUID | None = None,
    ) -> dict[str, Any] | None:
        """Post a message on a record of THIS module. Returns None (with a
        warning) when the kernel is unreachable or in offline mode."""
        org = org_id or current_context().org_id
        kernel = self._module._kernel
        if kernel is None:
            logging.getLogger("novvus").warning(
                "offline mode: chatter message for %s/%s was not posted", model, record_id
            )
            return None
        try:
            return await kernel.post_chatter_message(
                org, self._module.id, model, record_id, body, kind=kind, meta=meta
            )
        except Exception:  # chatter must never break the business operation
            logging.getLogger("novvus").warning(
                "could not post chatter message for %s/%s", model, record_id
            )
            return None

    async def track_changes(
        self,
        model: str,
        record_id: UUID,
        changes: list[tuple[str, Any, Any]],
    ) -> None:
        """One system message per tracked field change (docs/CHATTER.md §6)."""
        for field, old, new in changes:
            await self.post(
                model,
                record_id,
                f"{field}: {old!r} → {new!r}",
                meta={"field": field, "old": old, "new": new},
            )
