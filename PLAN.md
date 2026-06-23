# Cartograph — Project Plan

> **Watch AI agents map your codebase.**
> Paste a GitHub repo URL → a fleet of agents explores it live → you get an interactive
> architecture map, a guided onboarding walkthrough, and a chat that answers questions
> with verified `file:line` citations — at ~1/50th the cost per question after the first one.

| | |
|---|---|
| **Status** | Planning |
| **Timeline** | ~4 weeks to public v1 |
| **LLM Provider** | Google Gemini (`google-genai` Python SDK) |
| **Primary goals** | (1) Portfolio piece demonstrating SOTA multi-agent + GraphRAG engineering to AI engineers and hiring managers. (2) Genuinely useful tool for onboarding onto unfamiliar codebases. |
| **Audience** | AI engineers, hiring managers, open-source contributors, new hires |

---

## 1. Product Vision

### 1.1 The pitch

Understanding an unfamiliar codebase is one of the most universal pains in software:
new hires take weeks to ramp, open-source contributors bounce off repos they can't
navigate, and interviewers/clients constantly evaluate code they didn't write.

Cartograph turns that into a two-minute experience:

1. **Paste a repo URL.** Cartograph clones it and builds a structural knowledge graph
   (zero LLM cost — derived from the AST).
2. **Watch agents explore.** A planner partitions the repo into subsystems and spawns
   parallel explorer agents. Their activity streams live to a "mission control" view.
   A critic adversarially verifies every claim before it's accepted.
3. **Get the atlas.** An interactive architecture graph, a generated onboarding
   walkthrough ("read these 7 files in this order"), and a chat that answers questions
   with `file:line` citations — every citation checked against the actual file before
   it's shown.
4. **Come back later, pay almost nothing.** The knowledge graph persists. Repeat
   questions are answered from the graph in seconds for fractions of a cent, with
   live agent exploration only as an escalation path — and anything those escalation
   agents learn is written back into the graph, so the system gets cheaper and smarter
   with use.

### 1.2 Why this project (positioning)

> **Market reality (June 2026, see PRODUCT.md → Competitive Landscape):** this
> space is validated and active. **Greptile** (funded) and **Sourcegraph Cody**
> own the "understand your codebase" value prop; **GitNexus** (open source, Aug
> 2025) independently shipped almost our exact tree-sitter → code-knowledge-graph
> architecture, including cluster detection and incremental reindex. So the graph,
> the chat, and even cheap GraphRAG-for-code are **commodity** — do not pitch them
> as novel. What follows is honestly scoped against that.

"Chat with your codebase" exists (Cursor, Copilot, Greptile, GitNexus). The parts
of Cartograph that are still genuinely differentiated — and that signal engineering
depth for a portfolio — are:

- **Watch agents explore as the product** (the real edge). Competitors hide
  indexing behind a progress bar; Cartograph makes the live, beautiful
  multi-agent exploration — *with the verification loop visible on screen* — the
  centerpiece. The supervisor → parallel explorers → synthesizer → critic topology
  is structurally justified (codebases partition into independently explorable
  subsystems), and rendering it live is the hardest thing for a competitor to copy.
- **Adversarially verified citations with PUBLISHED evals** (the credibility moat).
  Every `file:line` claim is checked against the real file before display;
  hallucinated citations are caught and regenerated. A real `evals/` directory with
  golden Q&A and a **citation-accuracy precision/recall scoreboard in the README** —
  which no competitor publishes — is the strongest depth signal in the repo.
- **Standalone "paste a URL, watch it happen" web experience.** GitNexus is an MCP
  server for your editor; Greptile/Cody are platforms. The instant, zero-setup,
  visual "watch a stranger's repo get mapped in 2 minutes" is its own distinct thing.
- **Supporting (not headline) engineering rigor:** the static-graph-first design
  keeps indexing cheap (LLM only for the semantic layer), giving an honest cost
  story — "first question ~$0.50/90s, every one after ~$0.01/3s." This is sound
  engineering, **not a novel insight** (GitNexus does the same); present it as
  craft, not breakthrough.

**Writeup framing:** *"how I'd architect this class of system, with the rigor —
evals, adversarial verification, cost accounting — that shipped products skip."*
A crowded market validates the problem; the goal is demonstrating depth, not
winning share against a funded startup.

### 1.3 Non-goals (v1)

- **Not** a code *editing* tool. Read/understand only.
- **Not** multi-tenant SaaS with auth/billing. Single-deploy demo + local-run.
- **Not** support for every language. v1: **Python + TypeScript/JavaScript** (tree-sitter
  grammars are mature; covers the demo repos). Architecture must make adding a language
  a config change, not a rewrite.
- **Not** monorepo-scale (Chromium). Target: repos up to ~5k files / ~500k LOC.
  Larger repos get a clear "partial index" message, not silent truncation.
- **No** fine-tuning, no self-hosted models in v1.

---

## 2. System Architecture

### 2.1 Bird's-eye view

Two-phase system: **expensive indexing once per repo**, **cheap queries forever after**.

```
                          ┌──────────────────────────────────────────────┐
                          │                INDEX TIME (once)             │
                          │                                              │
 GitHub URL ──► Cloner ──►│ 1. Static pass (tree-sitter)                 │
                          │      symbols + edges, $0, deterministic     │
                          │ 2. Agent enrichment (LangGraph fleet)        │
                          │      Planner → N Explorers → Synthesizer     │
                          │      → Critic loop; findings WRITTEN INTO    │
                          │      the graph                               │
                          │ 3. Community detection (Leiden) +            │
                          │      hierarchical summaries (Gemini Flash)   │
                          └──────────────┬───────────────────────────────┘
                                         │ persisted knowledge graph
                                         ▼
                          ┌──────────────────────────────────────────────┐
                          │              QUERY TIME (every Q)            │
                          │                                              │
 User question ──► Router │  local search   │ global search │ escalate   │
                          │  (entity hood)  │ (community    │ (live agent│
                          │  1 small call   │  summaries)   │  + write-  │
                          │                 │  1 small call │  back)     │
                          │        └──── Citation Verifier ────┘         │
                          └──────────────────────────────────────────────┘
                                         │ WebSocket event stream
                                         ▼
                              Next.js UI (mission control /
                              architecture graph / cited chat)
```

