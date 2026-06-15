# Cartograph — Build Status

_Working log for picking up where we left off. Not the plan (see PLAN.md) — this
is "where are we right now and what's next."_

**Last updated:** 2026-06-15

---

## Where we are

Backend is built through the **semantic layer**. The full indexing pipeline works
end to end: clone a repo → static graph (tree-sitter) → summaries + embeddings.
Everything is committed, CI-green, and runs against **Supabase** (live) for local
dev + a throwaway Postgres in CI.

### Done & verified

- **Foundations** — FastAPI, async SQLAlchemy, health/readiness, Docker, CI.
- **Static indexer** — sandboxed cloner (private-repo detection, fast-fail),
  tree-sitter Python extractor, graph builder (cross-file imports/calls/inherits
  with confidence scores), pipeline + `POST /api/repos`. Verified on a real
  GitHub repo (psf/cachecontrol: 296 nodes / 658 edges).
- **Provider-agnostic LLM layer** — LangChain `init_chat_model`; Gemini/OpenAI/
  Anthropic swappable via `.env`. Cost via **LangSmith** (no hardcoded prices),
  stored in our DB.
- **Semantic layer** — bottom-up symbol summaries + pgvector embeddings, gated on
  `llm_available` (skips cleanly with no key).
- **Rate limiter** — token-bucket paces LLM calls to `LLM_RPM` (default 10) so we
  don't trip Gemini free-tier 429s; retry backs off hard on rate limits.
- **Infra** — Supabase wired (async driver + pgbouncer `statement_cache_size=0`
  fix); migrations applied to Supabase (head = **0004**).
- **RLS** — deny-all RLS enabled on every table (migration 0004). Backend
  connects as `postgres` (BYPASSRLS) so it's unaffected; anon/public gets
  nothing. Verified the backend still queries with RLS on.

### Tests: 34 passing, CI green. Lint/format/pyright all clean.

---

## ✅ Validated on real data (2026-06-15)

Indexed a small real repo (benhoyt/pybktree) end-to-end with **real Gemini calls
against live Supabase** — no 429s, ~65s with the rate limiter at 10 RPM:
9 nodes → 9 real summaries + 9 summary embeddings + 9 chunk embeddings, all
persisted to Supabase. Summaries are accurate ("implements a Burkhard-Keller tree
… for efficient proximity search"). The full pipeline (clone → graph → summaries
→ embeddings) is **proven**, not just correct-by-construction.

## ⚠️ Throughput note (not a blocker)

**Gemini free tier ≈ 10 RPM** — too slow to index a real repo (paygraph's ~427
symbols would take ~43 min, and the free tier 429s under load). We:
- Built the rate limiter (correct floor — never crashes, just paces).
- Tried multi-key rotation → **Google blocks it** (per-account limits). Reverted.
- **Decision: user is getting a PAID Gemini key.** Once set, bump `LLM_RPM` to
  1000+ in `.env` and indexing runs full-speed (~$0.10 / paygraph, per estimate).

**What this means:** the semantic layer is *correct by construction and unit-tested
with fakes*, but has **not yet completed a full real-API run** end to end. The
first thing to do tomorrow with the paid key is exactly that — index a real repo
and watch summaries + embeddings + real LangSmith cost populate.

---

## First thing tomorrow (with the paid key)

1. In `backend/.env`: set the paid `GOOGLE_API_KEY`, set `LLM_RPM=1000`.
2. Real end-to-end index of a small repo to validate the LLM path:
   ```
   cd backend
   uv run python -c "import asyncio; from app.db.session import session_scope, dispose_engine; \
   from app.indexer.pipeline import index_repo; \
   asyncio.run((lambda: __import__('asyncio').get_event_loop())())"  # (use the driver we had)
   ```
   (Or just ask Claude to run the paygraph index — the driver snippet is in the
   chat history.)
3. Confirm: nodes have `summary` + `summary_embedding`, chunks have `embedding`,
   `index_runs.cost_usd` is populated from LangSmith.

## Then: resume the build (Phase 4)

- **Task #13** — hybrid retrieval (BM25 + pgvector dense + graph expansion).
- **Task #14** — local-route Q&A + citation verification. **This is the Week-1
  finish line** ("ask the graph a question, get a verified `file:line` answer").

Remaining v1 after that: multi-agent LangGraph fleet, the whole frontend, eval
harness, GitHub OAuth (task #15), deploy + demo + writeup. Est. ~3-4 weeks.

---

## Housekeeping / notes

- **🔑 ROTATE EXPOSED KEYS:** the Google + LangSmith keys and Supabase password
  were pasted into the build chat. They're gitignored (never committed) but
  should be rotated since they appeared in a transcript.
- `.env` is configured and working (Supabase + Gemini + LangSmith all wired).
- Local dev DB = Supabase (needs internet). CI = throwaway Postgres (isolated).
- `LLM_RPM` is the throughput knob — 10 for free tier, 1000+ for paid.
