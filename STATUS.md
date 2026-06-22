# Cartograph — Build Status

_Working log for picking up where we left off. Not the plan (see PLAN.md) — this
is "where are we right now and what's next."_

**Last updated:** 2026-06-22 (question-type-aware prompting shipped — the answerer now
detects 6 question types and tailors the system prompt + retrieval breadth per type)

---

## 🎉 Working product — backend spine, a usable Chat UI, and a real landing page

You can do the whole loop **in a browser**: land on a designed marketing page →
paste a repo → it's indexed → ask a question → get an answer grounded in real code
with VERIFIED `file:line` citations, in the dark "instrument panel" UI. Proven live
against Supabase. The core product value is working and clickable, and the front
door now sells it.

### Done & verified

**Frontend:**

- **Next.js 16 + React 19 + Tailwind v4** app in `frontend/`. DESIGN.md tokens
  wired (OKLCH instrument-panel palette, IBM Plex). Verified against the bundled
  Next 16 docs (params-as-Promise, `proxy.ts` not `middleware.ts`, etc.).
- **Landing page (`/`)** — a real brand surface, built with the taste/impeccable/
  emil-design-eng skills. Asymmetric split hero with a **living graph** behind it,
  a **live verified-citation terminal** that types an answer and resolves a
  citation from `checking` → `verified`, a connected Parse → Enrich → Answer
  pipeline, an economics strip (mono numerals on hairlines), and a magnetic CTA.
  No section-eyebrow grammar, no card grids, zero em-dashes. Verified at 390px and
  1440px via headless capture.
- **3D hero graph** — the hero graph is a restrained **React Three Fiber** scene
  (z-layered nodes, edges, amber important-nodes that glint, spring-damped pointer
  parallax). Lazy-loaded (`ssr:false`) so Three.js never touches SSR/LCP; falls
  back to the 2D canvas `GraphField` on mobile / coarse-pointer / reduced-motion /
  no-WebGL. This is the engine the future Mission Control traversal reuses.
- **The repo-paste flow lives in the hero** — paste a GitHub URL → index → route to
  chat. Honest errors (private 403, backend unreachable). Re-indexing an
  already-indexed repo is idempotent (returns instantly → straight to chat).
- **Google sign-in (Supabase Auth)** — optional sign-in via `@supabase/ssr`
  (browser + server clients, `proxy.ts` session refresh, `/auth/callback` PKCE
  exchange, POST `/auth/signout`, `AuthMenu` in the nav, `useUser` hook).
  Anonymous use stays the default; sign-in unlocks "my repos" + history.
  - **Frontend:** ✅ `AuthMenu`, sign-in/signout routes, session refresh all wired.
  - **Backend:** ✅ JWKS-based JWT validation (`backend/app/auth/jwt.py` via
    PyJWT — fetches public keys from Supabase's `/auth/v1/.well-known/jwks.json`,
    validates ES256 signatures). `owner_user_id` populated on repos + questions.
  - **RLS:** ✅ Per-user `SELECT` policies (0006) layer over the deny-all baseline
    — rows visible if `owner_user_id IS NULL OR owner_user_id = auth.uid()`.
  - **Operator setup:** `SUPABASE_JWT_SECRET` in `.env` (used as HMAC fallback;
    JWKS requires no additional config — project ref extracted from the JWT `iss`).
  - **UserProfile table** (migration 0007) — maps `owner_user_id` to optional
    `email` and `github_username`.
- **Chat console (`/r/[repo]/chat`)** — research-console UI: threaded Q&A, inline
  citation chips (verified=amber / unverified=rejected+strikethrough),
  transparency strip (route · N/M verified · nodes consulted), repo-status
  polling, live elapsed-time pending indicator (free-tier ~15s is paced, shown
  honestly). **Demoed live: a real onboarding question returned 3/3 verified
  citations.**
  - **Session sidebar** — left-side session list (w-64): "New chat" button, session
    list with first-question preview / message count / relative time, active session
    highlighting, click to switch sessions and load past questions, mobile hamburger
    toggle + backdrop overlay.
  - **Mandatory session_id + conversation_id** — every question is accompanied by
    both a `session_id` (groups questions into 1-hour chat sessions) and a
    `conversation_id` (unique per-turn UUID). Backend auto-creates sessions when
    missing; frontend captures them from the response.
  - **Redis session context** — last 5 Q&A pairs stored in Upstash Redis with 1-hour
    TTL. Injected as conversation history into the LLM prompt on subsequent questions.
