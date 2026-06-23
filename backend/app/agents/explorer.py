"""Explorer — investigates one subsystem and emits structured findings.

Genuinely agentic: a bounded tool-use loop. Each step the explorer (fast tier)
picks one tool to learn more about its territory, or decides it's seen enough and
emits findings. The loop is capped by a tool-call budget and an iteration cap so a
confused explorer can't run away (PLAN.md §2.2 "hard budgets"). N explorers run in
parallel, one per subsystem.

Findings are CLAIMS, not facts — the critic verifies them against real code before
the librarian persists them.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

import structlog

from app.agents import llm
from app.agents.events import EventEmitter
from app.agents.schemas import ExplorerReport, ExplorerStep, Finding, Subsystem
from app.agents.tools import RepoTools
from app.db.enums import AgentEventType, AgentRole

log = structlog.get_logger(__name__)

_SYSTEM = (
    "You are an explorer agent investigating ONE subsystem of a codebase. You have "
    "tools to read the graph and source. Work in steps: each step, either call one "
    "tool to learn more, or finish by emitting findings. Be efficient — you have a "
    "limited tool budget. Findings must be concrete, specific claims about THIS "
    "subsystem, each targeting a real symbol (fqname) you've seen in the graph. "
    "Good findings: a symbol's role ('this is the auth boundary'), a key flow, a "
    "code smell, or a surprise. Each finding needs evidence (a symbol, path:line, or "
    "short quote). Do not invent symbols or claims you haven't verified with a tool."
)

# Per-explorer caps (the orchestrator can tighten via args).
_MAX_STEPS = 8
_MAX_TOOL_CALLS = 10


async def _run_tool(tools: RepoTools, action: str, arg: str) -> object:
    """Dispatch one tool action; return its result (or an error dict)."""
    if action == "read_file":
        return await tools.read_file(arg)
    if action == "get_node":
        return await tools.get_node(arg)
    if action == "get_neighbors":
        return await tools.get_neighbors(arg)
    if action == "search_graph":
        return await tools.search_graph(arg)
    if action == "grep":
        return await tools.grep(arg)
    return {"error": f"unknown tool '{action}'"}


async def explore(
    *,
    subsystem: Subsystem,
    tools: RepoTools,
    emit: Callable[[AgentRole, AgentEventType, dict], Awaitable[object]],
    label: str,
    ledger: llm.UsageLedger,
    max_steps: int = _MAX_STEPS,
    max_tool_calls: int = _MAX_TOOL_CALLS,
) -> ExplorerReport:
    """Explore one subsystem and return its findings.

    `emit` publishes events tagged with this explorer's `label` (e.g. 'explorer:auth')
    so the live feed attributes activity correctly. `label` is carried in payloads.
    """
    model = llm.fast(ledger)
    transcript: list[str] = [
        f"Subsystem: {subsystem.name}\nBrief: {subsystem.brief}",
        f"Seed paths: {', '.join(subsystem.seed_paths) or '(none)'}",
        f"Seed symbols: {', '.join(subsystem.seed_fqnames) or '(none)'}",
    ]
    findings: list[Finding] = []

    for _step in range(max_steps):
        if tools.calls >= max_tool_calls:
            transcript.append("[budget] tool-call budget reached — finish and report findings now.")
        prompt = (
            "\n\n".join(transcript)
            + "\n\nDecide your next step. If you have enough to report concrete findings "
            "for this subsystem, set action='done' and include them. Otherwise call one tool."
        )
        decision = await model.complete_structured(prompt, ExplorerStep, system=_SYSTEM)

        if decision.action == "done" or tools.calls >= max_tool_calls:
            findings = decision.findings
            break

        await emit(
            AgentRole.EXPLORER,
            AgentEventType.TOOL_CALL,
            {
                "label": label,
                "tool": decision.action,
                "arg": decision.arg,
                "why": decision.reasoning,
            },
        )
        result = await _run_tool(tools, decision.action, decision.arg)
        # Feed the result back into the loop, trimmed so the transcript stays bounded.
        transcript.append(f"[{decision.action}({decision.arg})] → {str(result)[:1500]}")

    # Tag each finding with the owning subsystem (the critic/librarian need it).
    for f in findings:
        await emit(
            AgentRole.EXPLORER,
            AgentEventType.FINDING,
            {
                "label": label,
                "subsystem": subsystem.name,
                "target": f.target_fqname,
                "kind": f.kind,
                "text": f.text,
            },
        )
    log.info(
        "explorer.done", subsystem=subsystem.name, findings=len(findings), tool_calls=tools.calls
    )
    return ExplorerReport(subsystem=subsystem.name, findings=findings)


async def explore_subsystem(
    *,
    subsystem: Subsystem,
    session_repo: tuple,
    emitter: EventEmitter,
    ledger: llm.UsageLedger,
) -> ExplorerReport:
    """Convenience entry used by the orchestrator: builds tools, runs explore().

    `session_repo` is (AsyncSession, repo_id). Each explorer gets its own RepoTools
    (its own call counter) so budgets are per-explorer.
    """
    session, repo_id = session_repo
    tools = RepoTools(session=session, repo_id=repo_id)
    label = f"explorer:{subsystem.name}"

    async def _emit(role: AgentRole, etype: AgentEventType, payload: dict) -> object:
        return await emitter.emit(role, etype, payload)

    await _emit(
        AgentRole.EXPLORER,
        AgentEventType.SPAWN,
        {"label": label, "subsystem": subsystem.name, "brief": subsystem.brief},
    )
    return await explore(subsystem=subsystem, tools=tools, emit=_emit, label=label, ledger=ledger)
