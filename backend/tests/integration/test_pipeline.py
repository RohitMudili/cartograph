"""End-to-end pipeline tests — the Phase 2 milestone.

Two tiers:
- `test_build_from_local_dir` (db): runs the real parse + build pipeline core
  against a local directory — no clone needed, fully deterministic, exercises
  file discovery, multi-file parsing, and cross-file graph resolution together.
- `test_index_github_repo` (db + network): the *full* path through the real
  cloner + extractor + builder against a small public GitHub repo. Marked
  network so it can be deselected offline.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.enums import EdgeKind, RepoStatus
from app.db.models import Edge, Node, Repo
from app.indexer.pipeline import build_graph_from_workspace, index_repo

pytestmark = pytest.mark.db


def _write_fixture_repo(root: Path) -> None:
    """A tiny two-file package exercising imports, inheritance, and calls."""
    pkg = root / "app"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("")
    (pkg / "base.py").write_text("class Base:\n    def describe(self):\n        return 'base'\n")
    (pkg / "service.py").write_text(
        "from app.base import Base\n\n\n"
        "class Service(Base):\n"
        "    def run(self):\n"
        "        return compute(1)\n\n\n"
        "def compute(x):\n"
        "    return x + 1\n"
    )


async def test_build_from_local_dir(db_session: AsyncSession, tmp_path: Path) -> None:
    _write_fixture_repo(tmp_path)
    repo = Repo(url="local://fixture", head_commit="0" * 40, status=RepoStatus.PARSING)
    db_session.add(repo)
    await db_session.flush()

    stats = await build_graph_from_workspace(db_session, repo.id, tmp_path)

    # 3 files (__init__, base, service) + Base, describe, Service, run, compute = 8
    assert stats.files == 3
    assert stats.nodes == 8

    node_count = await db_session.scalar(
        select(func.count()).select_from(Node).where(Node.repo_id == repo.id)
    )
    assert node_count == 8

    # The cross-file INHERITS edge is the proof the whole pipeline connected.
    svc = await db_session.scalar(
        select(Node).where(Node.repo_id == repo.id, Node.fqname == "app.service.Service")
    )
    base = await db_session.scalar(
        select(Node).where(Node.repo_id == repo.id, Node.fqname == "app.base.Base")
    )
    assert svc and base
    inherits = await db_session.scalar(
        select(Edge).where(
            Edge.src_node_id == svc.id,
            Edge.dst_node_id == base.id,
            Edge.kind == EdgeKind.INHERITS,
        )
    )
    assert inherits is not None


async def test_skips_noise_dirs(db_session: AsyncSession, tmp_path: Path) -> None:
    _write_fixture_repo(tmp_path)
    # A vendored file under a skip-dir must not be parsed.
    vendored = tmp_path / "node_modules" / "junk"
    vendored.mkdir(parents=True)
    (vendored / "mod.py").write_text("def should_not_appear():\n    pass\n")

    repo = Repo(url="local://fixture2", head_commit="1" * 40, status=RepoStatus.PARSING)
    db_session.add(repo)
    await db_session.flush()
    await build_graph_from_workspace(db_session, repo.id, tmp_path)

    leaked = await db_session.scalar(
        select(Node).where(Node.repo_id == repo.id, Node.fqname.like("%should_not_appear%"))
    )
    assert leaked is None


@pytest.mark.network
async def test_index_github_repo(db_session: AsyncSession) -> None:
    """Full path: real cloner + extractor + builder on a small public repo."""
    result = await index_repo(db_session, "https://github.com/psf/cachecontrol")

    repo = await db_session.get(Repo, uuid.UUID(result.repo_id))
    assert repo is not None
    assert repo.status == RepoStatus.INDEXED
    assert result.stats.nodes > 0
    assert result.head_commit
    assert repo.stats["files_parsed"] >= 1
