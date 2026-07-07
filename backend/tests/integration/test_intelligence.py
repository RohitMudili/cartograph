"""Query-intelligence tests (db, no real LLM): communities, enrichment, router.

Covers the GraphRAG layer end to end on a seeded graph with a deterministic
fake LLM: Leiden clustering persists communities; verified annotations and the
RepoModel flow into answer context; the router picks global for architecture
questions and escalates (with write-back) when the first answer is unanswerable.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents import llm
from app.agents.schemas import ExplorerStep, Finding, Verdict
from app.config import EMBEDDING_DIM
from app.db.enums import EdgeKind, NodeKind, RunKind
from app.db.models import Chunk, Community, Edge, IndexRun, Node, Repo
from app.indexer.communities import build_communities
from app.query import answerer as ans_mod
from app.query import retrieval as retr_mod
from app.query import router as router_mod
from app.query.answerer import QuestionType, _AnswerOut, _CitationOut, _QuestionTypeOut
from app.query.enrichment import (
    format_enrichment_block,
    load_annotations_for_nodes,
    load_repo_model,
)

pytestmark = pytest.mark.db


async def _seed(session: AsyncSession) -> tuple[Repo, list[Node]]:
    """Two small 'subsystems' wired by calls/imports, with chunks + annotations."""
    repo = Repo(url="https://github.com/test/intel", head_commit="e" * 40)
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
                    "summary": "A tiny two-part service.",
                    "subsystems": [{"name": "api", "description": "the HTTP layer"}],
                    "flows": [{"name": "request", "steps": ["api.handle", "core.add"]}],
                    "walkthrough": [
                        {
                            "title": "Start at the API",
                            "detail": "Read handle().",
                            "fqname": "api.handle",
                        }
                    ],
                },
            }
        ],
    )
    session.add(repo_node)

    def make_fn(fq: str, path: str, annotated: bool = False) -> Node:
        return Node(
            repo_id=repo.id,
            kind=NodeKind.FUNCTION,
            fqname=fq,
            path=path,
            start_line=1,
            end_line=2,
            summary=f"{fq} does its job.",
            annotations=(
                [
                    {
                        "kind": "role",
                        "text": f"{fq} is load-bearing.",
                        "verified": True,
                        "source": "explorer:t",
                    }
                ]
                if annotated
                else []
            ),
        )

    a1, a2 = make_fn("api.handle", "api.py", annotated=True), make_fn("api.parse", "api.py")
    c1, c2 = make_fn("core.add", "core.py"), make_fn("core.mul", "core.py")
    session.add_all([a1, a2, c1, c2])
    await session.flush()

    session.add_all(
        [
            Chunk(
                repo_id=repo.id,
                node_id=a1.id,
                path="api.py",
                start_line=1,
                end_line=2,
                text="def handle(req):\n    return parse(req)",
            ),
            Chunk(
                repo_id=repo.id,
                node_id=c1.id,
                path="core.py",
                start_line=1,
                end_line=2,
                text="def add(a, b):\n    return a + b",
            ),
            # Dense-ish cluster edges: api pair and core pair, one weak bridge.
            Edge(
                repo_id=repo.id,
                src_node_id=a1.id,
                dst_node_id=a2.id,
                kind=EdgeKind.CALLS,
                confidence=1.0,
            ),
            Edge(
                repo_id=repo.id,
                src_node_id=a2.id,
                dst_node_id=a1.id,
                kind=EdgeKind.IMPORTS,
                confidence=1.0,
            ),
            Edge(
                repo_id=repo.id,
                src_node_id=c1.id,
                dst_node_id=c2.id,
                kind=EdgeKind.CALLS,
                confidence=1.0,
            ),
            Edge(
                repo_id=repo.id,
                src_node_id=c2.id,
                dst_node_id=c1.id,
                kind=EdgeKind.IMPORTS,
                confidence=1.0,
            ),
        ]
    )
    await session.flush()
    return repo, [a1, a2, c1, c2]


async def test_communities_cluster_and_persist(db_session: AsyncSession, monkeypatch) -> None:
    """Leiden splits the two wired pairs into two communities; no LLM needed."""
    monkeypatch.setattr(
        "app.indexer.communities.get_settings", lambda: type("S", (), {"llm_available": False})()
    )
    repo, _ = await _seed(db_session)
    stats = await build_communities(db_session, repo.id)
    assert stats.communities == 2
    coms = (await db_session.scalars(select(Community).where(Community.repo_id == repo.id))).all()
    assert {c.size for c in coms} == {2}
    assert all(c.summary is None for c in coms)  # LLM gated off


async def test_enrichment_loaders(db_session: AsyncSession) -> None:
    repo, nodes = await _seed(db_session)
    model = await load_repo_model(db_session, repo.id)
    assert model is not None and model["summary"] == "A tiny two-part service."
    ann = await load_annotations_for_nodes(db_session, repo.id, [n.id for n in nodes])
    assert ann == ["- api.handle: api.handle is load-bearing."]
    block = format_enrichment_block(model, ann, ["- [c0] api (2 symbols): the HTTP layer"])
    assert "Repository model" in block and "Verified agent findings" in block


class _FakeLLM:
    """Deterministic outputs; records prompts so tests can assert on context."""

    def __init__(self) -> None:
        self.prompts: list[str] = []
        self.qtype = QuestionType.ARCHITECTURE
        self.answerable = True

    async def complete_structured(self, prompt, schema, *, system=None):
        self.prompts.append(prompt)
        if schema is _QuestionTypeOut:
            return _QuestionTypeOut(type=self.qtype)
        if schema is _AnswerOut:
            return _AnswerOut(
                answer="It adds numbers.",
                citations=[
                    _CitationOut(
                        path="core.py", start_line=1, end_line=2, quoted_snippet="return a + b"
                    )
                ],
                answerable=self.answerable,
            )
        raise AssertionError(f"unexpected schema {schema}")


@pytest.fixture
def fake_llm(monkeypatch: pytest.MonkeyPatch) -> _FakeLLM:
    fake = _FakeLLM()
    monkeypatch.setattr(ans_mod, "fast", lambda ledger=None: fake)
    monkeypatch.setattr(ans_mod, "reasoning", lambda ledger=None: fake)

    # Neutralize the dense-retrieval embedding call (no network in tests).
    async def _fake_embed(text, *, ledger=None):
        return [0.0] * EMBEDDING_DIM

    monkeypatch.setattr(retr_mod, "embed_query", _fake_embed)

    # Escalation off by default so no test path reaches the real fleet LLM;
    # the escalation test opts back in with its own get_settings patch.
    monkeypatch.setattr(
        router_mod, "get_settings", lambda: type("S", (), {"llm_available": False})()
    )
    return fake


async def test_router_global_route_uses_repo_model(
    db_session: AsyncSession, fake_llm: _FakeLLM, monkeypatch
) -> None:
    repo, _ = await _seed(db_session)
    fake_llm.qtype = QuestionType.ARCHITECTURE
    ans = await router_mod.answer_question(db_session, repo.id, "How does it all fit together?")
    assert ans.route == "global"
    # The synthesis prompt carried the repo-model block.
    assert any("Repository model" in p for p in fake_llm.prompts)
    assert ans.fully_verified  # the fake citation matches the seeded chunk


async def test_router_local_route_merges_annotations(
    db_session: AsyncSession, fake_llm: _FakeLLM
) -> None:
    repo, _ = await _seed(db_session)
    fake_llm.qtype = QuestionType.SPECIFIC_SYMBOL
    # plainto_tsquery ANDs lexemes, so every word must appear in the seeded
    # chunk ("def handle(req): return parse(req)") for BM25 to surface it.
    ans = await router_mod.answer_question(db_session, repo.id, "handle parse")
    assert ans.route == "local"
    # Retrieval surfaced the annotated node, so its verified finding rides along.
    joined = "\n".join(fake_llm.prompts)
    assert "load-bearing" in joined
    assert ans.answerable


async def test_router_escalates_and_writes_back(
    db_session: AsyncSession, fake_llm: _FakeLLM, monkeypatch
) -> None:
    """Unanswerable → one scoped explorer runs, verified finding lands in the graph."""
    repo, _ = await _seed(db_session)
    fake_llm.qtype = QuestionType.GENERAL
    fake_llm.answerable = False  # every synthesis says "can't answer"

    monkeypatch.setattr(
        router_mod, "get_settings", lambda: type("S", (), {"llm_available": True})()
    )

    # The escalation explorer + critic run on the agents' LLM handles.
    class _FleetFake:
        async def complete_structured(self, prompt, schema, *, system=None):
            if schema is ExplorerStep:
                return ExplorerStep(
                    action="done",
                    findings=[
                        Finding(target_fqname="core.add", kind="role", text="core.add sums inputs.")
                    ],
                )
            if schema is Verdict:
                return Verdict(
                    target_fqname="core.add",
                    finding_text="core.add sums inputs.",
                    accepted=True,
                    reason="Matches the source.",
                )
            raise AssertionError(f"unexpected fleet schema {schema}")

    fleet_fake = _FleetFake()
    monkeypatch.setattr(llm, "fast", lambda ledger=None: fleet_fake)
    monkeypatch.setattr(llm, "reasoning", lambda ledger=None: fleet_fake)

    ans = await router_mod.answer_question(db_session, repo.id, "Something obscure?")
    assert ans.route == "escalate"

    # Write-back happened: the finding is on core.add, attributed to escalation.
    node = await db_session.scalar(
        select(Node).where(Node.repo_id == repo.id, Node.fqname == "core.add")
    )
    assert node is not None
    assert any(a.get("source") == "explorer:escalation" for a in node.annotations)
    run = await db_session.scalar(
        select(IndexRun).where(IndexRun.repo_id == repo.id, IndexRun.kind == RunKind.ESCALATION)
    )
    assert run is not None