### 2.2 Phase 1 — Indexing pipeline

#### Step 1: Clone & static analysis (zero LLM cost)

- Shallow-clone the repo into a sandboxed workspace (see §10 Security).
- **tree-sitter** parses every supported source file into an AST.
- Extract **nodes**: `repo → package/module → file → class → function/method`,
  plus `config`, `doc`, and `test` file nodes.
- Extract **edges** deterministically:
  - `CONTAINS` (structural nesting)
  - `IMPORTS` (import resolution, including relative/aliased imports)
  - `CALLS` (best-effort static call resolution; mark confidence — dynamic dispatch
    in Python is annotated `confidence: low` rather than guessed)
  - `INHERITS`, `IMPLEMENTS`
  - `TESTS` (test file ↔ subject heuristics: path conventions + imports)
- Compute per-node metrics used later for prioritization: LOC, fan-in/fan-out,
  git churn (commit count touching the file), centrality.
- **Output:** a complete structural skeleton in Postgres. This step takes seconds,
  costs $0, and is fully re-runnable.

Key implementation note: chunking for embeddings is **AST-aware** — a chunk is a
function/class with its docstring and signature context, never an arbitrary 1,000-char
window. Each chunk records exact `(path, start_line, end_line)` so citations are
mechanical, not inferred.

#### Step 2: Multi-agent enrichment (the showpiece)

> **Status (2026-06-24): ✅ BUILT** in `backend/app/agents/` (planner → parallel
> explorers → synthesizer → critic → librarian, with an `agent_events` stream +
> replay/WS API, run during indexing as the `ENRICHING` phase; backend tested).
> Implemented as a direct async supervisor rather than a LangGraph `StateGraph`
> object — same supervisor pattern, transparent and unit-testable, no checkpointer
> coupling to our session. The Mission Control UI that renders the stream is the
> next piece (`FRONTEND.md §5.2`). The design below is the authoritative spec.

Implemented as a **LangGraph** graph (recognizable framework; its supervisor pattern
maps exactly to our topology). All agents call Gemini through a thin internal
`llm.py` wrapper (see §5.3) so model choice, retries, token accounting, and cost
tracking live in one place.

| Agent | Role | Model tier | Output |
|---|---|---|---|
| **Planner** | Reads the structural skeleton (dir tree, top-central nodes, manifests, README) and partitions the repo into 3–8 subsystems with exploration briefs. | Pro-tier | `ExplorationPlan` (Pydantic) |
| **Explorer ×N** | One per subsystem, run in parallel. Each has tools: `read_file`, `get_node`, `get_neighbors`, `search_graph`, `grep`. Explores its territory and emits **structured findings**: node summaries, role annotations ("this is the auth boundary"), key flows, surprises/code smells. | Flash-tier (cheap, parallel) | `list[Finding]` |
| **Synthesizer** | Merges explorer findings into the coherent repo-level model: subsystem descriptions, cross-subsystem flows, the onboarding walkthrough, architecture-level annotations. | Pro-tier | `RepoModel` |
| **Critic** | Adversarially verifies a sample of claims **against the actual code** (re-reads cited files, checks that named symbols exist, checks edge claims against the static graph). Rejected claims go back to the owning explorer for one revision round; twice-rejected claims are dropped and logged. | Pro-tier | `list[Verdict]` |
| **Librarian** (writer, not an LLM agent) | Persists accepted findings into the graph as node/edge annotations and summaries. Every write is attributed (`source: explorer_3, verified_by: critic, run_id`). | — | graph mutations |

Design rules that keep this honest:

- **Every agent's output is structured** (Gemini JSON mode / `response_schema` with
  Pydantic models). No free-text parsing between agents.
- **Findings are claims, not facts**, until the critic passes them. The graph stores
  verification status per annotation.
- **The agents write to the graph, not to a transcript.** This is the core
  architectural idea: exploration produces a durable artifact, so its cost amortizes.
- **Hard budgets:** per-agent tool-call cap, per-run token budget, and wall-clock
  timeout. A runaway explorer gets cancelled, its partial findings flagged.
- **Every agent event** (spawn, tool call, finding, verdict, handoff) is published to
  the run's event log → streamed over WebSocket → rendered in mission control. The
  event log is also the debugging/replay record.

#### Step 3: Community detection + hierarchical summaries

- Run **Leiden** clustering (via `igraph`/`leidenalg`) over the enriched graph
  (weighted: structural edges + co-change affinity from git history).
- Build a 2–3 level community hierarchy: `repo → subsystem communities → tight clusters`.
- Generate a summary per community with Gemini Flash, **bottom-up**: leaf-cluster
  summaries are composed from member node summaries; parent summaries are composed
  from child summaries. This caps prompt sizes and makes invalidation surgical (§9).
- Embed all node and community summaries (Gemini embedding model) into pgvector.

**Indexing cost model (estimate, to be measured in week 1):** a 1,500-file repo ≈
6k symbols → ~6k Flash summarization calls (batched) + ~40 explorer/synthesis/critic
calls + ~150 community summaries. Target: **< $1.00 and < 3 minutes** on Flash-tier
pricing for mid-size repos. These numbers go in the README once measured.

### 2.3 Phase 2 — Query pipeline

#### Router

A single cheap classification call (Flash, JSON mode) labels each question:

| Route | Trigger | Strategy | Typical cost |
|---|---|---|---|
| **Local** | Names or implies a specific symbol/file ("what does `refresh_token` do?", "where is rate limiting?") | Embed query → top-k entity match → pull graph neighborhood (the node, its summary, callers, callees, containing community summary) → one synthesis call | ~$0.005, ~2–3s |
| **Global** | Architecture/big-picture ("how does error handling work overall?", "what are the main components?") | Map over relevant community summaries (already computed) → one reduce call. Drill into specific nodes only if confidence is low. | ~$0.01, ~3–5s |
| **Escalate** | Router or answerer signals the graph can't support an answer (low retrieval scores, critic-rejected draft, "why was this designed this way" style questions) | Spawn a **single live explorer agent** with graph + file tools, scoped to the question. Its verified findings are **written back** into the graph. | ~$0.05–0.15, ~20–60s |

