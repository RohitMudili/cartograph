<div align="center">

# Cartograph

**Watch AI agents map your codebase.**

Paste a GitHub repo → a fleet of agents explores it live → you get an interactive
architecture map, a guided onboarding walkthrough, and a chat that answers
questions with verified `file:line` citations — at a fraction of the cost per
question after the first one.

</div>

---

> **🤖 AI agents / new contributors: start with [`AGENTS.md`](AGENTS.md).** It's
> written to get you productive in one read — conventions, gotchas, how to run it,
> and what's left. Then [`STATUS.md`](STATUS.md) for the live "where we are" log.

> **Status:** the backend "ask a question → get a verified cited answer" core works
> end-to-end (proven on live data); there's a working Chat UI, a designed **landing
> page** (with a restrained 3D hero graph), and **Google sign-in** (Supabase,
> frontend wired). The multi-agent fleet and the graph/Mission-Control views are not
> built yet — see [`STATUS.md`](STATUS.md) for the itemized breakdown. Architecture:
> [`PLAN.md`](PLAN.md); UI plan: [`FRONTEND.md`](FRONTEND.md); code-navigation map:
> [`ARCHITECTURE.md`](ARCHITECTURE.md); design/product: [`DESIGN.md`](DESIGN.md) /
> [`PRODUCT.md`](PRODUCT.md).

## How it works

Two phases: **expensive indexing once per repo, cheap queries forever after.**

1. **Static pass** — tree-sitter builds a structural knowledge graph (symbols +
   imports/calls/inheritance edges) with zero LLM cost.
2. **Agent enrichment** — a LangGraph fleet (planner → parallel explorers →
   synthesizer → critic) explores the repo and writes verified findings *into*
   the graph. Community detection + hierarchical summaries make big-picture
   questions cheap.
3. **Query time** — a router answers most questions from the persisted graph in
   seconds; only genuinely novel questions escalate to a live agent, whose
   findings are written back. The graph is a learning cache.

Every answer carries `file:line` citations verified against the actual source
before display.

## Tech

**Backend:** Python 3.12 · FastAPI · async SQLAlchemy 2.0 · LangChain
(`init_chat_model`, provider-agnostic) · LangGraph · Google Gemini · Postgres +
pgvector (Supabase) · tree-sitter · LangSmith (cost).

**Frontend:** Next.js 16 · React 19 · Tailwind v4 · TypeScript · Motion ·
React Three Fiber (3D hero) · Supabase Auth (Google sign-in) · IBM Plex.

## Local development

```bash
cp backend/.env.example backend/.env     # add your GEMINI_API_KEY
docker compose up --build                # Postgres + API at :8000
```

Or run the API directly against a local Postgres:

```bash
cd backend
uv sync --extra dev
uv run alembic upgrade head
uv run uvicorn app.main:app --reload
```

Health check: `GET http://localhost:8000/health` (liveness),
`GET /health/ready` (DB + pgvector readiness).

## Development commands

```bash
cd backend
uv run ruff check .          # lint
uv run ruff format .         # format
uv run pyright               # type check
uv run pytest                # tests
```
