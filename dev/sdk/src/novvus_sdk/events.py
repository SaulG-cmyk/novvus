"""Event consumption with built-in idempotency (docs/EVENTS.md §4).

Deliveries arrive as POST /_novvus/events from the kernel dispatcher. The
handler and the processed-marker insert share one transaction: the handler
runs at most once per event even though transport is at-least-once."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

PROCESSED_TABLE = "_processed_events"


class Event(BaseModel):
    id: UUID
    org_id: UUID
    module_id: str
    event_type: str
    payload: dict[str, Any] = Field(default_factory=dict)
    occurred_at: datetime


EventHandler = Callable[[Event, AsyncSession], Awaitable[None]]


class EventRegistry:
    def __init__(self) -> None:
        self._handlers: dict[str, list[EventHandler]] = {}

    def on(self, event_type: str) -> Callable[[EventHandler], EventHandler]:
        def decorator(handler: EventHandler) -> EventHandler:
            self._handlers.setdefault(event_type, []).append(handler)
            return handler

        return decorator

    def handlers_for(self, event_type: str) -> list[EventHandler]:
        return self._handlers.get(event_type, [])

    async def replay(self, since: datetime | None = None) -> None:
        """Re-deliver this module's subscribed events from `since` (all of
        them when None). Signature frozen under ADR-001; the kernel side
        of the replay lands in fase G."""
        raise NotImplementedError("event replay is planned (ADR-001, fase G)")


async def mark_processed(session: AsyncSession, event_id: UUID) -> bool:
    """Record the event as processed. Returns False if it already was
    (duplicate delivery): the caller must skip the handlers."""
    result = await session.execute(
        text(
            f"INSERT INTO {PROCESSED_TABLE} (event_id) VALUES (:event_id) "
            "ON CONFLICT (event_id) DO NOTHING"
        ),
        {"event_id": event_id},
    )
    return result.rowcount == 1  # type: ignore[attr-defined,no-any-return]


PROCESSED_EVENTS_DDL = f"""
CREATE TABLE IF NOT EXISTS {PROCESSED_TABLE} (
    event_id uuid PRIMARY KEY,
    processed_at timestamptz NOT NULL DEFAULT now()
);
""".strip()
