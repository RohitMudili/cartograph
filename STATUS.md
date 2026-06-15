# Cartograph — Build Status

_Working log for picking up where we left off. Not the plan (see PLAN.md) — this
is "where are we right now and what's next."_

**Last updated:** 2026-06-15 (end of session — dev servers stopped, clean checkpoint)

---

## 🎉 Working product — backend spine + a usable UI

You can now do the whole loop **in a browser**: paste a repo → it's indexed → ask
a question → get an answer grounded in real code with VERIFIED `file:line`
citations, in the dark "instrument panel" UI. Proven live against Supabase. The
core product value is working and clickable.

### Done & verified

**Frontend (this session):**

- **Next.js 16 + React 19 + Tailwind v4** app in `frontend/`. DESIGN.md tokens
  wired (OKLCH instrument-panel palette, IBM Plex). Verified against the bundled
  Next 16 docs (params-as-Promise etc.).
- **Home (`/`)** — paste a GitHub URL → index → route to chat. Honest errors
  (private 403, backend unreachable). Re-indexing an already-indexed repo is
  idempotent (returns instantly → straight to chat).
- **Chat console (`/r/[repo]/chat`)** — research-console UI: threaded Q&A, inline
  citation chips (verified=amber / unverified=rejected+strikethrough),
  transparency strip (route · N/M verified · nodes consulted), repo-status
  polling, live elapsed-time pending indicator (free-tier ~15s is paced, shown
  honestly). **Demoed live: a real onboarding question returned 4/4 verified
  citations across multiple files.**

**Backend:**

- **Foundations** — FastAPI, async SQLAlchemy, health/readiness, Docker, CI.
- **Static indexer** — sandboxed cloner (private-repo fast-fail), tree-sitter
  Python extractor, graph builder (cross-file imports/calls/inherits with
  confidence), pipeline + `POST /api/repos`. (psf/cachecontrol: 296 nodes.)
- **Provider-agnostic LLM** — LangChain `init_chat_model`; Gemini/OpenAI/Anthropic
  swappable via `.env`. Cost via **LangSmith** (no hardcoded prices), our DB.
- **Semantic layer** — bottom-up summaries + pgvector embeddings; gated on
  `llm_available` (skips cleanly with no key).
- **Hybrid retrieval** — BM25 (chunk `tsv`) + dense (pgvector) + 1-hop graph
  expansion, fused with reciprocal-rank fusion. `RetrievedItem` carries exact
  `file:line` for citations.
- **Cited Q&A + citation verification** ← the differentiator. Answer synthesized
  from retrieved context only, every citation checked against indexed source;
  hallucinated citations are caught + stripped (one regen attempt first), never
  shown as verified. `POST /api/repos/{id}/questions`.
- **Rate limiter** — token-bucket paces calls to `LLM_RPM` (default 10) so we
  don't trip Gemini free-tier 429s.
- **Infra** — Supabase (async + pgbouncer fix), migrations at head **0005**,
  deny-all RLS on all tables (backend = `postgres`/BYPASSRLS, unaffected).

### Proven on real data (2026-06-15)

Indexed benhoyt/pybktree live (Gemini + Supabase, no 429s). Then asked it real
questions through the full retrieve→synthesize→verify chain:

- *"What does hamming_distance do?"* → correct answer, **VERIFIED** cite to
  `pybktree.py:22-29`.
- *"How does BKTree add items and search for nearby matches?"* → accurate
  two-method explanation incl. the pruning logic, **2 VERIFIED** citations.

### Tests: backend 46 passing, CI green. Frontend: tsc + eslint + build clean.

### Run it locally (two terminals)

```bash
# backend  (needs backend/.env with Supabase + Gemini keys)
cd backend && uv run uvicorn app.main:app --port 8000
# frontend (needs frontend/.env.local — copy from .env.local.example)
cd frontend && npm run dev    # → http://localhost:3000
```

pybktree is already indexed in Supabase, so pasting
`https://github.com/benhoyt/pybktree` jumps straight to chat for an instant demo.
_(Dev servers are currently STOPPED.)_

---

## ⚠️ Throughput note (not a blocker)

**Gemini free tier ≈ 10 RPM** — fine for small repos (pybktree indexed in ~65s),
too slow for big ones (~427-symbol repo ≈ 43 min). Multi-key rotation was tried
and reverted (Google blocks per-account). **A paid Gemini key is the fix:** set it
in `.env` and bump `LLM_RPM=1000` for full-speed indexing (~$0.10/mid-size repo).
Until then, develop/test on small repos — fully unblocked.

---

## What's left — detailed, by area

