"""Add communities table — the GraphRAG clustering layer.

Leiden partitions each repo's structural graph into communities; the global
query route answers big-picture questions from their summaries (PLAN.md §2.2
step 3, §2.3). Single-level for v1.

Revision ID: 0011
Revises: 0010
Create Date: 2026-06-25
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "communities",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("repo_id", sa.UUID(), nullable=False),
        sa.Column("level", sa.Integer(), server_default="0", nullable=False),
        sa.Column("key", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("node_ids", postgresql.JSONB(), server_default=sa.text("'[]'"), nullable=False),
        sa.Column("size", sa.Integer(), server_default="0", nullable=False),
        sa.ForeignKeyConstraint(
            ["repo_id"], ["repos.id"], name=op.f("fk_communities_repo_id"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_communities")),
        sa.UniqueConstraint("repo_id", "level", "key", name="uq_communities_repo_level_key"),
    )
    op.create_index("ix_communities_repo", "communities", ["repo_id"])

    # RLS deny-all floor, matching migration 0004 (plain ENABLE, not FORCE — the
    # backend `postgres` role bypasses RLS; FORCE risks a lockout).
    op.execute("ALTER TABLE communities ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.drop_index("ix_communities_repo", table_name="communities")
    op.drop_table("communities")
