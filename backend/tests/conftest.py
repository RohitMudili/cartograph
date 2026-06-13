"""Shared test fixtures.

Tests run against the ASGI app in-process via httpx's ASGITransport — no network,
no live server. The DB-dependent readiness path is tested separately (Phase 2
adds a Postgres-backed integration tier); these Phase 1 tests cover the app wiring
and liveness without requiring a database.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import create_app


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
