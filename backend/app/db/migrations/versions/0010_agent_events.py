"""Add agent_events table and 'enriching' repo_status value.

The enrichment fleet (PLAN.md §2.2) publishes a stream of events as it works —
the Mission Control feed and the replay/debug log. `agent_events` stores them
append-only with a per-run monotonic `seq` for gap-free reconnect.

Also adds an ENRICHING value to repo_status, the state a repo is in while the
fleet explores/annotates its graph (between SUMMARIZING and INDEXED).

Revision ID: 0010
Revises: 0009
Create Date: 2026-06-24
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Enum value uses the Python MEMBER NAME (uppercase), inserted before INDEXED.
    # ADD VALUE can't run in a txn block on older PGs; commit first. Idempotent.
    op.execute("COMMIT")
    op.execute("ALTER TYPE repo_status ADD VALUE IF NOT EXISTS 'ENRICHING' BEFORE 'INDEXED'")

    op.create_table(
        "agent_events",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("run_id", sa.UUID(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column(
            "ts", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("agent", sa.String(length=32), nullable=False),
        sa.Column("type", sa.String(length=32), nullable=False),
        sa.Column("payload", postgresql.JSONB(), server_default=sa.text("'{}'"), nullable=False),
        sa.ForeignKeyConstraint(
            ["run_id"], ["index_runs.id"], name=op.f("fk_agent_events_run_id"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agent_events")),
        sa.UniqueConstraint("run_id", "seq", name="uq_agent_events_run_seq"),
    )
    op.create_index("ix_agent_events_run_seq", "agent_events", ["run_id", "seq"])

    # RLS deny-all floor, matching migration 0004: plain ENABLE with no policy
    # (NOT FORCE — the backend `postgres` role bypasses RLS, and FORCE risks a
    # lockout). Events reach clients only via the API/WS layer, which scopes by
    # repo ownership.
    op.execute("ALTER TABLE agent_events ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.drop_index("ix_agent_events_run_seq", table_name="agent_events")
    op.drop_table("agent_events")
    # Postgres cannot drop an enum value without recreating the type; the unused
    # ENRICHING value is harmless, so this is a documented no-op (matches 0003).
