"""Static indexing pipeline: clone → parse → build graph.

Orchestrates the deterministic, zero-LLM static-graph flow end to end and records
it as an IndexRun, then runs the semantic layer (summaries + embeddings) when an
LLM is configured. The static portion is fully functional and testable on its own.

Flow:
  1. Create/lookup the Repo row, open an IndexRun.
  2. Clone the repo into a sandboxed workspace (cloner, with all guards).
  3. Walk supported source files; parse each with the language extractor.
  4. Build + persist the graph (nodes/edges/chunks/metrics) in one transaction.
  5. Mark the repo INDEXED with stats, or FAILED with the error; always clean
     up the workspace.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.events import EventEmitter
from app.agents.llm import UsageLedger
from app.config import get_settings
from app.db.enums import AgentEventType, AgentRole, RepoStatus, RunStatus
from app.db.models import IndexRun, Repo
from app.indexer.cloner import CloneError, _validate_url, cleanup_workspace, clone_repo
from app.indexer.graph_builder import BuildStats, GraphBuilder
from app.indexer.parser.markdown import extract_markdown
from app.indexer.parser.python import extract_python
from app.indexer.parser.types import FileExtract
from app.indexer.summarizer import Summarizer

log = structlog.get_logger(__name__)

# Directories never worth indexing — vendored deps, caches, build output, VCS.
SKIP_DIRS = {
    ".git",
    "node_modules",
    "__pycache__",
    ".venv",
    "venv",
    "dist",
    "build",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "site-packages",
}

# Extension → extractor. Adding a language is a new entry here plus its extractor.
EXTRACTORS = {
    ".py": extract_python,
    ".md": extract_markdown,
}


@dataclass(slots=True)
class IndexResult:
    repo_id: str
    run_id: str
    head_commit: str
    stats: BuildStats


def _iter_source_files(workspace: Path) -> list[Path]:
    """Find indexable source files under the workspace, skipping noise dirs."""
    out: list[Path] = []
    for path in workspace.rglob("*"):
        if not path.is_file():
            continue
        if any(part in SKIP_DIRS for part in path.relative_to(workspace).parts):
            continue
        if path.suffix in EXTRACTORS:
            out.append(path)
    return out


def _parse_files(workspace: Path, files: list[Path]) -> list[FileExtract]:
    """Parse each file with its extractor. A file that fails to read is skipped;
    a file that fails to parse still yields a FileExtract (had_errors=True)."""
    extracts: list[FileExtract] = []
    for f in files:
        rel = f.relative_to(workspace).as_posix()
        try:
            source = f.read_bytes()
        except OSError as exc:
            log.warning("parse.read_failed", path=rel, error=str(exc))
            continue
        extractor = EXTRACTORS[f.suffix]
        extracts.append(extractor(rel, source))
    return extracts


async def _get_or_create_repo(session: AsyncSession, url: str) -> Repo:
    existing = await session.scalar(
        select(Repo).where(Repo.url == url).order_by(Repo.created_at.desc()).limit(1)
    )
    if existing is not None:
        return existing
    repo = Repo(url=url, status=RepoStatus.PENDING)
    session.add(repo)
    await session.flush()
    return repo


async def _make_emitter(run_id: uuid.UUID) -> EventEmitter:
    """An EventEmitter on its own dedicated session, for the whole run's phase +
    agent events (so `seq` stays monotonic across the entire pipeline)."""
    from app.db.session import get_sessionmaker

    event_session = get_sessionmaker()()
    return EventEmitter(run_id, event_session)


async def _run_enrichment(
    session: AsyncSession,
    repo_id: uuid.UUID,
    run_id: uuid.UUID,
    ledger: UsageLedger,
    emitter: EventEmitter | None,
):
    """Run the agent fleet over the summarized graph. Best-effort: any failure is
    swallowed (the fleet itself also catches internally) so a bad enrichment never
    fails an otherwise-good index. Reuses the run's `emitter` so all events share
    one monotonic seq; if none was supplied (no event stream), the fleet makes its
    own throwaway emitter."""
    from app.agents.graph_def import run_enrichment_fleet
    from app.db.session import get_sessionmaker

    try:
        if emitter is not None:
            return await run_enrichment_fleet(
                session, repo_id, run_id=run_id, emitter=emitter, ledger=ledger
            )
        async with get_sessionmaker()() as event_session:
            return await run_enrichment_fleet(
                session, repo_id, run_id=run_id, event_session=event_session, ledger=ledger
            )
    except Exception as exc:  # noqa: BLE001 — enrichment must never fail the index
        log.warning("index.enrichment_failed", repo_id=str(repo_id), error=str(exc))
        return None


async def build_graph_from_workspace(
    session: AsyncSession, repo_id: uuid.UUID, workspace: Path
) -> BuildStats:
    """Parse all supported files under `workspace` and build the graph.

    This is the post-clone core of the pipeline, factored out so it can be tested
    directly against a local directory without going through the (deliberately
    file://-blocking) cloner.
    """
    files = _iter_source_files(workspace)
    extracts = _parse_files(workspace, files)
    return await GraphBuilder(session, repo_id).build(extracts)


async def index_repo(
    session: AsyncSession,
    url: str,
    *,
    branch: str | None = None,
    emit_events: bool = False,
) -> IndexResult:
    """Run the full static index for `url`. Commits on success; the caller's
    session transaction wraps the whole operation.

    Idempotent: if the repo is already indexed, returns its existing result
    without re-cloning or re-building (re-indexing is an explicit reindex action,
    not the default — so the UI can send a user straight to chat).

    `emit_events=True` publishes supervisor `phase` events (cloning/parsing/
    summarizing/enriching) and a terminal done/error to the run's agent_events
    stream, so the live Mission Control page can show the whole pipeline, not just
    the fleet. Used by the background-kickoff path.
    """
    repo = await _get_or_create_repo(session, url)

    if repo.status == RepoStatus.INDEXED:
        stats = repo.stats or {}
        latest_run = await session.scalar(
            select(IndexRun)
            .where(IndexRun.repo_id == repo.id)
            .order_by(IndexRun.started_at.desc())
            .limit(1)
        )
        return IndexResult(
            repo_id=str(repo.id),
            run_id=str(latest_run.id) if latest_run else "",
            head_commit=repo.head_commit or "",
            stats=BuildStats(
                nodes=int(stats.get("nodes", 0)),
                edges=int(stats.get("edges", 0)),
                chunks=int(stats.get("chunks", 0)),
                files=int(stats.get("files_parsed", 0)),
            ),
        )

    # Reuse a RUNNING run if the kickoff (start_index) already created one for this
    # repo — so the run_id the client is already streaming matches. Otherwise make
    # one (the direct/synchronous path).
    run = await session.scalar(
        select(IndexRun)
        .where(IndexRun.repo_id == repo.id, IndexRun.status == RunStatus.RUNNING)
        .order_by(IndexRun.started_at.desc())
        .limit(1)
    )
    if run is None:
        run = IndexRun(repo_id=repo.id, status=RunStatus.RUNNING)
        session.add(run)
    repo.status = RepoStatus.CLONING
    # Commit the repo + run rows up front so the run_id exists durably: the live
    # Mission Control page resolves it immediately and the phase events below
    # (emitted on a separate session) can FK to index_runs.id.
    await session.commit()

    emitter = await _make_emitter(run.id) if emit_events else None

    async def phase(name: str, **extra: object) -> None:
        if emitter is not None:
            await emitter.emit(AgentRole.SUPERVISOR, AgentEventType.PHASE, {"phase": name, **extra})

    workspace: Path | None = None
    try:
        await phase("cloning")
        clone = await clone_repo(url, workspace_id=str(repo.id), branch=branch)
        workspace = clone.workspace
        repo.head_commit = clone.head_commit
        repo.default_branch = clone.default_branch
        repo.status = RepoStatus.PARSING
        await session.flush()

        await phase("parsing")
        stats = await build_graph_from_workspace(session, repo.id, workspace)
        await phase("parsing", nodes=stats.nodes, edges=stats.edges)

        # Semantic layer (summaries + embeddings). Skipped cleanly when no LLM key
        # is configured — the static graph above is fully usable on its own;
        # enrichment just doesn't run.
        ledger = UsageLedger()
        summary_stats = None
        fleet_result = None
        if get_settings().llm_available:
            repo.status = RepoStatus.SUMMARIZING
            await session.flush()
            await phase("summarizing")
            summary_stats = await Summarizer(session, repo.id, ledger=ledger).run()

            # Agent-fleet enrichment (PLAN.md §2.2) — explorers map the now-summarized
            # graph and write verified findings back. Non-fatal: if it fails or hits a
            # budget, the repo still indexes on the static + summary layers.
            #
            # COMMIT before enrichment: the fleet's event emitter writes agent_events
            # on a SEPARATE session, and those rows FK to index_runs.id. That session
            # can only see the IndexRun if it's already committed (a flush keeps it in
            # this session's uncommitted transaction). Committing here also makes the
            # index durable before the best-effort fleet runs.
            repo.status = RepoStatus.ENRICHING
            await session.commit()
            fleet_result = await _run_enrichment(session, repo.id, run.id, ledger, emitter)
        else:
            log.info("index.summaries_skipped", repo_id=str(repo.id), reason="no_llm_key")

        repo.status = RepoStatus.INDEXED
        repo.indexed_at = dt.datetime.now(dt.UTC)
        repo.stats = {
            "files_total": clone.file_count,
            "files_parsed": stats.files,
            "nodes": stats.nodes,
            "edges": stats.edges,
            "chunks": stats.chunks,
            "size_bytes": clone.size_bytes,
            "summarized": summary_stats.summarized if summary_stats else 0,
            "enrichment": {
                "subsystems": fleet_result.subsystems,
                "findings": fleet_result.findings,
                "accepted": fleet_result.accepted,
                "annotations": fleet_result.annotations_written,
            }
            if fleet_result
            else None,
        }
        # Token counts recorded; cost (usd) is filled from LangSmith when enabled.
        run.token_usage = ledger.summary()
        run.cost_usd = ledger.total_usd or 0.0
        run.status = RunStatus.SUCCEEDED
        run.finished_at = dt.datetime.now(dt.UTC)
        await session.flush()

        # Terminal event for the live page: the map is ready. `enriched` tells the
        # UI whether the agent pass actually produced findings or was skipped/
        # throttled (graceful-finish either way).
        if emitter is not None:
            await emitter.emit(
                AgentRole.SUPERVISOR,
                AgentEventType.DONE,
                {
                    "terminal": True,
                    "enriched": bool(fleet_result and fleet_result.annotations_written > 0),
                    "enrichment_error": (fleet_result.error if fleet_result else None),
                    "nodes": stats.nodes,
                    "edges": stats.edges,
                    "findings": fleet_result.findings if fleet_result else 0,
                    "accepted": fleet_result.accepted if fleet_result else 0,
                    "annotations": fleet_result.annotations_written if fleet_result else 0,
                },
            )

        log.info("index.done", repo_id=str(repo.id), head=clone.head_commit, **asdict(stats))
        return IndexResult(
            repo_id=str(repo.id),
            run_id=str(run.id),
            head_commit=clone.head_commit,
            stats=stats,
        )
    except CloneError as exc:
        repo.status = RepoStatus.FAILED
        run.status = RunStatus.FAILED
        run.error = str(exc)
        run.finished_at = dt.datetime.now(dt.UTC)
        await session.flush()
        if emitter is not None:
            await emitter.emit(
                AgentRole.SUPERVISOR, AgentEventType.ERROR, {"terminal": True, "error": str(exc)}
            )
        log.warning("index.clone_failed", repo_id=str(repo.id), error=str(exc))
        raise
    except Exception as exc:
        repo.status = RepoStatus.FAILED
        run.status = RunStatus.FAILED
        run.error = f"{type(exc).__name__}: {exc}"
        run.finished_at = dt.datetime.now(dt.UTC)
        await session.flush()
        if emitter is not None:
            await emitter.emit(
                AgentRole.SUPERVISOR,
                AgentEventType.ERROR,
                {"terminal": True, "error": f"{type(exc).__name__}: {exc}"},
            )
        log.error("index.failed", repo_id=str(repo.id), error=str(exc))
        raise
    finally:
        if workspace is not None:
            cleanup_workspace(workspace)
        if emitter is not None:
            await emitter.aclose()  # release the dedicated event session


@dataclass(slots=True)
class StartResult:
    """What the kickoff returns immediately, before indexing runs."""

    repo_id: str
    run_id: str
    status: str
    already_indexed: bool


async def start_index(
    session: AsyncSession,
    url: str,
    *,
    branch: str | None = None,
    owner_user_id: uuid.UUID | None = None,
) -> StartResult:
    """Kick off indexing and return immediately so the UI can open the live map.

    Creates (or finds) the repo + an IndexRun, commits them, then schedules the
    full pipeline (clone → parse → summarize → fleet, with event emission) as a
    detached background task. The client gets repo_id + run_id at once and follows
    the run via the agent-event stream / repo status.

    If the repo is already INDEXED, returns its existing run without re-running
    (idempotent) — the UI sends the user straight to chat.

    Raises CloneError synchronously for an invalid scheme / disallowed host, so a
    bad URL fails fast at the API boundary (400) rather than spinning up a doomed
    background run. (The actual clone — auth failures, missing repos — still
    happens in the background and surfaces on the run.)
    """
    _validate_url(url, get_settings())

    repo = await _get_or_create_repo(session, url)
    if owner_user_id is not None:
        repo.owner_user_id = owner_user_id

    if repo.status == RepoStatus.INDEXED:
        latest = await session.scalar(
            select(IndexRun)
            .where(IndexRun.repo_id == repo.id)
            .order_by(IndexRun.started_at.desc())
            .limit(1)
        )
        await session.commit()
        return StartResult(
            repo_id=str(repo.id),
            run_id=str(latest.id) if latest else "",
            status=repo.status.value,
            already_indexed=True,
        )

    run = IndexRun(repo_id=repo.id, status=RunStatus.RUNNING)
    session.add(run)
    repo.status = RepoStatus.PENDING
    await session.commit()  # durable repo_id + run_id before the bg task starts
    repo_id, run_id = repo.id, run.id

    async def _runner() -> None:
        from app.db.session import get_sessionmaker

        async with get_sessionmaker()() as bg_session:
            try:
                await index_repo(bg_session, url, branch=branch, emit_events=True)
                if owner_user_id is not None:
                    bg = await bg_session.get(Repo, repo_id)
                    if bg is not None and bg.owner_user_id is None:
                        bg.owner_user_id = owner_user_id
                await bg_session.commit()
            except Exception as exc:  # noqa: BLE001 — bg task; errors already recorded on the run
                log.warning("index.background_failed", repo_id=str(repo_id), error=str(exc))

    asyncio.create_task(_runner())  # noqa: RUF006 — detached background run
    return StartResult(
        repo_id=str(repo_id), run_id=str(run_id), status="pending", already_indexed=False
    )
