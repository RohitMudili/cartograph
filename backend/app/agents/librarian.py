"""Librarian — persists accepted findings into the graph. Not an LLM agent.

The write-back step that makes exploration a durable artifact (PLAN.md §2.2): each
accepted finding becomes an attributed annotation on its target node
(`Node.annotations`), and the synthesized repo model is stored on the repo (REPO)
node so the query layer and UI can read the big picture. Every write records its
provenance: which subsystem found it, that the critic verified it, and the run id.
"""

from __future__ import annotations

import datetime as dt
import uuid

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.schemas import Finding, RepoModel
from app.db.enums import NodeKind
from app.db.models import Node

log = structlog.get_logger(__name__)


async def persist(
    session: AsyncSession,
    repo_id: uuid.UUID,
    *,
    run_id: uuid.UUID,
    accepted: list[tuple[Finding, str]],
    repo_model: RepoModel | None,
) -> int:
    """Write accepted findings + the repo model into the graph.

    `accepted` is a list of (finding, source_label) pairs — source_label is the
    owning explorer/subsystem, recorded for attribution. Returns the number of
    annotations written. Findings whose target node no longer exists are skipped.
    """
    now = dt.datetime.now(dt.UTC).isoformat()
    written = 0

    # Group findings by target fqname so we touch each node once.
    by_target: dict[str, list[tuple[Finding, str]]] = {}
    for finding, source in accepted:
        by_target.setdefault(finding.target_fqname, []).append((finding, source))

    for fqname, items in by_target.items():
        node = await session.scalar(
            select(Node).where(Node.repo_id == repo_id, Node.fqname == fqname)
        )
        if node is None:
            log.warning("librarian.target_missing", fqname=fqname)
            continue
        annotations = list(node.annotations or [])
        for finding, source in items:
            annotations.append(
                {
                    "text": finding.text,
                    "kind": finding.kind,
                    "evidence": finding.evidence,
                    "source": source,
                    "verified": True,
                    "run_id": str(run_id),
                    "created_at": now,
                }
            )
            written += 1
        node.annotations = annotations

    # Store the synthesized repo model on the REPO node's annotations.
    if repo_model is not None:
        repo_node = await session.scalar(
            select(Node).where(Node.repo_id == repo_id, Node.kind == NodeKind.REPO)
        )
        if repo_node is not None:
            annotations = list(repo_node.annotations or [])
            annotations.append(
                {
                    "text": repo_model.summary,
                    "kind": "repo_model",
                    "source": "synthesizer",
                    "verified": True,
                    "run_id": str(run_id),
                    "created_at": now,
                    "model": repo_model.model_dump(),
                }
            )
            repo_node.annotations = annotations

    await session.flush()
    log.info("librarian.done", repo_id=str(repo_id), annotations_written=written)
    return written
