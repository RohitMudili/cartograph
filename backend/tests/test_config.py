"""Guardrail tests for the model registry.

These lock the invariants that the cost-accounting and tiering logic rely on:
every model used by a tier must have a price entry, and the embedding dimension
must stay in sync with whatever the DB vector columns expect (Phase 2).
"""

from __future__ import annotations

from app.config import (
    EMBEDDING_DIM,
    MODEL_FAST,
    MODEL_PRICING,
    MODEL_REASONING,
    Settings,
)


def test_active_models_have_pricing() -> None:
    for model in (MODEL_REASONING, MODEL_FAST):
        assert model in MODEL_PRICING, f"{model} missing from MODEL_PRICING"


def test_embedding_dim_is_supported() -> None:
    # gemini-embedding-2 supports MRL truncation to 128..3072; recommended tiers
    # are 768/1536/3072. We standardize on one; assert it's a recommended value.
    assert EMBEDDING_DIM in (768, 1536, 3072)


def test_allowed_git_hosts_parsing() -> None:
    s = Settings(allowed_git_hosts="github.com, GitLab.com ,")
    assert s.allowed_git_hosts_set == {"github.com", "gitlab.com"}
