"""Provider-agnostic LLM access — the single entry point for every model call.

Cartograph is provider-agnostic: agents, the summarizer, the router, and the
answerer all call through this module, never a provider SDK directly. Swapping a
tier's provider/model is a one-line .env change (PLAN.md §4.2). Built on
LangChain's `init_chat_model`, so any supported provider
(google_genai / openai / anthropic / …) works from a "provider:model" string.

Responsibilities centralized here:
- **Tiered chat models** — `reasoning` (smart) and `fast` (cheap, high-volume),
  cached per process.
- **Structured output** — `complete_structured()` returns a validated Pydantic
  model via LangChain's `.with_structured_output()` (uniform across providers).
- **Embeddings** — `embed_texts()` against the configured embedding model.
- **Cost + token accounting** — every call records (model, in/out tokens, USD)
  into a `UsageLedger` so index-run and per-question costs are real, not guessed.
- **Resilience** — bounded retries with exponential backoff on transient errors.
"""

from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass, field
from functools import lru_cache
from typing import TypeVar

import structlog
from langchain.chat_models import init_chat_model
from langchain_core.embeddings import Embeddings
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from pydantic import BaseModel
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_random_exponential,
)

from app.config import (
    EMBEDDING_DIM,
    Settings,
    get_settings,
    split_model,
)

log = structlog.get_logger(__name__)


class _RateLimiter:
    """Async token-bucket limiter shared across all LLM calls.

    Paces requests to `rpm` requests/minute regardless of how many coroutines
    fan out concurrently, so we never exceed the provider tier's rate limit and
    trip 429s. Refills continuously; `acquire()` waits until a token is free.
    """

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._tokens = 0.0
        self._rpm = 0
        self._last = 0.0

    async def acquire(self, rpm: int) -> None:
        async with self._lock:
            now = time.monotonic()
            if rpm != self._rpm:
                # (Re)configure; start with a full bucket of 1 to allow an
                # immediate first call.
                self._rpm = rpm
                self._tokens = 1.0
                self._last = now
            per_sec = rpm / 60.0
            # Refill based on elapsed time, capped at the burst size (rpm).
            self._tokens = min(float(rpm), self._tokens + (now - self._last) * per_sec)
            self._last = now
            if self._tokens < 1.0:
                wait = (1.0 - self._tokens) / per_sec
                await asyncio.sleep(wait)
                self._tokens = 0.0
                self._last = time.monotonic()
            else:
                self._tokens -= 1.0


_rate_limiter = _RateLimiter()

T = TypeVar("T", bound=BaseModel)

# Map our provider prefix → the env var that provider's LangChain package reads.
_PROVIDER_ENV = {
    "google_genai": "GOOGLE_API_KEY",
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
}


@dataclass(slots=True)
class CallCost:
    """One model call's accounting.

    Token counts come from the provider's usage_metadata (always available).
    `usd` is the dollar cost — left None and filled later from LangSmith's
    computed run cost (PLAN.md §7.1). With LangSmith disabled it stays None
    (cost is honestly unknown, never fabricated from a price table we don't keep).
    """

    model: str
    input_tokens: int
    output_tokens: int
    usd: float | None = None


@dataclass(slots=True)
class UsageLedger:
    """Accumulates token counts (and, post-LangSmith, cost) across a run/question."""

    calls: list[CallCost] = field(default_factory=list)

    def record(self, cost: CallCost) -> None:
        self.calls.append(cost)

    @property
    def total_usd(self) -> float | None:
        """Total dollar cost, or None if no call has a cost yet (LangSmith off)."""
        priced = [c.usd for c in self.calls if c.usd is not None]
        return sum(priced) if priced else None

    @property
    def total_input_tokens(self) -> int:
        return sum(c.input_tokens for c in self.calls)

    @property
    def total_output_tokens(self) -> int:
        return sum(c.output_tokens for c in self.calls)

    def summary(self) -> dict:
        total = self.total_usd
        return {
            "calls": len(self.calls),
            "input_tokens": self.total_input_tokens,
            "output_tokens": self.total_output_tokens,
            "usd": round(total, 6) if total is not None else None,
        }


