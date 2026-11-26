"""Declarative model base. Every NovvusModel automatically carries:

- ``id``          UUIDv7 primary key (app-generated, time ordered)
- ``org_id``      tenant column, enforced by RLS (docs/MULTITENANCY.md)
- ``created_at`` / ``updated_at`` timestamps
- ``deleted_at``  soft-delete marker (auto-API filters it out)
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, ClassVar
from uuid import UUID

import uuid6
from sqlalchemy import DateTime, MetaData, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, mapped_column

_SNAKE_1 = re.compile(r"(.)([A-Z][a-z]+)")
_SNAKE_2 = re.compile(r"([a-z0-9])([A-Z])")


def snake_case(name: str) -> str:
    return _SNAKE_2.sub(r"\1_\2", _SNAKE_1.sub(r"\1_\2", name)).lower()


def new_uuid7() -> UUID:
    return uuid6.uuid7()


class NovvusModel(DeclarativeBase):
    """Base class for every module model.

    The table lives in the module schema (``mod_{id}``); the SDK pins the
    schema on the metadata when the module app is created.
    """

    __abstract__ = True

    metadata = MetaData()

    # Columns the platform owns; modules must not redefine them.
    SYSTEM_COLUMNS: ClassVar[frozenset[str]] = frozenset(
        {"id", "org_id", "created_at", "updated_at", "deleted_at", "ext", "custom"}
    )

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=new_uuid7)
    org_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    # Cross-module extension data (docs/EXTENSIONS.md): {extender: {field: value}}.
    # Only this module writes it, through the SDK's validated API surface.
    ext: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    # Per-organization custom fields (docs/CUSTOM_FIELDS.md): {field: value},
    # validated against the org's definitions in core.custom_fields.
    custom: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    @declared_attr.directive
    def __tablename__(cls) -> str:
        return snake_case(cls.__name__)

    @classmethod
    def resource_name(cls) -> str:
        """URL segment for the auto-API (override with __resource__)."""
        explicit: str | None = getattr(cls, "__resource__", None)
        if explicit:
            return explicit
        name = cls.__tablename__
        return name if name.endswith("s") else f"{name}s"

    def as_dict(self) -> dict[str, Any]:
        return {c.key: getattr(self, c.key) for c in self.__mapper__.column_attrs}
