"""Enable RLS on questions + per-user isolation policies on repos and questions.

Migration 0004 enabled RLS (deny-all) on the original tables. This migration
adds the same protection to the `questions` table (added in 9baa59ec04d8) and
adds per-user SELECT policies on `repos` and `questions` so that authenticated
Supabase roles can see rows they own or that are unowned (anonymous).

Design:
- repos: users can SELECT repos WHERE owner_user_id IS NULL (anonymous) OR
  owner_user_id = auth.uid() (their own).
- questions: same pattern — anon sees all unowned questions, authenticated
  users also see their own.
- INSERT/UPDATE/DELETE are NOT granted via RLS — only the backend (which
  connects as postgres, BYPASSRLS) mutates data. The policies are strictly
  read-only for Supabase client roles, as defense-in-depth.

See PLAN.md §9B and migration 0004 for the RLS baseline rationale.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0006"
down_revision: str | None = "9baa59ec04d8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Tables that need RLS enabled (questions was created after 0004).
_RLS_TABLES = ["questions"]

# Per-user SELECT policies: users see their own rows + anonymous rows.
# The backend (postgres role, BYPASSRLS) is unaffected — these only gate
# direct Supabase client connections (defense-in-depth).
_REPO_POLICY = """
    CREATE POLICY user_repo_isolation ON repos
        FOR SELECT
        USING (owner_user_id IS NULL OR owner_user_id = auth.uid())
"""

_QUESTION_POLICY = """
    CREATE POLICY user_question_isolation ON questions
        FOR SELECT
        USING (owner_user_id IS NULL OR owner_user_id = auth.uid())
"""

# Supabase provides the auth schema with auth.uid() out of the box, but plain
# Postgres (e.g. CI's pgvector/pgvector:pg16 image) does not. We create the
# schema and a stub function so the RLS policies below don't fail with
# "schema auth does not exist". In Supabase these are no-ops.
_AUTH_BOOTSTRAP = """
    CREATE SCHEMA IF NOT EXISTS auth;
    DO $$
    BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM pg_proc p
            JOIN pg_namespace n ON p.pronamespace = n.oid
            WHERE n.nspname = 'auth' AND p.proname = 'uid'
        ) THEN
            CREATE FUNCTION auth.uid() RETURNS uuid
                LANGUAGE SQL STABLE
            AS $$ SELECT NULL::uuid; $$;
        END IF;
    END;
    $$
"""

# Named policies for clean downgrade.
_REPO_POLICY_NAME = "user_repo_isolation"
_QUESTION_POLICY_NAME = "user_question_isolation"


def upgrade() -> None:
    # Bootstrap the auth schema/uid() for environments (like CI) that don't have
    # Supabase's auth schema. Safe no-op in Supabase.
    op.execute(_AUTH_BOOTSTRAP)

    # Enable RLS on the questions table (defense-in-depth baseline).
    for table in _RLS_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")

    # Add per-user SELECT policies.
    op.execute(_REPO_POLICY)
    op.execute(_QUESTION_POLICY)


def downgrade() -> None:
    # Drop per-user policies first.
    op.execute(f"DROP POLICY IF EXISTS {_REPO_POLICY_NAME} ON repos")
    op.execute(f"DROP POLICY IF EXISTS {_QUESTION_POLICY_NAME} ON questions")

    # Disable RLS on tables added after 0004.
    for table in reversed(_RLS_TABLES):
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
