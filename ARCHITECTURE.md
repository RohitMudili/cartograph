# ARCHITECTURE.md — Code Navigation Map

> Companion to `AGENTS.md`. This traces the two core flows through the **actual
> files** so you can navigate the codebase without reading everything. File paths
> are clickable references; follow them.

---

## Flow 1: Indexing a repo (`POST /api/repos`)

What happens when a user pastes a repo URL, in execution order:

```
backend/app/api/repos.py          create_index()  — the HTTP entry
  └─▶ indexer/pipeline.py         index_repo()     — orchestrates everything
        ├─ _get_or_create_repo()  — idempotent: if already INDEXED, returns instantly
        ├─ indexer/cloner.py      clone_repo()     — sandboxed git clone (security-hardened)
        ├─ build_graph_from_workspace():
        │    ├─ _iter_source_files()               — walk files, skip noise dirs,
        │    │                                        match EXTRACTORS by extension (.py only today)
        │    ├─ indexer/parser/python.py  extract_python()  — tree-sitter → RawSymbol/Import/Call
        │    │     (produces FileExtract objects defined in parser/types.py)
        │    └─ indexer/graph_builder.py  GraphBuilder.build()
        │          — resolves cross-file edges, computes metrics, bulk-inserts
        │            nodes/edges/chunks to Postgres
        └─ indexer/summarizer.py  Summarizer.run()  — IF an LLM key is configured:
               — bottom-up LLM summaries per symbol + pgvector embeddings
               — gated on settings.llm_available (skips cleanly with no key)
```

**Key files & what to know:**
- `pipeline.py` — the conductor. Sets repo status (cloning→parsing→summarizing→indexed),
  records an `IndexRun`, cleans the workspace in a `finally`.
- `cloner.py` — **security-critical.** Blocks `file://`, disables hooks, size caps,
  `GIT_TERMINAL_PROMPT=0` for fast-fail on private repos. Don't weaken it.
- `parser/python.py` — pure (no DB). Walks the tree-sitter AST. To **add a language**:
  write a new extractor producing the same `FileExtract` shape, register it in
  `pipeline.py`'s `EXTRACTORS` dict. (Adding markdown is task #20 — see STATUS.md.)
- `parser/types.py` — the `RawSymbol`/`RawImport`/`RawCall`/`FileExtract` dataclasses.
  The decoupling between parser output and ORM is deliberate (parsers stay testable).
- `graph_builder.py` — where the per-file extracts become a connected graph.
  Cross-file edge resolution (imports/calls/inherits) with **confidence scores**
  (dynamic dispatch gets low confidence). Bulk inserts via SQLAlchemy 2.0 patterns.
