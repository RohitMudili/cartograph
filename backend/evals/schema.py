"""Golden-dataset and result shapes for the eval harness.

A golden case states what a good answer must do, in checkable terms:
- `expected_paths` — files a grounded answer should cite (recall is measured
  against these; a verified citation to any of them counts as a hit).
- `expected_keywords` — facts the answer text must mention (case-insensitive
  substring match). Keep them minimal and unambiguous — they grade content,
  not style.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pydantic import BaseModel, Field


class GoldenCase(BaseModel):
    """One golden question with its checkable expectations."""

    id: str = Field(description="Stable case id, e.g. 'hamming-distance'.")
    question: str
    expected_paths: list[str] = Field(
        default_factory=list,
        description="Repo-relative paths a grounded answer should cite.",
    )
    optional_paths: list[str] = Field(
        default_factory=list,
        description=(
            "Paths that are legitimate to cite (they count toward precision) "
            "but are not required (they don't count toward recall) — e.g. "
            "README/setup/tests on an onboarding question."
        ),
    )
    expected_keywords: list[str] = Field(
        default_factory=list,
        description="Substrings the answer text must contain (case-insensitive).",
    )
    notes: str = ""


class GoldenSet(BaseModel):
    """A golden dataset: the repo it grades and its cases."""

    repo_url: str
    cases: list[GoldenCase]


@dataclass(slots=True)
class CaseResult:
    """Scores for one golden case."""

    case_id: str
    question: str
    route: str
    question_type: str
    answerable: bool
    fully_verified: bool
    citations_total: int
    citations_verified: int
    # Verified citations that land in an expected path / all verified citations.
    citation_precision: float
    # Expected paths covered by at least one verified citation / expected paths.
    citation_recall: float
    keyword_coverage: float
    missing_keywords: list[str] = field(default_factory=list)
    cited_paths: list[str] = field(default_factory=list)
    latency_s: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float | None = None
    answer_text: str = ""
    error: str | None = None


@dataclass(slots=True)
class EvalReport:
    """Aggregate scoreboard over all cases."""

    repo_url: str
    results: list[CaseResult]

    @property
    def cases(self) -> int:
        return len(self.results)

    @property
    def scored(self) -> list[CaseResult]:
        return [r for r in self.results if r.error is None]

    def _mean(self, values: list[float]) -> float:
        return sum(values) / len(values) if values else 0.0

    @property
    def answerable_rate(self) -> float:
        return self._mean([1.0 if r.answerable else 0.0 for r in self.scored])

    @property
    def fully_verified_rate(self) -> float:
        return self._mean([1.0 if r.fully_verified else 0.0 for r in self.scored])

    @property
    def citation_precision(self) -> float:
        return self._mean([r.citation_precision for r in self.scored])

    @property
    def citation_recall(self) -> float:
        return self._mean([r.citation_recall for r in self.scored])

    @property
    def keyword_coverage(self) -> float:
        return self._mean([r.keyword_coverage for r in self.scored])

    @property
    def total_cost_usd(self) -> float | None:
        priced = [r.cost_usd for r in self.scored if r.cost_usd is not None]
        return sum(priced) if priced else None