#### Hybrid retrieval (used by local route and escalation)

- **BM25** (Postgres full-text or `rank_bm25`) over code + summaries — code questions
  are often exact-identifier lookups where embeddings underperform.
- **Dense** retrieval over pgvector summary/chunk embeddings.
- **Graph expansion**: from the top hits, walk 1-hop neighborhoods (callers/callees/
  siblings) to assemble context that *explains* rather than just matches.
- Reciprocal-rank fusion to merge; optional rerank pass only if eval data shows it
  pays for itself (measure first, don't cargo-cult).

#### Citation verification (non-negotiable)

Every answer must end in `citations: [{path, start_line, end_line, quoted_snippet}]`
(enforced by response schema). Before display, the verifier:

1. Confirms the path exists at the indexed commit.
2. Confirms the quoted snippet actually appears within ±3 lines of the cited range.
3. On failure: one regeneration attempt with the violation named; if it fails again,
   the answer ships with the bad citation **removed and the claim downgraded to
   "unverified"** — visibly, in the UI. Never silently keep a fake citation.

Verification results are logged per answer → feeds the eval dashboard (§8).

#### Answer write-back

Escalation findings, and high-confidence answer syntheses for questions the graph
couldn't answer locally, are written back as graph annotations (critic-checked,
attributed). A repeated question that needed escalation yesterday is a local-route
hit today. **The graph is a learning cache.** This loop is a headline feature of
the writeup.

#### Answer quality — scoped improvements (observed gap)

The first working version answers correctly and cites verifiably, but on
**open-ended / onboarding questions** ("help me get started contributing") the
answers read like flat API docs, not a senior engineer orienting you. Honest
diagnosis from a real run: the quality is capped by *what we retrieve* and *how we
prompt*, **not** by the model — which means it's tunable, not fundamental. Scoped
work, in rough leverage order:

1. **Index docs/markdown (highest leverage).** ✅ **DONE** for `.md`
   (`parser/markdown.py`, wired into `EXTRACTORS`). The model now sees the
   `README` — the single best source for "what is this and why." The markdown
   extractor emits a FILE-level `DOC` node plus one `DOC` node **per section**
   (split on `#`/`##`/`###` headers, each with its own line range), flowing
   through the existing graph builder → summarizer → embeddings → retrieval with
   no downstream changes. Section-level chunking matters: a whole 500-line README
   as one chunk poisons retrieval. **Still to do:** index other docs
   (`CONTRIBUTING`, `docs/*.md` are covered by `.md`; `.rst`/`.txt` are not) and config (`pyproject`,
   `package.json`) as `CONFIG`/`DOC` nodes.
2. **Question-type-aware prompting.** ✅ **DONE** (`backend/app/query/answerer.py`,
   implemented 2026-06-22). The answerer now classifies questions into 6 types
   (onboarding/architecture/specific-symbol/how-to/comparison/general) using a
   cheap Flash-tier call before synthesis. Per-type system prompts shape the answer
   format: onboarding leads with purpose, then orientation; specific-symbol goes
   straight to signature and call sites. Retrieval breadth adjusts per type
   (8–15 items). Falls back to `general` on any classification error so questions
   are never blocked.
3. **Retrieve more for broad questions.** ✅ **DONE** (shipped as part of the
   question-type-aware prompting above — `_TOP_K_BY_TYPE` adjusts retrieval
   breadth: 15 for onboarding/architecture, 8 for specific-symbol, etc.)
4. **Measure it, don't vibe it.** These improvements get **graded by the eval
   harness** (§6) on an *answer-quality* dimension (purpose stated? oriented?
   actionable?) split by question type — so we tune deliberately. This gap is
   exactly the kind of thing evals exist to catch.

Status: items #1–3 shipped (markdown indexing, question-type-aware prompting,
adjusted retrieval breadth). #4 (eval-graded measurement) is the last remaining
piece and is tied to the eval harness build-out.

---

## 3. Data Model

Postgres (+ pgvector). Graph traversal/clustering happens in-process with NetworkX/
igraph loaded from these tables — **deliberately no Neo4j in v1** (documented as a
considered-and-deferred decision; nothing at our scale needs it).

```sql
repos        (id, url, default_branch, head_commit, status, indexed_at,
              index_cost_usd, stats jsonb)

nodes        (id, repo_id, kind,            -- repo|package|file|class|function|...
              fqname, path, start_line, end_line,
              signature, docstring,
              metrics jsonb,                -- loc, fan_in, fan_out, churn, centrality
              summary text,                 -- LLM-written, 1-2 lines
              summary_embedding vector,
              annotations jsonb[],          -- {text, source, verified, run_id, created_at}
              content_hash)                 -- for incremental invalidation

edges        (id, repo_id, src_node_id, dst_node_id,
              kind,                         -- contains|imports|calls|inherits|tests
              confidence, metadata jsonb)

communities  (id, repo_id, level, parent_id,
              member_node_ids bigint[],
              title, summary text, summary_embedding vector,
              dirty boolean)                -- invalidation flag

chunks       (id, repo_id, node_id, path, start_line, end_line,
              text, embedding vector, tsv tsvector)   -- hybrid retrieval unit

index_runs   (id, repo_id, kind,            -- full|incremental|escalation
              status, started_at, finished_at,
              token_usage jsonb, cost_usd)

agent_events (id, run_id, ts, agent, type,  -- spawn|tool_call|finding|verdict|error
              payload jsonb)                -- the replay/debug/UI stream record

questions    (id, repo_id, text, route, answer jsonb,
              session_id, conversation_id,        -- UUID strings; both ALWAYS set
              citations jsonb, citation_verified boolean,
              cost_usd, latency_ms, created_at)

user_profiles (id, owner_user_id unique,        -- maps Supabase user to identity
               email, github_username nullable)
```

---

## 4. Backend Design (Python / FastAPI)

### 4.1 Service layout

Single deployable FastAPI app + a worker process. No microservices — v1 runs as
`api` + `worker` + `postgres` via docker-compose.

