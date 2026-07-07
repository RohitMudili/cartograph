"""Loaders for the enrichment layers the query pipeline consumes.

Three artifacts feed answers beyond raw retrieval (this is what makes the graph
a *learning cache* — exploration cost amortizes into cheaper answers):

- **RepoModel** — the synthesizer's repo-level model (summary, subsystems,
  flows, walkthrough), stored by the librarian on the REPO node's annotations.
- **Verified annotations** — critic-approved findings the librarian attached to
  specific nodes (`Node.annotations`).
- **Community summaries** — Leiden clusters with LLM titles/summaries; the
  global route's primary context.

All loaders are read-only and cheap (indexed lookups, no LLM).
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.enums import NodeKind
from app.db.models import Community, Node


async def load_repo_model(session: AsyncSession, repo_id: uuid.UUID) -> dict[str, Any] | None:
    """The latest synthesized RepoModel dict, or None if the fleet hasn't run."""
    repo_node = await session.scalar(
        select(Node).where(Node.repo_id == repo_id, Node.kind == NodeKind.REPO)
    )
    if repo_node is None:
        return None
    models = [
        a.get("model")
        for a in (repo_node.annotations or [])
        if a.get("kind") == "repo_model" and isinstance(a.get("model"), dict)
    ]
    return models[-1] if models else None


async def load_annotations_for_nodes(
    session: AsyncSession, repo_id: uuid.UUID, node_ids: list[int], *, limit: int = 20
) -> list[str]:
    """Verified findings attached to the given nodes, as prompt-ready lines."""
    if not node_ids:
        return []
    rows = (
        await session.execute(
            select(Node.fqname, Node.annotations).where(
                Node.repo_id == repo_id, Node.id.in_(node_ids)
            )
        )
    ).all()
    lines: list[str] = []
    for fqname, node_annotations in rows:
        for a in node_annotations or []:
            if a.get("verified") and a.get("kind") != "repo_model" and a.get("text"):
                lines.append(f"- {fqname}: {a['text']}")
                if len(lines) >= limit:
                    return lines
    return lines


async def load_community_summaries(
    session: AsyncSession, repo_id: uuid.UUID, *, limit: int = 12
) -> list[str]:
    """Summarized communities (largest first), as prompt-ready lines."""
    rows = (
        await session.execute(
            select(Community.key, Community.title, Community.summary, Community.size)
            .where(Community.repo_id == repo_id, Community.summary.is_not(None))
            .order_by(Community.size.desc())
            .limit(limit)
        )
    ).all()
    return [
        f"- [{key}] {title or 'cluster'} ({size} symbols): {summary}"
        for key, title, summary, size in rows
    ]


def format_enrichment_block(
    repo_model: dict[str, Any] | None,
    annotations: list[str],
    communities: list[str],
) -> str:
    """Render the enrichment layers as one prompt block ('' if nothing exists).

    The answerer appends this to the retrieved-code context. It's framed as
    background knowledge: claims in it were verified by the critic at index
    time, but line-level citations must still come from the code context.
    """
    parts: list[str] = []
    if repo_model:
        summary = repo_model.get("summary", "")
        subsystems = repo_model.get("subsystems") or []
        flows = repo_model.get("flows") or []
        lines = [f"Repository model (agent-synthesized): {summary}"]
        if subsystems:
            lines.append("Subsystems:")
            lines += [f"- {s.get('name')}: {s.get('description')}" for s in subsystems[:8]]
        if flows:
            lines.append("Key flows:")
            lines += [f"- {f.get('name')}: " + " -> ".join(f.get("steps") or []) for f in flows[:5]]
        parts.append("\n".join(lines))
    if communities:
        parts.append("Code communities (graph clustering):\n" + "\n".join(communities))
    if annotations:
        parts.append("Verified agent findings:\n" + "\n".join(annotations))
    if not parts:
        return ""
    return (
        "── Background knowledge (verified at index time; cite code lines from the "
        "context above for concrete claims) ──\n" + "\n\n".join(parts)
    )
