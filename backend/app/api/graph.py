"""Graph-facing read APIs — what Atlas, the code panel, and the walkthrough use.

- `GET /api/repos/{id}/graph`       — a capped slice of nodes + edges (+ community
  membership) for the Atlas view. Nodes are ranked by degree so a huge repo
  returns its load-bearing structure, not 50k leaves.
- `GET /api/repos/{id}/file?path=`  — a file's source reconstructed from stored
  chunks (exact line ranges), for the citation code panel. No re-clone.
- `GET /api/repos/{id}/walkthrough` — the synthesizer's onboarding walkthrough
  from the RepoModel (404s with a reason until the fleet has produced one).

All read-only; repo-scoped.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.tools import RepoTools
from app.db.models import Community, Edge, Node, Repo
from app.db.session import get_session
from app.query.enrichment import load_repo_model

router = APIRouter(prefix="/api/repos", tags=["graph"])


# ── Graph slice ──────────────────────────────────────────────────────────────


class GraphNode(BaseModel):
    id: int
    fqname: str
    kind: str
    path: str | None
    start_line: int | None
    end_line: int | None
    summary: str | None
    community: str | None  # community key, e.g. "c0"
    annotations: int  # count of verified findings on this node
    degree: int


class GraphEdge(BaseModel):
    src: int
    dst: int
    kind: str
    confidence: float


class GraphCommunity(BaseModel):
    key: str
    title: str | None
    summary: str | None
    size: int


class GraphSlice(BaseModel):
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    communities: list[GraphCommunity]
    total_nodes: int  # in the repo, before capping


async def _repo_or_404(session: AsyncSession, repo_id: uuid.UUID) -> Repo:
    repo = await session.get(Repo, repo_id)
    if repo is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Repo not found")
    return repo


@router.get("/{repo_id}/graph", response_model=GraphSlice)
async def get_graph(
    repo_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    max_nodes: Annotated[int, Query(ge=10, le=1500)] = 400,
) -> GraphSlice:
    """A renderable slice of the repo's graph, capped to the most-connected nodes."""
    await _repo_or_404(session, repo_id)

    nodes = (await session.scalars(select(Node).where(Node.repo_id == repo_id))).all()
    total = len(nodes)
    edges = (
        await session.execute(
            select(Edge.src_node_id, Edge.dst_node_id, Edge.kind, Edge.confidence).where(
                Edge.repo_id == repo_id
            )
        )
    ).all()

    # Degree ranking so the cap keeps the load-bearing structure.
    degree: dict[int, int] = {}
    for src, dst, _, _ in edges:
        degree[src] = degree.get(src, 0) + 1
        degree[dst] = degree.get(dst, 0) + 1
    ranked = sorted(nodes, key=lambda n: degree.get(n.id, 0), reverse=True)[:max_nodes]
    kept_ids = {n.id for n in ranked}

    communities = (
        await session.scalars(
            select(Community).where(Community.repo_id == repo_id).order_by(Community.size.desc())
        )
    ).all()
    community_of: dict[int, str] = {}
    for com in communities:
        for nid in com.node_ids:
            community_of.setdefault(nid, com.key)

    def _verified_count(n: Node) -> int:
        return sum(
            1 for a in (n.annotations or []) if a.get("verified") and a.get("kind") != "repo_model"
        )

    return GraphSlice(
        nodes=[
            GraphNode(
                id=n.id,
                fqname=n.fqname,
                kind=str(n.kind.value if hasattr(n.kind, "value") else n.kind),
                path=n.path,
                start_line=n.start_line,
                end_line=n.end_line,
                summary=n.summary,
                community=community_of.get(n.id),
                annotations=_verified_count(n),
                degree=degree.get(n.id, 0),
            )
            for n in ranked
        ],
        edges=[
            GraphEdge(
                src=src,
                dst=dst,
                kind=str(kind.value if hasattr(kind, "value") else kind),
                confidence=conf,
            )
            for src, dst, kind, conf in edges
            if src in kept_ids and dst in kept_ids
        ],
        communities=[
            GraphCommunity(key=c.key, title=c.title, summary=c.summary, size=c.size)
            for c in communities
        ],
        total_nodes=total,
    )


# ── File content (for the citation code panel) ───────────────────────────────


class FileContent(BaseModel):
    path: str
    found: bool
    start_line: int | None = None
    end_line: int | None = None
    truncated: bool = False
    text: str = ""


@router.get("/{repo_id}/file", response_model=FileContent)
async def get_file(
    repo_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    path: Annotated[str, Query(min_length=1, max_length=1024)],
) -> FileContent:
    """A file's source, reconstructed from its indexed chunks (exact line ranges)."""
    await _repo_or_404(session, repo_id)
    result = await RepoTools(session=session, repo_id=repo_id).read_file(path)
    return FileContent(
        path=path,
        found=bool(result.get("found")),
        start_line=result.get("start_line"),
        end_line=result.get("end_line"),
        truncated=bool(result.get("truncated")),
        text=str(result.get("text", "")),
    )


# ── Walkthrough ──────────────────────────────────────────────────────────────


class WalkthroughStep(BaseModel):
    title: str
    detail: str
    fqname: str | None = None


class Walkthrough(BaseModel):
    summary: str
    steps: list[WalkthroughStep]


@router.get("/{repo_id}/walkthrough", response_model=Walkthrough)
async def get_walkthrough(
    repo_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Walkthrough:
    """The synthesizer's onboarding walkthrough (available after enrichment ran)."""
    await _repo_or_404(session, repo_id)
    model = await load_repo_model(session, repo_id)
    if not model or not model.get("walkthrough"):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No walkthrough yet — the agent enrichment pass hasn't produced one for this repo.",
        )
    return Walkthrough(
        summary=str(model.get("summary", "")),
        steps=[
            WalkthroughStep(
                title=str(s.get("title", "")),
                detail=str(s.get("detail", "")),
                fqname=s.get("fqname"),
            )
            for s in model["walkthrough"]
        ],
    )
