"""Event bus for enrichment runs — persistence + live fan-out (PLAN.md §4.3).

Two responsibilities, one module:

1. **Durable log.** Every agent event is written to the `agent_events` table with
   a per-run monotonic `seq`. This is the replay/debug record and the source of
   truth a reconnecting client catches up from (`?after_seq=`).

2. **Live fan-out.** An in-process pub/sub (`EventHub`) pushes each event to any
   connected WebSocket subscribers for that run, in real time, as it's emitted.

`EventEmitter` is the handle agents use: `await emitter.emit(role, type, payload)`.
It owns the `seq` counter for its run, persists the row, and publishes to the hub.
Persistence and fan-out are best-effort-decoupled: a fan-out with no subscribers
is a no-op, and a subscriber that's slow/gone never blocks the agents.

Note on scope: the in-memory hub is per-process. v1 runs as a single API+worker
process, so live streaming works; multi-process live streaming would need Redis
pub/sub (the durable table already supports cross-process replay regardless).
"""

from __future__ import annotations

import asyncio
import datetime as dt
import uuid
from collections import defaultdict

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.schemas import AgentEventModel
from app.db.enums import AgentEventType, AgentRole
from app.db.models import AgentEvent

log = structlog.get_logger(__name__)


class EventHub:
    """In-process pub/sub: subscribers get an async queue of events per run."""

    def __init__(self) -> None:
        self._subscribers: dict[str, set[asyncio.Queue[AgentEventModel]]] = defaultdict(set)

    def subscribe(self, run_id: str) -> asyncio.Queue[AgentEventModel]:
        q: asyncio.Queue[AgentEventModel] = asyncio.Queue(maxsize=1000)
        self._subscribers[run_id].add(q)
        return q

    def unsubscribe(self, run_id: str, q: asyncio.Queue[AgentEventModel]) -> None:
        subs = self._subscribers.get(run_id)
        if subs is not None:
            subs.discard(q)
            if not subs:
                self._subscribers.pop(run_id, None)

    def publish(self, run_id: str, event: AgentEventModel) -> None:
        for q in list(self._subscribers.get(run_id, ())):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                # A subscriber that can't keep up loses live events; it can still
                # catch up from the durable table via ?after_seq=. Don't block.
                log.warning("events.subscriber_lagging", run_id=run_id)


# Module-level hub — shared by emitters (publishers) and the WS route (subscribers).
hub = EventHub()


class EventEmitter:
    """Per-run event publisher: assigns seq, persists, fans out.

    Holds its own AsyncSession dedicated to event writes so emitting an event
    never interferes with (or is rolled back by) the agents' main work session.
    The caller is responsible for `await emitter.aclose()` when the run ends.
    """

    def __init__(self, run_id: uuid.UUID, session: AsyncSession) -> None:
        self.run_id = run_id
        self._session = session
        self._seq = 0
        self._lock = asyncio.Lock()

    async def emit(
        self,
        agent: AgentRole,
        type: AgentEventType,
        payload: dict | None = None,
    ) -> AgentEventModel:
        """Record one event: bump seq, persist the row, publish to the hub."""
        payload = payload or {}
        async with self._lock:
            self._seq += 1
            seq = self._seq
            row = AgentEvent(
                run_id=self.run_id,
                seq=seq,
                agent=str(agent),
                type=str(type),
                payload=payload,
            )
            self._session.add(row)
            try:
                await self._session.commit()
            except Exception:  # noqa: BLE001 — event persistence is best-effort, never kills the run
                await self._session.rollback()
                log.warning("events.persist_failed", run_id=str(self.run_id), seq=seq)

        model = AgentEventModel(
            seq=seq,
            run_id=str(self.run_id),
            agent=agent,
            type=type,
            payload=payload,
            ts=dt.datetime.now(dt.UTC).isoformat(),
        )
        hub.publish(str(self.run_id), model)
        return model


async def load_events(
    session: AsyncSession, run_id: uuid.UUID, *, after_seq: int = 0
) -> list[AgentEventModel]:
    """Replay: all persisted events for a run with seq > after_seq, in order."""
    rows = (
        await session.scalars(
            select(AgentEvent)
            .where(AgentEvent.run_id == run_id, AgentEvent.seq > after_seq)
            .order_by(AgentEvent.seq)
        )
    ).all()
    return [
        AgentEventModel(
            seq=r.seq,
            run_id=str(r.run_id),
            agent=r.agent,
            type=r.type,
            payload=r.payload,
            ts=r.ts.isoformat() if r.ts else None,
        )
        for r in rows
    ]
