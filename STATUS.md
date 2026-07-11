# Cartograph — Build Status

_Working log for picking up where we left off. Not the plan (see PLAN.md) — this
is "where are we right now and what's next."_

**Last updated:** 2026-07-12 (**frontend views milestone**: app shell icon rail
across `/r/[repo]/*`; **Atlas** — community-colored force-layout graph canvas +
search + community spotlight + inspector with "Ask about this"/"Open code";
**code panel** — chat citation chips and Atlas both open the indexed source with
the cited lines highlighted; **walkthrough view** — the synthesizer's onboarding
steps as quiet prose deep-linking into Atlas; `/r/[repo]` status-aware redirect;
the run view knows the new `communities` phase. Backend: migration **0012**
(RLS on `user_profiles` + `alembic_version`, closing the Supabase advisor
findings) — applied to live Supabase. Earlier: the query-intelligence milestone —
the router routes local/global/escalate (RepoModel + Leiden community summaries
ground big-picture answers; unanswerable questions spawn one scoped explorer whose
critic-verified findings are WRITTEN BACK — the learning-cache loop is live),
Leiden clustering as a pipeline phase (0011), verified annotations in every
answer's context, and the `GET /graph` / `GET /file` / `GET /walkthrough` APIs.
Earlier still: paste → live-mapping flow; Mission Control; the agent fleet with
agent_events stream + replay/WS API. Backend tested green: 71 passing.)

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
- **Query router (local / global / escalate)** — `query/router.py` is now the single
  entry point behind `POST /questions`. Architecture/onboarding questions take the
  **global route** when repo-level knowledge exists (the synthesizer's RepoModel +
  Leiden community summaries are injected as a background-knowledge block). When the
  first pass is unanswerable and an LLM is available, the **escalation route**
  (`query/escalation.py`) spawns ONE scoped explorer, runs the critic over its
  findings, writes accepted ones back to `Node.annotations` (attributed
  `explorer:escalation`, under an `ESCALATION` IndexRun), and answers once more —
  the graph is a learning cache, live. The route label rides on the persisted
  Question for the UI transparency strip.
- **Enrichment feeds answers** — `query/enrichment.py` loads the RepoModel, verified
  per-node annotations, and community summaries; the answerer merges verified
  annotations on retrieved nodes into EVERY route's context, and can answer from
  enrichment alone when retrieval comes back empty (big-picture questions no longer
  depend on the right 10 chunks surfacing).
- **Leiden community detection** — `indexer/communities.py` clusters the structural
  graph (igraph + leidenalg, seeded, weighted by edge kind: CALLS 1.0 … TESTS 0.4,
  CONTAINS excluded) as a `communities` pipeline phase after summarizing; persists
  largest-first as `c0`, `c1`, … with optional Flash-written titles/summaries
  (gated on `llm_available`, stops at the first LLM failure to protect quota).
  Migration head is now **0011** (`communities` table).
- **Graph-facing read APIs** (`api/graph.py`) — what Atlas / the code panel / the
  walkthrough view will consume: `GET /api/repos/{id}/graph?max_nodes=` (degree-ranked
  node slice + edges + community membership), `GET /api/repos/{id}/file?path=`
  (source reconstructed from indexed chunks — no re-clone), and
  `GET /api/repos/{id}/walkthrough` (the RepoModel's onboarding steps; 404 with a
  reason until enrichment has produced one).
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
- **Infra** — Supabase (async + pgbouncer fix), migrations at head **0012**
  (0010 `agent_events`, 0011 `communities`, 0012 RLS on `user_profiles` +
  `alembic_version`), deny-all RLS + per-user RLS on repos/questions.
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

### Tests: backend 71 passing, CI green. Frontend: tsc + eslint + build clean.

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

### Backend  (answer-one-question core ~100% · full scope ~80%)

Query / answer layer:
- ✅ **Router** (local / global / escalate) — `query/router.py`, wired into
  `POST /questions`; route label persisted on the Question
- ✅ **Global route** — RepoModel + Leiden community summaries injected as
  background knowledge for architecture/onboarding questions
- ✅ **Escalation route + write-back** — one scoped explorer → critic → verified
  findings written to `Node.annotations` → re-answer. The learning-cache loop, live.
- ✅ **Enrichment in answers** — verified annotations merge into every route's
  context; enrichment alone can answer when retrieval comes back empty