```
cartograph/
├── PLAN.md                      # this file
├── README.md                    # demo gif, architecture diagram, eval table, cost chart
├── docker-compose.yml           # api, worker, postgres(pgvector)
├── backend/
│   ├── pyproject.toml           # uv-managed
│   ├── app/
│   │   ├── main.py              # FastAPI app, lifespan, routers
│   │   ├── config.py            # pydantic-settings; model IDs/keys/budgets live here
│   │   ├── api/
│   │   │   ├── repos.py         # POST /repos, GET /repos/{id}, repo status
│   │   │   ├── questions.py     # POST /repos/{id}/questions
│   │   │   ├── graph.py         # GET graph slices for the UI
│   │   │   └── ws.py            # /ws/runs/{run_id} event stream
│   │   ├── indexer/
│   │   │   ├── cloner.py        # sandboxed shallow clone
│   │   │   ├── parser/          # tree-sitter wrappers, per-language extractors
│   │   │   │   ├── python.py
│   │   │   │   └── typescript.py
│   │   │   ├── graph_builder.py # nodes/edges → Postgres
│   │   │   ├── communities.py   # leiden + hierarchy
│   │   │   ├── summarizer.py    # batched Flash summaries, bottom-up
│   │   │   └── incremental.py   # diff-based re-index (§9)
│   │   ├── agents/
│   │   │   ├── llm.py           # ALL Gemini calls: client, retry, JSON-mode helper,
│   │   │   │                    #   token/cost accounting, model registry
│   │   │   ├── graph_def.py     # LangGraph topology (supervisor pattern)
│   │   │   ├── planner.py
│   │   │   ├── explorer.py
│   │   │   ├── synthesizer.py
│   │   │   ├── critic.py
│   │   │   ├── librarian.py     # graph write-back
│   │   │   ├── tools.py         # read_file, get_neighbors, search_graph, grep
│   │   │   └── schemas.py       # Pydantic models for every inter-agent payload
│   │   ├── query/
│   │   │   ├── router.py        # local | global | escalate classifier
│   │   │   ├── retrieval.py     # BM25 + dense + graph expansion + fusion
│   │   │   ├── answerer.py      # per-route synthesis
│   │   │   ├── verifier.py      # citation verification
│   │   │   └── escalation.py    # scoped live explorer + write-back
│   │   ├── events.py            # event bus: agent_events table + WS fanout
│   │   └── db/                  # SQLAlchemy models, alembic migrations
│   └── tests/
├── evals/
│   ├── datasets/                # golden Q&A per repo (yaml)
│   ├── run_evals.py
│   └── results/                 # committed score history (jsonl)
└── frontend/                    # Next.js (see §6)
```

### 4.2 Gemini integration (`agents/llm.py`)

All model access goes through one module. Rules:

- **SDK:** `google-genai` (the current unified SDK — not the deprecated
  `google-generativeai`). LangGraph agents use `langchain-google-genai` bindings,
  which sit on the same credentials/config.
- **Model registry in config, not in code.** Two logical tiers used throughout:
  `MODEL_REASONING` (planner/synthesizer/critic — Gemini Pro tier) and `MODEL_FAST`
  (explorers/summaries/router — Gemini Flash tier), plus `MODEL_EMBEDDING`.
  Exact model IDs are config values — **verify current Gemini model IDs and pricing
  at implementation time** and record them in `config.py` with a dated comment;
  do not hardcode IDs from memory across the codebase.
- **Structured output everywhere:** every call that feeds another component uses
  Gemini JSON mode with a `response_schema` derived from the Pydantic models in
  `schemas.py`, validated on receipt; one retry-with-error-named on validation
  failure.
- **Context caching:** Gemini context caching for the large stable prefixes
  (repo skeleton given to every explorer; community summaries given to the global
  answerer). Measure hit rates; this is part of the cost story.
- **Accounting:** every call records `(model, input_tokens, output_tokens, cost,
  purpose, run_id)` → `index_runs.token_usage` / `questions.cost_usd`. The cost
  chart in the README is generated from this table, not estimated.
- **Resilience:** exponential backoff on 429/5xx, per-run circuit breaker, global
  concurrency limiter (explorers run parallel but bounded, e.g. 6 concurrent).

### 4.3 API surface

```
POST   /api/repos                      {url}            → {repo_id, run_id}   (idempotent per URL+commit)
GET    /api/repos                                       → list user's repos (authenticated)
GET    /api/repos/{id}                                  → status, stats, cost
POST   /api/repos/{id}/reindex                          → incremental update run
GET    /api/repos/{id}/graph?level=&community=&node=    → UI graph slices (paginated)
GET    /api/repos/{id}/walkthrough                      → generated onboarding doc
POST   /api/repos/{id}/questions       {text}           → streamed answer (SSE) + citations + route + cost
GET    /api/repos/{id}/questions                        → history (optional ?session_id= filter)
POST   /api/repos/{id}/sessions       (no body)         → create chat session, returns session_id
GET    /api/repos/{id}/sessions                         → list sessions for a repo (from Postgres)
WS     /ws/runs/{run_id}                                → agent event stream (mission control)
GET    /api/evals/latest                                → published eval scores (powers README badge)
```

**Session system:** Every question is accompanied by both a `session_id` (groups
Q&A into 1-hour chat sessions stored in Upstash Redis) and a `conversation_id`
(unique per-turn UUID). The backend auto-creates sessions when missing. Last 5
Q&A pairs are maintained in Redis for conversation continuity and injected into
the LLM prompt on subsequent questions.

WebSocket event envelope (one schema, every agent event):

```json
{"ts": "...", "run_id": "...", "agent": "explorer_3", "type": "tool_call",
 "payload": {"tool": "read_file", "args": {"path": "src/auth/jwt.py"}},
 "seq": 1042}
```

`seq` enables reconnect-and-replay from the `agent_events` table — the UI never
misses events on a dropped connection.

---

## 5. Frontend Design (Next.js + Tailwind)

> **Superseded by [`FRONTEND.md`](FRONTEND.md)** — the full frontend plan
> (design system in [`DESIGN.md`](DESIGN.md), strategy in
> [`PRODUCT.md`](PRODUCT.md)). This section remains as the original summary.

