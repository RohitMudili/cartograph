"""Synthesizer — merges explorer findings into one coherent repo model.

Takes every explorer's findings and the planner's overview and produces the
repo-level model: per-subsystem descriptions, cross-cutting flows, and an ordered
onboarding walkthrough. Reasoning-tier; one structured call (PLAN.md §2.2).
"""

from __future__ import annotations

import structlog

from app.agents import llm
from app.agents.schemas import ExplorationPlan, ExplorerReport, RepoModel

log = structlog.get_logger(__name__)

_SYSTEM = (
    "You are the synthesizer in a multi-agent system that maps a codebase. Several "
    "explorers each investigated one subsystem and produced findings. Merge them "
    "into a single coherent model of the repository: a tight summary of what it is "
    "and how it's organized, a description per subsystem, the important end-to-end "
    "flows that cross subsystems, and an ordered onboarding walkthrough (the path a "
    "new engineer should read to understand the repo). Ground everything in the "
    "findings provided; prefer specifics over generic statements. Do not invent "
    "subsystems or flows the findings don't support."
)


def _format_reports(plan: ExplorationPlan, reports: list[ExplorerReport]) -> str:
    lines = [f"Repository overview (planner): {plan.overview}", ""]
    for r in reports:
        lines.append(f"### Subsystem: {r.subsystem}")
        if not r.findings:
            lines.append("  (no findings)")
        for f in r.findings:
            ev = f" [evidence: {f.evidence}]" if f.evidence else ""
            lines.append(f"  - ({f.kind}) {f.target_fqname}: {f.text}{ev}")
        lines.append("")
    return "\n".join(lines)


async def synthesize(
    plan: ExplorationPlan,
    reports: list[ExplorerReport],
    *,
    ledger: llm.UsageLedger,
) -> RepoModel:
    """Produce the merged RepoModel from explorer reports."""
    prompt = (
        "Merge the explorer findings below into a coherent repo model "
        "(summary, subsystem descriptions, cross-cutting flows, onboarding walkthrough).\n\n"
        + _format_reports(plan, reports)
    )
    model = await llm.reasoning(ledger).complete_structured(prompt, RepoModel, system=_SYSTEM)
    log.info(
        "synthesizer.done",
        subsystems=len(model.subsystems),
        flows=len(model.flows),
        steps=len(model.walkthrough),
    )
    return model
