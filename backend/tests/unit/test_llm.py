"""Unit tests for the provider-agnostic LLM layer.

Cost is computed by LangSmith and read back into our DB (PLAN.md §7.1) — we
maintain no price table — so these test the token-accounting and model-string
logic, and that cost is honestly None when no LangSmith cost has been attached.
A real round-trip lives in tests/integration/test_llm_live.py (network).
"""

from __future__ import annotations

from app.agents.llm import CallCost, UsageLedger, _tokens
from app.config import split_model


def test_split_model() -> None:
    assert split_model("google_genai:gemini-3.5-flash") == ("google_genai", "gemini-3.5-flash")
    assert split_model("openai:gpt-5-mini") == ("openai", "gpt-5-mini")
    assert split_model("no-prefix") == ("", "no-prefix")


def test_tokens_extraction() -> None:
    assert _tokens({"input_tokens": 120, "output_tokens": 40}) == (120, 40)
    assert _tokens({}) == (0, 0)
    assert _tokens({"input_tokens": None, "output_tokens": None}) == (0, 0)


def test_ledger_tracks_tokens_cost_none_without_langsmith() -> None:
    ledger = UsageLedger()
    ledger.record(CallCost("google_genai:gemini-3.5-flash", 1000, 200))
    ledger.record(CallCost("google_genai:gemini-3.1-flash-lite", 500, 100))
    assert ledger.total_input_tokens == 1500
    assert ledger.total_output_tokens == 300
    # No LangSmith cost attached → total is honestly None, not a fabricated 0.
    assert ledger.total_usd is None
    summary = ledger.summary()
    assert summary["calls"] == 2
    assert summary["input_tokens"] == 1500
    assert summary["usd"] is None


def test_ledger_totals_cost_when_present() -> None:
    ledger = UsageLedger()
    ledger.record(CallCost("m", 100, 50, usd=0.0008))
    ledger.record(CallCost("m", 100, 50, usd=0.0002))
    assert ledger.total_usd is not None
    assert abs(ledger.total_usd - 0.0010) < 1e-9
