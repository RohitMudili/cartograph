"""Enable RLS on user_profiles and alembic_version.

Closes the two Supabase security-advisor findings: both tables live in the
`public` schema (exposed through PostgREST) but were created without RLS —
`user_profiles` in 0007, `alembic_version` by Alembic itself. Plain ENABLE
(not FORCE), matching the 0004 deny-all baseline: the backend's `postgres`
role owns the tables and bypasses RLS, so the app and Alembic are unaffected
while anon-key API clients are denied.

Revision ID: 0012
Revises: 0011
Create Date: 2026-07-12
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE user_profiles ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE alembic_version ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.execute("ALTER TABLE alembic_version DISABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE user_profiles DISABLE ROW LEVEL SECURITY")