Honest accounting (✅ done · ⚠️ partial · ❌ not built). The "answer one question"
core is solid; the "full query intelligence + streaming + agent fleet + the big
UI views" is the bulk of remaining work.

### Backend  (answer-one-question core ~95% · full scope ~50%)

Query / answer layer:
- ❌ **Router** (local / global / escalate) — every question forces `local` today
- ❌ **Global route** — big-picture answers from community summaries
- ❌ **Escalation route + write-back** — the "graph is a learning cache" loop
- ❌ **Answer quality (task #20)** — markdown/README indexing + question-type prompts

Indexing layer:
- ❌ **Markdown / docs / config extractors** (Python-only today — no README indexed)
- ❌ **TypeScript / JavaScript extractor** (v1 was meant to cover TS/JS too)
- ❌ **Community detection (Leiden) + hierarchical summaries** (GraphRAG big-picture layer)
- ❌ **Incremental re-indexing** (diff-based; today re-index = full re-run / skip-if-indexed)
- ⚠️ **Metrics** — LOC/fan-in/out done; git churn + graph centrality not computed

Production shape:
- ❌ **Background worker + job queue** (indexing runs inline in the request today)
- ❌ **WebSocket event stream** (`/ws/runs/{id}`) — backbone for fleet + Mission Control
- ❌ **`agent_events` table + event bus** (persisted replay/stream log)
- ❌ **Graph-slice API** (`GET /repos/{id}/graph`) — what Atlas queries
- ❌ **Walkthrough generation** (`GET /repos/{id}/walkthrough`)
- ❌ **GitHub OAuth** (task #15 — designed §9A, not built)
- ⚠️ **Budget caps** — LLM rate limiter done; per-run hard $ cap w/ graceful abort not wired

### Frontend  (~38%)

- ✅ App scaffold + design tokens · ✅ Home (paste-a-repo) · ✅ Chat console (working)
- ❌ **Mission Control** (`/r/[repo]/run`) — live agent roster, territory map, findings
  feed, cost ticker, replay scrubber. The visual centerpiece. Needs the event stream.
- ❌ **Atlas** (`/r/[repo]/atlas`) — force-directed / semantic-zoom graph + inspector
- ❌ **Code panel** — clicking a Chat citation chip should open source at the lines
- ❌ **Walkthrough view** · ❌ **Landing page** (brand surface; `/` is the app home today)
- ❌ **App shell** — icon rail + telemetry drawer (only a minimal Chat top bar exists)
- ❌ **Shared infra** — WebSocket event store (Zustand), replay-from-fixtures harness, Storybook
- ❌ **Hardening** — skeletons, error boundaries, responsive/mobile, full a11y pass

### Agent fleet  (0% — all spec, no code)

The whole PLAN §2.2 topology is unbuilt. Foundation exists (`langgraph` installed,
provider-agnostic `llm.py` ready), but none of the fleet itself:
- ❌ LangGraph supervisor graph (planner → explorers → synthesizer → critic → librarian)
- ❌ Planner / Explorer (parallel) / Synthesizer / Critic agents
- ❌ Librarian (writes verified findings back to the graph)
- ❌ Agent tools (`read_file` / `get_neighbors` / `search_graph` / `grep`)
- ❌ Inter-agent Pydantic schemas · run budgets (tool-call caps, token budget, timeouts)
- ❌ Event emission → event log → WebSocket → Mission Control

> **Key dependency:** agent fleet → event stream (backend) → Mission Control (frontend)
> are **one connected feature** — none demos without the other two. Replay-first design
> lets the UI build against recorded event logs first, but the fleet still must be built.

### Cross-cutting
- ❌ **Eval harness** — golden Q&A + citation precision/recall + answer-quality scoreboard
  (credibility moat; also grades task #20)
- ❌ **Deploy + demo video + writeup**

**Overall v1 ≈ 45-50%.** Core value (cited Q&A) is demoable in the browser today;
the agent fleet is the single biggest remaining chunk.

---

## Housekeeping / notes

- **🔑 ROTATE EXPOSED KEYS:** the Google + LangSmith keys and Supabase password
  appeared in the build chat. Gitignored (never committed) but rotate them.
- **Test data in Supabase:** indexing test runs left rows in there
  (benhoyt/pybktree + any `test/...` repos). Harmless; clean out before indexing
  repos you care about (cascade-deletes from the `repos` row).
- `.env` is configured + working (Supabase + Gemini + LangSmith). Local dev DB =
  Supabase (needs internet); CI = throwaway Postgres (isolated).
- `LLM_RPM` is the throughput knob — 10 for free tier, 1000+ for paid.
- **Run the FULL gate before pushing:** `ruff check` + `ruff format --check` +
  `pyright` + `pytest -m "not network"` (the format check has bitten us twice).
