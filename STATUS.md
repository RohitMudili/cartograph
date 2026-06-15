# Cartograph — Build Status

_Working log for picking up where we left off. Not the plan (see PLAN.md) — this
is "where are we right now and what's next."_

**Last updated:** 2026-06-15

---

## 🎉 Week 1 is COMPLETE — the backend spine works end to end

You can now: **paste a repo → it's indexed → ask a question → get an answer
grounded in real code with VERIFIED `file:line` citations.** Proven on live data
against Supabase. This is the core product value, working.

### Done & verified

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

### Tests: 46 passing, CI green. Lint / format / pyright all clean.

---

## ⚠️ Throughput note (not a blocker)

**Gemini free tier ≈ 10 RPM** — fine for small repos (pybktree indexed in ~65s),
too slow for big ones (~427-symbol repo ≈ 43 min). Multi-key rotation was tried
and reverted (Google blocks per-account). **A paid Gemini key is the fix:** set it
in `.env` and bump `LLM_RPM=1000` for full-speed indexing (~$0.10/mid-size repo).
Until then, develop/test on small repos — fully unblocked.

---

## What's next (remaining for v1)

In rough priority / dependency order:

- **Frontend so far:** ✅ home (paste-a-repo) + ✅ Chat console (working, demoed
  live). Remaining UI: Mission Control + Atlas graph view.
1. **Answer quality (task #20)** — index markdown/README (DOC node per section) +
   question-type-aware prompting. A real, observed gap: onboarding answers are
   correct+cited but read like flat API docs. #1 (markdown indexing) is a small
   isolated win, landable anytime. See PLAN.md §2.3 Answer Quality.
2. **Multi-agent LangGraph fleet** — planner → explorers → synthesizer → critic;
   GraphRAG community summaries; WebSocket event stream. The "watch agents
   explore" centerpiece; feeds Mission Control.
3. **Atlas + Mission Control UI** — the remaining views (replay-first).
4. **Eval harness** — golden Q&A + citation precision/recall + answer-quality
   scoreboard (the credibility moat; also grades task #20).
5. **GitHub OAuth** (task #15) — private/org repo access; PLAN.md §9A.
6. **Deploy + demo video + writeup.**

Est. ~3 weeks. The core value (cited Q&A) is already demoable in the browser today.

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
