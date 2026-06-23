"""The enrichment supervisor — wires the agent fleet into one run (PLAN.md §2.2).

Topology (supervisor pattern):

    planning   → planner produces an ExplorationPlan (3-8 subsystems)
    exploring  → N explorers run IN PARALLEL (capped by max_agent_concurrency),
                 one per subsystem, each emitting structured findings
    synthesis  → synthesizer merges findings into a RepoModel
    critique   → critic verifies findings against real code; rejected findings
                 go back to their explorer for ONE revision round, then are
                 dropped; accepted findings proceed
    writing    → librarian persists accepted findings + the RepoModel into the
                 graph, attributed (source, verified-by-critic, run_id)

Every phase transition and agent action publishes an event (EventEmitter →
agent_events table → live WS). The whole run is bounded by:
  - a per-run cost budget (max_run_cost_usd) checked between phases,
  - a wall-clock timeout (the whole run is wrapped in asyncio.timeout),
  - per-explorer tool-call/step caps (enforced inside the explorer).

This is deliberately a direct async orchestration rather than a LangGraph
StateGraph object: it maps 1:1 to the supervisor pattern, stays transparent and
unit-testable with a fake LLM, and avoids coupling LangGraph's checkpointer to our
SQLAlchemy session. The phase names above are the supervisor's states.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents import llm
from app.agents.critic import critique
from app.agents.events import EventEmitter
from app.agents.explorer import explore_subsystem
from app.agents.librarian import persist
from app.agents.planner import plan
from app.agents.schemas import ExplorerReport, Finding, Subsystem
from app.agents.synthesizer import synthesize
from app.config import get_settings
from app.db.enums import AgentEventType, AgentRole

log = structlog.get_logger(__name__)

# Whole-run wall-clock cap (seconds). Generous on free tier (rate-limited), but
# bounded so a stuck run can't hang indexing forever.
_RUN_TIMEOUT_S = 900


@dataclass(slots=True)
class FleetResult:
    """Outcome of an enrichment run, for the pipeline to record."""

    subsystems: int = 0
    findings: int = 0
    accepted: int = 0
    annotations_written: int = 0
    ledger: llm.UsageLedger = field(default_factory=llm.UsageLedger)
    error: str | None = None


class _BudgetExceeded(Exception):
    """Raised between phases when the run's cost budget is spent."""


def _check_budget(ledger: llm.UsageLedger) -> None:
    spent = ledger.total_usd
    cap = get_settings().max_run_cost_usd
    if spent is not None and spent >= cap:
        raise _BudgetExceeded(f"run cost ${spent:.2f} ≥ cap ${cap:.2f}")


async def _explore_all(
    repo_id: uuid.UUID,
    subsystems: list[Subsystem],
    emitter: EventEmitter,
    ledger: llm.UsageLedger,
) -> list[ExplorerReport]:
    """Run explorers in parallel, capped by max_agent_concurrency. Each explorer
    gets its OWN read session — a single async SQLAlchemy session can't be shared
    across concurrent coroutines. A failed explorer yields an empty report rather
    than killing the run."""
    from app.db.session import get_sessionmaker

    sem = asyncio.Semaphore(get_settings().max_agent_concurrency)
    sessionmaker = get_sessionmaker()

    async def _one(sub: Subsystem) -> ExplorerReport:
        async with sem:
            try:
                async with sessionmaker() as ex_session:
                    return await explore_subsystem(
                        subsystem=sub,
                        session_repo=(ex_session, repo_id),
                        emitter=emitter,
                        ledger=ledger,
                    )
            except Exception as exc:  # noqa: BLE001 — one explorer must not kill the run
                log.warning("fleet.explorer_failed", subsystem=sub.name, error=str(exc))
                await emitter.emit(
                    AgentRole.EXPLORER,
                    AgentEventType.ERROR,
                    {"label": f"explorer:{sub.name}", "error": str(exc)},
                )
                return ExplorerReport(subsystem=sub.name, findings=[])

    return await asyncio.gather(*(_one(s) for s in subsystems))