Three views. The bar: *the screen-recording of mission control should be inherently
share-worthy.* Polish budget is concentrated here (and the installed design skills —
`impeccable` / `taste-skill` — get applied during week 3).

### 5.1 Mission Control (index-time)

- Left: live agent roster — planner/explorers/synthesizer/critic as cards with
  state (thinking / tool call / done), current activity line, token spend ticking up.
- Center: the repo file-tree / graph progressively "lighting up" as territory is
  explored — claimed regions colored per explorer.
- Right: scrolling verified-findings feed; critic rejections shown distinctly
  (this is the moment that demonstrates the verification loop on camera).
- Bottom: run totals — elapsed, tokens, **live cost counter** (the cost counter is
  a deliberate flex).

### 5.2 Atlas (the architecture map)

- Force-directed graph (Sigma.js or react-force-graph; WebGL — must stay smooth at
  ~5k nodes) with **semantic zoom**: communities at far zoom → files → symbols.
- Click a node: summary, annotations (with source attribution + verified badge),
  metrics, edges; "ask about this" pre-fills chat.
- Edge-type and confidence filters; "show the auth flow"-style saved subgraph views
  generated by the synthesizer.
- Generated **onboarding walkthrough** as an ordered overlay: step 1..N highlight
  path through the graph with prose.

### 5.3 Chat (query-time)

- Answers stream token-by-token; citations render as `path:line` chips → click opens
  a code panel scrolled to the exact lines, with the verified-quote highlighted.
- Per-answer transparency strip: route taken (local/global/escalated), cost, latency,
  subgraph used (mini-map that highlights the consulted nodes in the Atlas).
