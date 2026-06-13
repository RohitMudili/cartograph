"""Shared test fixtures.

Two tiers:
- App/unit tests run against the ASGI app in-process via httpx (no DB, no network).
- DB integration tests use `db_session` against a live Postgres+pgvector (the
  docker-compose `db` service on port 5433, or TEST_DATABASE_URL). Each runs in a
  transaction rolled back afterwards, so the database is never mutated.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.main import create_app

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://cartograph:cartograph@localhost:5433/cartograph",
)


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    """Transactional session rolled back after each test (no data persists)."""
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