- **"My repos" page (`/repos`)** — signed-in users see their indexed repos sorted
  by status (indexed first), each showing name, status chip, last question text,
  stats (nodes/edges/chunks/files), and indexed date. Three states: signed-out
  prompt, empty state, repo list. Visible "My repos" link in landing nav and chat
  header when signed in.

**Backend:**

- **Foundations** — FastAPI, async SQLAlchemy, health/readiness, Docker, CI.
- **Static indexer** — sandboxed cloner (private-repo fast-fail), tree-sitter
  Python extractor + a Markdown extractor (`.md` → `DOC` nodes by heading section,
  so READMEs/docs are indexed and retrievable), graph builder (cross-file
  imports/calls/inherits with confidence), pipeline + `POST /api/repos`.
  (psf/cachecontrol: 296 nodes.)
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
- **Question-type-aware prompting** — before retrieval, the answerer classifies the
  question into one of 6 types (onboarding / architecture / specific-symbol / how-to /
  comparison / general) using the cheap Flash-tier model. Retrieval breadth adjusts
  per type (8-15 items). The synthesis prompt is tailored to the detected type:
  onboarding leads with purpose → orientation → how to contribute; architecture
  focuses on component roles and data flow; specific-symbol goes straight to
  signature and call sites. All per-type prompts retain the grounded+citation
  constraints. Falls back to `general` on any error.
- **Rate limiter** — token-bucket paces calls to `LLM_RPM` (default 10) so we
  don't trip Gemini free-tier 429s.
- **Infra** — Supabase (async + pgbouncer fix), migrations at head **0009**
  (0006 plus `session_id` on questions in 0008, `conversation_id` on questions in 0009,
  `user_profiles` table in 0007), deny-all RLS + per-user RLS on repos/questions.
- **JWT library:** `PyJWT` (replaced `python-jose` which doesn't support EC keys
  needed for Supabase ES256 tokens). Use `PyJWK` for JWKS key construction.
- **Upstash Redis session store** — `app/session/store.py`: 1-hour TTL per session,
  last 5 Q&A pairs stored as conversation context. Every question gets both a
  `session_id` (groups into chat sessions) and a `conversation_id` (per-turn UUID),
  auto-created by the backend if not provided by the client.
- **Session endpoints** — `POST /api/repos/{id}/sessions` (create), `GET /api/repos/{id}/sessions` (list),
  `GET /api/repos/{id}/questions?session_id=` (filter by session).
- **UserProfile table** (migration 0007) — maps `owner_user_id` to optional `email`
  and `github_username` for future GitHub OAuth integration.

### Proven on real data

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
core is solid and there's now a real front door; the "full query intelligence +
streaming + agent fleet + the big graph UI views" is the bulk of remaining work.

### Backend  (answer-one-question core ~98% · full scope ~58%)

