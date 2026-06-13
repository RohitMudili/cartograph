"""API tests for the repos endpoints (HTTP surface).

Happy-path indexing is covered end-to-end in test_pipeline.py. Here we cover the
HTTP contract: validation, the disallowed-host 400, and the 404 path. DB-backed
cases override `get_session` with the transactional `db_session` fixture so they
share the rollback isolation and avoid the app's global engine.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.main import create_app

pytestmark = pytest.mark.db


@pytest.fixture
async def api_client(db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    """ASGI client whose DB dependency is the rolled-back test session."""
    app = create_app()

    async def _override() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_session] = _override
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


async def test_index_rejects_disallowed_host(api_client: AsyncClient) -> None:
    resp = await api_client.post("/api/repos", json={"url": "https://evil.example.com/x/y"})
    assert resp.status_code == 400
    assert "not allowed" in resp.json()["detail"].lower()


async def test_index_requires_url(api_client: AsyncClient) -> None:
    resp = await api_client.post("/api/repos", json={})
    assert resp.status_code == 422  # pydantic validation


async def test_get_unknown_repo_404(api_client: AsyncClient) -> None:
    resp = await api_client.get(f"/api/repos/{uuid.uuid4()}")
    assert resp.status_code == 404
