"""Enable RLS (deny-all) on all tables — defense in depth.

Cartograph's database is reached ONLY by the backend via the service-role
connection, which bypasses RLS — so the app is unaffected. Enabling RLS with no
permissive policy means that if the Supabase anon/public key is ever used to
connect directly (it isn't today, but defense in depth), it gets ZERO access.

This also clears Supabase's "Unrestricted" dashboard warning.

When per-user auth lands (the GitHub-OAuth phase), real ownership policies
(`USING (owner_id = auth.uid())`) are added on top of this baseline — but the
deny-by-default floor stays.

Revision ID: 0004
Revises: 0003
Create Date: 2026-06-15
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# All application tables. alembic_version is Alembic's own bookkeeping — leave it
# alone (migrations run as the owner, which bypasses RLS regardless).
_TABLES = ["repos", "nodes", "edges", "chunks", "index_runs"]


def upgrade() -> None:
    # ENABLE RLS with no policy = deny-all for roles subject to RLS (anon,
    # authenticated). Our backend connects as `postgres`, which has BYPASSRLS,
    # so it is unaffected — verified before writing this migration.
    #
    # We deliberately do NOT use FORCE ROW LEVEL SECURITY: `postgres` already
    # bypasses RLS via its BYPASSRLS attribute (which takes precedence over
    # FORCE), so FORCE would add no protection here while risking a lockout if
    # the connection role's config ever changes. Plain ENABLE is the right floor.
    for table in _TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    for table in _TABLES:
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
