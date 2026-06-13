"""Smoke tests for app wiring and the liveness endpoint."""

from __future__ import annotations

from httpx import AsyncClient

from app import __version__


async def test_liveness_ok(client: AsyncClient) -> None:
    resp = await client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"status": "ok", "service": "cartograph", "version": __version__}


async def test_openapi_served(client: AsyncClient) -> None:
    resp = await client.get("/openapi.json")
    assert resp.status_code == 200
    assert resp.json()["info"]["title"] == "Cartograph"
