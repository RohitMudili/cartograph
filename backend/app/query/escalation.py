"""Escalation route — a scoped live explorer for questions the graph can't answer.

When retrieval + the enriched graph still can't support an answer, we spawn ONE
explorer agent scoped to the question (same agent, tools, and critic as the
indexing fleet), verify its findings against the code, and **write the accepted
ones back into the graph** before answering again. That write-back is the core
product thesis: the graph is a learning cache, so this question is cheap next
time (PLAN.md §2.3).

Recorded as an `IndexRun(kind=ESCALATION)` so cost and provenance are attributed;
best-effort — a failed escalation just means the original "can't answer" stands.
"""

from __future__ import annotations

import datetime as dt
import uuid

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents import llm
from app.agents.critic import critique
from app.agents.explorer import explore
from app.agents.librarian import persist
from app.agents.schemas import Subsystem
from app.agents.tools import RepoTools
from app.db.enums import RunKind, RunStatus
from app.db.models import IndexRun, Node

log = structlog.get_logger(__name__)


async def _noop_emit(*_args: object, **_kwargs: object) -> None:
    """Escalations are single-agent and short; no event stream needed."""


async def escalate_and_write_back(
    session: AsyncSession,
    repo_id: uuid.UUID,
    question: str,
    *,
    seed_node_ids: list[int],
    ledger: llm.UsageLedger | None = None,
) -> int:
    """Run one scoped explorer for `question`; persist verified findings.

    Returns the number of annotations written (0 if nothing survived the critic
    or the explorer failed). Never raises — escalation is best-effort.
    """
    run = IndexRun(repo_id=repo_id, kind=RunKind.ESCALATION, status=RunStatus.RUNNING)
    session.add(run)
    await session.flush()

    try:
        # Seed the explorer with whatever retrieval *did* find — even weak hits
        # anchor the exploration in the right neighborhood.
        seeds = (
            (await session.execute(select(Node.fqname).where(Node.id.in_(seed_node_ids[:6]))))
            .scalars()
            .all()
            if seed_node_ids
            else []
        )
        subsystem = Subsystem(
            name="escalation",
            brief=(
                "A user asked a question the current graph couldn't answer. "
                f"Investigate the code to answer it: {question!r}. Emit findings "
                "that capture what you learn, targeting the relevant symbols."
            ),
            seed_fqnames=list(seeds),
        )
        tools = RepoTools(session=session, repo_id=repo_id)
        ledger = ledger or llm.UsageLedger()

        report = await explore(
            subsystem=subsystem,
            tools=tools,
            emit=_noop_emit,
            label="explorer:escalation",
            ledger=ledger,
        )
        if not report.findings:
            run.status = RunStatus.SUCCEEDED
            run.finished_at = dt.datetime.now(dt.UTC)
            await session.flush()
            return 0

        verdicts = await critique(report.findings, tools, ledger=ledger)
        by_key = {(f.target_fqname, f.text): f for f in report.findings}
        accepted = [
            (f, "explorer:escalation")
            for v in verdicts.verdicts
            if v.accepted and (f := by_key.get((v.target_fqname, v.finding_text))) is not None
        ]
        written = await persist(session, repo_id, run_id=run.id, accepted=accepted, repo_model=None)

        run.status = RunStatus.SUCCEEDED
        run.token_usage = ledger.summary()
        run.cost_usd = ledger.total_usd or 0.0
        run.finished_at = dt.datetime.now(dt.UTC)
        await session.flush()
        log.info(
            "escalation.done",
            repo_id=str(repo_id),
            findings=len(report.findings),
            written=written,
        )
        return written
    except Exception as exc:  # noqa: BLE001 — best-effort; the original answer stands
        run.status = RunStatus.FAILED
        run.error = f"{type(exc).__name__}: {exc}"
        run.finished_at = dt.datetime.now(dt.UTC)
        await session.flush()
        log.warning("escalation.failed", repo_id=str(repo_id), error=str(exc)[:160])
        return 0
