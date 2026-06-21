"""Add user_profiles table and claim anonymous repos.

Revision ID: 0007
Revises: 0006
Create Date: 2026-06-21

Adds a user_profiles table that maps a Supabase user UUID (owner_user_id) to
optional email and GitHub username fields. Both are optional because a user
might sign in with Google first (email populated) and later authenticate GitHub
(github_username populated), or vice versa.

Also claims any repos with owner_user_id IS NULL for the first known user.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# The user's Supabase UUID — repos with NULL owner_user_id are claimed to this user.
_USER_UUID = "f8ec6ad7-7e76-418a-ba47-7bca06e110e7"


def upgrade() -> None:
    # Create the user_profiles table.
    op.create_table(
        "user_profiles",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("owner_user_id", sa.UUID(), nullable=False, unique=True, index=True),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column("github_username", sa.String(length=255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_user_profiles")),
    )

    # Create a user profile row for the known user (email populated later from JWT).
    op.execute(
        f"INSERT INTO user_profiles (id, owner_user_id) VALUES "
        f"(gen_random_uuid(), '{_USER_UUID}'::uuid)"
    )

    # Claim all currently unowned repos to this user.
    op.execute(f"UPDATE repos SET owner_user_id = '{_USER_UUID}'::uuid WHERE owner_user_id IS NULL")


def downgrade() -> None:
    # Note: we do NOT unclaim repos here because we can't distinguish between
    # repos that were originally NULL (claimed by this migration) and repos
    # the user indexed after signing in (intentionally owned). The
    # user_profiles table is dropped, but ownership of repos is preserved.
    op.drop_table("user_profiles")
