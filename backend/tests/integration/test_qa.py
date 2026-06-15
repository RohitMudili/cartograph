"""Tests for citation verification + local-route Q&A (db, no real LLM).

The verifier tests are pure DB logic. The answerer tests mock the LLM so CI runs
them with no key — including the critical path: a hallucinated citation is caught
and stripped, never returned as verified.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import EMBEDDING_DIM
from app.db.models import Node, Repo
from app.indexer.graph_builder import GraphBuilder
from app.indexer.parser.python import extract_python
from app.query import answerer as ans_mod
from app.query import retrieval as retr_mod
from app.query.answerer import Answerer, _AnswerOut, _CitationOut
from app.query.verifier import Citation, CitationVerifier

pytestmark = pytest.mark.db

FILE_A = b'''def compute(x):
    """Add one to the input."""
    return x + 1
'''


async def _seed(session: AsyncSession) -> Repo:
    repo = Repo(url="https://github.com/test/qa", head_commit="d" * 40)
    session.add(repo)
    await session.flush()
    await GraphBuilder(session, repo.id).build([extract_python("app/m.py", FILE_A)])
    nodes = (await session.scalars(select(Node).where(Node.repo_id == repo.id))).all()
    for n in nodes:
        await session.execute(
            update(Node)
            .where(Node.id == n.id)
            .values(summary=f"{n.fqname} summary", summary_embedding=[0.0] * EMBEDDING_DIM)
        )
    return repo


# ── Verifier ──────────────────────────────────────────────────────────────────


async def test_verify_good_citation(db_session: AsyncSession) -> None:
    repo = await _seed(db_session)
    v = CitationVerifier(db_session, repo.id)
    # `compute` is at app/m.py lines 1-3, source contains "def compute".
    result = await v.verify(Citation("app/m.py", 1, 3, "def compute(x):"))
    assert result.verified, result.reason


async def test_verify_rejects_unknown_path(db_session: AsyncSession) -> None:
    repo = await _seed(db_session)
    v = CitationVerifier(db_session, repo.id)
    result = await v.verify(Citation("does/not/exist.py", 1, 3, "whatever"))
    assert not result.verified
    assert "not in repo" in result.reason


async def test_verify_rejects_fabricated_snippet(db_session: AsyncSession) -> None:
    repo = await _seed(db_session)
    v = CitationVerifier(db_session, repo.id)
    # Right file, but a snippet that isn't there.
    result = await v.verify(Citation("app/m.py", 1, 3, "def totally_made_up_function():"))
    assert not result.verified
    assert "snippet" in result.reason


async def test_verify_rejects_out_of_range_lines(db_session: AsyncSession) -> None:
    repo = await _seed(db_session)
    v = CitationVerifier(db_session, repo.id)
    result = await v.verify(Citation("app/m.py", 9000, 9010, None))
    assert not result.verified


# ── Answerer (mocked LLM) ─────────────────────────────────────────────────────


def _patch_retrieval_embed(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_embed(text, *, ledger=None):
        return [0.0] * EMBEDDING_DIM

    monkeypatch.setattr(retr_mod, "embed_query", _fake_embed)


def _patch_llm(monkeypatch: pytest.MonkeyPatch, outputs: list[_AnswerOut]) -> None:
    """Make reasoning().complete_structured return the queued outputs in order."""
    calls = {"i": 0}

    class _FakeLLM:
        async def complete_structured(self, prompt, schema, *, system=None):
            out = outputs[min(calls["i"], len(outputs) - 1)]
            calls["i"] += 1
            return out

    monkeypatch.setattr(ans_mod, "reasoning", lambda ledger=None: _FakeLLM())


async def test_answer_with_verified_citation(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = await _seed(db_session)
    _patch_retrieval_embed(monkeypatch)
    _patch_llm(
        monkeypatch,
        [
            _AnswerOut(
                answer="compute adds one.",
                citations=[
                    _CitationOut(
                        path="app/m.py", start_line=1, end_line=3, quoted_snippet="def compute(x):"
                    )
                ],
                answerable=True,
            )
        ],
    )
    ans = await Answerer(db_session, repo.id).answer("what does compute do?")
    assert ans.fully_verified
    assert len(ans.verified_citations) == 1
    assert ans.verified_citations[0].path == "app/m.py"


async def test_hallucinated_citation_is_caught(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A made-up citation must NOT come back verified — both attempts hallucinate."""
    repo = await _seed(db_session)
    _patch_retrieval_embed(monkeypatch)
    fake = _AnswerOut(
        answer="it does magic.",
        citations=[
            _CitationOut(
                path="app/ghost.py", start_line=1, end_line=5, quoted_snippet="def ghost():"
            )
        ],
        answerable=True,
    )
    _patch_llm(monkeypatch, [fake, fake])  # regen also hallucinates

    ans = await Answerer(db_session, repo.id).answer("what does compute do?")
    assert not ans.fully_verified
    # The bad citation is present but flagged unverified; verified list is empty.
    assert ans.verified_citations == []
    assert any(not vc.verified for vc in ans.citations)


async def test_regeneration_fixes_bad_citation(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """First attempt cites a ghost file; the retry cites correctly and verifies."""
    repo = await _seed(db_session)
    _patch_retrieval_embed(monkeypatch)
    bad = _AnswerOut(
        answer="x",
        citations=[
            _CitationOut(path="app/ghost.py", start_line=1, end_line=2, quoted_snippet="nope")
        ],
        answerable=True,
    )
    good = _AnswerOut(
        answer="compute adds one.",
        citations=[
            _CitationOut(
                path="app/m.py", start_line=1, end_line=3, quoted_snippet="def compute(x):"
            )
        ],
        answerable=True,
    )
    _patch_llm(monkeypatch, [bad, good])

    ans = await Answerer(db_session, repo.id).answer("what does compute do?")
    assert ans.fully_verified
    assert len(ans.verified_citations) == 1
