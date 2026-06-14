"""Unit tests for the provider-agnostic LLM layer.

These test the cost-accounting and model-string logic with no network/API key —
the parts most likely to silently break (wrong price, wrong provider split).
A real round-trip lives in tests/integration/test_llm_live.py (network).
"""

from __future__ import annotations

from app.agents.llm import CallCost, UsageLedger, _chat_price
from app.config import split_model


def test_split_model() -> None:
    assert split_model("google_genai:gemini-3.5-flash") == ("google_genai", "gemini-3.5-flash")
    assert split_model("openai:gpt-5-mini") == ("openai", "gpt-5-mini")
    assert split_model("no-prefix") == ("", "no-prefix")


def test_chat_price_known_model() -> None:
    # gemini-3.1-flash-lite: $0.10 in / $0.40 out per 1M
    in_tok, out_tok, usd = _chat_price(
        "google_genai:gemini-3.1-flash-lite",
        {"input_tokens": 1_000_000, "output_tokens": 1_000_000},
    )
    assert in_tok == 1_000_000
    assert out_tok == 1_000_000
    assert abs(usd - 0.50) < 1e-9  # 0.10 + 0.40


def test_chat_price_unknown_model_is_free_but_counted() -> None:
    in_tok, out_tok, usd = _chat_price(
        "openai:some-future-model",
        {"input_tokens": 100, "output_tokens": 50},
    )
    assert in_tok == 100
    assert out_tok == 50
    assert usd == 0.0  # unknown price → 0 cost, tokens still counted


def test_chat_price_handles_missing_usage() -> None:
    in_tok, out_tok, usd = _chat_price("google_genai:gemini-3.5-flash", {})
    assert (in_tok, out_tok, usd) == (0, 0, 0.0)


def test_usage_ledger_accumulates() -> None:
    ledger = UsageLedger()
    ledger.record(CallCost("google_genai:gemini-3.5-flash", 1000, 200, 0.0008))
    ledger.record(CallCost("google_genai:gemini-3.1-flash-lite", 500, 100, 0.0001))
    assert ledger.total_input_tokens == 1500
    assert ledger.total_output_tokens == 300
    assert abs(ledger.total_usd - 0.0009) < 1e-9
    summary = ledger.summary()
    assert summary["calls"] == 2
    assert summary["input_tokens"] == 1500
