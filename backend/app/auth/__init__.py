"""Authentication — Supabase JWT validation for the backend half of Google sign-in.

Every user-facing endpoint remains anonymous-friendly: the auth dependency returns
None when no valid JWT is present. Sign-in only enables per-user ownership
persistence (owner_user_id on repos/questions) and future "my repos"/history UI.
See PLAN.md §9B.
"""
