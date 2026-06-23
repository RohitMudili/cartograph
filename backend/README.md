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
├── api/           HTTP routers: health, repos (index + questions), events (replay + WS)
├── db/            engine/session, declarative base, health probe, migrations (head 0010)
├── indexer/       clone → parse (tree-sitter Python + Markdown) → static graph + semantic layer
├── agents/        llm.py (LLM wrapper) + the enrichment fleet: graph_def (supervisor),
│                  planner/explorer/synthesizer/critic/librarian, tools, schemas, events
└── query/         retrieval (BM25 + dense + graph), answering, citation verification
```

> Status: the index → enrich (agent fleet) → cited-answer → verify core works end to
> end. The fleet (planner → parallel explorers → synthesizer → critic → librarian)
> runs during indexing and streams `agent_events`. Not yet built: the query router
> (local/global/escalate), Leiden communities, and the Mission Control UI that
> renders the stream. See [`../STATUS.md`](../STATUS.md) for the itemized breakdown.

## Commands

| Command | Purpose |
|---|---|
| `uv run ruff check .` | lint |
| `uv run ruff format .` | format |
| `uv run pyright` | type check |
| `uv run pytest` | tests |
| `uv run alembic revision --autogenerate -m "..."` | new migration |
| `uv run alembic upgrade head` | apply migrations |
