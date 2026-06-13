# Cartograph — backend

FastAPI + LangGraph + Gemini service for multi-agent GraphRAG codebase
intelligence. See the repository root [`README.md`](../README.md) for the full
project overview and [`PLAN.md`](../PLAN.md) for the architecture.

## Quick start

```bash
uv sync --extra dev
uv run alembic upgrade head      # needs Postgres + pgvector (see ../docker-compose.yml)
uv run uvicorn app.main:app --reload
```

## Layout

```
app/
├── main.py        FastAPI app, lifespan, router wiring
├── config.py      settings + Gemini model registry (single source of truth)
├── logging.py     structlog configuration
├── api/           HTTP routers (health; more in later phases)
├── db/            engine/session, declarative base, health probe, migrations
├── indexer/       static analysis pipeline (Phase 2)
├── agents/        LangGraph agent fleet (Phase 3)
└── query/         retrieval, routing, answering, citation verification (Phase 4)
```

## Commands

| Command | Purpose |
|---|---|
| `uv run ruff check .` | lint |
| `uv run ruff format .` | format |
| `uv run pyright` | type check |
| `uv run pytest` | tests |
| `uv run alembic revision --autogenerate -m "..."` | new migration |
| `uv run alembic upgrade head` | apply migrations |
