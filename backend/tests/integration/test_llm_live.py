"""Live LLM round-trip tests (network + real API key).

Skipped automatically unless a provider key is configured, so the suite stays
green on machines/CI without keys. When a key IS present, these prove the full
provider-agnostic path: a real call, structured output validated against a
Pydantic schema, embeddings, and cost accounting populated from real usage.
"""

from __future__ import annotations

import os

import pytest
from pydantic import BaseModel, Field

from app.agents import llm

pytestmark = pytest.mark.network

_HAS_KEY = bool(
    os.environ.get("GOOGLE_API_KEY")
    or os.environ.get("OPENAI_API_KEY")
    or os.environ.get("ANTHROPIC_API_KEY")
)
_skip = pytest.mark.skipif(not _HAS_KEY, reason="no provider API key configured")


class Answer(BaseModel):
    capital: str = Field(description="The capital city")
    country: str = Field(description="The country")


@_skip
async def test_complete_text_and_cost() -> None:
    ledger = llm.UsageLedger()
    text = await llm.fast(ledger).complete("Reply with exactly the word: pong")
    assert "pong" in text.lower()
    # Cost accounting populated from real usage_metadata.
    assert ledger.total_input_tokens > 0
    assert len(ledger.calls) == 1


@_skip
async def test_structured_output() -> None:
    ledger = llm.UsageLedger()
    result = await llm.fast(ledger).complete_structured("What is the capital of Japan?", Answer)
    assert isinstance(result, Answer)
    assert result.capital.lower() == "tokyo"
    assert ledger.total_input_tokens > 0


@_skip
async def test_embeddings() -> None:
    ledger = llm.UsageLedger()
    vectors = await llm.embed_texts(["hello world", "goodbye world"], ledger=ledger)
    assert len(vectors) == 2
    from app.config import EMBEDDING_DIM

    assert len(vectors[0]) == EMBEDDING_DIM
