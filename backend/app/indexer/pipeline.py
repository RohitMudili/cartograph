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

import datetime as dt
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.llm import UsageLedger
from app.config import get_settings
from app.db.enums import RepoStatus, RunStatus
from app.db.models import IndexRun, Repo
from app.indexer.cloner import CloneError, cleanup_workspace, clone_repo
from app.indexer.graph_builder import BuildStats, GraphBuilder
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


async def index_repo(session: AsyncSession, url: str, *, branch: str | None = None) -> IndexResult:
    """Run the full static index for `url`. Commits on success; the caller's
    session transaction wraps the whole operation."""
    repo = await _get_or_create_repo(session, url)
    run = IndexRun(repo_id=repo.id, status=RunStatus.RUNNING)
    session.add(run)
    repo.status = RepoStatus.CLONING
    await session.flush()

    workspace: Path | None = None
    try:
        clone = await clone_repo(url, workspace_id=str(repo.id), branch=branch)
        workspace = clone.workspace
        repo.head_commit = clone.head_commit
        repo.default_branch = clone.default_branch
        repo.status = RepoStatus.PARSING
        await session.flush()

        stats = await build_graph_from_workspace(session, repo.id, workspace)

        # Semantic layer (summaries + embeddings). Skipped cleanly when no LLM key
        # is configured — the static graph above is fully usable on its own;
        # enrichment just doesn't run.
        ledger = UsageLedger()
        summary_stats = None
        if get_settings().llm_available:
            repo.status = RepoStatus.SUMMARIZING
            await session.flush()
            summary_stats = await Summarizer(session, repo.id, ledger=ledger).run()
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
        }
        # Token counts recorded; cost (usd) is filled from LangSmith when enabled.
        run.token_usage = ledger.summary()
        run.cost_usd = ledger.total_usd or 0.0
        run.status = RunStatus.SUCCEEDED
        run.finished_at = dt.datetime.now(dt.UTC)
        await session.flush()

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
        log.warning("index.clone_failed", repo_id=str(repo.id), error=str(exc))
        raise
    except Exception as exc:
        repo.status = RepoStatus.FAILED
        run.status = RunStatus.FAILED
        run.error = f"{type(exc).__name__}: {exc}"
        run.finished_at = dt.datetime.now(dt.UTC)
        await session.flush()
        log.error("index.failed", repo_id=str(repo.id), error=str(exc))
        raise
    finally:
        if workspace is not None:
            cleanup_workspace(workspace)
