"""Enable the pgvector extension.

This is the bootstrap migration: the readiness probe (and the entire retrieval
layer) requires the `vector` extension. The graph-schema tables build on top of
this.

Revision ID: 0001
Revises:
Create Date: 2026-06-13
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")


def downgrade() -> None:
    op.execute("DROP EXTENSION IF EXISTS vector")
