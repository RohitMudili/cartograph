# AGENTS.md — Onboarding for AI Coding Agents

> **Read this first, fully, before writing any code.** It is written specifically
> so an AI agent (Cursor, Copilot, Codex, Aider, Claude, etc.) can become productive
> on this repo in one pass. It captures the non-obvious context — conventions,
> gotchas, and *why* things are built the way they are — that the code alone won't
> tell you.
>
> **Companion docs (read in this order):**
> 1. This file — how to work in the repo.
> 2. `STATUS.md` — **the single source of truth for "where are we / what's left."** Always check it.
> 3. `ARCHITECTURE.md` — **code-navigation map**: traces the indexing and Q&A flows
>    through the actual files. Read this to find where things live without reading everything.
> 4. `PLAN.md` — the full architecture and design rationale (long, authoritative).
> 5. `PRODUCT.md` / `DESIGN.md` / `FRONTEND.md` — product strategy, design system, frontend spec.

---

## 1. What this project is (30-second version)

**Cartograph** turns a GitHub repo into a knowledge graph and answers questions
about it with **verified `file:line` citations**. Paste a repo → it's cloned,
parsed (tree-sitter), summarized + embedded (LLM) → ask questions → get answers
grounded in real code, every citation *checked against the actual source* before
it's shown.

It's a **portfolio project** demonstrating SOTA AI-engineering depth (multi-agent
orchestration, GraphRAG, eval-driven quality). The differentiators are: visible
agent exploration, **adversarially-verified citations**, and an honest cost story.

**Current state:** the backend "ask a question, get a verified cited answer" core
works end-to-end and is proven on live data; a Chat UI exists; and there's now a
real **landing page** (with a 3D hero graph) plus **Google sign-in** (Supabase,
frontend only). The multi-agent fleet and the big graph/Mission-Control UI views
are not built yet. **`STATUS.md` has the exact itemized breakdown — read it.**

---

## 2. Architecture at a glance

Two phases: **expensive indexing once per repo, cheap queries forever after.**

```
INDEX:  clone (sandboxed) ─▶ tree-sitter parse ─▶ graph (nodes/edges/chunks in Postgres)
                                                      └▶ LLM summaries + pgvector embeddings
QUERY:  question ─▶ hybrid retrieval (BM25 + dense + graph) ─▶ LLM answer w/ citations
                                                                  └▶ VERIFY each citation vs source
```

- **One database: PostgreSQL + pgvector**, hosted on **Supabase** (dev + prod), a
  throwaway Postgres in CI. It does relational + vector + full-text(BM25 via tsvector)
  duty. Graph algorithms run in-process (NetworkX/igraph). **No Neo4j, no Pinecone** —
  deliberate; nothing at our scale needs them.
- **Provider-agnostic LLM** via LangChain `init_chat_model` — Gemini (default),
  OpenAI, Anthropic swappable with a `.env` string. Cost computed by **LangSmith**
  (we maintain *no* price tables) and stored in our DB.

---

## 3. Repo layout

```
cartograph/
├── AGENTS.md          ← you are here
├── STATUS.md          ← READ THIS: live "where we are / what's left"
├── PLAN.md            ← architecture + rationale (long, authoritative)
├── PRODUCT.md DESIGN.md FRONTEND.md   ← product/design/frontend specs
├── README.md          ← public-facing overview
├── docker-compose.yml ← Postgres(pgvector) + api for local dev
│
├── backend/           ← Python 3.12, FastAPI, uv-managed
│   ├── app/
│   │   ├── main.py          FastAPI app, lifespan, CORS, router wiring
│   │   ├── config.py        ★ settings + model registry (SINGLE SOURCE OF TRUTH)
│   │   ├── logging.py       structlog setup
│   │   ├── api/             HTTP routers: health.py, repos.py (index + questions)
│   │   ├── db/              session.py, base.py, models.py, enums.py, health.py, migrations/
│   │   ├── indexer/         cloner.py, pipeline.py, graph_builder.py, summarizer.py,
│   │   │                    communities.py (Leiden), parser/{python.py,markdown.py,types.py}
│   │   ├── agents/          llm.py (provider-agnostic LLM wrapper) + the enrichment
│   │   │                    FLEET: graph_def.py (supervisor), planner/explorer/
│   │   │                    synthesizer/critic/librarian, tools.py, schemas.py, events.py
│   │   ├── query/           retrieval.py, answerer.py, verifier.py, router.py
│   │   │                    (local/global/escalate), enrichment.py, escalation.py
│   │   └── api/             health.py, repos.py, events.py (agent-event replay + WS),
│   │                        graph.py (graph slice / file / walkthrough)
│   └── tests/          unit/ (no DB) + integration/ (db/network markers)
│
└── frontend/          ← Next.js 16, React 19, Tailwind v4, TypeScript
    ├── app/            layout.tsx, globals.css (design tokens), page.tsx (→ <Landing/>),
    │                   r/[repo]/chat/{page.tsx,ChatConsole.tsx},
    │                   auth/{callback,signout,auth-error}   ← Google sign-in routes
    ├── proxy.ts        ★ Next 16's renamed middleware — refreshes Supabase session
    ├── components/
    │   ├── ui.tsx           shared vocabulary (StatusChip, badges, Button)
    │   ├── landing/         Landing.tsx + GraphField(2D)/GraphField3D(R3F,cursor-follow)/
    │   │                    GraphFieldAuto, useMotionPreference (pause toggle),
    │   │                    VerifiedAnswer (live cite terminal), MagneticButton
    │   └── auth/AuthMenu.tsx   nav sign-in → account chip
    └── lib/
        ├── api.ts           typed backend client
        └── supabase/        client/server/middleware + useUser hook
```

