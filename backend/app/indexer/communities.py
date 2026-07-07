"""Community detection — the GraphRAG clustering layer (PLAN.md §2.2 step 3).

Partitions a repo's structural graph (imports / calls / inherits edges, weighted
by kind and confidence) into communities with **Leiden** (igraph + leidenalg —
the real algorithm, seeded for determinism). Each community then gets an LLM
title + summary composed bottom-up from its members' node summaries, so the
global query route can answer big-picture questions from a handful of community
summaries instead of re-reading code.

The clustering itself is deterministic and free (no LLM); the summaries are
gated on `llm_available` and best-effort. Re-running replaces the repo's
existing communities (idempotent).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import igraph as ig
import leidenalg
import structlog
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents import llm
from app.config import get_settings
from app.db.enums import EdgeKind
from app.db.models import Community, Edge, Node

log = structlog.get_logger(__name__)

# Edge weights: how strongly each relationship binds two symbols into one
# "subsystem". CONTAINS is excluded — the file/package tree would dominate and
# reproduce the directory structure instead of the behavioral structure.
_EDGE_WEIGHT: dict[EdgeKind, float] = {
    EdgeKind.CALLS: 1.0,
    EdgeKind.INHERITS: 0.9,
    EdgeKind.IMPLEMENTS: 0.9,
    EdgeKind.IMPORTS: 0.6,
    EdgeKind.TESTS: 0.4,
}

_LEIDEN_SEED = 1337
_MAX_SUMMARIZED = 20  # LLM budget: only the largest N communities get summaries
_MAX_MEMBERS_IN_PROMPT = 25


@dataclass(slots=True)
class CommunityStats:
    communities: int
    summarized: int


class _CommunitySummaryOut(BaseModel):
    title: str = Field(description="A 2-5 word name for what this cluster of code does.")
    summary: str = Field(
        description="2-3 sentences: the cluster's responsibility and how its parts relate."
    )


_SUMMARY_SYSTEM = (
    "You name and summarize a cluster of related code symbols from one repository. "
    "The members below were grouped by their call/import/inheritance structure. "
    "Give the cluster a short functional name and a 2-3 sentence summary of its "
    "collective responsibility, grounded only in the member summaries shown."
)


async def build_communities(
    session: AsyncSession,
    repo_id: uuid.UUID,
    *,
    ledger: llm.UsageLedger | None = None,
) -> CommunityStats:
    """Cluster the repo's graph and persist Community rows. Returns stats."""
    # Structural edges only (weighted); nodes that participate in at least one.
    rows = (
        await session.execute(
            select(Edge.src_node_id, Edge.dst_node_id, Edge.kind, Edge.confidence).where(
                Edge.repo_id == repo_id, Edge.kind.in_(list(_EDGE_WEIGHT.keys()))
            )
        )
    ).all()

    # Idempotent: replace any previous clustering for this repo.
    await session.execute(delete(Community).where(Community.repo_id == repo_id))

    if len(rows) < 2:
        log.info("communities.skipped", repo_id=str(repo_id), reason="too_few_edges")
        await session.flush()
        return CommunityStats(communities=0, summarized=0)

    # Map node ids to contiguous igraph vertex indices.
    node_ids: list[int] = sorted({n for src, dst, _, _ in rows for n in (src, dst)})
    index_of = {nid: i for i, nid in enumerate(node_ids)}
    edges = [(index_of[src], index_of[dst]) for src, dst, _, _ in rows]
    weights = [_EDGE_WEIGHT[kind] * float(conf) for _, _, kind, conf in rows]

    g = ig.Graph(n=len(node_ids), edges=edges, directed=False)
    partition = leidenalg.find_partition(
        g,
        leidenalg.ModularityVertexPartition,
        weights=weights,
        seed=_LEIDEN_SEED,
    )

    # Largest communities first; stable keys c0, c1, ...
    clusters = sorted((list(c) for c in partition), key=len, reverse=True)
    created: list[Community] = []
    for i, members in enumerate(clusters):
        member_ids = [node_ids[v] for v in members]
        created.append(
            Community(
                repo_id=repo_id,
                level=0,
                key=f"c{i}",
                node_ids=member_ids,
                size=len(member_ids),
            )
        )
    session.add_all(created)
    await session.flush()

    summarized = 0
    if get_settings().llm_available:
        summarized = await _summarize_communities(
            session, repo_id, created[:_MAX_SUMMARIZED], ledger
        )

    log.info(
        "communities.done", repo_id=str(repo_id), communities=len(created), summarized=summarized
    )
    return CommunityStats(communities=len(created), summarized=summarized)


async def _summarize_communities(
    session: AsyncSession,
    repo_id: uuid.UUID,
    communities: list[Community],
    ledger: llm.UsageLedger | None,
) -> int:
    """Best-effort Flash summaries composed from member node summaries."""
    done = 0
    for com in communities:
        members = (
            await session.execute(
                select(Node.fqname, Node.kind, Node.summary)
                .where(Node.id.in_(com.node_ids[:_MAX_MEMBERS_IN_PROMPT]))
                .order_by(Node.fqname)
            )
        ).all()
        listing = "\n".join(
            f"- {fq} [{kind}] — {(summary or '').strip()[:160]}" for fq, kind, summary in members
        )
        prompt = (
            f"Cluster of {com.size} symbols (showing {len(members)}):\n{listing}\n\n"
            "Name and summarize this cluster."
        )
        try:
            out = await llm.fast(ledger).complete_structured(
                prompt, _CommunitySummaryOut, system=_SUMMARY_SYSTEM
            )
            com.title = out.title[:255]
            com.summary = out.summary
            done += 1
        except Exception as exc:  # noqa: BLE001 — one failed summary must not kill indexing
            log.warning(
                "communities.summary_failed",
                repo_id=str(repo_id),
                key=com.key,
                error=str(exc)[:120],
            )
            break  # a throttled model will throttle the rest too; stop burning quota
    await session.flush()
    return done
