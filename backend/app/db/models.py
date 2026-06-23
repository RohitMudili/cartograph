"""ORM models — the knowledge-graph schema (PLAN.md §3).

The static indexer populates: Repo, Node, Edge, Chunk, IndexRun. LLM-written
columns (`summary`, `summary_embedding`, `annotations`) and the agent-fleet
tables (Community, AgentEvent, Question) are defined now so the schema is whole
and migrations stay stable, but remain null/empty until those layers run.

Design notes:
- BigInteger PKs on graph tables (nodes/edges/chunks) — a large repo is millions
  of rows; we never want to hit the int4 ceiling.
- (repo_id, content_hash) and (repo_id, fqname) carry uniqueness/lookup load, so
  they're indexed. Citations and incremental invalidation both key on these.
- ON DELETE CASCADE from repo downward — dropping a repo cleans its whole graph.
- Vector columns are nullable; they're filled by the summarizer/embedding layer.
"""

from __future__ import annotations

import datetime as dt
import uuid

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Computed,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.config import EMBEDDING_DIM
from app.db.base import Base, TimestampMixin
from app.db.enums import EdgeKind, NodeKind, RepoStatus, RunKind, RunStatus


class UserProfile(Base, TimestampMixin):
    """Maps a Supabase user to optional email and GitHub username.

    `owner_user_id` is the Supabase user UUID (``sub`` claim in the JWT).
    `email` is populated from the Google OAuth profile.
    `github_username` is set when the user authenticates GitHub for private
    repo access (PLAN.md §9A — not yet built). Both are optional because a
    user may only sign in with Google (no GitHub) or only later add GitHub.
    """

    __tablename__ = "user_profiles"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    owner_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), unique=True, nullable=False, index=True
    )
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    github_username: Mapped[str | None] = mapped_column(String(255), nullable=True)


class Repo(Base, TimestampMixin):
    __tablename__ = "repos"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    default_branch: Mapped[str | None] = mapped_column(String(255))
    head_commit: Mapped[str | None] = mapped_column(String(40))
    status: Mapped[RepoStatus] = mapped_column(
        Enum(RepoStatus, name="repo_status"), default=RepoStatus.PENDING, nullable=False
    )
    indexed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    index_cost_usd: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    # Aggregate counts/metadata for the UI (file count, LOC, language breakdown).
    stats: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    nodes: Mapped[list[Node]] = relationship(back_populates="repo", cascade="all, delete-orphan")
    runs: Mapped[list[IndexRun]] = relationship(back_populates="repo", cascade="all, delete-orphan")
    questions: Mapped[list[Question]] = relationship(
        back_populates="repo", cascade="all, delete-orphan"
    )

    __table_args__ = (
        # One row per (url, commit): re-indexing the same commit is idempotent.
        UniqueConstraint("url", "head_commit", name="uq_repos_url_commit"),
    )


class Node(Base):
    """A symbol in the graph: repo, package, file, class, function, etc."""

    __tablename__ = "nodes"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    repo_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("repos.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[NodeKind] = mapped_column(Enum(NodeKind, name="node_kind"), nullable=False)

    # Fully-qualified name, e.g. "app.auth.jwt.decode_token". Unique per repo.
    fqname: Mapped[str] = mapped_column(Text, nullable=False)
    path: Mapped[str | None] = mapped_column(Text)  # null for the repo node
    start_line: Mapped[int | None] = mapped_column(Integer)
    end_line: Mapped[int | None] = mapped_column(Integer)

    signature: Mapped[str | None] = mapped_column(Text)
    docstring: Mapped[str | None] = mapped_column(Text)

    # loc, fan_in, fan_out, churn, centrality — filled by the graph builder.
    metrics: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    # Semantic layer — null until the summarizer/embedding step runs.
    summary: Mapped[str | None] = mapped_column(Text)
    summary_embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM))
    # Verified findings written back by the agent fleet: list of
    # {text, source, verified, run_id, created_at}.
    annotations: Mapped[list[dict]] = mapped_column(JSONB, default=list, nullable=False)

    # Hash of the node's source slice — drives incremental invalidation (PLAN.md §8).
    content_hash: Mapped[str | None] = mapped_column(String(64))

    repo: Mapped[Repo] = relationship(back_populates="nodes")

    __table_args__ = (
        UniqueConstraint("repo_id", "fqname", name="uq_nodes_repo_fqname"),
        Index("ix_nodes_repo_kind", "repo_id", "kind"),
        Index("ix_nodes_repo_path", "repo_id", "path"),
        Index("ix_nodes_repo_content_hash", "repo_id", "content_hash"),
    )


