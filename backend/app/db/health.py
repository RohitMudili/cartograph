"""Database health probing, including pgvector availability.

The health check is deliberately specific: it confirms not just connectivity but
that the `vector` extension is installed, since the whole retrieval layer depends
on it. A green health check means "the DB can actually serve Cartograph", not
merely "a socket opened".
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True, slots=True)
class DbHealth:
    connected: bool
    pgvector: bool
    server_version: str | None = None
    error: str | None = None


async def check_db_health(session: AsyncSession) -> DbHealth:
    """Probe connectivity + pgvector. Never raises; returns a structured result."""
    try:
        version = (await session.execute(text("SHOW server_version"))).scalar_one()
        has_vector = (
            await session.execute(
                text("SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector')")
            )
        ).scalar_one()
        return DbHealth(
            connected=True,
            pgvector=bool(has_vector),
            server_version=str(version),
        )
    except Exception as exc:  # noqa: BLE001 — health must never propagate
        return DbHealth(connected=False, pgvector=False, error=str(exc))
