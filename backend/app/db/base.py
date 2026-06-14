"""Declarative base and shared column types.

Uses SQLAlchemy 2.0 typed declarative mapping (`Mapped` / `mapped_column`) so the
ORM models are fully type-checked by pyright. Concrete table models live in
`models.py`; this module defines the shared base and reusable mixins.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import DateTime, MetaData, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Explicit naming convention so Alembic autogenerate produces stable, named
# constraints (critical for reversible migrations — unnamed constraints can't be
# dropped cleanly across DBs).
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class TimestampMixin:
    """Adds DB-managed created/updated timestamps. Server-side `now()` so the DB
    is the single clock — avoids app/DB clock skew and works under replay."""

    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
