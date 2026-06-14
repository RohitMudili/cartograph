"""Guardrail tests for the model registry.

These lock the invariants that the cost-accounting and tiering logic rely on:
every model used by a tier must have a price entry, and the embedding dimension
must stay in sync with whatever the DB vector columns expect (Phase 2).
"""

from __future__ import annotations

from app.config import (
    DEFAULT_FAST_MODEL,
    DEFAULT_REASONING_MODEL,
    EMBEDDING_DIM,
    MODEL_PRICING,
    Settings,
    split_model,
)


def test_default_models_have_pricing() -> None:
    # The bare model id (after the provider prefix) must have a price entry so
    # cost accounting is real for the out-of-the-box config.
    for model in (DEFAULT_REASONING_MODEL, DEFAULT_FAST_MODEL):
        _, bare = split_model(model)
        assert bare in MODEL_PRICING, f"{bare} missing from MODEL_PRICING"


def test_default_models_are_provider_prefixed() -> None:
    # init_chat_model needs "provider:model"; a missing prefix is a config bug.
    for model in (DEFAULT_REASONING_MODEL, DEFAULT_FAST_MODEL):
        provider, _ = split_model(model)
        assert provider, f"{model} is missing a provider prefix"


def test_embedding_dim_is_supported() -> None:
    # gemini-embedding-2 supports MRL truncation to 128..3072; recommended tiers
    # are 768/1536/3072. We standardize on one; assert it's a recommended value.
    assert EMBEDDING_DIM in (768, 1536, 3072)


def test_allowed_git_hosts_parsing() -> None:
    s = Settings(allowed_git_hosts="github.com, GitLab.com ,")
    assert s.allowed_git_hosts_set == {"github.com", "gitlab.com"}