class Edge(Base):
    """A directed relationship between two nodes (contains, imports, calls, ...)."""

    __tablename__ = "edges"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    repo_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("repos.id", ondelete="CASCADE"), nullable=False
    )
    src_node_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("nodes.id", ondelete="CASCADE"), nullable=False
    )
    dst_node_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("nodes.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[EdgeKind] = mapped_column(Enum(EdgeKind, name="edge_kind"), nullable=False)
    # 0..1 — static analysis confidence. Dynamic dispatch / aliased imports get
    # low scores and are never presented as fact in answers (PLAN.md §12).
    confidence: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, default=dict, nullable=False)

    __table_args__ = (
        # An edge of a given kind between two nodes is unique.
        UniqueConstraint("src_node_id", "dst_node_id", "kind", name="uq_edges_src_dst_kind"),
        Index("ix_edges_repo_kind", "repo_id", "kind"),
        Index("ix_edges_src", "src_node_id"),
        Index("ix_edges_dst", "dst_node_id"),
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="confidence_range"),
    )


class Chunk(Base):
    """AST-aware retrieval unit: a symbol's source slice with exact line range.

    Chunks are the unit of hybrid retrieval (BM25 over `text`/`tsv`, dense over
    `embedding`). Exact line ranges make citations mechanical, not inferred.
    """

    __tablename__ = "chunks"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    repo_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("repos.id", ondelete="CASCADE"), nullable=False
    )
    node_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("nodes.id", ondelete="CASCADE")
    )
    path: Mapped[str] = mapped_column(Text, nullable=False)
    start_line: Mapped[int] = mapped_column(Integer, nullable=False)
    end_line: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM))  # set by embedder
    # DB-maintained full-text search vector over `text` — the BM25-ish keyword
    # side of hybrid retrieval. Generated column (Postgres keeps it in sync);
    # GIN-indexed for fast `@@` matches.
    tsv: Mapped[str | None] = mapped_column(
        TSVECTOR,
        Computed("to_tsvector('english', text)", persisted=True),
    )

    __table_args__ = (
        Index("ix_chunks_repo", "repo_id"),
        Index("ix_chunks_node", "node_id"),
        Index("ix_chunks_tsv", "tsv", postgresql_using="gin"),
    )


class IndexRun(Base):
    """One indexing run (full / incremental / escalation) — the cost + event anchor."""

    __tablename__ = "index_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    repo_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("repos.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[RunKind] = mapped_column(
        Enum(RunKind, name="run_kind"), default=RunKind.FULL, nullable=False
    )
    status: Mapped[RunStatus] = mapped_column(
        Enum(RunStatus, name="run_status"), default=RunStatus.RUNNING, nullable=False
    )
    started_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    finished_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    token_usage: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    error: Mapped[str | None] = mapped_column(Text)

    repo: Mapped[Repo] = relationship(back_populates="runs")

    __table_args__ = (Index("ix_index_runs_repo", "repo_id"),)


class AgentEvent(Base):
    """One event in an enrichment run — the Mission Control stream + replay log.

    Append-only. Each agent (planner / explorer_N / synthesizer / critic /
    librarian / supervisor) publishes events as it works: spawn, tool_call,
    finding, verdict, phase transition, error, done. `seq` is a per-run monotonic
    counter so a reconnecting WebSocket client can ask for "everything after
    seq N" and never miss or duplicate an event (PLAN.md §4.3, §6 state layer).

    `agent` and `type` are stored as plain strings (values of AgentRole /
    AgentEventType) rather than PG enums — this is a fast-growing log vocabulary,
    and append-only rows don't need enum-level integrity. `payload` carries the
    type-specific body (the finding text, the tool args, the verdict reason, …).
    """

    __tablename__ = "agent_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("index_runs.id", ondelete="CASCADE"), nullable=False
    )
    # Per-run monotonic sequence (1, 2, 3, …) for gap-free reconnect/replay.
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    ts: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    agent: Mapped[str] = mapped_column(String(32), nullable=False)  # AgentRole value
    type: Mapped[str] = mapped_column(String(32), nullable=False)  # AgentEventType value
    payload: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    __table_args__ = (
        UniqueConstraint("run_id", "seq", name="uq_agent_events_run_seq"),
        Index("ix_agent_events_run_seq", "run_id", "seq"),
    )


class Question(Base, TimestampMixin):
    """A user question asked about a repo (PLAN.md §3)."""

    __tablename__ = "questions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    repo_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("repos.id", ondelete="CASCADE"), nullable=False
    )
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    # The classification route the router picked (local, global, escalate).
    route: Mapped[str] = mapped_column(String(255), nullable=False)
    answer: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    # Groups questions into chat sessions (1hr TTL in Redis).
    # Auto-created by the backend if not provided by the client.
    session_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    # Unique per-turn identifier for this Q&A exchange. Always set by the API.
    # Nullable at the DB level for backward compatibility with existing rows.
    conversation_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    citations: Mapped[list[dict]] = mapped_column(JSONB, default=list, nullable=False)
    citation_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    repo: Mapped[Repo] = relationship(back_populates="questions")

    __table_args__ = (
        Index("ix_questions_repo", "repo_id"),
        Index("ix_questions_session", "session_id"),
        Index("ix_questions_conversation", "conversation_id"),
    )
