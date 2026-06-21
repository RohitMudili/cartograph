"""Repository indexing endpoints.

POST /api/repos                       — index a repo.
GET  /api/repos                       — list repos owned by the current user.
GET  /api/repos/{id}                  — repo status and stats.
GET  /api/repos/{id}/questions        — question history for a repo.
POST /api/repos/{id}/questions        — ask a question (optionally in a session).
POST /api/repos/{id}/sessions         — create a new chat session.
GET  /api/repos/{id}/sessions         — list sessions for a repo.

For now indexing runs inline within the request. The static pipeline is fast
(seconds for mid-size repos), but a long clone could exceed a request budget;
the worker/queue split is a documented future change (PLAN.md §4.1).
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.jwt import AuthUser, get_optional_user
from app.db.models import Question, Repo
from app.db.session import get_session
from app.indexer.cloner import CloneError, PrivateRepoError
from app.indexer.pipeline import index_repo
from app.query.answerer import Answerer
from app.session.store import add_message, format_context
from app.session.store import create_session as create_session_in_redis

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


class RepoSummary(BaseModel):
    """A repo in the user's list, with the most recent question text."""

    id: str
    url: str
    status: str
    head_commit: str | None
    default_branch: str | None
    indexed_at: str | None
    stats: dict
    last_question: str | None = None


class QuestionOut(BaseModel):
    """A persisted question with its answer summary."""

    id: str
    text: str
    route: str
    answer: dict
    citations: list[dict]
    citation_verified: bool
    cost_usd: float
    latency_ms: int
    created_at: str
    session_id: str | None = None
    conversation_id: str | None = None


@router.get("", response_model=list[RepoSummary])
async def list_repos(
    session: Annotated[AsyncSession, Depends(get_session)],
    user: Annotated[AuthUser | None, Depends(get_optional_user)] = None,
) -> list[RepoSummary]:
    """List repos owned by the current user.

    Authenticated users see only their own repos (where owner_user_id matches).
    Sign-in is required to persist repo ownership, so anonymous users see an
    empty list.
    """
    if user is None:
        return []

    user_id = uuid.UUID(user.id)
    rows = (
        await session.execute(
            select(
                Repo,
                select(Question.text)
                .where(Question.repo_id == Repo.id)
                .order_by(Question.created_at.desc())
                .limit(1)
                .correlate(Repo)
                .scalar_subquery(),
            )
            .where(Repo.owner_user_id == user_id)
            .order_by(Repo.indexed_at.desc().nulls_last(), Repo.created_at.desc())
        )
    ).all()

    return [
        RepoSummary(
            id=str(repo.id),
            url=repo.url,
            status=repo.status.value,
            head_commit=repo.head_commit,
            default_branch=repo.default_branch,
            indexed_at=repo.indexed_at.isoformat() if repo.indexed_at else None,
            stats=repo.stats,
            last_question=last_q,
        )
        for repo, last_q in rows
    ]


@router.get("/{repo_id}/questions", response_model=list[QuestionOut])
async def list_questions(
    repo_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    user: Annotated[AuthUser | None, Depends(get_optional_user)] = None,
    session_id: str | None = Query(default=None, description="Filter by session ID"),
) -> list[QuestionOut]:
    """List question history for a repo, most recent first."""
    repo = await session.get(Repo, repo_id)
    if repo is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Repo not found")

    # Only the owner can see question history for now.
    if user is None or (
        repo.owner_user_id is not None and repo.owner_user_id != uuid.UUID(user.id)
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Question history is only available for repos you own.",
        )

    stmt = select(Question).where(Question.repo_id == repo_id)
    if session_id:
        stmt = stmt.where(Question.session_id == session_id)
    stmt = stmt.order_by(Question.created_at.desc()).limit(50)

    questions = (await session.execute(stmt)).scalars().all()

    return [
        QuestionOut(
            id=str(q.id),
            text=q.text,
            route=q.route,
            answer=q.answer,
            citations=q.citations,
            citation_verified=q.citation_verified,
            cost_usd=q.cost_usd,
            latency_ms=q.latency_ms,
            created_at=q.created_at.isoformat() if q.created_at else "",
            session_id=q.session_id,
            conversation_id=q.conversation_id,
        )
        for q in questions
    ]


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


