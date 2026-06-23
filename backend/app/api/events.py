"""Agent-event endpoints — the Mission Control stream (PLAN.md §4.3, §6).

Two ways to consume an enrichment run's event log:

- `GET  /api/repos/{repo_id}/runs/{run_id}/events?after_seq=N` — replay: all
  persisted events after seq N, in order. The UI uses this on load and to
  backfill gaps after a reconnect.
- `WS   /api/repos/{repo_id}/runs/{run_id}/events/ws?after_seq=N` — live: first
  replays everything after N from the durable log, then streams new events from
  the in-process hub as they're emitted. Reconnect-safe: the client tracks the
  last seq it saw and passes it as after_seq.

Both verify the run belongs to the repo before exposing anything.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.events import hub, load_events
from app.agents.schemas import AgentEventModel
from app.db.models import IndexRun
from app.db.session import get_session, get_sessionmaker

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/repos", tags=["events"])


async def _run_belongs_to_repo(
    session: AsyncSession, repo_id: uuid.UUID, run_id: uuid.UUID
) -> bool:
    found = await session.scalar(
        select(IndexRun.id).where(IndexRun.id == run_id, IndexRun.repo_id == repo_id)
    )
    return found is not None


@router.get("/{repo_id}/runs/{run_id}/events", response_model=list[AgentEventModel])
async def get_run_events(
    repo_id: uuid.UUID,
    run_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    after_seq: Annotated[int, Query(ge=0)] = 0,
) -> list[AgentEventModel]:
    """Replay an enrichment run's events with seq > after_seq."""
    if not await _run_belongs_to_repo(session, repo_id, run_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="run not found")
    return await load_events(session, run_id, after_seq=after_seq)


@router.websocket("/{repo_id}/runs/{run_id}/events/ws")
async def stream_run_events(
    websocket: WebSocket,
    repo_id: uuid.UUID,
    run_id: uuid.UUID,
    after_seq: int = 0,
) -> None:
    """Live event stream: backfill from the durable log, then push new events.

    We subscribe to the hub BEFORE the backfill so no event emitted during
    backfill is lost; we then drop any streamed event whose seq we already sent.
    """
    await websocket.accept()
    queue = hub.subscribe(str(run_id))
    last_sent = after_seq
    try:
        # Verify ownership and backfill from the durable log.
        async with get_sessionmaker()() as session:
            if not await _run_belongs_to_repo(session, repo_id, run_id):
                await websocket.close(code=4404, reason="run not found")
                return
            for event in await load_events(session, run_id, after_seq=after_seq):
                await websocket.send_json(event.model_dump(mode="json"))
                last_sent = max(last_sent, event.seq)

        # Stream live events, de-duping against what backfill already sent.
        while True:
            event = await queue.get()
            if event.seq <= last_sent:
                continue
            await websocket.send_json(event.model_dump(mode="json"))
            last_sent = event.seq
    except WebSocketDisconnect:
        pass
    except asyncio.CancelledError:  # pragma: no cover
        raise
    finally:
        hub.unsubscribe(str(run_id), queue)