Query / answer layer:
- ❌ **Router** (local / global / escalate) — every question forces `local` today
- ❌ **Global route** — big-picture answers from community summaries
- ❌ **Escalation route + write-back** — the "graph is a learning cache" loop
- ✅ **Answer quality (task #20)** — markdown/README indexing ✅ DONE;
  question-type-aware prompting ✅ DONE (the answerer classifies questions into 6
  types and tailors the system prompt + retrieval breadth per type).

Indexing layer:
- ✅ **Markdown extractor** — `.md` files parse into `DOC` nodes by heading section
  (`parser/markdown.py`, wired into `EXTRACTORS`), so READMEs/docs feed retrieval.
- ❌ **Other docs / config extractors** (`.rst`, `.txt`, `.toml`, `.yaml`, etc. — not parsed)
- ❌ **TypeScript / JavaScript extractor** (v1 was meant to cover TS/JS too)
- ❌ **Community detection (Leiden) + hierarchical summaries** (GraphRAG big-picture layer)
- ❌ **Incremental re-indexing** (diff-based; today re-index = full re-run / skip-if-indexed)
- ⚠️ **Metrics** — LOC/fan-in/out done; git churn + graph centrality not computed

Auth / identity:
- ✅ **Google sign-in** — complete end-to-end. Frontend wired (Supabase Auth);
  backend validates Supabase JWT via JWKS (PyJWT, ES256/RS256). `owner_user_id`
  populated on repos + questions. RLS policies (0006) layer per-user SELECT over
  the deny-all baseline.
- ✅ **"My repos" / history UI** — `GET /api/repos` endpoint returns repos for the
  authenticated user. `frontend/app/repos/page.tsx` with signed-out/empty/list states.
  "My repos" link visible in landing nav and chat header. `owner_user_id`
  populated on all new repos and questions.
- ✅ **UserProfile table** — maps `owner_user_id` to optional `email` and
  `github_username` for future GitHub OAuth linking.
- ❌ **GitHub OAuth for private repos** (task #15 — designed §9A, not built)

Production shape:
- ❌ **Background worker + job queue** (indexing runs inline in the request today)
- ❌ **WebSocket event stream** (`/ws/runs/{id}`) — backbone for fleet + Mission Control
- ❌ **`agent_events` table + event bus** (persisted replay/stream log)
- ❌ **Graph-slice API** (`GET /repos/{id}/graph`) — what Atlas queries
- ❌ **Walkthrough generation** (`GET /repos/{id}/walkthrough`)
- ⚠️ **Budget caps** — LLM rate limiter done; per-run hard $ cap w/ graceful abort not wired

### Frontend  (~50%)

- ✅ App scaffold + design tokens
- ✅ **Landing page** (`/`) — full brand surface: hero, live verified-citation
  terminal, pipeline, economics, magnetic CTA. **Built and shipped.**
- ✅ **3D hero graph** (R3F) with 2D fallback + lazy-load. Reuses toward Mission Control.
- ✅ **Google sign-in (frontend)** — optional Supabase auth in the nav.
- ✅ **Index-a-repo flow** (now in the hero) · ✅ **Chat console** (working)
- ❌ **Mission Control** (`/r/[repo]/run`) — live agent roster, territory map, findings
  feed, cost ticker, replay scrubber. The visual centerpiece. Needs the event stream.
  (The R3F graph engine from the hero is the seed for its live graph.)
- ❌ **Atlas** (`/r/[repo]/atlas`) — force-directed / semantic-zoom graph + inspector
- ❌ **Code panel** — clicking a Chat citation chip should open source at the lines
- ❌ **Walkthrough view**
- ❌ **App shell** — icon rail + telemetry drawer (only a minimal Chat top bar + the
  landing nav exist)
- ✅ **"My repos" / history** — `GET /api/repos` + `frontend/app/repos/page.tsx`
  with signed-out/empty/list states. "My repos" link in landing nav and chat header.
- ✅ **Chat session sidebar** — left-side session list (w-64) with New Chat button,
  session previews, active session highlighting, past session loading. Every question
  has mandatory `session_id` + `conversation_id`.
- ✅ **Redis session store** — Upstash Redis with 1-hour TTL, last 5 Q&A pairs
  for conversation continuity.
- ❌ **Shared infra** — WebSocket event store (Zustand), replay-from-fixtures harness, Storybook
- ❌ **Hardening** — skeletons, error boundaries, full responsive/mobile pass beyond
  the landing, full a11y pass

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

**Overall v1 ≈ 58%.** Core value (cited Q&A) + auth identity + question-type-aware
prompting are now complete; the agent fleet + the live graph UI views are the single
biggest remaining chunk.

### Dependency gotchas (new, this session)
- **`python-jose` doesn't support EC JWK keys** — `jose.jwk.construct()` fails
  with `Unable to find an algorithm for key` for Supabase's ES256 keys. Use
  `PyJWT` + `PyJWK` instead (already done). Don't re-introduce `python-jose`.
- **Supabase JWKS URL** is `/auth/v1/.well-known/jwks.json`, NOT `/auth/v1/jwks`
  (which returns 401). The project ref is extracted from the JWT `iss` claim
  (`https://<ref>.supabase.co/auth/v1`) — no separate config needed.
- **`jwt.decode()` returns the payload, never the header** — use
  `jwt.get_unverified_header(token)` for header extraction. This was a real bug.

---

## Housekeeping / notes

- **🔑 ROTATE EXPOSED KEYS:** the Google + LangSmith keys, Supabase password, and
  the Supabase anon key appeared in the build chat. Gitignored (never committed)
  but rotate them. The anon key is a public client key by design, but rotating the
  whole set is cleanest.
- **Test data in Supabase:** indexing test runs left rows in there
  (benhoyt/pybktree + any `test/...` repos). Harmless; clean out before indexing
  repos you care about (cascade-deletes from the `repos` row).
- `.env` is configured + working (Supabase + Gemini + LangSmith). `frontend/.env.local`
  holds the real Supabase URL + anon key. Local dev DB = Supabase (needs internet);
  CI = throwaway Postgres (isolated).
- **`.gitignore` tracks `.env*.example` templates** but ignores real env files.
- `LLM_RPM` is the throughput knob — 10 for free tier, 1000+ for paid.
- **Backend gate before pushing:** `ruff check` + `ruff format --check` +
  `pyright` + `pytest -m "not network"` (the format check has bitten us twice).
- **Frontend gate before pushing:** `npx tsc --noEmit` + `npx eslint <changed>` +
  `npx next build`.
- **Merge straight to `main`** (owner's preference — no PRs).