# ── Session endpoints ──────────────────────────────────────────────────────


class CreateSessionResponse(BaseModel):
    session_id: str


class SessionOut(BaseModel):
    """A session with its summary metadata."""

    id: str
    repo_id: str
    created_at: str
    last_activity: str
    message_count: int
    preview: str = ""


@router.post(
    "/{repo_id}/sessions", response_model=CreateSessionResponse, status_code=status.HTTP_201_CREATED
)
async def create_session(
    repo_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    user: Annotated[AuthUser | None, Depends(get_optional_user)] = None,
) -> CreateSessionResponse:
    """Create a new chat session for a repo.

    Sessions live in Redis with a 1-hour TTL and track the last 5 Q&A
    pairs for conversation continuity. Questions are always durably
    persisted in Postgres regardless of session expiry.
    """
    repo = await session.get(Repo, repo_id)
    if repo is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Repo not found")

    owner_id = user.id if user else None
    session_id = await create_session_in_redis(str(repo_id), owner_user_id=owner_id)
    return CreateSessionResponse(session_id=session_id)


@router.get("/{repo_id}/sessions", response_model=list[SessionOut])
async def list_sessions(
    repo_id: uuid.UUID,
    db_session: Annotated[AsyncSession, Depends(get_session)],
    user: Annotated[AuthUser | None, Depends(get_optional_user)] = None,
) -> list[SessionOut]:
    """List sessions for a repo, ordered by most recent activity.

    Sessions are derived from distinct `session_id` values in the questions
    table. Metadata (message count, preview of first question) comes from
    the question data itself — Redis is not needed for listing.
    """
    repo = await db_session.get(Repo, repo_id)
    if repo is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Repo not found")
    if user is None or (
        repo.owner_user_id is not None and repo.owner_user_id != uuid.UUID(user.id)
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Session list is only available for repos you own.",
        )

    # Get distinct sessions with metadata
    rows = (
        await db_session.execute(
            select(
                Question.session_id,
                func.min(Question.created_at).label("created_at"),
                func.max(Question.created_at).label("last_activity"),
                func.count(Question.id).label("message_count"),
                func.min(Question.text).label("first_question"),
            )
            .where(Question.repo_id == repo_id, Question.session_id.isnot(None))
            .group_by(Question.session_id)
            .order_by(func.max(Question.created_at).desc())
            .limit(50)
        )
    ).all()

    return [
        SessionOut(
            id=row.session_id,
            repo_id=str(repo_id),
            created_at=row.created_at.isoformat() if row.created_at else "",
            last_activity=row.last_activity.isoformat() if row.last_activity else "",
            message_count=row.message_count,
            preview=(row.first_question or "")[:120],
        )
        for row in rows
    ]


# ── Question endpoint ──────────────────────────────────────────────────────


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
    session_id: str = Field(description="The session this question belongs to")
    conversation_id: str = Field(description="Unique per-turn identifier for this Q&A exchange")


class QuestionRequest(BaseModel):
    question: str = Field(..., min_length=1)
    session_id: str | None = Field(
        default=None, description="Session ID for conversation continuity"
    )


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

    # Every question gets a unique conversation_id for per-turn tracking.
    conversation_id = str(uuid.uuid4())

    # Every question MUST belong to a session. If the client didn't provide one,
    # auto-create a new session in Redis.
    session_id = body.session_id
    if not session_id:
        owner_id = user.id if user else None
        session_id = await create_session_in_redis(str(repo_id), owner_user_id=owner_id)

    # Get session conversation context for continuity.
    session_context = await format_context(session_id)

    t0 = dt.datetime.now(dt.UTC)
    ans = await Answerer(session, repo_id).answer(
        body.question,
        session_context=session_context,
    )
    latency_ms = int((dt.datetime.now(dt.UTC) - t0).total_seconds() * 1000)

    # Persist the question with both IDs.
    question = Question(
        repo_id=repo_id,
        owner_user_id=uuid.UUID(user.id) if user else None,
        session_id=session_id,
        conversation_id=conversation_id,
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

    # Save Q&A to Redis session context for conversation continuity.
    await add_message(session_id, body.question, ans.text)

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
        session_id=session_id,
        conversation_id=conversation_id,
    )