- Escalations show inline mini-mission-control (the spawned agent's activity) and
  end with "✦ graph updated — this answer is cheaper next time."

---

## 6. The Eval Harness (`evals/`)

This is a first-class deliverable, not an afterthought — it's the strongest
credibility signal in the repo.

- **Datasets:** 25–40 golden Q&A per repo for 3–4 well-known repos (candidates:
  `fastapi`, `httpx`, `flask`, `excalidraw` for the TS side). Each item:
  `{question, route_expected, must_cite: [path(:line-range)...], rubric}`.
  Hand-authored against the pinned commit; pinned commits committed with the dataset.
- **Metrics:**
  - **Citation precision/recall** — mechanically checkable, the headline number.
  - **Route accuracy** (router picked the expected tier).
  - **Answer quality** — LLM-as-judge against rubric, using a judge model *different
    from the answering model*, with the judge prompt published. Spot-check 20% by hand.
  - **Cost & latency** per question, split by route — feeds the README cost chart.
- **Regression discipline:** `python evals/run_evals.py` runs the suite against a
  local stack; results append to `evals/results/history.jsonl` (committed). CI runs
  a 10-question smoke subset on PRs. README table is generated from latest results.
- **Negative tests:** questions whose answer is *not in the repo* — measures refusal
  quality ("I can't find this") vs hallucination. Hallucination rate is reported.

---

## 7. Cost & Latency Engineering (the economics chapter)

Targets (to validate in week 1–2, then publish as measured):

| Operation | Target cost | Target latency |
|---|---|---|
| Index 1,500-file repo (full) | < $1.00 | < 3 min |
| Local question | < $0.01 | < 3 s |
| Global question | < $0.02 | < 5 s |
| Escalated question | < $0.15 | < 60 s |
| Incremental re-index (typical commit) | < $0.05 | < 30 s |

Levers, in order of leverage:

1. **Static-first graph** — the single biggest saving; the LLM never reads the repo
   "to find out what's there."
2. **Tiered models** — Flash for volume (summaries, explorers, router), Pro only for
   planning/synthesis/criticism.
3. **Persisted graph + write-back** — repeat and similar questions never re-explore.
4. **Bottom-up summaries** — prompts stay small; invalidation stays local.
5. **Context caching** on stable prefixes (skeleton, community summaries).
6. **Batching** symbol summaries (many symbols per call with structured output).
7. **Semantic answer cache** — embed questions; near-duplicate (cosine > threshold)
   against a *verified* prior answer on the same commit → serve cached, marked as such.

Every README cost number is generated from real accounting data (§4.2), with the
measurement date.

### 7.1 Cost accounting (billing-ready, zero price upkeep)

Cost is a **product feature and a future billing input**, not just ops telemetry —
it powers the live cost ticker, the per-question transparency strip, per-run
totals, future per-user budgets, and eventual metered billing. So the cost
**number** is stored in **our own Postgres** (`index_runs.cost_usd`,
`questions.cost_usd`), where billing and the UI can read it directly.

**We maintain zero model prices.** LangSmith traces every model call and
**computes the cost itself** against the price map *it* maintains (current pricing
for OpenAI/Anthropic/Gemini, no upkeep on our side). We read the computed cost
back per run (`run.total_cost` via the LangSmith SDK) and persist it as our
record:

```
model call ──▶ LangSmith trace + cost (their maintained prices)
                      │  read run.total_cost (SDK)
   our pipeline ──────┴──▶ index_runs.cost_usd / questions.cost_usd (our Postgres)
                            → ticker, transparency strip, billing record
```

Key properties and honest caveats:

- **No hardcoded price table on our side.** Earlier drafts proposed syncing
  LangSmith's price map into our DB — **not possible: LangSmith exposes no API to
  read the price map** (dashboard-only). But it *does* expose the **computed cost
  per run** (`total_cost`/`prompt_cost`/`completion_cost`), which is what we read.
- **Post-run, not in-request-path.** `total_cost` is available once the run is
  traced, so the live ticker fetches costs as runs complete (fine for a ~90s index
  run); it is not synchronous per-token. LangSmith labels it "estimated" — we store
  the fetched value as our authoritative record.
- **Graceful when LangSmith is off** (local dev / CI without a key): cost is
  recorded as **null / unknown, never fabricated.** Honest-missing beats
  estimated-from-a-map-we-chose-not-to-keep. Token counts (from provider
  `usage_metadata`, already free) are still recorded so a run is never opaque.
- **LangSmith tracing** doubles as run observability (the agent-fleet phase leans
  on it for debugging). Opt-in via env var, off by default, never required to run.

---

## 8. Incremental Updates & Staleness (§the part everyone skips)

The graph is keyed to a commit. On re-index request (manual button in v1; webhook
support is a v2 item):

1. `git fetch` + diff `old_commit..new_commit` → changed file set.
2. Re-parse only changed files; diff symbol sets by `content_hash` →
   add/update/remove nodes and incident edges.
3. Invalidate: summaries of changed nodes; mark containing communities `dirty`
   (and parents transitively). Re-run Leiden **only if** the structural change is
   large (> X% nodes/edges changed — else keep memberships, refresh summaries).
4. Re-summarize dirty nodes/communities bottom-up. Annotations on changed nodes are
   demoted to `unverified` (cheap critic pass re-verifies the affected ones).
5. Answers cached against the old commit are not served for the new one.

UI always shows the indexed commit + "graph is N commits behind" badge.

---

## 9. Security & Safety

Cloning and parsing **arbitrary repos** is the main risk surface:

- Clone into an isolated workspace; **size caps** (repo size, file count, file size),
  depth-1 clone, no submodule recursion, no git hooks (`--no-checkout` + explicit
  checkout, `core.hooksPath=/dev/null`).
- **We never execute repo code.** tree-sitter parses bytes; that invariant is stated
  in the README.
- Worker runs in a container with no secrets beyond its own DB/Gemini creds;
  workspace on a quota'd volume; cleanup after indexing.
- **Prompt-injection awareness:** repo content (READMEs, docstrings, code comments)
  is untrusted input to the agents. Mitigations: agents' instructions delimit repo
  content as data; the critic verifies claims against code (not comments); tools are
  read-only by construction; findings that cite no code are rejected. Documented
  honestly in the writeup as mitigated-not-solved — that honesty is itself a
  credibility signal.
- Rate limiting on `POST /repos` (it triggers paid work); allowlist of git hosts
  (github.com in v1); per-run hard budget cap with graceful abort.

---

## 9A. Private & Org Repository Access

Most repositories worth onboarding onto are **private**, so authenticated cloning
is in scope, not a v2 nicety. The public-only cloner shipped in Phase 2 is the
anonymous path; this section specifies the authenticated path layered on top of
it.

### Mechanism: GitHub OAuth App (v1)

Users connect their GitHub account via OAuth. Cartograph acts **on the user's
behalf** with a scoped token — the standard model for this product category
(Greptile, Cursor). GitHub App / installation tokens are a documented v2 upgrade
(stronger for enterprise; see §14).

**Flow:**

```
1. User clicks "Connect GitHub" → redirect to github.com OAuth authorize
   (scopes: repo read; read:org for org membership/visibility).
2. Callback → exchange code for an access token (+ refresh token if available).
3. List repos the user can read (their own + org repos their account reaches),
   including private ones → user picks one.
4. Index using the token for the clone; the graph persists, and the token is
   stored encrypted for later re-indexing (see Token handling).
```

### Org-owned private repos

**The user's own access is the authorization.** If the connecting account can read
the org repo, Cartograph can index it on their behalf — no separate per-repo org
step beyond GitHub's own OAuth-app policy.

**The one real-world wrinkle:** some orgs **block third-party OAuth apps** at the
org level. In that case GitHub simply makes the org's repos invisible to the
token — a clone/list returns 404, not a clear "denied". We detect this (repo
not visible despite a valid token) and surface an actionable message:

> "Cartograph can't see this org's repositories. Your org may restrict
> third-party OAuth apps — an org owner can approve Cartograph at
> `github.com/organizations/<org>/settings/oauth_application_policy`, or grant
> access on request."

So the access path is: **try the user's own access first; on org-policy block,
guide them to admin approval.** No silent failures.

### Token handling — encrypted at rest

Tokens are stored **encrypted at rest** so re-indexing on new commits doesn't
force re-auth (it enables the "watch for changes" feature). This is a deliberate
stored-secret surface and carries obligations:

- **Encryption:** authenticated symmetric encryption (Fernet / AES-GCM) with a
  key from the environment/KMS — **never** in the DB or repo. The DB stores only
  ciphertext.
- **Scope & least privilege:** request the narrowest scopes that work (repo
  read). Per-user tokens, never shared.
- **Revocation & expiry:** store token metadata (scopes, expiry, github login);
  support user-initiated disconnect that deletes the stored token and (best
  effort) revokes it via GitHub. Refresh-token rotation where GitHub provides it.
- **Never logged, never echoed.** Tokens are redacted from logs/errors; API
  responses never return them. Clone uses the token via an in-memory credential
  helper / URL injection, never written to the workspace `.git/config`.
- **Blast radius:** a token grants read to repos the user can read — documented
  honestly. Compromise of the encryption key is the worst case; key custody is
  the critical control (rotate on suspicion, KMS in production).

### Data model additions

```sql
github_identities (id, user_id, github_login, access_token_ciphertext,
                   refresh_token_ciphertext, scopes, token_expires_at,
                   created_at, updated_at)
-- repos gains: owner_identity_id (nullable FK — null = anonymous/public clone),
--              visibility ('public'|'private')
```

### Cloner changes

The Phase 2 cloner already routes git over HTTPS with all safety flags. Auth adds:
inject the token as an HTTP extra-header credential (`http.extraHeader`
`Authorization: Bearer …` via `-c`, not in the URL — keeps it out of process
listings and `.git/config`); on failure, distinguish **404/not-found** (private
or nonexistent — prompt auth) from **403/blocked** (org policy) from a genuine
clone error, so the API returns the right guidance. The `protocol.file.allow` and
hooks guards are unchanged.

### Build placement

This is a **dedicated phase after the Week-1 spine** (it needs the frontend's
"Connect GitHub" affordance and is orthogonal to the indexing/Q&A core). It does
**not** block the Week-1 milestone, which proves the pipeline on public repos.
Until it lands, `POST /api/repos` on a private repo returns a clear "this repo is
private — connect GitHub to index it" 403, not a cryptic clone failure.

> **Two distinct auth concerns — do not conflate (see §9B):** GitHub auth here is
> *repo-access authorization* ("can we clone this private repo"). User **identity**
> ("who is this person, what are their saved repos") is a separate layer handled by
> Google sign-in via Supabase (§9B). A user signs in with Google, then connects
> GitHub *on top* only when they try to index a private repo.

---

## 9B. User Authentication & Identity (Google via Supabase)

> **Status (2026-06-21): ✅ COMPLETE (+ "My repos" UI + UserProfile table).** The Google sign-in flow is fully wired:
> frontend (`@supabase/ssr`: browser/server clients, `proxy.ts` session refresh,
> `/auth/callback` PKCE exchange, `AuthMenu`, `useUser`) and backend (JWKS-based
> JWT validation via PyJWT at `backend/app/auth/jwt.py`, `owner_user_id` on
> repos/questions, RLS policies in migration 0006).
> 
> **Note on JWT library choice:** PyJWT was chosen over `python-jose` because
> `jose.jwk.construct()` doesn't support EC keys (needed for Supabase's ES256
> tokens). `PyJWK()` handles EC JWK keys correctly. See `backend/app/auth/jwt.py`.

