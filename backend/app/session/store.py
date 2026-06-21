"""Upstash Redis session store — 1-hour TTL per session.

Each session stores:
- Metadata (repo_id, owner_user_id, created_at, last_activity) in a Redis hash.
- Conversation context (last N Q&A pairs) as a JSON array for fast retrieval.

Keys:
  session:{id}           → JSON {repo_id, owner_user_id, created_at, last_activity}  TTL: 3600
  session:{id}:context   → JSON [{role, text}, ...]  (last N messages)                TTL: 3600

On every new question in a session, both keys get their TTL refreshed (1 hour
from last activity). When a session expires, the questions are still persisted
in Postgres — Redis only stores the active conversation context.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

from upstash_redis import Redis

from app.config import get_settings

# How many past Q&A pairs to include as context in the LLM prompt.
_MAX_CONTEXT_PAIRS = 5

# Session TTL in seconds (1 hour).
_SESSION_TTL = 3600


@dataclass(slots=True)
class SessionMessage:
    role: str  # "user" | "assistant"
    text: str


@dataclass(slots=True)
class Session:
    id: str
    repo_id: str
    owner_user_id: str | None = None
    created_at: str = ""
    last_activity: str = ""
    message_count: int = 0
    context: list[SessionMessage] = field(default_factory=list)


def _get_redis() -> Redis:
    """Get configured Upstash Redis client."""
    settings = get_settings()
    url = settings.upstash_redis_rest_url
    token = settings.upstash_redis_rest_token
    return Redis(url=url, token=token)


async def create_session(repo_id: str, owner_user_id: str | None = None) -> str:
    """Create a new session and return its ID."""
    r = _get_redis()
    session_id = str(uuid.uuid4())
    now = datetime.now(UTC).isoformat()
    data = {
        "repo_id": repo_id,
        "id": session_id,
        "owner_user_id": owner_user_id or "",
        "created_at": now,
        "last_activity": now,
        "message_count": 0,
    }
    r.set(f"session:{session_id}", json.dumps(data), ex=_SESSION_TTL)
    r.set(f"session:{session_id}:context", json.dumps([]), ex=_SESSION_TTL)
    return session_id


async def get_session(session_id: str) -> Session | None:
    """Get session metadata from Redis."""
    r = _get_redis()
    raw = r.get(f"session:{session_id}")
    if raw is None:
        return None
    data = json.loads(raw)
    ctx_raw = r.get(f"session:{session_id}:context")
    ctx = json.loads(ctx_raw) if ctx_raw else []
    return Session(
        id=data["id"],
        repo_id=data["repo_id"],
        owner_user_id=data.get("owner_user_id") or None,
        created_at=data["created_at"],
        last_activity=data["last_activity"],
        message_count=data.get("message_count", len(ctx) // 2),
        context=[SessionMessage(**m) for m in ctx],
    )


async def add_message(session_id: str, question: str, answer_text: str) -> None:
    """Add a Q&A pair to the session context and refresh TTL.

    Trims to the last N pairs to keep context bounded.
    """
    r = _get_redis()

    # Update metadata
    raw = r.get(f"session:{session_id}")
    if raw is None:
        return  # session expired, skip
    data = json.loads(raw)
    now = datetime.now(UTC).isoformat()
    data["last_activity"] = now
    data["message_count"] = data.get("message_count", 0) + 1
    r.set(f"session:{session_id}", json.dumps(data), ex=_SESSION_TTL)

    # Update context
    ctx_raw = r.get(f"session:{session_id}:context")
    ctx = json.loads(ctx_raw) if ctx_raw else []
    ctx.append({"role": "user", "text": question})
    ctx.append({"role": "assistant", "text": answer_text})
    # Keep only the last N pairs
    max_msgs = _MAX_CONTEXT_PAIRS * 2
    if len(ctx) > max_msgs:
        ctx = ctx[-max_msgs:]
    r.set(f"session:{session_id}:context", json.dumps(ctx), ex=_SESSION_TTL)


async def format_context(session_id: str | None) -> str | None:
    """Format the session conversation history as a prompt preamble.

    Returns None if there's no session_id or no context.
    """
    if not session_id:
        return None
    session = await get_session(session_id)
    if not session or not session.context:
        return None
    lines = ["Previous conversation:"]
    for msg in session.context:
        label = "You" if msg.role == "user" else "Assistant"
        lines.append(f"{label}: {msg.text}")
    lines.append("---")
    return "\n".join(lines)
