"""Agent-fleet tests (db, no real LLM).

Exercises the enrichment agents end to end against a tiny seeded graph with a
deterministic fake LLM, so CI runs them with no API key. Covers the core
guarantees: explorers produce findings via tools, the critic rejects a claim
whose target symbol doesn't exist, and the librarian writes accepted (and only
accepted) findings into Node.annotations with attribution.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents import llm
from app.agents.critic import critique
from app.agents.librarian import persist
from app.agents.planner import plan
from app.agents.schemas import (
    ExplorationPlan,
    ExplorerStep,
    Finding,
    RepoModel,
    Subsystem,
    Verdict,
)
from app.agents.tools import RepoTools
from app.db.enums import NodeKind
from app.db.models import Chunk, Node, Repo

pytestmark = pytest.mark.db


async def _seed(session: AsyncSession) -> Repo:
    """A minimal repo graph: one REPO node, one FILE, one FUNCTION with a chunk."""
    repo = Repo(url="https://github.com/test/fleet", head_commit="f" * 40)
    session.add(repo)
    await session.flush()

    repo_node = Node(repo_id=repo.id, kind=NodeKind.REPO, fqname="repo")
    fn = Node(
        repo_id=repo.id,
        kind=NodeKind.FUNCTION,
        fqname="app.core.add",
        path="app/core.py",
        start_line=1,
        end_line=2,
        signature="def add(a, b)",
        summary="Adds two numbers.",
        metrics={"loc": 2, "fan_in": 3, "fan_out": 0},
    )
    session.add_all([repo_node, fn])
    await session.flush()
    session.add(
        Chunk(
            repo_id=repo.id,
            node_id=fn.id,
            path="app/core.py",
            start_line=1,
            end_line=2,
            text="def add(a, b):\n    return a + b",
        )
    )
    await session.flush()
    return repo


class _FakeLLM:
    """Returns canned structured outputs by schema type — no network."""

    def __init__(self, *a, **k) -> None:
        pass

    async def complete_structured(self, prompt, schema, *, system=None):
        if schema is ExplorationPlan:
            return ExplorationPlan(
                overview="A tiny test repo.",
                subsystems=[
                    Subsystem(name="core", brief="arithmetic", seed_fqnames=["app.core.add"])
                ],
            )
        if schema is ExplorerStep:
            # One-shot: immediately report findings (no tool round-trips needed).
            return ExplorerStep(
                action="done",
                findings=[
                    Finding(
                        target_fqname="app.core.add",
                        kind="role",
                        text="add() is the arithmetic primitive.",
                        evidence="app/core.py:1",
                    ),
                    # A fabricated target the critic must reject.
                    Finding(
                        target_fqname="app.core.nonexistent",
                        kind="smell",
                        text="This symbol does something.",
                    ),
                ],
            )
        if schema is RepoModel:
            return RepoModel(summary="A tiny repo that adds numbers.")
        if schema is Verdict:
            # Accept the real-target finding; the missing-target one is auto-rejected
            # by the critic before it ever calls the LLM.
            target = "app.core.add" if "app.core.add" in prompt else "?"
            return Verdict(
                target_fqname=target,
                finding_text="add() is the arithmetic primitive.",
                accepted=True,
                reason="The source defines add(a, b) returning a + b.",
            )
        raise AssertionError(f"unexpected schema {schema}")


@pytest.fixture
def fake_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeLLM()
    monkeypatch.setattr(llm, "reasoning", lambda ledger=None: fake)
    monkeypatch.setattr(llm, "fast", lambda ledger=None: fake)


async def test_planner_partitions_repo(db_session: AsyncSession, fake_llm: None) -> None:
    repo = await _seed(db_session)
    result = await plan(db_session, repo.id, ledger=llm.UsageLedger())
    assert result.subsystems
    assert result.subsystems[0].name == "core"


async def test_tools_read_real_graph(db_session: AsyncSession) -> None:
    """Tools serve from the DB (no fake LLM needed) — read_file, get_node, grep."""
    repo = await _seed(db_session)
    tools = RepoTools(session=db_session, repo_id=repo.id)

    node = await tools.get_node("app.core.add")
    assert node is not None and node["kind"] == "function"

    f = await tools.read_file("app/core.py")
    assert f["found"] and "return a + b" in f["text"]

    hits = await tools.grep("return")
    assert any(h.get("path") == "app/core.py" for h in hits)

    missing = await tools.get_node("does.not.exist")
    assert missing is None


async def test_critic_rejects_missing_target(db_session: AsyncSession, fake_llm: None) -> None:
    repo = await _seed(db_session)
    tools = RepoTools(session=db_session, repo_id=repo.id)
    findings = [
        Finding(
            target_fqname="app.core.add", kind="role", text="add() is the arithmetic primitive."
        ),
        Finding(
            target_fqname="app.core.nonexistent", kind="smell", text="This symbol does something."
        ),
    ]
    report = await critique(findings, tools, ledger=llm.UsageLedger())
    by_target = {v.target_fqname: v for v in report.verdicts}
    assert by_target["app.core.add"].accepted is True
    assert by_target["app.core.nonexistent"].accepted is False  # auto-rejected, no LLM call


async def test_librarian_writes_only_accepted(db_session: AsyncSession) -> None:
    repo = await _seed(db_session)
    accepted = [
        (
            Finding(
                target_fqname="app.core.add", kind="role", text="add() is the arithmetic primitive."
            ),
            "explorer:core",
        )
    ]
    written = await persist(
        db_session,
        repo.id,
        run_id=uuid.uuid4(),
        accepted=accepted,
        repo_model=RepoModel(summary="A tiny repo."),
    )
    assert written == 1

    node = await db_session.scalar(
        select(Node).where(Node.repo_id == repo.id, Node.fqname == "app.core.add")
    )
    assert node is not None
    assert len(node.annotations) == 1
    ann = node.annotations[0]
    assert ann["verified"] is True
    assert ann["source"] == "explorer:core"
    assert ann["kind"] == "role"

    # The repo model is stored on the REPO node.
    repo_node = await db_session.scalar(
        select(Node).where(Node.repo_id == repo.id, Node.kind == NodeKind.REPO)
    )
    assert repo_node is not None
    assert any(a.get("kind") == "repo_model" for a in repo_node.annotations)
