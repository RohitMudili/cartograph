"""Health and readiness endpoints.

`/health` is a liveness probe (process is up). `/health/ready` is a readiness
probe (dependencies — the DB and pgvector — are actually usable). Orchestrators
should gate traffic on readiness, not liveness.
"""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app import __version__
from app.db.health import check_db_health
from app.db.session import get_session

router = APIRouter(tags=["health"])


class LivenessResponse(BaseModel):
    status: Literal["ok"]
    service: str
    version: str


class ReadinessResponse(BaseModel):
    status: Literal["ready", "degraded"]
    database: bool
    pgvector: bool
    server_version: str | None = None
    detail: str | None = None


@router.get("/health", response_model=LivenessResponse)
async def liveness() -> LivenessResponse:
    return LivenessResponse(status="ok", service="cartograph", version=__version__)


@router.get("/health/ready", response_model=ReadinessResponse)
async def readiness(
    response: Response,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ReadinessResponse:
    health = await check_db_health(session)
    ready = health.connected and health.pgvector
    if not ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return ReadinessResponse(
        status="ready" if ready else "degraded",
        database=health.connected,
        pgvector=health.pgvector,
        server_version=health.server_version,
        detail=health.error,
    )