async def _run(
    session: AsyncSession, repo_id: uuid.UUID, emitter: EventEmitter, ledger: llm.UsageLedger
) -> FleetResult:
    result = FleetResult(ledger=ledger)

    # ── planning ──
    await emitter.emit(AgentRole.SUPERVISOR, AgentEventType.PHASE, {"phase": "planning"})
    await emitter.emit(AgentRole.PLANNER, AgentEventType.SPAWN, {})
    plan_out = await plan(session, repo_id, ledger=ledger)
    result.subsystems = len(plan_out.subsystems)
    await emitter.emit(
        AgentRole.PLANNER,
        AgentEventType.DONE,
        {"overview": plan_out.overview, "subsystems": [s.name for s in plan_out.subsystems]},
    )
    if not plan_out.subsystems:
        return result

    # ── exploring (parallel) ──
    _check_budget(ledger)
    await emitter.emit(
        AgentRole.SUPERVISOR,
        AgentEventType.PHASE,
        {"phase": "exploring", "explorers": len(plan_out.subsystems)},
    )
    reports = await _explore_all(repo_id, plan_out.subsystems, emitter, ledger)
    all_findings: list[tuple[Finding, str]] = [
        (f, r.subsystem) for r in reports for f in r.findings
    ]
    result.findings = len(all_findings)
    if not all_findings:
        return result

    # ── synthesis ──
    _check_budget(ledger)
    await emitter.emit(AgentRole.SUPERVISOR, AgentEventType.PHASE, {"phase": "synthesis"})
    await emitter.emit(AgentRole.SYNTHESIZER, AgentEventType.SPAWN, {})
    repo_model = await synthesize(plan_out, reports, ledger=ledger)
    await emitter.emit(
        AgentRole.SYNTHESIZER,
        AgentEventType.DONE,
        {
            "summary": repo_model.summary,
            "flows": len(repo_model.flows),
            "walkthrough_steps": len(repo_model.walkthrough),
        },
    )

    # ── critique (with one revision round for rejects) ──
    _check_budget(ledger)
    await emitter.emit(AgentRole.SUPERVISOR, AgentEventType.PHASE, {"phase": "critique"})
    await emitter.emit(AgentRole.CRITIC, AgentEventType.SPAWN, {})

    from app.agents.tools import RepoTools

    tools = RepoTools(session=session, repo_id=repo_id)
    findings_only = [f for f, _ in all_findings]
    source_by_text = {(f.target_fqname, f.text): src for f, src in all_findings}

    report = await critique(findings_only, tools, ledger=ledger)
    accepted: list[tuple[Finding, str]] = []
    rejected: list[Finding] = []
    by_key = {(f.target_fqname, f.text): f for f in findings_only}
    for v in report.verdicts:
        await emitter.emit(
            AgentRole.CRITIC,
            AgentEventType.VERDICT,
            {
                "target": v.target_fqname,
                "accepted": v.accepted,
                "reason": v.reason,
                "text": v.finding_text,
            },
        )
        f = by_key.get((v.target_fqname, v.finding_text))
        if f is None:
            continue
        if v.accepted:
            accepted.append((f, source_by_text[(f.target_fqname, f.text)]))
        else:
            rejected.append(f)

    # One revision round: re-critique the rejected findings once. (A full
    # explorer-revision loop is a future refinement; re-judging catches flaky
    # rejects cheaply without another exploration pass.)
    if rejected:
        _check_budget(ledger)
        recheck = await critique(rejected, tools, ledger=ledger)
        for v in recheck.verdicts:
            f = by_key.get((v.target_fqname, v.finding_text))
            if v.accepted and f is not None:
                accepted.append((f, source_by_text[(f.target_fqname, f.text)]))
                await emitter.emit(
                    AgentRole.CRITIC,
                    AgentEventType.VERDICT,
                    {
                        "target": v.target_fqname,
                        "accepted": True,
                        "reason": v.reason,
                        "text": v.finding_text,
                        "revised": True,
                    },
                )
    result.accepted = len(accepted)

    # ── writing ──
    await emitter.emit(AgentRole.SUPERVISOR, AgentEventType.PHASE, {"phase": "writing"})
    await emitter.emit(AgentRole.LIBRARIAN, AgentEventType.SPAWN, {})
    written = await persist(
        session, repo_id, run_id=emitter.run_id, accepted=accepted, repo_model=repo_model
    )
    result.annotations_written = written
    await emitter.emit(AgentRole.LIBRARIAN, AgentEventType.DONE, {"annotations": written})
    return result


async def run_enrichment_fleet(
    session: AsyncSession,
    repo_id: uuid.UUID,
    *,
    run_id: uuid.UUID,
    event_session: AsyncSession,
    ledger: llm.UsageLedger | None = None,
) -> FleetResult:
    """Run the full enrichment fleet for a repo. Entry point for the pipeline.

    `session` is the agents' work session (graph reads + librarian writes).
    `event_session` is a SEPARATE session dedicated to event persistence, so
    emitting events (which commits) never interferes with the work transaction.
    The caller commits `session` after this returns.
    """
    ledger = ledger or llm.UsageLedger()
    emitter = EventEmitter(run_id, event_session)
    await emitter.emit(AgentRole.SUPERVISOR, AgentEventType.SPAWN, {"repo_id": str(repo_id)})

    try:
        async with asyncio.timeout(_RUN_TIMEOUT_S):
            result = await _run(session, repo_id, emitter, ledger)
        await emitter.emit(
            AgentRole.SUPERVISOR,
            AgentEventType.DONE,
            {
                "findings": result.findings,
                "accepted": result.accepted,
                "annotations": result.annotations_written,
                **ledger.summary(),
            },
        )
        log.info(
            "fleet.done",
            repo_id=str(repo_id),
            **{
                "subsystems": result.subsystems,
                "findings": result.findings,
                "accepted": result.accepted,
                "written": result.annotations_written,
            },
        )
        return result
    except (TimeoutError, _BudgetExceeded) as exc:
        msg = "timeout" if isinstance(exc, TimeoutError) else str(exc)
        await emitter.emit(
            AgentRole.SUPERVISOR, AgentEventType.ERROR, {"error": msg, "stopped": "budget/timeout"}
        )
        log.warning("fleet.stopped", repo_id=str(repo_id), reason=msg)
        return FleetResult(ledger=ledger, error=msg)
    except Exception as exc:  # noqa: BLE001 — enrichment failure must not fail the index
        await emitter.emit(AgentRole.SUPERVISOR, AgentEventType.ERROR, {"error": str(exc)})
        log.error("fleet.failed", repo_id=str(repo_id), error=str(exc))
        return FleetResult(ledger=ledger, error=str(exc))