- `summarizer.py` — bottom-up (leaves first so containers can summarize from
  children's summaries). Concurrent but bounded by a semaphore.

---

## Flow 2: Answering a question (`POST /api/repos/{id}/questions`)

```
backend/app/api/repos.py          ask_question()   — HTTP entry
  └─▶ query/answerer.py           Answerer.answer()
        ├─ query/retrieval.py     Retriever.retrieve()  — HYBRID retrieval:
        │     ├─ _bm25_node_ids()   — keyword search over chunk.tsv (plainto_tsquery)
        │     ├─ _dense_node_ids()  — pgvector cosine over node summary embeddings
        │     │                        (calls agents/llm.py embed_query)
        │     ├─ _rrf_merge()        — reciprocal-rank fusion of the two signals
        │     └─ _neighbours()       — 1-hop graph expansion (callers/callees/etc.)
        ├─ _synthesize()           — agents/llm.py reasoning().complete_structured()
        │                            LLM answers from retrieved context ONLY, returns
        │                            structured answer + citations (Pydantic)
        └─ query/verifier.py       CitationVerifier.verify_all()  ← THE DIFFERENTIATOR
              — checks each citation against the actual indexed source (chunks):
                path exists? lines overlap a chunk? quoted snippet really there?
              — on failure: ONE regeneration attempt naming the violations, then
                strip bad citations + flag unverified. Never shows a fake citation.
```

**Key files & what to know:**
- `retrieval.py` — three signals fused. Returns `RetrievedItem`s carrying exact
  `file:line` (so citations are mechanical). RRF is rank-based/scale-free (robust
  when mixing a BM25 score with a cosine distance).
- `answerer.py` — orchestrates retrieve→synthesize→verify→(regen). The system prompt
  is here; it optimizes for grounded+cited (which is why answers are accurate but
  dry — improving this is task #20).
- `verifier.py` — **the trust layer.** Verifies against the `chunks` table (stored
  source slices with exact line ranges) — no re-clone needed. This is what makes
  the product's "verified citations" claim real.

---

## The LLM layer (`agents/llm.py`) — every model call goes through here

- `reasoning()` / `fast()` — two tiers (smart vs cheap-high-volume).
- `complete()` / `complete_structured(schema)` — text or Pydantic-validated output,
  provider-uniform via LangChain `.with_structured_output`.
- `embed_texts()` / `embed_query()` — embeddings (dimension pinned to `EMBEDDING_DIM`).
- `UsageLedger` — records token counts; dollar cost is filled from LangSmith (we
  keep no price tables).
- `_RateLimiter` — token-bucket pacing to `LLM_RPM` so we don't 429 on free tier.
- Provider is chosen by the `"provider:model"` strings in `config.py` / `.env`.

To swap providers or models: change the strings in `.env` (`REASONING_MODEL`,
`FAST_MODEL`, `EMBEDDING_MODEL`). No code change.

---

## The database (`db/`)

- `models.py` — the ORM. `Repo → Node → Edge → Chunk → IndexRun → Question`.
  SQLAlchemy 2.0 typed (`Mapped[...]`). `Question` table is now **active** — used by
  `POST /api/repos/{id}/questions` to persist Q&A history. `owner_user_id` on repos
  and questions drives per-user ownership + RLS. `communities`/`agent_events` still
  defined but unused until the agent fleet lands.
- `session.py` — async engine/session. **Contains the Supabase pgbouncer fix**
  (`statement_cache_size=0`). `db_session` test fixture rolls back.
- `enums.py` — native Postgres enums (stored as UPPERCASE member names).
- `migrations/` — alembic, sequential `0001`..`0009`, head = `0009`. pgvector enabled
  in 0001; graph schema in 0002; RLS deny-all in 0004; chunk tsvector in 0005;
  **0006**: adds `owner_user_id` on repos, `questions` table, and per-user RLS policies.
  **0007**: adds `user_profiles` table (maps `owner_user_id` to optional email/github).
  **0008**: adds `session_id` on questions for chat session grouping.
  **0009**: adds `conversation_id` on questions for per-turn tracking.
  The `migrations/env.py` now includes the pgbouncer `statement_cache_size=0` fix
  (applies when connecting through the Supabase pooler).

---

## Frontend (`frontend/`)

```
app/layout.tsx          — root layout, IBM Plex fonts as CSS vars
app/globals.css         — design tokens (@theme, OKLCH) — the "instrument panel" palette
app/page.tsx            — renders <Landing /> (the marketing surface)
app/r/[repo]/chat/
  page.tsx              — server component, awaits params (Next 16!), renders ↓
  ChatConsole.tsx       — the Chat UI (client): threads, citation chips, transparency strip
app/auth/               — Google sign-in routes (see "Auth flow" below)
  callback/route.ts     — PKCE code → session exchange
  signout/route.ts      — POST-only sign-out
  auth-error/page.tsx   — friendly sign-in failure surface
proxy.ts                — Next 16's renamed middleware: refreshes the Supabase session cookie
components/
  ui.tsx                — shared vocabulary: StatusChip, VerifyBadge, RouteBadge, Button
  landing/              — the landing page (see "Landing flow" below)
    Landing.tsx         — composes the whole page (Nav, Hero, Proof, Pipeline, Economics, CTA, Footer)
    GraphField.tsx      — 2D canvas hero graph (the always-safe fallback)
    GraphField3D.tsx    — 3D R3F hero graph (z-layered nodes, edges, cursor-follow)
    GraphFieldAuto.tsx  — picks 3D vs 2D per device; lazy-loads Three.js (ssr:false)
    useMotionPreference.ts — hero motion on/off (localStorage + reduced-motion)
    VerifiedAnswer.tsx  — the live "answer types in, citation resolves to verified" terminal
    MagneticButton.tsx  — cursor-leaning CTA (motion values, not state)
  auth/AuthMenu.tsx     — nav sign-in button → account chip + sign-out
lib/api.ts              — typed client mirroring the backend response models
lib/supabase/           — Supabase clients + the useUser hook (see "Auth flow")
```

The Chat UI calls `lib/api.ts` → the FastAPI backend. Verified citations render as
amber chips; unverified ones render struck-through in red (the honesty rule).

**Session system:** Active sessions are stored in **Upstash Redis** with 1-hour TTL
(`app/session/store.py`). Every question carries both a `session_id` (groups into
chat sessions) and a `conversation_id` (unique per-turn UUID). The backend
auto-creates sessions when missing; the last 5 Q&A pairs are injected as
conversation context in the LLM prompt. Session sidebar on the chat page shows
past sessions with previews and message counts.

**"My repos" page** (`/repos`): `GET /api/repos` returns repos owned by the signed-in
user. `frontend/app/repos/page.tsx` renders three states (signed-out, empty, list).
A visible "My repos" link appears in the landing nav and chat header when signed in.

**Not built yet:** Mission Control (`/r/[repo]/run`), Atlas (`/r/[repo]/atlas`),
the code panel, the app shell/drawer. See `FRONTEND.md` for specs and `STATUS.md`
for status.

---

## Flow 3: Landing page (`/`)

```
app/page.tsx                       → <Landing />
components/landing/Landing.tsx      — "use client"; composes the sections:
  Nav        — wordmark + Source link + <AuthMenu/>
  Hero       — asymmetric split: copy + repo input (left), graph (right)
    ├─ GraphFieldAuto → GraphField3D (desktop+WebGL) | GraphField (else)
    │    (paused prop = !motionEnabled, from useMotionPreference)
    ├─ "Pause tracking" toggle (bottom-right) → toggleMotion()
    └─ MagneticButton — the "Map it" CTA; on submit calls api.indexRepo → /r/{id}/chat
  Proof      — claim (left) + <VerifiedAnswer/> live terminal (right)
  Pipeline   — connected Parse → Enrich → Answer flow (Phosphor icons)
  Economics  — mono numerals on hairlines (no card boxes)
  CallToAction — single intent, magnetic button → the demo repo's chat
  Footer
```

**Key files & what to know:**
- `GraphFieldAuto.tsx` — the safety gate. Renders the 2D `GraphField` by default
  (also the SSR output, so no hydration mismatch), then upgrades to `GraphField3D`
  **only** on desktop with usable WebGL and motion allowed. `GraphField3D` is
  `next/dynamic({ ssr: false })`, so the ~150KB Three.js bundle never touches SSR
  or the LCP path; `/` still prerenders as static. Forwards the `paused` prop.
- `GraphField3D.tsx` — React Three Fiber. Instanced node meshes, edge `lineSegments`,
  amber important-node glints, and a per-node bob/pulse (the "blink") that always
  runs. **Cursor-follow:** the whole graph translates toward the cursor (plus a
  light tilt) — the pointer is tracked at the **window** level, NOT `useThree().pointer`,
  because the graph layer is `pointer-events-none` (so it never steals clicks from
  the hero input) and therefore the canvas itself receives no mouse events.
  - `paused` (from `useMotionPreference`) stops ONLY the cursor-follow: on pause
    the group snaps to its default centered/untilted state immediately and ignores
    the pointer; the node blink keeps running, so the graph stays alive. Resuming
    starts from default.
  - `FrameGate` pauses the render loop via `IntersectionObserver` when scrolled
    out of view (runs whenever on-screen, regardless of the pause toggle, since
    the blink needs frames). DPR capped.
  - **This is the engine the future Mission Control live graph reuses** — same
    renderer, camera, primitives.
- `useMotionPreference.ts` — owns the hero-motion on/off state. Persists the
  user's choice to `localStorage` (`cartograph:hero-motion`); with no stored
  choice it defaults to the inverse of `prefers-reduced-motion` (off if the user
  prefers reduced motion). The hero's "Pause tracking" pill calls `toggleMotion`.
- `VerifiedAnswer.tsx` — motivated motion: on `whileInView`, the answer types in and
  a citation resolves `checking` → `verified`, dramatizing the product's core claim.
  Reduced-motion shows the settled end-state immediately.
- The graph is **illustrative**, not live telemetry (honors PRODUCT.md's
  never-simulate rule — same status as the old 2D field).

---

## Flow 4: Google sign-in (`/auth/*`, Supabase Auth)

Optional sign-in. Anonymous use is the default; sign-in unlocks "my repos" / history
and is required before connecting GitHub for private repo access.

```
components/auth/AuthMenu.tsx        — nav: "Sign in" (signed out) | account chip (signed in)
  └─ signInWithOAuth({provider:'google', redirectTo:/auth/callback?next=…})
       → Google consent → back to:
app/auth/callback/route.ts          — exchangeCodeForSession(code) → redirect to `next`
proxy.ts → lib/supabase/middleware.ts (updateSession)
                                    — runs every request, refreshes the auth cookie
app/auth/signout/route.ts           — POST-only signOut() → home
```

**Key files & what to know:**
- `lib/supabase/client.ts` / `server.ts` — `@supabase/ssr` browser + server clients
  (cookie-based sessions). Use the anon (public) key, never a service key.
- `lib/supabase/middleware.ts` — `updateSession`; no-ops gracefully if the Supabase
  env vars are absent, so the app runs before keys are configured.
- `lib/supabase/use-user.ts` — reactive `{ user, loading }` for client components
  (subscribes to `onAuthStateChange`).
- `proxy.ts` — **Next 16 renamed `middleware.ts` → `proxy.ts`** (exports a `proxy`
  function). It wires `updateSession` and excludes static assets via `matcher`.
- **Backend half built:** `backend/app/auth/jwt.py` validates Supabase JWTs using
  **PyJWT** with JWKS (fetches public keys from `https://<ref>.supabase.co/auth/v1/.well-known/jwks.json`)
  and falls back to HMAC (HS256) if `SUPABASE_JWT_SECRET` is configured. Returns
  `AuthUser(id, email)` or `None` — never rejects, anonymous-friendly.
- `owner_user_id` column on `Repos` and `Questions` — populated by `POST /api/repos`
  and `POST /api/repos/{id}/questions` when a valid JWT is present.
- RLS policies (migration 0006) layer per-user `SELECT` over the deny-all baseline.
- The frontend (`lib/api.ts`) automatically sends the Supabase access token as
  `Authorization: Bearer <token>` on every API request.

---

## Where the spec lives for things not yet built

- **Agent fleet** (planner/explorers/synthesizer/critic) → `PLAN.md §2.2`. Goes in
  `backend/app/agents/`. `langgraph` is installed; `llm.py` is ready for it.
- **Query router / global / escalate routes** → `PLAN.md §2.3`. Goes in `query/`.
- **Mission Control / Atlas UI** → `FRONTEND.md §5.2/5.3`, `DESIGN.md`.
- **WebSocket event stream** (the backbone the fleet + Mission Control need) →
  `PLAN.md §4.3`. Not built; nothing streams yet.
- **Eval harness** → `PLAN.md §6`. Goes in `evals/`.
