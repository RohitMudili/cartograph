"""Tests for the eval harness's deterministic scoring (no DB, no LLM)."""

from __future__ import annotations

from evals.runner import render_markdown, score_case
from evals.schema import EvalReport, GoldenCase, GoldenSet

from app.agents.llm import UsageLedger


def _case(**overrides) -> GoldenCase:
    base = {
        "id": "c1",
        "question": "What does f do?",
        "expected_paths": ["src/f.py"],
        "expected_keywords": ["adds", "one"],
    }
    base.update(overrides)
    return GoldenCase.model_validate(base)


def _score(case: GoldenCase, *, citations, answer="It adds one.", fully_verified=True):
    return score_case(
        case,
        route="local",
        question_type="specific_symbol",
        answerable=True,
        fully_verified=fully_verified,
        answer_text=answer,
        citations=citations,
        latency_s=1.0,
        ledger=UsageLedger(),
    )


def test_perfect_case() -> None:
    r = _score(_case(), citations=[("src/f.py", True)])
    assert r.citation_precision == 1.0
    assert r.citation_recall == 1.0
    assert r.keyword_coverage == 1.0
    assert r.missing_keywords == []


def test_unverified_citations_never_count() -> None:
    # The right path but unverified — precision has no verified citations to
    # credit, and recall stays at zero: the expected file was never PROVEN.
    r = _score(_case(), citations=[("src/f.py", False)])
    assert r.citations_verified == 0
    assert r.citation_precision == 0.0
    assert r.citation_recall == 0.0


def test_precision_penalizes_off_target_citations() -> None:
    # Two verified citations, one in the expected file: precision 0.5, recall 1.0.
    r = _score(_case(), citations=[("src/f.py", True), ("src/other.py", True)])
    assert r.citation_precision == 0.5
    assert r.citation_recall == 1.0


def test_optional_paths_count_toward_precision_not_recall() -> None:
    case = _case(optional_paths=["README.md"])
    # Cites only the README: precision credits it, recall still demands src/f.py.
    r = _score(case, citations=[("README.md", True)])
    assert r.citation_precision == 1.0
    assert r.citation_recall == 0.0
    # Cites both: perfect on both axes.
    r2 = _score(case, citations=[("README.md", True), ("src/f.py", True)])
    assert r2.citation_precision == 1.0
    assert r2.citation_recall == 1.0


def test_recall_over_multiple_expected_paths() -> None:
    case = _case(expected_paths=["src/f.py", "src/g.py"])
    r = _score(case, citations=[("src/f.py", True)])
    assert r.citation_recall == 0.5


def test_keyword_coverage_case_insensitive_and_missing_listed() -> None:
    r = _score(_case(expected_keywords=["Adds", "banana"]), citations=[("src/f.py", True)])
    assert r.keyword_coverage == 0.5
    assert r.missing_keywords == ["banana"]


def test_path_normalization() -> None:
    # Citation paths tolerate a leading './' and case differences.
    r = _score(_case(), citations=[("./SRC/F.py", True)])
    assert r.citation_recall == 1.0


def test_no_expectations_scores_vacuously() -> None:
    case = _case(expected_paths=[], expected_keywords=[])
    r = _score(case, citations=[])
    assert r.citation_recall == 1.0  # nothing expected, nothing missed
    assert r.keyword_coverage == 1.0


def test_report_aggregates_and_renders() -> None:
    case = _case()
    good = _score(case, citations=[("src/f.py", True)])
    bad = _score(case, citations=[("src/other.py", True)], answer="unrelated")
    report = EvalReport(repo_url="https://github.com/t/r", results=[good, bad])
    assert report.citation_precision == 0.5
    assert report.citation_recall == 0.5
    md = render_markdown(report)
    assert "citation precision 50%" in md
    assert "| c1 |" in md
    assert "missed keywords" in md


def test_golden_set_parses() -> None:
    from pathlib import Path

    golden_path = Path(__file__).parents[2] / "evals" / "golden" / "pybktree.json"
    golden = GoldenSet.model_validate_json(golden_path.read_text(encoding="utf-8"))
    assert golden.repo_url.endswith("pybktree")
    assert len(golden.cases) >= 5
    ids = [c.id for c in golden.cases]
    assert len(ids) == len(set(ids)), "case ids must be unique"