def _tokens(usage: dict) -> tuple[int, int]:
    """(input_tokens, output_tokens) from a LangChain usage_metadata dict."""
    return (
        int(usage.get("input_tokens", 0) or 0),
        int(usage.get("output_tokens", 0) or 0),
    )


def _ensure_provider_env(model: str, settings: Settings) -> None:
    """Export the provider's API key to the environment for its SDK to read.

    LangChain provider packages read GOOGLE_API_KEY / OPENAI_API_KEY /
    ANTHROPIC_API_KEY. We hold them in Settings (loaded from .env) and surface
    them here without overwriting an already-set environment value.
    """
    provider, _ = split_model(model)
    env_var = _PROVIDER_ENV.get(provider)
    if env_var is None:
        return
    key = {
        "GOOGLE_API_KEY": settings.google_api_key,
        "OPENAI_API_KEY": settings.openai_api_key,
        "ANTHROPIC_API_KEY": settings.anthropic_api_key,
    }.get(env_var, "")
    if key and not os.environ.get(env_var):
        os.environ[env_var] = key


@lru_cache(maxsize=1)
def _configure_langsmith() -> bool:
    """Enable LangSmith tracing if configured. Returns whether it's active.

    Cached so the env is set once. When active, LangChain auto-traces every model
    call to LangSmith, which computes cost — we read run.total_cost back into our
    DB (PLAN.md §7.1). When inactive, no tracing happens and cost stays unknown.
    """
    settings = get_settings()
    if not settings.langsmith_enabled:
        return False
    os.environ.setdefault("LANGSMITH_TRACING", "true")
    os.environ.setdefault("LANGSMITH_API_KEY", settings.langsmith_api_key)
    os.environ.setdefault("LANGSMITH_PROJECT", settings.langsmith_project)
    log.info("llm.langsmith.enabled", project=settings.langsmith_project)
    return True


@lru_cache(maxsize=8)
def _chat_model(model: str) -> BaseChatModel:
    """Instantiate (and cache) a chat model from a 'provider:model' string."""
    settings = get_settings()
    _configure_langsmith()
    _ensure_provider_env(model, settings)
    # init_chat_model accepts "provider:model"; max_retries=0 because we own retry.
    return init_chat_model(model, max_retries=0)


@lru_cache(maxsize=4)
def _embeddings(model: str) -> Embeddings:
    """Instantiate (and cache) an embeddings client from a 'provider:model' string.

    The output dimensionality is pinned to EMBEDDING_DIM so vectors always fit the
    pgvector column. Both Gemini (MRL truncation) and OpenAI text-embedding-3
    support a configurable output size; we request it explicitly rather than
    relying on the model's larger default.
    """
    settings = get_settings()
    _ensure_provider_env(model, settings)
    provider, bare = split_model(model)
    if provider == "google_genai":
        from langchain_google_genai import GoogleGenerativeAIEmbeddings

        return GoogleGenerativeAIEmbeddings(model=bare, output_dimensionality=EMBEDDING_DIM)
    if provider == "openai":
        from langchain_openai import OpenAIEmbeddings

        return OpenAIEmbeddings(model=bare, dimensions=EMBEDDING_DIM)
    raise ValueError(
        f"No embedding adapter for provider '{provider}'. "
        "Supported: google_genai, openai. (Anthropic has no first-party embeddings.)"
    )


# Transient errors worth retrying. We keep this broad-but-bounded: any exception
# except validation/value errors gets backoff attempts.
_RETRYABLE = (Exception,)

# Provider overload / rate-limit signals. Gemini in particular returns 503
# UNAVAILABLE ("model experiencing high demand") and 429 RESOURCE_EXHAUSTED during
# capacity spikes; these are temporary and worth waiting out longer than a generic
# error. We detect them by substring (the SDK surfaces them in the message).
_TRANSIENT_MARKERS = (
    "503",
    "UNAVAILABLE",
    "429",
    "RESOURCE_EXHAUSTED",
    "high demand",
    "overloaded",
    "try again later",
)


def _is_transient(exc: BaseException) -> bool:
    return any(m.lower() in str(exc).lower() for m in _TRANSIENT_MARKERS)


def _log_retry(state) -> None:  # type: ignore[no-untyped-def]
    exc = state.outcome.exception() if state.outcome else None
    if exc is not None:
        log.warning(
            "llm.retry",
            attempt=state.attempt_number,
            transient=_is_transient(exc),
            error=str(exc)[:160],
        )


