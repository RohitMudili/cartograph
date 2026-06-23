"""Planner — partitions a repo into 3-8 subsystems with exploration briefs.

Reads the structural skeleton (file tree, the most-connected nodes, the README/doc
summaries) and decides how to divide the repo so explorers can work in parallel
without overlapping. Reasoning-tier; one structured call (PLAN.md §2.2).
"""

from __future__ import annotations

import uuid

import structlog
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents import llm
from app.agents.schemas import ExplorationPlan
from app.db.enums import NodeKind
from app.db.models import Node

log = structlog.get_logger(__name__)

_SYSTEM = (
    "You are the planner in a multi-agent system that maps a codebase. Given a "
    "structural skeleton of a repository, partition it into 3 to 8 coherent "
    "SUBSYSTEMS that together cover the important code. A good subsystem is a slice "
    "a single engineer could own: a layer, a feature area, or a pipeline stage "
    "(e.g. 'HTTP API', 'indexing pipeline', 'auth'). Avoid trivial or overlapping "
    "splits. For each subsystem write a one-to-two sentence brief and list a few "
    "seed files and seed symbol fqnames that anchor it, chosen from the skeleton. "
    "Base everything on the skeleton given; do not invent paths or symbols."
)

_MAX_CENTRAL = 40
_MAX_FILES = 80


async def _skeleton(session: AsyncSession, repo_id: uuid.UUID) -> str:
    """Build the structural skeleton prompt: file list, central symbols, doc summaries."""
    # Files (with LOC where known) — the shape of the tree.
    file_rows = (
        await session.execute(
            select(Node.path, Node.metrics)
            .where(Node.repo_id == repo_id, Node.kind == NodeKind.FILE)
            .order_by(Node.path)
            .limit(_MAX_FILES)
        )
    ).all()
    files = "\n".join(
        f"  {path} ({(metrics or {}).get('loc', '?')} loc)" for path, metrics in file_rows
    )

    # Most-connected symbols (fan_in + fan_out) — the load-bearing nodes.
    fan = (func.coalesce(Node.metrics["fan_in"].as_integer(), 0)) + (
        func.coalesce(Node.metrics["fan_out"].as_integer(), 0)
    )
    central_rows = (
        await session.execute(
            select(Node.fqname, Node.kind, Node.summary)
            .where(
                Node.repo_id == repo_id,
                Node.kind.in_([NodeKind.FUNCTION, NodeKind.METHOD, NodeKind.CLASS]),
            )
            .order_by(desc(fan))
            .limit(_MAX_CENTRAL)
        )
    ).all()
    central = "\n".join(f"  {fq} [{k}] — {(s or '').strip()[:120]}" for fq, k, s in central_rows)

    # Doc/README summaries — the human-written intent.
    doc_rows = (
        await session.execute(
            select(Node.fqname, Node.summary)
            .where(Node.repo_id == repo_id, Node.kind == NodeKind.DOC)
            .limit(20)
        )
    ).all()
    docs = "\n".join(f"  {fq} — {(s or '').strip()[:160]}" for fq, s in doc_rows if s)

    return (
        f"## Files ({len(file_rows)} shown)\n{files or '  (none)'}\n\n"
        f"## Central symbols (by fan-in+fan-out)\n{central or '  (none)'}\n\n"
        f"## Docs\n{docs or '  (none)'}"
    )


async def plan(
    session: AsyncSession, repo_id: uuid.UUID, *, ledger: llm.UsageLedger
) -> ExplorationPlan:
    """Produce an ExplorationPlan for the repo."""
    skeleton = await _skeleton(session, repo_id)
    prompt = (
        "Partition this repository into subsystems for parallel exploration.\n\n"
        f"{skeleton}\n\n"
        "Return an overview plus 3-8 subsystems, each with a brief and seed "
        "paths/fqnames drawn from the skeleton above."
    )
    result = await llm.reasoning(ledger).complete_structured(
        prompt, ExplorationPlan, system=_SYSTEM
    )
    # Clamp to the contracted 3-8 range defensively (the model is told, but enforce).
    if len(result.subsystems) > 8:
        result.subsystems = result.subsystems[:8]
    log.info("planner.done", repo_id=str(repo_id), subsystems=len(result.subsystems))
    return result
