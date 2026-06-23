"""Inter-agent payload schemas for the enrichment fleet (PLAN.md §2.2).

Every handoff between agents is a validated Pydantic model — no free-text
parsing between stages. The LLM agents return these via `llm.complete_structured`
(provider-uniform JSON mode), so a malformed response fails loudly at the
boundary instead of corrupting downstream state.

The flow of types:
    Planner   → ExplorationPlan (list[Subsystem])
    Explorer  → ExplorerReport (list[Finding])      one per subsystem, parallel
    Synthesizer → RepoModel (subsystems + flows + walkthrough)
    Critic    → list[Verdict]                        one per sampled finding
    Librarian → writes accepted Findings into Node.annotations (no schema out)

`AgentEventModel` is the wire/replay shape for the Mission Control stream.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.db.enums import AgentEventType, AgentRole

# ── Planner ──────────────────────────────────────────────────────────────────


class Subsystem(BaseModel):
    """One coherent slice of the repo for an explorer to investigate."""

    name: str = Field(description="Short subsystem name, e.g. 'auth', 'indexing pipeline'.")
    brief: str = Field(
        description="What this subsystem appears to do and why it's distinct, in 1-2 sentences."
    )
    seed_paths: list[str] = Field(
        default_factory=list,
        description="A few representative file paths that anchor this subsystem.",
    )
    seed_fqnames: list[str] = Field(
        default_factory=list,
        description="A few central symbol fqnames (functions/classes) to start exploration from.",
    )


class ExplorationPlan(BaseModel):
    """The planner's partition of the repo into 3-8 subsystems."""

    overview: str = Field(description="One-paragraph first-impression of what this repo is.")
    subsystems: list[Subsystem] = Field(
        description="3-8 subsystems that together cover the repo's important code."
    )


# ── Explorer ─────────────────────────────────────────────────────────────────


class Finding(BaseModel):
    """A structured claim about the code — a claim, not a fact, until the critic
    verifies it. Targets a specific node so the librarian can attach it and the
    critic can re-read the cited code."""

    target_fqname: str = Field(
        description="The fqname of the node this finding is about (must exist in the graph)."
    )
    kind: str = Field(
        description="One of: role, flow, summary, smell, surprise — the kind of claim.",
    )
    text: str = Field(description="The claim itself, one or two sentences, concrete and specific.")
    evidence: str = Field(
        default="",
        description="Why this is true: a symbol name, a path:line, or a short quote from the code.",
    )


class ExplorerReport(BaseModel):
    """One explorer's output for its assigned subsystem."""

    subsystem: str = Field(description="The subsystem name this report covers.")
    findings: list[Finding] = Field(description="Structured findings discovered while exploring.")


class ExplorerStep(BaseModel):
    """The explorer's next move in its bounded tool-use loop: either call one more
    tool to learn more, or stop and report findings."""

    action: str = Field(
        description="One of: read_file, get_node, get_neighbors, search_graph, grep, done.",
    )
    arg: str = Field(
        default="",
        description="The single argument for the tool (a path, fqname, query, or regex). Empty for 'done'.",
    )
    reasoning: str = Field(
        default="",
        description="One short sentence on why this step (shown in the live feed).",
    )
    findings: list[Finding] = Field(
        default_factory=list,
        description="When action is 'done', the structured findings discovered. Empty otherwise.",
    )


# ── Synthesizer ──────────────────────────────────────────────────────────────


class SubsystemSummary(BaseModel):
    name: str
    description: str = Field(description="What the subsystem does, synthesized across findings.")


class CrossCuttingFlow(BaseModel):
    name: str = Field(description="Name of an end-to-end flow, e.g. 'indexing a repo'.")
    steps: list[str] = Field(description="Ordered steps of the flow across subsystems.")


class WalkthroughStep(BaseModel):
    title: str
    detail: str = Field(description="What to read/understand at this step and why.")
    fqname: str | None = Field(
        default=None, description="An optional anchor symbol/file for this step."
    )


class RepoModel(BaseModel):
    """The synthesizer's coherent repo-level model, merged from explorer findings."""

    summary: str = Field(description="A tight paragraph: what this repo is and how it's organized.")
    subsystems: list[SubsystemSummary] = Field(default_factory=list)
    flows: list[CrossCuttingFlow] = Field(default_factory=list)
    walkthrough: list[WalkthroughStep] = Field(
        default_factory=list, description="An ordered onboarding path through the repo."
    )


# ── Critic ───────────────────────────────────────────────────────────────────


class Verdict(BaseModel):
    """The critic's adversarial check of a single finding against the real code."""

    target_fqname: str = Field(description="The finding's target (echoed back for matching).")
    finding_text: str = Field(description="The finding text being judged (echoed back).")
    accepted: bool = Field(description="True if the claim holds against the actual code.")
    reason: str = Field(description="Why accepted or rejected, citing what was checked.")


class CriticReport(BaseModel):
    """All verdicts for the sampled findings."""

    verdicts: list[Verdict] = Field(default_factory=list)


# ── Event wire shape ─────────────────────────────────────────────────────────


class AgentEventModel(BaseModel):
    """The Mission Control stream / replay shape of one agent event."""

    seq: int
    run_id: str
    agent: AgentRole | str
    type: AgentEventType | str
    payload: dict = Field(default_factory=dict)
    ts: str | None = None
