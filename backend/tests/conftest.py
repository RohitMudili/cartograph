"""Shared test fixtures.

Two tiers:
- App/unit tests run against the ASGI app in-process via httpx (no DB, no network).
- DB integration tests use `db_session` against an ISOLATED throwaway Postgres
  (CI's ephemeral service, or a sandbox you point TEST_DATABASE_URL at). Each runs
  in a transaction rolled back afterwards, so the DB is never mutated.

This is the ONE place a non-Supabase database is used, on purpose: the app and
local dev write to Supabase, but tests must never touch real data, and CI has no
Supabase access. `db`-marked tests therefore require TEST_DATABASE_URL to be set
to a disposable database — they will not silently fall back to anything.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.main import create_app

# No default: a sandbox/CI DSN must be provided explicitly so tests never reach
# the real Supabase DB. db-marked tests skip with a clear message if it's unset.
TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL", "")


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    """Transactional session rolled back after each test (no data persists).

    Requires TEST_DATABASE_URL (an isolated/disposable DB). If it's not set the
    db-marked test skips rather than risk connecting to the real Supabase DB.
    """
    if not TEST_DATABASE_URL:
        pytest.skip("TEST_DATABASE_URL not set (point it at a disposable Postgres for db tests)")
    engine = create_async_engine(TEST_DATABASE_URL)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.connect() as conn:
        trans = await conn.begin()
        session = maker(bind=conn)
        try:
            yield session
        finally:
            await session.close()
            await trans.rollback()
    await engine.dispose()