User identity is separate from repo access (§9A). Identity answers "who is this
person" so users have accounts, saved/recently-indexed repos, and question
history. **Mechanism: Google sign-in via Supabase Auth.** Supabase already hosts
our Postgres, so its Auth (a managed `auth.users` table + JWT sessions + the
OAuth dance) is the low-friction choice — no second vendor.

### Flow

```
Landing / app → "Continue with Google" (supabase-js) → Google consent →
  Supabase mints a session (JWT) → frontend holds it →
  backend validates the Supabase JWT on protected routes →
  our app rows (repos, questions) gain a nullable owner_user_id.
```

- **Identity ≠ repo access.** A signed-in Google user can index *public* repos
  immediately. Indexing a *private* repo triggers the §9A "connect GitHub" prompt
  — GitHub links onto the existing identity, it is not a second login.
- **Anonymous still works** (at least in early phases): indexing a public repo
  without an account stays allowed; sign-in unlocks persistence (saved repos,
  history) and is required before connecting GitHub.

### What's needed to wire it (operator setup, one-time)

1. **Google OAuth client** (Google Cloud Console → Credentials → OAuth client ID,
   type Web): yields a **Client ID + Secret**; authorized redirect URI is the one
   Supabase shows (`https://<project>.supabase.co/auth/v1/callback`).
2. **Enable Google in Supabase** → Auth → Providers → Google → paste Client ID/Secret.
3. **Frontend keys:** Supabase **project URL + anon key** (Project Settings → API)
   for `supabase-js`. These are the public client keys — distinct from the DB
   connection string we already use for SQLAlchemy.

### Backend / data-model additions

- `auth.users` is managed by Supabase. Our tables gain a **nullable
  `owner_user_id`** (Supabase user uuid) on `repos` (and later `questions`) — null
  = anonymous/public. **This is where the RLS deny-all baseline (migration 0004)
  earns out:** real per-user ownership policies (`USING (owner_user_id = auth.uid())`)
  layer on top once identity exists.
