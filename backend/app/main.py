"""FastAPI application entry point.

Wires structured logging, the lifespan (engine disposal on shutdown), CORS for
the local frontend, and the API routers. Run with:

    uv run uvicorn app.main:app --reload
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api import health, repos
from app.config import get_settings
from app.db.session import dispose_engine, get_engine
from app.logging import configure_logging

log = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    settings = get_settings()
    get_engine()  # eager-create so connection errors surface at startup
    log.info("cartograph.startup", env=settings.cartograph_env, version=__version__)
    try:
        yield
    finally:
        await dispose_engine()
        log.info("cartograph.shutdown")


def create_app() -> FastAPI:
    app = FastAPI(
        title="Cartograph",
        version=__version__,
        summary="Watch AI agents map your codebase.",
        lifespan=lifespan,
    )

    # Local frontend dev server (Next.js). Tighten / env-drive before any deploy.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health.router)
    app.include_router(repos.router)
    return app


app = create_app()
