"""Tenant-scoped database access.

The SDK never hands out a raw connection: every session lives inside a
transaction that first pins ``app.org_id`` with ``SET LOCAL`` (via
``set_config(..., true)``), so RLS applies and nothing leaks across pooled
connections (docs/MULTITENANCY.md §3)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


def to_async_dsn(dsn: str) -> str:
    """Normalize a postgres:// DSN to SQLAlchemy's async psycopg dialect."""
    for prefix in ("postgresql+psycopg://", "postgresql://", "postgres://"):
        if dsn.startswith(prefix):
            return "postgresql+psycopg://" + dsn.removeprefix(prefix)
    return dsn


class Database:
    def __init__(self, dsn: str, schema: str) -> None:
        self.schema = schema
        self.engine: AsyncEngine = create_async_engine(
            to_async_dsn(dsn),
            pool_size=5,
            max_overflow=5,
            # Pin search_path so unqualified names resolve inside the module
            # schema only.
            connect_args={"options": f"-csearch_path={schema}"},
        )
        self._sessions = async_sessionmaker(self.engine, expire_on_commit=False)

    @asynccontextmanager
    async def tenant_session(self, org_id: UUID) -> AsyncIterator[AsyncSession]:
        """A transaction bound to one tenant. Commits on success."""
        async with self._sessions() as session, session.begin():
            await session.execute(
                text("SELECT set_config('app.org_id', :org, true)"),
                {"org": str(org_id)},
            )
            yield session

    async def dispose(self) -> None:
        await self.engine.dispose()
