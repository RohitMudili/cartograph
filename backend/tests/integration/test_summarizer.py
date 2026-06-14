"""Tests for the summarizer's orchestration (db, no real LLM).

The LLM and embedding calls are monkeypatched with deterministic fakes so we test
the real logic — bottom-up ordering, summary persistence, embedding write-back,
batching — against a live Postgres without API cost or flakiness. A real end-to-end
summarize lives behind the `network` marker in test_pipeline.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import EMBEDDING_DIM
from app.db.models import Chunk, Node, Repo
from app.indexer import summarizer as summ_mod
from app.indexer.graph_builder import GraphBuilder
from app.indexer.parser.python import extract_python
from app.indexer.summarizer import Summarizer, _Summary

pytestmark = pytest.mark.db

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


async def _seed_graph(session: AsyncSession) -> Repo:
    repo = Repo(url="https://github.com/test/summ", head_commit="a" * 40)
    session.add(repo)
    await session.flush()
    extracts = [
        extract_python("app/service.py", FILE_A),
        extract_python("app/base.py", FILE_B),
    ]
    await GraphBuilder(session, repo.id).build(extracts)
    return repo


def _install_fakes(monkeypatch: pytest.MonkeyPatch) -> dict[str, int]:
    """Patch the LLM + embeddings the summarizer calls. Returns call counters."""
    counters = {"summaries": 0, "embeds": 0}

    class _FakeLLM:
        def __init__(self, *a, **k) -> None: ...

        async def complete_structured(self, prompt, schema, *, system=None):
            counters["summaries"] += 1
            # Echo a deterministic summary derived from the prompt's Name line.
            name = next(
                (ln.split("Name: ", 1)[1] for ln in prompt.splitlines() if ln.startswith("Name: ")),
                "?",
            )
            return _Summary(summary=f"summary of {name}")

    def _fake_fast(ledger=None):
        return _FakeLLM()

    async def _fake_embed(texts, *, ledger=None):
        counters["embeds"] += len(texts)
        return [[0.1] * EMBEDDING_DIM for _ in texts]

    monkeypatch.setattr(summ_mod, "fast", _fake_fast)
    monkeypatch.setattr(summ_mod, "embed_texts", _fake_embed)
    return counters


async def test_summarizer_writes_summaries_and_embeddings(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = await _seed_graph(db_session)
    counters = _install_fakes(monkeypatch)

    ledger = summ_mod.UsageLedger()
    stats = await Summarizer(db_session, repo.id, ledger=ledger).run()

    # Every node got a summary call.
    node_count = len((await db_session.scalars(select(Node).where(Node.repo_id == repo.id))).all())
    assert stats.summarized == node_count
    assert counters["summaries"] == node_count

    # Summaries persisted to the nodes.
    svc = await db_session.scalar(
        select(Node).where(Node.repo_id == repo.id, Node.fqname == "app.service.Service")
    )
    assert svc is not None and svc.summary == "summary of app.service.Service"
    assert svc.summary_embedding is not None
    assert len(svc.summary_embedding) == EMBEDDING_DIM

    # Chunks embedded.
    chunks = (await db_session.scalars(select(Chunk).where(Chunk.repo_id == repo.id))).all()
    assert all(c.embedding is not None for c in chunks)
    assert stats.embedded_chunks == len(chunks)


async def test_bottom_up_order_feeds_child_summaries(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A container (class/file) must be summarized AFTER its children, with their
    summaries available — verify the file prompt sees child summaries."""
    repo = await _seed_graph(db_session)

    seen_prompts: list[str] = []

    class _RecordingLLM:
        def __init__(self, *a, **k) -> None: ...

        async def complete_structured(self, prompt, schema, *, system=None):
            seen_prompts.append(prompt)
            name = next(
                (ln.split("Name: ", 1)[1] for ln in prompt.splitlines() if ln.startswith("Name: ")),
                "?",
            )
            return _Summary(summary=f"sum:{name}")

    async def _fake_embed(texts, *, ledger=None):
        return [[0.0] * EMBEDDING_DIM for _ in texts]

    monkeypatch.setattr(summ_mod, "fast", lambda ledger=None: _RecordingLLM())
    monkeypatch.setattr(summ_mod, "embed_texts", _fake_embed)

    await Summarizer(db_session, repo.id, ledger=summ_mod.UsageLedger()).run()

    # The file-level prompt for app.service should include its children's summaries.
    file_prompt = next(
        p for p in seen_prompts if "Name: app.service\n" in p or p.endswith("app.service")
    )
    assert "Contains (child summaries)" in file_prompt