---

## 4. ⚠️ CRITICAL GOTCHAS — read before you touch anything

These are the things that have actually bitten us. Internalize them.

### Backend
1. **Run the FULL gate before every commit/push** (the format check has been missed
   twice and broken CI):
   ```bash
   cd backend
   uv run ruff check .          # lint
   uv run ruff format --check . # FORMAT CHECK — easy to forget, CI enforces it
   uv run pyright               # types (must be 0 errors)
   uv run pytest -m "not network"   # tests
   ```
2. **ONE database, every environment: Supabase.** There is no local Postgres.
   The app and local dev both write to Supabase (set `DATABASE_URL` in
   `backend/.env`), so it **needs internet**. The *only* exception is the
   automated `db`-marked test suite, which runs against a disposable Postgres via
   `TEST_DATABASE_URL` (CI provides an ephemeral one) so tests never touch real
   data. Don't reintroduce a local dev DB or a docker-compose `db` service.
3. **Supabase + asyncpg needs the pgbouncer fix** — already handled in `db/session.py`
   (`statement_cache_size=0` when the URL contains `pooler.supabase.com`). Don't remove it.
4. **`DATABASE_URL` must use `postgresql+asyncpg://`** (async driver), not plain
   `postgresql://`. Supabase gives you the latter — change the scheme.
5. **Model IDs / pricing: never edit from memory.** They live ONLY in `config.py`
   with a dated comment. Verify current IDs against provider docs before changing.
6. **We maintain NO model price tables.** Cost comes from LangSmith (`run.total_cost`).
   If you see a hardcoded price dict, that's a regression — it was deliberately removed.
7. **Native Postgres enums** (`repo_status` etc.) store the Python enum **member
   NAMES (UPPERCASE)**, not `.value`. Adding an enum value needs an `ALTER TYPE ...
   ADD VALUE` migration (see `0003`). Reference the UPPERCASE label.
8. **Migrations are sequential** (`0001`..`0011`). After autogenerate, rename to the
   next number AND set `revision`/`down_revision` to match. Migration head is **0011**
   (`communities` table for Leiden clusters; 0010 added `agent_events`).
9. **The cloner deliberately blocks `file://` and disables git hooks** — security.
   Don't "fix" it to clone local paths; tests work around it via the local-dir path.
10. **`GIT_TERMINAL_PROMPT=0`** in the cloner is load-bearing — without it, a private
    repo clone *hangs* until timeout instead of failing fast. Keep it.

### Frontend
11. **This is Next.js 16 / React 19 / Tailwind v4 — NOT what your training data
    assumes.** `frontend/AGENTS.md` says it, and it's true. Key differences:
    - `params` in pages is a **`Promise`** — `await` it (`const { repo } = await params`).
    - Tailwind v4 uses **`@theme` in `globals.css`**, NOT a `tailwind.config.ts`.
    - **Read `frontend/node_modules/next/dist/docs/`** (bundled docs) before writing
      Next-specific code. They ship the real API for this exact version.
