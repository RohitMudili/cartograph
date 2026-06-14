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
├── config.py      settings + provider-agnostic model registry (single source of truth)
├── logging.py     structlog configuration
├── api/           HTTP routers (health, repos; more to come)
├── db/            engine/session, declarative base, health probe, migrations
├── indexer/       clone → parse → static graph + semantic layer
├── agents/        LLM wrapper + LangGraph agent fleet
└── query/         retrieval, routing, answering, citation verification
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
