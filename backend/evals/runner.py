"""Eval runner — asks each golden question through the real router and scores it.

Scoring is pure comparison against the golden expectations:

- **citation precision** — of the VERIFIED citations, how many land in an
  expected file. (Unverified citations never count; the verifier already
  stripped or flagged them.)
- **citation recall** — how many expected files are covered by at least one
  verified citation.
- **keyword coverage** — fraction of expected keywords present in the answer
  text (case-insensitive substring).
- plus the honesty rates the product promises: answerable, fully_verified.

Each case runs with its own UsageLedger so latency/token/cost columns are
per-question. A case that raises is recorded as an error row, never a crash —
one flaky question must not void a scoreboard.
"""

from __future__ import annotations

import time
import uuid

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.llm import UsageLedger
from app.query.router import answer_question
from evals.schema import CaseResult, EvalReport, GoldenCase, GoldenSet

log = structlog.get_logger(__name__)


def _norm_path(p: str) -> str:
    return p.strip().lstrip("./").lower()


def score_case(
    case: GoldenCase,
    *,
    route: str,
    question_type: str,
    answerable: bool,
    fully_verified: bool,
    answer_text: str,
    citations: list[tuple[str, bool]],
    latency_s: float,
    ledger: UsageLedger,
) -> CaseResult:
    """Score one answered case. `citations` is [(path, verified), ...]."""
    expected = {_norm_path(p) for p in case.expected_paths}
    acceptable = expected | {_norm_path(p) for p in case.optional_paths}
    verified_paths = [_norm_path(p) for p, ok in citations if ok]

    precision_hits = [p for p in verified_paths if p in acceptable]
    precision = len(precision_hits) / len(verified_paths) if verified_paths else 0.0
    recall_hits = {p for p in verified_paths if p in expected}
    recall = len(recall_hits) / len(expected) if expected else 1.0

    text_lower = answer_text.lower()
    missing = [k for k in case.expected_keywords if k.lower() not in text_lower]
    coverage = (
        (len(case.expected_keywords) - len(missing)) / len(case.expected_keywords)
        if case.expected_keywords
        else 1.0
    )

    return CaseResult(
        case_id=case.id,
        question=case.question,
        route=route,
        question_type=question_type,
        answerable=answerable,
        fully_verified=fully_verified,
        citations_total=len(citations),
        citations_verified=len(verified_paths),
        citation_precision=precision,
        citation_recall=recall,
        keyword_coverage=coverage,
        missing_keywords=missing,
        cited_paths=sorted({p for p, _ in citations}),
        latency_s=latency_s,
        input_tokens=ledger.total_input_tokens,
        output_tokens=ledger.total_output_tokens,
        cost_usd=ledger.total_usd,
        answer_text=answer_text,
    )


async def run_case(session: AsyncSession, repo_id: uuid.UUID, case: GoldenCase) -> CaseResult:
    ledger = UsageLedger()
    started = time.monotonic()
    try:
        ans = await answer_question(session, repo_id, case.question, ledger=ledger)
    except Exception as exc:  # noqa: BLE001 — one bad case must not void the run
        log.warning("eval.case_failed", case=case.id, error=str(exc))
        return CaseResult(
            case_id=case.id,
            question=case.question,
            route="-",
            question_type="-",
            answerable=False,
            fully_verified=False,
            citations_total=0,
            citations_verified=0,
            citation_precision=0.0,
            citation_recall=0.0,
            keyword_coverage=0.0,
            latency_s=time.monotonic() - started,
            error=f"{type(exc).__name__}: {exc}",
        )
    latency = time.monotonic() - started
    return score_case(
        case,
        route=ans.route,
        question_type=ans.question_type.value,
        answerable=ans.answerable,
        fully_verified=ans.fully_verified,
        answer_text=ans.text,
        citations=[(v.citation.path, v.verified) for v in ans.citations],
        latency_s=latency,
        ledger=ledger,
    )


async def run_eval(session: AsyncSession, repo_id: uuid.UUID, golden: GoldenSet) -> EvalReport:
    """Run every golden case sequentially (the rate limiter paces the LLM anyway)."""
    results: list[CaseResult] = []
    for case in golden.cases:
        log.info("eval.case", case=case.id)
        results.append(await run_case(session, repo_id, case))
    return EvalReport(repo_url=golden.repo_url, results=results)


def render_markdown(report: EvalReport) -> str:
    """The scoreboard: aggregate line + a per-case table + failures detail."""

    def pct(x: float) -> str:
        return f"{x * 100:.0f}%"

    lines = [
        f"# Cartograph eval — {report.repo_url}",
        "",
        f"**{report.cases} cases** · answerable {pct(report.answerable_rate)} · "
        f"fully verified {pct(report.fully_verified_rate)} · "
        f"citation precision {pct(report.citation_precision)} · "
        f"citation recall {pct(report.citation_recall)} · "
        f"keyword coverage {pct(report.keyword_coverage)}"
        + (
            f" · total cost ${report.total_cost_usd:.4f}"
            if report.total_cost_usd is not None
            else ""
        ),
        "",
        "| case | route | type | ans | verified | precision | recall | keywords | latency | tokens in/out |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in report.results:
        if r.error:
            lines.append(
                f"| {r.case_id} | — | — | ERROR | — | — | — | — | {r.latency_s:.1f}s | — |"
            )
            continue
        lines.append(
            f"| {r.case_id} | {r.route} | {r.question_type} "
            f"| {'✓' if r.answerable else '✗'} "
            f"| {r.citations_verified}/{r.citations_total} "
            f"| {pct(r.citation_precision)} | {pct(r.citation_recall)} "
            f"| {pct(r.keyword_coverage)} | {r.latency_s:.1f}s "
            f"| {r.input_tokens}/{r.output_tokens} |"
        )
    problems = [
        r for r in report.results if r.error or r.missing_keywords or r.citation_precision < 1.0
    ]
    if problems:
        lines += ["", "## Attention", ""]
        for r in problems:
            if r.error:
                lines.append(f"- **{r.case_id}**: ERROR — {r.error}")
                continue
            if r.missing_keywords:
                lines.append(f"- **{r.case_id}**: answer missed keywords: {r.missing_keywords}")
            if r.citation_precision < 1.0:
                lines.append(
                    f"- **{r.case_id}**: off-target citations — cited paths: {r.cited_paths} "
                    "(consider optional_paths if these are legitimate)"
                )
    lines += ["", "## Answers", ""]
    for r in report.results:
        if r.error:
            continue
        lines += [f"### {r.case_id}", "", f"> {r.question}", "", r.answer_text, ""]
    return "\n".join(lines) + "\n"