# One shared retry policy for all model calls. ~10 attempts with exponential
# backoff + jitter ≈ up to several minutes of waiting, which rides out the typical
# Gemini overload/quota spike instead of failing the whole run on the first 503.
_RETRY = retry(
    retry=retry_if_exception_type(_RETRYABLE),
    stop=stop_after_attempt(10),
    wait=wait_random_exponential(multiplier=2, min=2, max=90),
    before_sleep=_log_retry,
    reraise=True,
)


class LLM:
    """A tier-aware handle: pick `reasoning` or `fast`, call, get cost-tracked output."""

    def __init__(self, model: str, *, ledger: UsageLedger | None = None) -> None:
        self.model = model
        self.ledger = ledger

    def _account(self, message: AIMessage) -> None:
        usage = getattr(message, "usage_metadata", None) or {}
        in_tok, out_tok = _tokens(dict(usage))
        if self.ledger is not None:
            # usd left None — filled later from LangSmith's run.total_cost.
            self.ledger.record(CallCost(self.model, in_tok, out_tok))

    @_RETRY
    async def complete(self, prompt: str, *, system: str | None = None) -> str:
        """Plain text completion. Returns the response text."""
        await _rate_limiter.acquire(get_settings().llm_rpm)
        messages: list = []
        if system:
            messages.append(("system", system))
        messages.append(("human", prompt))
        result = await _chat_model(self.model).ainvoke(messages)
        assert isinstance(result, AIMessage)
        self._account(result)
        return result.text() if callable(getattr(result, "text", None)) else str(result.content)

    @_RETRY
    async def complete_structured(
        self, prompt: str, schema: type[T], *, system: str | None = None
    ) -> T:
        """Structured completion validated against a Pydantic schema.

        Uses LangChain's provider-uniform `.with_structured_output`. Token usage
        is accounted via a usage callback (the structured runnable returns the
        parsed object, not the raw AIMessage).
        """
        from langchain_core.callbacks import UsageMetadataCallbackHandler

        await _rate_limiter.acquire(get_settings().llm_rpm)
        messages: list = []
        if system:
            messages.append(("system", system))
        messages.append(("human", prompt))

        cb = UsageMetadataCallbackHandler()
        structured = _chat_model(self.model).with_structured_output(schema)
        result = await structured.ainvoke(messages, config={"callbacks": [cb]})

        # Account token counts from the callback's aggregated usage; cost (usd)
        # is filled later from LangSmith.
        for usage in cb.usage_metadata.values():
            in_tok, out_tok = _tokens(dict(usage))
            if self.ledger is not None:
                self.ledger.record(CallCost(self.model, in_tok, out_tok))
        return result  # type: ignore[return-value]


def reasoning(ledger: UsageLedger | None = None) -> LLM:
    """The smart tier (planner / synthesizer / critic / answerer)."""
    return LLM(get_settings().reasoning_model, ledger=ledger)


def fast(ledger: UsageLedger | None = None) -> LLM:
    """The cheap, high-volume tier (explorers / summaries / router)."""
    return LLM(get_settings().fast_model, ledger=ledger)


async def embed_texts(texts: list[str], *, ledger: UsageLedger | None = None) -> list[list[float]]:
    """Embed a batch of texts with the configured embedding model.

    Records an approximate token count (~4 chars/token) for visibility; dollar
    cost for embeddings, like chat, comes from LangSmith.
    """
    model = get_settings().embedding_model
    await _rate_limiter.acquire(get_settings().llm_rpm)
    vectors = await _embeddings(model).aembed_documents(texts)
    if ledger is not None:
        approx_tokens = sum(len(t) for t in texts) // 4
        ledger.record(CallCost(model, approx_tokens, 0))
    return vectors


async def embed_query(text: str, *, ledger: UsageLedger | None = None) -> list[float]:
    """Embed a single query string (uses the query-side embedding path)."""
    model = get_settings().embedding_model
    await _rate_limiter.acquire(get_settings().llm_rpm)
    vector = await _embeddings(model).aembed_query(text)
    if ledger is not None:
        approx_tokens = len(text) // 4
        ledger.record(CallCost(model, approx_tokens, 0))
    return vector
