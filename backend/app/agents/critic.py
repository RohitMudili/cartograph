"""Critic — adversarially verifies findings against the actual code.

For each finding it re-reads the cited node and its source (via the same tools the
explorers used) and judges whether the claim actually holds. Findings whose target
symbol doesn't even exist are rejected outright before spending an LLM call.
Reasoning-tier (PLAN.md §2.2). The orchestrator routes rejected findings back for
one revision round, then drops twice-rejected ones.
"""

from __future__ import annotations

import structlog

from app.agents import llm
from app.agents.schemas import CriticReport, Finding, Verdict
from app.agents.tools import RepoTools

log = structlog.get_logger(__name__)

_SYSTEM = (
    "You are the critic in a multi-agent system that maps a codebase. You are "
    "adversarial: your job is to catch claims that are wrong, vague, or unsupported "
    "by the actual code. For the finding below you are given the real node and its "
    "source. Accept the claim ONLY if the code genuinely supports it; reject if it's "
    "false, can't be verified from what's shown, or is too generic to be useful. "
    "Give a one-sentence reason citing what you checked. Echo back the target fqname "
    "and finding text unchanged."
)


async def _verify_one(finding: Finding, tools: RepoTools, *, ledger: llm.UsageLedger) -> Verdict:
    """Re-read the cited code and judge one finding."""
    node = await tools.get_node(finding.target_fqname)
    if node is None:
        # The claim targets a symbol that isn't in the graph — automatic reject,
        # no LLM call needed.
        return Verdict(
            target_fqname=finding.target_fqname,
            finding_text=finding.text,
            accepted=False,
            reason="Target symbol does not exist in the graph.",
        )

    source = {"summary": node.get("summary"), "signature": node.get("signature")}
    path = node.get("path")
    if path:
        file = await tools.read_file(path, max_chars=4000)
        source["source"] = file.get("text", "")

    prompt = (
        f"FINDING\n  target: {finding.target_fqname}\n  kind: {finding.kind}\n"
        f"  claim: {finding.text}\n  evidence offered: {finding.evidence or '(none)'}\n\n"
        f"THE REAL NODE\n  signature: {source.get('signature')}\n"
        f"  summary: {source.get('summary')}\n"
        f"  source:\n{(source.get('source') or '(no source)')[:3500]}\n\n"
        "Does the claim hold against this code? Accept or reject with a reason."
    )
    return await llm.reasoning(ledger).complete_structured(prompt, Verdict, system=_SYSTEM)


async def critique(
    findings: list[Finding],
    tools: RepoTools,
    *,
    ledger: llm.UsageLedger,
    sample: int | None = None,
) -> CriticReport:
    """Verify findings (optionally a sample of the first `sample`) against code."""
    target = findings if sample is None else findings[:sample]
    verdicts: list[Verdict] = []
    for f in target:
        verdicts.append(await _verify_one(f, tools, ledger=ledger))
    accepted = sum(1 for v in verdicts if v.accepted)
    log.info(
        "critic.done", judged=len(verdicts), accepted=accepted, rejected=len(verdicts) - accepted
    )
    return CriticReport(verdicts=verdicts)
