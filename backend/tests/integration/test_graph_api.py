"""API tests for the graph-facing endpoints: graph slice, file content, walkthrough.

Seeds a small graph (with communities + a RepoModel) through the rolled-back
test session and exercises the HTTP surface Atlas / the code panel / the
walkthrough view consume.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.enums import EdgeKind, NodeKind
from app.db.models import Chunk, Community, Edge, Node, Repo
from app.db.session import get_session
from app.main import create_app

pytestmark = pytest.mark.db


@pytest.fixture
async def api_client(db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    """ASGI client whose DB dependency is the rolled-back test session."""
    app = create_app()

    async def _override() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_session] = _override
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


async def _seed(session: AsyncSession) -> Repo:
    repo = Repo(url="https://github.com/test/graphapi", head_commit="a" * 40)
    session.add(repo)
    await session.flush()

    repo_node = Node(
        repo_id=repo.id,
        kind=NodeKind.REPO,
        fqname="repo",
        annotations=[
            {
                "kind": "repo_model",
                "verified": True,
                "source": "synthesizer",
                "model": {
                    "summary": "A test repo.",
                    "walkthrough": [
                        {"title": "Read main", "detail": "Start here.", "fqname": "pkg.main"}
                    ],
                },
            }
        ],
    )
    fn = Node(
        repo_id=repo.id,
        kind=NodeKind.FUNCTION,
        fqname="pkg.main",
        path="pkg/main.py",
        start_line=1,
        end_line=2,
        summary="Entry point.",
        annotations=[{"kind": "role", "text": "entry", "verified": True, "source": "x"}],
    )
    helper = Node(repo_id=repo.id, kind=NodeKind.FUNCTION, fqname="pkg.helper", path="pkg/main.py")
    session.add_all([repo_node, fn, helper])
    await session.flush()
    session.add_all(
        [
            Chunk(
                repo_id=repo.id,
                node_id=fn.id,
                path="pkg/main.py",
                start_line=1,
                end_line=2,
                text="def main():\n    helper()",
            ),
            Edge(
                repo_id=repo.id,
                src_node_id=fn.id,
                dst_node_id=helper.id,
                kind=EdgeKind.CALLS,
                confidence=1.0,
            ),
            Community(
                repo_id=repo.id,
                key="c0",
                title="core",
                summary="the core",
                node_ids=[fn.id],
                size=1,
            ),
        ]
    )
    await session.flush()
    return repo


async def test_graph_slice(api_client: AsyncClient, db_session: AsyncSession) -> None:
    repo = await _seed(db_session)
    resp = await api_client.get(f"/api/repos/{repo.id}/graph")
    assert resp.status_code == 200
    data = resp.json()
    fqnames = {n["fqname"] for n in data["nodes"]}
    assert {"pkg.main", "pkg.helper"} <= fqnames
    assert data["total_nodes"] == 3
    assert any(e["kind"] == "calls" for e in data["edges"])
    main = next(n for n in data["nodes"] if n["fqname"] == "pkg.main")
    assert main["community"] == "c0"
    assert main["annotations"] == 1
    assert data["communities"][0]["key"] == "c0"


async def test_graph_slice_caps_nodes(api_client: AsyncClient, db_session: AsyncSession) -> None:
    repo = await _seed(db_session)
    resp = await api_client.get(f"/api/repos/{repo.id}/graph?max_nodes=10")
    assert resp.status_code == 200
    assert len(resp.json()["nodes"]) <= 10


async def test_file_content(api_client: AsyncClient, db_session: AsyncSession) -> None:
    repo = await _seed(db_session)
    resp = await api_client.get(f"/api/repos/{repo.id}/file", params={"path": "pkg/main.py"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["found"] is True
    assert "helper()" in data["text"]
    assert data["start_line"] == 1

    missing = await api_client.get(f"/api/repos/{repo.id}/file", params={"path": "nope.py"})
    assert missing.status_code == 200
    assert missing.json()["found"] is False


async def test_walkthrough(api_client: AsyncClient, db_session: AsyncSession) -> None:
    repo = await _seed(db_session)
    resp = await api_client.get(f"/api/repos/{repo.id}/walkthrough")
    assert resp.status_code == 200
    data = resp.json()
    assert data["summary"] == "A test repo."
    assert data["steps"][0]["fqname"] == "pkg.main"


async def test_walkthrough_404_before_enrichment(
    api_client: AsyncClient, db_session: AsyncSession
) -> None:
    repo = Repo(url="https://github.com/test/bare", head_commit="b" * 40)
    db_session.add(repo)
    await db_session.flush()
    resp = await api_client.get(f"/api/repos/{repo.id}/walkthrough")
    assert resp.status_code == 404