12. **Design tokens live in `globals.css` `@theme`** as OKLCH values (e.g. `--color-bg`,
    `--color-primary`). Use the token utility classes (`bg-bg`, `text-primary`, etc.),
    don't hardcode colors. The design language is "instrument panel at night" (dark,
    amber telemetry) — see `DESIGN.md`.
13. **Next 16 renamed `middleware.ts` → `proxy.ts`** (exports a `proxy` function, not
    `middleware`). Ours wires the Supabase session refresh. Don't recreate a
    `middleware.ts` — it won't run.
14. **The 3D hero is lazy + guarded.** `GraphField3D` (React Three Fiber) loads via
    `next/dynamic({ ssr: false })` so Three.js stays off SSR/LCP; `GraphFieldAuto`
    falls back to the 2D `GraphField` on mobile / coarse-pointer / reduced-motion /
    no-WebGL. Keep that gate — never import `GraphField3D` directly into a server
    component or unconditionally. The graph **follows the cursor** via a `window`-level
    pointer listener (NOT `useThree().pointer`): the graph layer is `pointer-events-none`
    so it never steals clicks, which means the canvas gets no mouse events of its
    own. A "Pause tracking" toggle (`useMotionPreference`, persisted to localStorage,
    reduced-motion-aware) stops only the cursor-follow — node blink keeps running.
    See `ARCHITECTURE.md` Flow 3 for the details.
15. **Reveal animations must degrade visible.** The hero intro animates transform +
    blur only (opacity stays 1) so content is legible without JS / mid-animation /
    on a frozen frame. Don't gate content visibility behind a JS-driven `opacity:0`
    entry (it shipped a blank hero once before this rule existed).
16. **Frontend gate:** `cd frontend && npx tsc --noEmit && npx eslint <changed> && npx next build`
    (verify visually too — headless screenshot the actual render; it has caught real
    bugs that code review missed).

### General
17. **`.env` files are gitignored and contain real secrets** — never commit them.
    Templates are `.env.example` (backend) and `.env.local.example` (frontend). The
    `.gitignore` tracks `.env*.example` (placeholders only) but ignores real env files.
18. **Verify external API shapes against official docs before coding** (LangChain,
    Gemini, Next.js, SQLAlchemy 2.0, Supabase, R3F). Versions here are current and
    differ from older training data. This habit has prevented many bugs in this repo.
19. **Don't put build-phase labels ("Phase 2/3") in code comments** — describe the
    subsystem instead. Phase language belongs in the planning docs only.
20. **`python-jose` doesn't support EC JWK keys** (Supabase's ES256 tokens).
    `jose.jwk.construct()` fails with `Unable to find an algorithm for key`.
    Use `PyJWT` + `PyJWK` instead — this is already done in `auth/jwt.py`.
    Do not re-introduce `python-jose`.
21. **Supabase JWKS URL** is `/auth/v1/.well-known/jwks.json`, NOT `/auth/v1/jwks`
    (401). The project ref is extracted from the JWT `iss` claim — no env var needed.
22. **In PyJWT, `jwt.decode()` returns the payload, never the header.**
    Use `jwt.get_unverified_header(token)` for header extraction.

---

## 5. How to run it

