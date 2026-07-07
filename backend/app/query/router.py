"""Query router — local / global / escalate (PLAN.md §2.3).

One entry point (`answer_question`) that decides how a question is answered:

- **global** — big-picture questions (architecture / onboarding) when repo-level
  knowledge exists: the answer is grounded in the synthesized RepoModel and the
  Leiden community summaries in addition to retrieval, so "how does this all fit
  together" doesn't depend on the right 10 chunks surfacing.
- **local** — everything else: the hybrid-retrieval path (with verified per-node
  annotations merged in by the answerer).
- **escalate** — when the first pass comes back unanswerable and an LLM is
  available: spawn ONE scoped explorer, verify its findings, WRITE THEM BACK to
  the graph, and answer once more. The graph learns; the next asker pays cents.

The route label is recorded on the persisted Question so the UI's transparency
strip can show how the answer was produced.
"""

from __future__ import annotations

import uuid

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.llm import UsageLedger
from app.config import get_settings
from app.query.answerer import Answer, Answerer, QuestionClassifier, QuestionType
from app.query.enrichment import load_community_summaries, load_repo_model
from app.query.escalation import escalate_and_write_back

log = structlog.get_logger(__name__)

# Question types whose best context is repo-level knowledge, not one symbol.
_GLOBAL_TYPES = {QuestionType.ARCHITECTURE, QuestionType.ONBOARDING}


async def answer_question(
    session: AsyncSession,
    repo_id: uuid.UUID,
    question: str,
    *,
    session_context: str | None = None,
    ledger: UsageLedger | None = None,
) -> Answer:
    """Route and answer one question. See module docstring for the routes."""
    qtype = await QuestionClassifier.classify(question, ledger=ledger)

    repo_model = None
    community_lines: list[str] = []
    route = "local"
    if qtype in _GLOBAL_TYPES:
        repo_model = await load_repo_model(session, repo_id)
        community_lines = await load_community_summaries(session, repo_id)
        if repo_model or community_lines:
            route = "global"

    answerer = Answerer(session, repo_id)
    ans = await answerer.answer(
        question,
        session_context=session_context,
        ledger=ledger,
        qtype=qtype,
        repo_model=repo_model,
        community_lines=community_lines,
        route=route,
    )

    # Escalate: the graph couldn't support an answer. One scoped explorer digs,
    # verified findings are written back, and we answer once more against the
    # now-smarter graph.
    if not ans.answerable and get_settings().llm_available:
        log.info("route.escalating", repo_id=str(repo_id), qtype=qtype.value)
        written = await escalate_and_write_back(
            session, repo_id, question, seed_node_ids=ans.used_nodes, ledger=ledger
        )
        if written > 0:
            ans = await answerer.answer(
                question,
                session_context=session_context,
                ledger=ledger,
                qtype=qtype,
                repo_model=repo_model,
                community_lines=community_lines,
                route="escalate",
            )

    return ans