- ✅ **Answer quality (task #20)** — markdown/README indexing ✅ DONE;
  question-type-aware prompting ✅ DONE (the answerer classifies questions into 6
  types and tailors the system prompt + retrieval breadth per type).

Indexing layer:
- ✅ **Markdown extractor** — `.md` files parse into `DOC` nodes by heading section
  (`parser/markdown.py`, wired into `EXTRACTORS`), so READMEs/docs feed retrieval.
- ❌ **Other docs / config extractors** (`.rst`, `.txt`, `.toml`, `.yaml`, etc. — not parsed)
- ❌ **TypeScript / JavaScript extractor** (v1 was meant to cover TS/JS too)
- ✅ **Community detection (Leiden) + summaries** — `indexer/communities.py`, runs
  as a pipeline phase; flat (single-level) clustering with per-community Flash
  summaries. A 2–3 level hierarchy is still future polish.
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
- ⚠️ **Background indexing** — `POST /api/repos` now kicks off the pipeline as a
  detached in-process task (`start_index`) and returns 202 instantly with
  repo_id/run_id, so the UI opens the live map immediately. A durable job
  queue/worker (survives restarts, multi-process) is still future.
- ✅ **WebSocket event stream** — `WS /api/repos/{id}/runs/{run_id}/events/ws`
  (backfill + live) and a replay `GET …/events?after_seq=`. Drives Mission Control.
- ✅ **`agent_events` table + event bus** — migration 0010; `events.py` persists
  with per-run monotonic `seq` and fans out to an in-process hub.
- ✅ **Graph-slice API** (`GET /api/repos/{id}/graph`) — degree-ranked node cap,
  edges, community membership, annotation counts. What Atlas will query.
- ✅ **File API** (`GET /api/repos/{id}/file?path=`) — source reconstructed from
  indexed chunks, for the citation code panel.
- ✅ **Walkthrough API** (`GET /api/repos/{id}/walkthrough`) — serves the
  RepoModel's onboarding steps (404s with a reason until enrichment runs).
- ⚠️ **Budget caps** — LLM rate limiter done; per-run hard $ cap w/ graceful abort not wired

### Frontend  (~85%)

- ✅ App scaffold + design tokens
- ✅ **Landing page** (`/`) — full brand surface: hero, live verified-citation
  terminal, pipeline, economics, magnetic CTA. **Built and shipped.**
- ✅ **3D hero graph** (R3F) with 2D fallback + lazy-load. Engine reused by Mission Control.
- ✅ **Google sign-in (frontend)** — optional Supabase auth in the nav.
- ✅ **Index-a-repo flow** (now in the hero) · ✅ **Chat console** (working)
- ✅ **Mission Control** (`/r/[repo]/run`) — **BUILT.** Pasting a repo on the landing
  page routes straight here (already-indexed → chat instead). Resolves the repo's
  latest run, streams its agent events, renders: a **phase intro** (cloning →
  parsing → summarizing checklist) before the agents appear; agent roster (left),
  R3F **territory graph** that lights up as explorers touch symbols (center),
  findings/verdict feed with visible rejections (right), phase/cost telemetry
  footer, and a **replay scrubber** (LIVE/REPLAY · play/pause · 1×/4×/16× · seek).
  On terminal it shows a **finish panel**: "Mapping finished" when the fleet ran, or
  a graceful "Map ready (agent pass skipped)" + Retry when throttled — always with a
  **"Chat about your repo"** CTA. `components/mission/` (incl. PhaseIntro, FinishPanel)
  + `lib/{events,runState,useRunEvents}.ts`. Replay-first: one reducer renders live
  and replayed runs identically. Verified end-to-end via headless capture.
- ✅ **Atlas** (`/r/[repo]/atlas`) — **BUILT** (`components/atlas/`): a hand-rolled
  2D canvas force layout (Fruchterman–Reingold, seeded so it's stable, progressive
  over rAF so the map visibly settles) over `GET /graph`. Community-colored nodes
  (verified-findings ring in amber), pan/zoom/hover/click, `f`-search with camera
  flight, community legend with click-to-spotlight, and an **Inspector** (kind +
  fqname, summary, community card, edges grouped by kind that navigate, "Ask about
  this" → chat pre-filled via `?q=`, "Open code"). `?focus=<fqname>` deep-links a
  node. Deliberately not Sigma.js: the API caps the slice at ~400 degree-ranked
  nodes, well inside plain-canvas territory, and it kept the bundle small.
- ✅ **Code panel** — **BUILT** (`components/code/CodePanel.tsx`): a slide-over
  showing the indexed source from `GET /file` with the cited range highlighted
  amber and scrolled into view. Opened by Chat citation chips (now buttons) and
  Atlas's "Open code". What you read is what the verifier checked.
- ✅ **Walkthrough view** (`/r/[repo]/walkthrough`) — **BUILT**: the onboarding
  steps as quiet prose; steps deep-link into Atlas; honest empty state when the
  agent pass hasn't produced one.
- ✅ **App shell (icon rail)** — **BUILT** (`components/shell/IconRail.tsx` +
  `app/r/[repo]/layout.tsx`): Run / Atlas / Chat / Walkthrough across every
  `/r/[repo]/*` view, active = amber bar + filled icon. `/r/[repo]` itself now
  redirects by status (indexing → run, else atlas). The full telemetry drawer +
  command palette from FRONTEND.md §3 remain future polish.
- ✅ **"communities" pipeline phase** — in the reducer (`PIPELINE_PHASES`/`PHASES`),
  PhaseIntro ("Detecting code communities"), and RunFooter labels.
- ❌ **App shell** — icon rail + telemetry drawer (only a minimal Chat top bar + the
  landing nav exist)
- ✅ **"My repos" / history** — `GET /api/repos` + `frontend/app/repos/page.tsx`
  with signed-out/empty/list states. "My repos" link in landing nav and chat header.
- ✅ **Chat session sidebar** — left-side session list (w-64) with New Chat button,
  session previews, active session highlighting, past session loading. Every question
  has mandatory `session_id` + `conversation_id`.
- ✅ **Redis session store** — Upstash Redis with 1-hour TTL, last 5 Q&A pairs
  for conversation continuity.
- ✅ **Event store / replay-first infra** — `useRunEvents` (replay via `?after_seq=`
  then live WS) + a pure `reduceRun` reducer (events → roster/feed/graph/totals).
- ❌ **Hardening** — skeletons, error boundaries, full responsive/mobile pass beyond
  the landing, full a11y pass; Storybook

### Agent fleet  (~90% — BUILT, tested, and wired into Mission Control)

The PLAN §2.2 topology is built end to end (`backend/app/agents/`):
- ✅ **Supervisor** (`graph_def.py`) — `run_enrichment_fleet`: planner → parallel
  explorers (capped by `max_agent_concurrency`) → synthesizer → critic (one
  revision round) → librarian. Per-run cost budget (`max_run_cost_usd`) + a 15-min
  wall-clock timeout + per-explorer tool/step caps. Non-fatal: enrichment failure
  never fails the index.
- ✅ **Planner** (`planner.py`) — reads the structural skeleton (files, central
  symbols, doc summaries) → `ExplorationPlan` of 3-8 subsystems (reasoning tier).
- ✅ **Explorer** (`explorer.py`) — agentic bounded tool-use loop, one per subsystem,
  parallel (fast tier) → structured `Finding`s. Each gets its own read session.
- ✅ **Synthesizer** (`synthesizer.py`) — merges findings → `RepoModel` (subsystem
  descriptions, cross-cutting flows, onboarding walkthrough; reasoning tier).
- ✅ **Critic** (`critic.py`) — re-reads cited code, accepts/rejects each finding;
  findings targeting a non-existent symbol are auto-rejected with no LLM call.
- ✅ **Librarian** (`librarian.py`) — writes accepted findings into
  `Node.annotations` (attributed: source, verified, run_id) + stores the RepoModel
  on the REPO node. Not an LLM agent.
- ✅ **Agent tools** (`tools.py`) — `read_file` / `get_node` / `get_neighbors` /
  `search_graph` (reuses `Retriever`) / `grep`, all repo-scoped, read-only, served
  from Postgres (no re-clone), with per-call output caps + a tool-call counter.
- ✅ **Inter-agent schemas** (`schemas.py`) — all payloads are validated Pydantic
  (`ExplorationPlan`, `Subsystem`, `Finding`, `RepoModel`, `Verdict`, …).
- ✅ **Event stream** (`events.py` + `AgentEvent` model + migration 0010) — every
  phase/spawn/tool_call/finding/verdict/error/done event is persisted with a
  per-run monotonic `seq` and fanned out to a live in-process hub.
- ✅ **Events API** (`api/events.py`) — `GET .../runs/{run_id}/events?after_seq=`
  (replay) + `WS .../runs/{run_id}/events/ws` (live: backfill then stream).
- ✅ **Pipeline integration** — runs after summaries (`ENRICHING` status), before
  `INDEXED`; gated on `llm_available`. **Commits the IndexRun before enrichment** so
  the separate event-session can satisfy the `agent_events → index_runs` FK (the
  earlier bug: events failed to persist + the run rolled back). Enrichment is
  best-effort and non-fatal; stats land in `repo.stats`.
- ✅ **Mission Control UI consumes the stream** (frontend, see Frontend section).
- ✅ **Tests** — `tests/integration/test_fleet.py`: planner, tools, critic
  auto-reject, librarian write-back (deterministic fake LLM, real Postgres).
- ✅ **Annotations feed the query/answer layer** — done (see Query router above):
  verified findings + the RepoModel + community summaries all flow into answers,
  and escalation reuses the fleet's explorer + critic for write-back.
- ⏳ **Remaining:** a full explorer-revision loop (currently the critic re-judges
  rejects once); the LLM retry rides out transient 429/503 (10 attempts, exp
  backoff) but a sustained free-tier quota exhaustion still skips enrichment for
  that run (gracefully — the index completes).

> **The agent fleet → event stream → Mission Control are now all built and wired**
> as one connected feature. Replay-first: the UI renders recorded runs and live runs
> through the same reducer.

### Cross-cutting
- ❌ **Eval harness** — golden Q&A + citation precision/recall + answer-quality scoreboard
  (credibility moat; also grades task #20)
- ❌ **Deploy + demo video + writeup**

**Overall v1 ≈ 88%.** Core value (cited Q&A) + auth identity + the **multi-agent
enrichment fleet** + **Mission Control** + the full **query-intelligence layer**
(router with global/escalate, Leiden communities, enrichment-grounded answers,
write-back) are complete end to end, and the graph/file/walkthrough APIs the big
UI views need are live. Biggest remaining chunks: the **frontend views** (app
shell, Atlas, chat code panel, walkthrough — the backend for all of them is
ready), TypeScript extractor, eval harness, GitHub OAuth, deploy/demo/writeup.

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

- **Supabase free-tier auto-pause:** the project paused itself on 2026-07-08 (the
  pooler rejects with `tenant/user not found` while paused; it also takes a few
  minutes after unpausing to re-register the tenant — keep retrying). Resumed same
  day and migrated: **the live DB is at head 0011** (`communities` table applied).
- **🔑 ROTATE EXPOSED KEYS:** the Google + LangSmith keys, Supabase password, and
  the Supabase anon key appeared in the build chat. Gitignored (never committed)
  but rotate them. The anon key is a public client key by design, but rotating the
  whole set is cleanest.
- **Test data in Supabase:** indexing test runs left rows in there
  (benhoyt/pybktree + any `test/...` repos). Harmless; clean out before indexing
  repos you care about (cascade-deletes from the `repos` row).
- **ONE database, every environment: Supabase.** There is no local Postgres — the
  app and local dev both write to Supabase (`backend/.env` `DATABASE_URL`, needs
  internet). The ONLY exception is the `db`-marked test suite, which uses a
  disposable Postgres via `TEST_DATABASE_URL` (CI provides one; tests skip if unset)
  so they never touch real data. `frontend/.env.local` holds the Supabase URL +
  anon key. (`config.py` no longer defaults to a local DB; docker-compose has no
  `db` service.)
- **`.gitignore` tracks `.env*.example` templates** but ignores real env files.
- `LLM_RPM` is the throughput knob — 10 for free tier, 1000+ for paid.
- **Backend gate before pushing:** `ruff check` + `ruff format --check` +
  `pyright` + `pytest -m "not network"` (the format check has bitten us twice).
- **Frontend gate before pushing:** `npx tsc --noEmit` + `npx eslint <changed>` +
  `npx next build`.
- **Merge straight to `main`** (owner's preference — no PRs).
