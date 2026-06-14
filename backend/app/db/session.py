"""Async SQLAlchemy engine and session management.

The engine is created lazily on first use and disposed on app shutdown (wired in
main.py's lifespan). Use `get_session` as a FastAPI dependency for request-scoped
sessions, or `session_scope` as an async context manager elsewhere.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import get_settings

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    """Return the process-wide async engine, creating it on first call."""
    global _engine, _sessionmaker
    if _engine is None:
        settings = get_settings()
        connect_args: dict = {}
        # Supabase's transaction pooler (pgbouncer, port 6543) does not support
        # prepared statements, which asyncpg uses by default — disable its
        # statement cache so connections through the pooler work. Harmless on a
        # direct Postgres connection (local docker), so we key off the pooler host.
        if "pooler.supabase.com" in settings.database_url:
            connect_args["statement_cache_size"] = 0
        _engine = create_async_engine(
            settings.database_url,
            pool_pre_ping=True,
            pool_size=10,
            max_overflow=20,
            echo=False,
            connect_args=connect_args,
        )
        _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False)
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    if _sessionmaker is None:
        get_engine()
    assert _sessionmaker is not None
    return _sessionmaker


async def dispose_engine() -> None:
    """Dispose the engine's connection pool. Called on app shutdown."""
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _sessionmaker = None


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """Transactional session context manager for use outside request handlers."""
    maker = get_sessionmaker()
    async with maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding a request-scoped session."""
    maker = get_sessionmaker()
    async with maker() as session:
        yield session
