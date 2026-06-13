"""Integration tests for the graph builder against a live Postgres.

Marked `db` — requires the docker-compose database. Each test creates a repo,
builds a graph from real extracted source, and asserts the resolved structure,
then rolls back.
"""

from __future__ import annotations

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.enums import EdgeKind, NodeKind
from app.db.models import Chunk, Edge, Node, Repo
from app.indexer.graph_builder import GraphBuilder
from app.indexer.parser.python import extract_python

pytestmark = pytest.mark.db


# A tiny two-file package exercising contains, imports, inherits, and calls.
FILE_A = b"""from app.base import Base


class Service(Base):
    def run(self):
        return compute(1)


def compute(x):
    return x + 1
"""

FILE_B = b"""class Base:
    def describe(self):
        return "base"
"""


async def _make_repo(session: AsyncSession) -> Repo:
    repo = Repo(url="https://github.com/test/fixture", head_commit="deadbeef" * 5)
    session.add(repo)
    await session.flush()
    return repo


async def test_builds_nodes_edges_chunks(db_session: AsyncSession) -> None:
    repo = await _make_repo(db_session)
    extracts = [
        extract_python("app/service.py", FILE_A),
        extract_python("app/base.py", FILE_B),
    ]
    builder = GraphBuilder(db_session, repo.id)
    stats = await builder.build(extracts)

    # Nodes: 2 files + Service + run + compute + Base + describe = 7
    assert stats.nodes == 7
    assert stats.files == 2
    assert stats.chunks >= 5

    node_count = await db_session.scalar(
        select(func.count()).select_from(Node).where(Node.repo_id == repo.id)
    )
    assert node_count == 7


async def test_contains_edges(db_session: AsyncSession) -> None:
    repo = await _make_repo(db_session)
    extracts = [extract_python("app/service.py", FILE_A), extract_python("app/base.py", FILE_B)]
    await GraphBuilder(db_session, repo.id).build(extracts)

    # Service contains run
    svc = await db_session.scalar(
        select(Node).where(Node.repo_id == repo.id, Node.fqname == "app.service.Service")
    )
    run = await db_session.scalar(
        select(Node).where(Node.repo_id == repo.id, Node.fqname == "app.service.Service.run")
    )
    assert svc is not None and run is not None
    contains = await db_session.scalar(
        select(Edge).where(
            Edge.src_node_id == svc.id,
            Edge.dst_node_id == run.id,
            Edge.kind == EdgeKind.CONTAINS,
        )
    )
    assert contains is not None


async def test_inherits_resolves_cross_file(db_session: AsyncSession) -> None:
    repo = await _make_repo(db_session)
    extracts = [extract_python("app/service.py", FILE_A), extract_python("app/base.py", FILE_B)]
    await GraphBuilder(db_session, repo.id).build(extracts)

    svc = await db_session.scalar(
        select(Node).where(Node.fqname == "app.service.Service", Node.repo_id == repo.id)
    )
    base = await db_session.scalar(
        select(Node).where(Node.fqname == "app.base.Base", Node.repo_id == repo.id)
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
    assert inherits.confidence == 1.0


async def test_calls_resolved_with_confidence(db_session: AsyncSession) -> None:
    repo = await _make_repo(db_session)
    extracts = [extract_python("app/service.py", FILE_A), extract_python("app/base.py", FILE_B)]
    await GraphBuilder(db_session, repo.id).build(extracts)

    run = await db_session.scalar(
        select(Node).where(Node.fqname == "app.service.Service.run", Node.repo_id == repo.id)
    )
    compute = await db_session.scalar(
        select(Node).where(Node.fqname == "app.service.compute", Node.repo_id == repo.id)
    )
    assert run and compute
    # run() calls compute(1) — unique name, full confidence.
    call = await db_session.scalar(
        select(Edge).where(
            Edge.src_node_id == run.id,
            Edge.dst_node_id == compute.id,
            Edge.kind == EdgeKind.CALLS,
        )
    )
    assert call is not None
    assert call.confidence == 1.0


async def test_imports_edge_in_repo(db_session: AsyncSession) -> None:
    repo = await _make_repo(db_session)
    extracts = [extract_python("app/service.py", FILE_A), extract_python("app/base.py", FILE_B)]
    await GraphBuilder(db_session, repo.id).build(extracts)

    svc_file = await db_session.scalar(
        select(Node).where(Node.fqname == "app.service", Node.repo_id == repo.id)
    )
    base_file = await db_session.scalar(
        select(Node).where(Node.fqname == "app.base", Node.repo_id == repo.id)
    )
    assert svc_file and base_file
    # `from app.base import Base` → app.service imports app.base
    imp = await db_session.scalar(
        select(Edge).where(
            Edge.src_node_id == svc_file.id,
            Edge.dst_node_id == base_file.id,
            Edge.kind == EdgeKind.IMPORTS,
        )
    )
    assert imp is not None


async def test_metrics_written(db_session: AsyncSession) -> None:
    repo = await _make_repo(db_session)
    extracts = [extract_python("app/service.py", FILE_A), extract_python("app/base.py", FILE_B)]
    await GraphBuilder(db_session, repo.id).build(extracts)

    compute = await db_session.scalar(
        select(Node).where(Node.fqname == "app.service.compute", Node.repo_id == repo.id)
    )
    assert compute is not None
    # compute is called once by run → fan_in == 1; loc recorded.
    assert compute.metrics["fan_in"] == 1
    assert compute.metrics["loc"] >= 1


async def test_chunks_have_line_ranges(db_session: AsyncSession) -> None:
    repo = await _make_repo(db_session)
    extracts = [extract_python("app/service.py", FILE_A), extract_python("app/base.py", FILE_B)]
    await GraphBuilder(db_session, repo.id).build(extracts)

    chunks = (await db_session.scalars(select(Chunk).where(Chunk.repo_id == repo.id))).all()
    assert chunks
    for c in chunks:
        assert c.start_line >= 1
        assert c.end_line >= c.start_line
        assert c.text.strip()


async def test_node_kinds(db_session: AsyncSession) -> None:
    repo = await _make_repo(db_session)
    extracts = [extract_python("app/service.py", FILE_A), extract_python("app/base.py", FILE_B)]
    await GraphBuilder(db_session, repo.id).build(extracts)

    kinds = {
        row.fqname: row.kind
        for row in (await db_session.scalars(select(Node).where(Node.repo_id == repo.id))).all()
    }
    assert kinds["app.service"] == NodeKind.FILE
    assert kinds["app.service.Service"] == NodeKind.CLASS
    assert kinds["app.service.Service.run"] == NodeKind.METHOD
    assert kinds["app.service.compute"] == NodeKind.FUNCTION
