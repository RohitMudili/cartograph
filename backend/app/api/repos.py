"""Repository indexing endpoints.

POST /api/repos       — index a repo (synchronous for now; moves to a background
                        worker + WebSocket events later).
GET  /api/repos/{id}  — repo status and stats.

For now indexing runs inline within the request. The static pipeline is fast
(seconds for mid-size repos), but a long clone could exceed a request budget;
the worker/queue split is a documented future change (PLAN.md §4.1).
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.jwt import AuthUser, get_optional_user
from app.db.models import Question, Repo
from app.db.session import get_session
from app.indexer.cloner import CloneError, PrivateRepoError
from app.indexer.pipeline import index_repo
from app.query.answerer import Answerer

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
    user: Annotated[AuthUser | None, Depends(get_optional_user)] = None,
) -> IndexResponse:
    try:
        result = await index_repo(session, body.url, branch=body.branch)
        # Attribute the repo to the authenticated user if available.
        if user is not None:
            repo = await session.get(Repo, uuid.UUID(result.repo_id))
            if repo is not None:
                repo.owner_user_id = uuid.UUID(user.id)
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


class QuestionRequest(BaseModel):
    question: str = Field(..., min_length=1)


class CitationOut(BaseModel):
    path: str
    start_line: int
    end_line: int
    verified: bool


class AnswerResponse(BaseModel):
    question: str
    answer: str
    route: str
    answerable: bool
    fully_verified: bool
    citations: list[CitationOut]
    used_nodes: list[int]


@router.post("/{repo_id}/questions", response_model=AnswerResponse)
async def ask_question(
    repo_id: uuid.UUID,
    body: QuestionRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    user: Annotated[AuthUser | None, Depends(get_optional_user)] = None,
) -> AnswerResponse:
    repo = await session.get(Repo, repo_id)
    if repo is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Repo not found")

    t0 = dt.datetime.now(dt.UTC)
    ans = await Answerer(session, repo_id).answer(body.question)
    latency_ms = int((dt.datetime.now(dt.UTC) - t0).total_seconds() * 1000)

    # Persist the question to the database so it appears in history.
    question = Question(
        repo_id=repo_id,
        owner_user_id=uuid.UUID(user.id) if user else None,
        text=ans.question,
        route=ans.route,
        answer={"text": ans.text, "answerable": ans.answerable},
        citations=[
            {
                "path": vc.citation.path,
                "start_line": vc.citation.start_line,
                "end_line": vc.citation.end_line,
                "verified": vc.verified,
            }
            for vc in ans.citations
        ],
        citation_verified=ans.fully_verified,
        cost_usd=0.0,  # Filled from LangSmith post-hoc when tracing is on
        latency_ms=latency_ms,
    )
    session.add(question)
    await session.commit()

    return AnswerResponse(
        question=ans.question,
        answer=ans.text,
        route=ans.route,
        answerable=ans.answerable,
        fully_verified=ans.fully_verified,
        citations=[
            CitationOut(
                path=vc.citation.path,
                start_line=vc.citation.start_line,
                end_line=vc.citation.end_line,
                verified=vc.verified,
            )
            for vc in ans.citations
        ],
        used_nodes=ans.used_nodes,
    )