- Backend validates the Supabase JWT (verify signature against Supabase's JWKS) on
  protected endpoints; an unauthenticated request is anonymous, not rejected,
  except for owner-scoped actions (connect GitHub, list my repos).
- The §9A encrypted GitHub token is stored against the `owner_user_id`.

### Build placement — ✅ COMPLETE

Landed in a dedicated phase after the landing page. Does not block the public-repo
demo, which stays anonymous-friendly.

---

## 10. Tech Stack Summary

| Layer | Choice | Why (one line for the writeup) |
|---|---|---|
| Language | Python 3.12 (uv) | Ecosystem for tree-sitter, LangGraph, igraph |
| API | FastAPI + Uvicorn | Async, WebSockets, Pydantic-native |
| Orchestration | LangGraph | Industry-recognizable supervisor pattern; checkpointing for run replay |
| LLM | Gemini via `google-genai` (+ `langchain-google-genai` inside LangGraph) | Two-tier Pro/Flash economics, JSON mode, context caching, long context |
| Parsing | tree-sitter (python, typescript grammars) | Incremental, language-extensible, no code execution |
| Graph algorithms | NetworkX + igraph/leidenalg | In-process; Leiden for communities; defer graph DB |
| Storage | Postgres 16 + pgvector — docker-compose locally/CI, **Supabase** (managed Postgres, free tier, pgvector built-in) for the hosted demo | One database for relational + vector + full-text (BM25-ish via tsvector). Supabase = same engine, $0 hosting; only `DATABASE_URL` changes (use the pooler/6543 string in prod). No code or schema differences. |
| Cost accounting | **LangSmith computes cost** per run (it maintains all model prices); we read `run.total_cost` back and store it in our Postgres as the billing/ticker record | Zero price-table upkeep on our side; cost lives in our DB for billing-readiness. Cost is null (not fabricated) when LangSmith is disabled — honest over estimated. See §7.1. |
| Queue | Postgres-backed job table + worker process (e.g. `arq`/custom) | One less moving part than Redis/Celery for v1 |
| Frontend | Next.js 15, TypeScript, Tailwind, shadcn/ui | Speed + polish |
| Graph viz | Sigma.js (WebGL) or react-force-graph | Smooth at 5k nodes |
| Realtime | Native WebSocket (FastAPI) + SSE for answer streaming | No extra infra |
| Deploy | docker-compose; single VM or Railway/Fly | Cheap, reproducible; live demo URL |
| CI | GitHub Actions: lint (ruff), typecheck (mypy/pyright), tests, eval smoke subset | The eval-in-CI is the differentiator |

---

## 11. Four-Week Roadmap

Each week ends in something demoable. Cut scope, never quality of what ships.

> **Progress (2026-06-24, ✅ done · ⚠️ partial · ❌ not built):** Week 1 DONE and
> proven on live data; the Chat UI (Week 3) + landing/auth built early; Week 2's
> agent fleet is ✅ built (supervisor topology + event stream, minus Leiden
> communities and the query router). Overall v1 ≈ 70%. The big remaining piece is
> the Mission Control / Atlas frontend that renders the fleet. Live log: `STATUS.md`.

### Week 1 — The spine (static graph + local Q&A) — ✅ DONE
- ✅ Repo scaffolding, docker-compose, CI skeleton.
- ✅ Cloner + tree-sitter extraction (Python) → nodes/edges in Postgres.
- ✅ Batched node summaries + embeddings; hybrid retrieval (BM25 + dense + 1-hop).
- ✅ Local-route Q&A with **citation verification** (verified on real data).
- ✅ REST demo + first real cost (LangSmith). Now running on Supabase.
- ✅ **Milestone hit:** asked pybktree real questions → correct, verified citations.

### Week 2 — The fleet (multi-agent enrichment + GraphRAG) — ⚠️ MOSTLY DONE
- ✅ Supervisor topology: planner → parallel explorers → synthesizer → critic → librarian.
- ✅ Agent tools, structured findings, write-back (Node.annotations), run budgets,
  event log + replay/WS API. Tested (`tests/integration/test_fleet.py`).
- ❌ Leiden communities + hierarchical summaries; global route; router; escalation
  route with write-back. (The escalation route can reuse the fleet's explorer.)
- ❌ TypeScript grammar support.
- ❌ **Milestone:** full index run with event log; global question from community summaries.

### Week 3 — The face (UI) — ⚠️ PARTIAL (Chat + Landing done; the big views not)
- ⚠️ Next.js app: ✅ **Chat** (working — threaded Q&A, verified citation chips,
  transparency strip; ❌ code panel on chip click). ✅ **Landing page** (brand
  surface, with a 3D R3F hero graph + a live verified-citation terminal).
  ✅ **Google sign-in** (Supabase, frontend wired; backend `owner_user_id` TODO).
  ❌ **Mission Control** (live WS). ❌ **Atlas** (semantic-zoom graph).
- ❌ Onboarding walkthrough generation + overlay.
- ✅ Design tokens (DESIGN.md, dark instrument-panel) wired; ⚠️ design/polish pass
  done on the landing + chat, not the (unbuilt) big views; ❌ the screen-recordable demo.
- ❌ **Milestone:** the 2-minute demo recording.

### Week 4 — The proof (evals, hardening, launch) — ❌ NOT STARTED
- ❌ Eval datasets, full harness, results history, CI smoke subset, README table + cost chart.
- ❌ Incremental re-index; security hardening checklist (§9); per-run budget cap.
  (✅ deny-all RLS on the DB; ✅ LLM rate limiter.)
- ❌ Deploy live demo (Supabase DB is live; app not deployed).
- ❌ **Writeup** + publish.
- ❌ **Milestone:** public URL + repo + writeup + video.

### Net remaining, by area (see STATUS.md for the itemized checklist)
- **Backend:** router/global/escalate routes, communities, markdown+TS extractors,
  worker+queue, WebSocket event stream, graph/walkthrough APIs, OAuth, incremental re-index.
- **Frontend:** Mission Control, Atlas, code panel, app shell + drawer, event store,
  "my repos"/history. (✅ landing page, ✅ 3D hero, ✅ Google sign-in frontend, ✅ Chat.)
- **Agent fleet:** ✅ §2.2 topology built (planner→explorers→synthesizer→critic→
  librarian + event stream). Remaining around it: Leiden communities, the query
  router/global/escalate routes, and the Mission Control UI that renders the stream.
- **Cross-cutting:** eval harness, deploy/demo/writeup.

### Explicit cut-line (if behind schedule)
Cut in this order: TypeScript support → onboarding walkthrough overlay → semantic
answer cache → incremental re-index (ship "re-index = full re-run" with the design
documented). **Never cut:** citation verification, the critic, evals, mission control.

---

## 12. Risks & Mitigations

| Risk | Likelihood | Mitigation |
|---|---|---|
| Static call-graph accuracy in dynamic Python (decorators, DI, dynamic dispatch) | High | Confidence-scored edges; explorers verify/annotate hot paths; never present low-confidence edges as fact in answers |
| Multi-agent indexing cost blows the < $1 target on big repos | Medium | Hard budgets; explorer count scales with repo size; degrade to "static + summaries only" mode above thresholds, clearly labeled |
| Force-graph UI chokes on large repos | Medium | Semantic zoom = render communities not nodes at distance; cap rendered nodes; WebGL renderer |
| Gemini JSON-mode drift / schema violations breaking agent pipeline | Medium | Pydantic validation + single retry-with-error; dead-letter findings logged, run continues without them |
| LLM-judge eval unconvincing to skeptics | Medium | Lead with mechanical citation precision/recall; publish judge prompts; hand-audited sample |
| "Another codebase-chat tool" dismissal | Medium | Branding + demo lead with *watch agents map*, the verification loop, and the economics — not the chat |
| Prompt injection via repo content | Low-Med | §9 mitigations; documented honestly |
| Scope creep (it's a fun project) | High | This plan's non-goals + cut-line are the contract; weekly milestone check against §11 |

---

## 13. Success Criteria

**Portfolio (primary):**
- A 2-minute demo that an AI engineer finds technically impressive without explanation.
- README with architecture diagram, real eval table, real cost chart — readable in 3 minutes.
- A writeup whose architecture decisions can carry a 45-minute interview conversation.
- Stretch: 200+ GitHub stars / front-page Show HN — distribution proof for clients.

**Product:**
- Citation precision ≥ 0.9 on the eval suite; hallucinated-citation rate shown ~0
  *post-verification* (the verifier makes this true by construction — report the
  pre-verification rate too, honestly).
- Cost targets in §7 met and published.
- A stranger can index their own mid-size repo unassisted and get value in < 5 minutes.

---

## 14. v2 Backlog (explicitly deferred)

GitHub webhook auto-reindex · PR-diff explanation mode ("what does this PR actually
change, architecturally?") · more languages (Go, Java, Rust) · cross-repo graphs ·
team memory (per-org annotation layers) · MCP server exposing the graph as tools to
other agents (strong ecosystem play — Cartograph becomes infrastructure) · VS Code
extension · auth/billing if it grows beyond portfolio.
