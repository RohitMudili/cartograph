"""Add conversation_id column to questions table for per-turn Q&A tracking.

Revision ID: 0009
Revises: 0008
Create Date: 2026-06-21

Adds a nullable conversation_id column (UUID string) to the questions table.
The API always populates this on new questions; existing rows get NULL.
Once this is deployed and all active questions have been backfilled, the
column can be made NOT NULL.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("questions", sa.Column("conversation_id", sa.String(length=36), nullable=True))
    op.create_index("ix_questions_conversation", "questions", ["conversation_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_questions_conversation", table_name="questions")
    op.drop_column("questions", "conversation_id")
