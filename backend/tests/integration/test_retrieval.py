"""Tests for hybrid retrieval (db, no real LLM).

Seeds a graph, hand-writes summaries + embeddings (deterministic vectors so the
vector search is predictable), then exercises BM25, dense, graph expansion, and
RRF fusion. The query embedding is monkeypatched so no API key is needed.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import EMBEDDING_DIM
from app.db.models import Node, Repo
from app.indexer.graph_builder import GraphBuilder
from app.indexer.parser.python import extract_python
from app.query import retrieval as retr_mod
from app.query.retrieval import Retriever, _rrf_merge

pytestmark = pytest.mark.db

FILE_A = b'''from app.base import Base


class Service(Base):
    def run(self):
        return compute(1)


def compute(x):
    """Add one to the input."""
    return x + 1
'''
FILE_B = b"""class Base:
    def describe(self):
        return "base"
"""


def _vec(seed: float) -> list[float]:
    """A deterministic unit-ish embedding; distinct seeds → distinct directions."""
    v = [0.0] * EMBEDDING_DIM
    v[int(seed) % EMBEDDING_DIM] = 1.0
    return v


async def _seed_indexed_repo(session: AsyncSession) -> Repo:
    repo = Repo(url="https://github.com/test/retr", head_commit="c" * 40)
    session.add(repo)
    await session.flush()
    extracts = [
        extract_python("app/service.py", FILE_A),
        extract_python("app/base.py", FILE_B),
    ]
    await GraphBuilder(session, repo.id).build(extracts)

    # Hand-write summaries + embeddings so retrieval has something to match.
    # `compute` gets a summary mentioning "addition"; give each node a distinct
    # embedding so cosine ranking is deterministic.
    nodes = (await session.scalars(select(Node).where(Node.repo_id == repo.id))).all()
    for i, n in enumerate(nodes):
        summ = f"{n.fqname} does something"
        if n.fqname.endswith("compute"):
            summ = "Adds one to the input integer (addition helper)."
        await session.execute(
            update(Node).where(Node.id == n.id).values(summary=summ, summary_embedding=_vec(i + 1))
        )
    return repo


def test_rrf_merge_ranks_multi_signal_higher() -> None:
    # id 5 appears in both lists near the top → should beat singletons.
    fused = _rrf_merge({"a": [5, 1, 2], "b": [5, 3, 4]})
    ordered = sorted(fused.items(), key=lambda kv: kv[1][0], reverse=True)
    assert ordered[0][0] == 5
    assert set(fused[5][1]) == {"a", "b"}


async def test_bm25_finds_by_keyword(db_session: AsyncSession, monkeypatch) -> None:
    repo = await _seed_indexed_repo(db_session)

    # Make the dense signal a no-op by embedding the query far from everything.
    async def _fake_embed(text, *, ledger=None):
        return _vec(9999)

    monkeypatch.setattr(retr_mod, "embed_query", _fake_embed)

    # "compute" appears literally in the source chunk → BM25 should surface it.
    items = await Retriever(db_session, repo.id).retrieve("compute", top_k=5, expand=False)
    fqnames = [it.fqname for it in items]
    assert any("compute" in fq for fq in fqnames)
    assert any("bm25" in it.signals for it in items)


async def test_dense_finds_by_meaning(db_session: AsyncSession, monkeypatch) -> None:
    repo = await _seed_indexed_repo(db_session)

    # Point the query embedding exactly at `compute`'s vector so cosine ranks it #1.
    compute = await db_session.scalar(
        select(Node).where(Node.fqname == "app.service.compute", Node.repo_id == repo.id)
    )
    assert compute is not None
    target_vec = list(compute.summary_embedding)  # type: ignore[arg-type]

    async def _fake_embed(text, *, ledger=None):
        return target_vec

    monkeypatch.setattr(retr_mod, "embed_query", _fake_embed)

    items = await Retriever(db_session, repo.id).retrieve("addition", top_k=5, expand=False)
    assert items
    assert items[0].fqname == "app.service.compute"
    assert "dense" in items[0].signals


async def test_graph_expansion_adds_neighbours(db_session: AsyncSession, monkeypatch) -> None:
    repo = await _seed_indexed_repo(db_session)

    # Seed retrieval on `run` (which calls compute); expansion should pull compute.
    run = await db_session.scalar(
        select(Node).where(Node.fqname == "app.service.Service.run", Node.repo_id == repo.id)
    )
    assert run is not None

    async def _fake_embed(text, *, ledger=None):
        return list(run.summary_embedding)  # type: ignore[arg-type]

    monkeypatch.setattr(retr_mod, "embed_query", _fake_embed)

    with_expand = await Retriever(db_session, repo.id).retrieve("run", top_k=10, expand=True)
    fqnames = {it.fqname for it in with_expand}
    # `compute` is a callee neighbour of `run` and should appear via expansion.
    assert "app.service.compute" in fqnames
    compute_item = next(it for it in with_expand if it.fqname == "app.service.compute")
    assert "graph" in compute_item.signals or "dense" in compute_item.signals


async def test_items_carry_citation_fields(db_session: AsyncSession, monkeypatch) -> None:
    repo = await _seed_indexed_repo(db_session)

    async def _fake_embed(text, *, ledger=None):
        return _vec(1)

    monkeypatch.setattr(retr_mod, "embed_query", _fake_embed)

    items = await Retriever(db_session, repo.id).retrieve("compute", top_k=5)
    assert items
    # Every item must have what citations need: path + line range.
    for it in items:
        if it.kind != "repo":
            assert it.path is not None
            assert it.start_line is not None and it.start_line >= 1
