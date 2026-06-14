"""Repository indexing endpoints.

POST /api/repos       — index a repo (synchronous in Phase 2; moves to a
                        background worker + WebSocket events in a later phase).
GET  /api/repos/{id}  — repo status and stats.

For now indexing runs inline within the request. The static pipeline is fast
(seconds for mid-size repos), but a long clone could exceed a request budget;
the worker/queue split is a documented Phase 5+ change (PLAN.md §4.1).
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Repo
from app.db.session import get_session
from app.indexer.cloner import CloneError, PrivateRepoError
from app.indexer.pipeline import index_repo

router = APIRouter(prefix="/api/repos", tags=["repos"])


class IndexRequest(BaseModel):
    url: str = Field(..., description="Git repository URL (host must be allowlisted)")
    branch: str | None = Field(default=None, description="Branch to index; defaults to HEAD")


class IndexResponse(BaseModel):
    repo_id: str
    run_id: str
    head_commit: str
    nodes: int
    edges: int
    chunks: int
    files: int


class RepoResponse(BaseModel):
    id: str
    url: str
    status: str
    head_commit: str | None
    default_branch: str | None
    indexed_at: str | None
    stats: dict


@router.post("", response_model=IndexResponse, status_code=status.HTTP_201_CREATED)
async def create_index(
    body: IndexRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> IndexResponse:
    try:
        result = await index_repo(session, body.url, branch=body.branch)
        await session.commit()
    except PrivateRepoError as exc:
        # Private/not-found anonymously → 403 with the connect-GitHub guidance
        # (PLAN.md §9A). Distinct from a generic clone failure.
        await session.commit()  # persist the FAILED run/repo state
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except CloneError as exc:
        await session.commit()  # persist the FAILED run/repo state
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return IndexResponse(
        repo_id=result.repo_id,
        run_id=result.run_id,
        head_commit=result.head_commit,
        nodes=result.stats.nodes,
        edges=result.stats.edges,
        chunks=result.stats.chunks,
        files=result.stats.files,
    )


@router.get("/{repo_id}", response_model=RepoResponse)
async def get_repo(
    repo_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> RepoResponse:
    repo = await session.get(Repo, repo_id)
    if repo is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Repo not found")
    return RepoResponse(
        id=str(repo.id),
        url=repo.url,
        status=repo.status.value,
        head_commit=repo.head_commit,
        default_branch=repo.default_branch,
        indexed_at=repo.indexed_at.isoformat() if repo.indexed_at else None,
        stats=repo.stats,
    )
