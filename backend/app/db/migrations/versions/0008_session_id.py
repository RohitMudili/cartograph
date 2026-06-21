"""Add session_id column to questions table for chat sessions.

Revision ID: 0008
Revises: 0007
Create Date: 2026-06-21

Adds a nullable session_id column (UUID string) to the questions table so
questions can be grouped into chat sessions. The session itself lives in
Upstash Redis with a 1-hour TTL; the session_id in Postgres is the durable
reference for listing past sessions.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("questions", sa.Column("session_id", sa.String(length=36), nullable=True))
    op.create_index("ix_questions_session", "questions", ["session_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_questions_session", table_name="questions")
    op.drop_column("questions", "session_id")