### Prereqs
- Python 3.12 + [`uv`](https://docs.astral.sh/uv/), Node 20+, Docker (for local test DB).
- API keys in `backend/.env` (copy `backend/.env.example`): a `GOOGLE_API_KEY`
  (Gemini), optionally `LANGSMITH_API_KEY` for real $ cost, and a Supabase
  `DATABASE_URL`. Frontend: copy `frontend/.env.local.example` → `.env.local`.

### Run both servers (two terminals)
```bash
# backend
cd backend && uv sync --extra dev && uv run uvicorn app.main:app --port 8000
# frontend
cd frontend && npm install && npm run dev      # http://localhost:3000
```
`benhoyt/pybktree` is already indexed in Supabase — pasting it on the home page
jumps straight to chat for an instant demo.

### Run the DB-backed tests locally
Tests must NOT hit Supabase — point `TEST_DATABASE_URL` at a disposable Postgres
(spin one up however you like; it's the one place a throwaway DB is used). Without
it, `db`-marked tests skip.
```bash
cd backend
docker run -d --name cg-testdb -p 5433:5432 \
  -e POSTGRES_USER=cartograph -e POSTGRES_PASSWORD=cartograph -e POSTGRES_DB=cartograph \
  pgvector/pgvector:pg16
export TEST_DATABASE_URL="postgresql+asyncpg://cartograph:cartograph@localhost:5433/cartograph"
DATABASE_URL="$TEST_DATABASE_URL" uv run alembic upgrade head   # migrate the sandbox
uv run pytest -m "not network"                                  # all but live-API tests
```

---

## 6. Throughput reality (important for any LLM work here)

**Gemini free tier ≈ 10 requests/minute.** The `LLM_RPM` setting + a token-bucket
rate limiter in `agents/llm.py` pace calls so we never 429 — but it means a question
takes ~15s and a big repo takes a long time to index. **A paid Gemini key (set
`LLM_RPM=1000`) makes it near-instant** (~$0.10 to index a mid-size repo). Small
repos work fine on free tier. Multi-key rotation was tried and reverted (Google
blocks it per-account). Don't re-attempt that.

---

## 7. Conventions

- **Python:** async everywhere (FastAPI + async SQLAlchemy 2.0 + asyncpg). Typed
  with `Mapped[...]`. ruff (lint+format) + pyright strict. Structured logging via
  structlog. Tenacity for retries.
- **Tests:** `unit/` (no DB/network), `integration/` (markers `db` and `network`).
  DB tests use a transactional `db_session` fixture that **rolls back** — they never
  mutate data permanently. LLM is mocked in tests with deterministic fakes; live-API
  tests are `network`-marked and auto-skip without a key.
- **Commits:** clear messages; **no `Co-Authored-By` trailer** (the owner wants sole
  attribution). Push only when asked. CI must be green.
- **One source of truth per concern:** model config → `config.py`; design tokens →
  `globals.css`; status vocabulary → `components/ui.tsx`; "what's left" → `STATUS.md`.

---

## 8. The data model (what's in Postgres)

`repos` → `nodes` (symbols: file/class/function/method, with summary + embedding +
verified `annotations` written by the fleet) → `edges` (contains/imports/calls/
inherits, confidence-scored) → `chunks` (source slices with exact line ranges +
tsvector + embedding) → `index_runs` (cost/tokens; kinds INDEX and ESCALATION) →
`questions` (Q&A history with route + citations) → `agent_events` (the fleet's
per-run event log) → `communities` (Leiden clusters + summaries). Every table is
active. Full schema + rationale: `PLAN.md §3` and `backend/app/db/models.py`.

The **chunk's exact line range is what makes citation verification mechanical** —
the verifier checks a claimed `file:line` snippet against the real chunk text.

---

## 9. What to build next (pointers)

`STATUS.md` has the itemized list. Done since this section was first written:
✅ Google sign-in end to end; ✅ answer quality (markdown indexing + question-type
prompting); ✅ the **multi-agent enrichment fleet** with the agent-event stream +
replay/WS API; ✅ **Mission Control** (`/r/[repo]/run`); ✅ the **query-intelligence
layer** — router (local/global/escalate with write-back), Leiden communities,
enrichment-grounded answers — plus the graph/file/walkthrough read APIs the big
UI views need. Remaining, in rough order:

1. **The big frontend views** — app shell (icon rail), **Atlas** (`/r/[repo]/atlas`:
   graph + inspector over `GET /graph`), the chat **code panel** (citation chip →
   `GET /file`), and the **walkthrough view** (`GET /walkthrough`). Also teach
   `lib/runState.ts` the new `communities` pipeline phase. (`FRONTEND.md §5.3`.)
2. **TypeScript extractor** (tree_sitter_typescript is already a dependency) and
   the **eval harness** (`evals/` — the credibility moat).
3. **GitHub OAuth for private repos** (`PLAN.md §9A`) — wiring + operator setup.
4. **Backend production shape** — a **durable** job queue/worker (indexing runs as
   an in-process background task via `start_index`; doesn't survive a restart),
   incremental re-index.
5. **Deploy + demo video + writeup.**

> **The agent fleet → WebSocket event stream → Mission Control UI are ONE connected
> feature** — none demos without the other two. The frontend is designed
> "replay-first" so it can build against recorded event-log fixtures before the live
> fleet exists.

---

## 10. When in doubt

- Check `STATUS.md` for current state.
- Read the relevant module's docstring — they're written to explain *why*, not just what.
- Verify external library APIs against their docs/bundled docs before writing code.
- Run the full gate before committing. Keep CI green.
- The existing code is the style guide — match it.
