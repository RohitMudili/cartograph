"""Add 'summarizing' to repo_status enum.

The semantic layer (summaries + embeddings) adds a SUMMARIZING repo state between
PARSING and INDEXED. Postgres enums are extended with ALTER TYPE ... ADD VALUE.

Revision ID: 0003
Revises: 0002
Create Date: 2026-06-14
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Labels are stored as the Python enum MEMBER NAMES (uppercase) because
    # SQLAlchemy's Enum() uses names by default — so the value is 'SUMMARIZING',
    # inserted before 'INDEXED'. ADD VALUE can't run in a txn block on older PGs;
    # commit first. IF NOT EXISTS makes it idempotent.
    op.execute("COMMIT")
    op.execute("ALTER TYPE repo_status ADD VALUE IF NOT EXISTS 'SUMMARIZING' BEFORE 'INDEXED'")


def downgrade() -> None:
    # Postgres cannot drop a value from an enum without recreating the type.
    # The extra value is harmless if unused, so downgrade is a no-op (documented).
    pass
