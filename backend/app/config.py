"""Application configuration and the Gemini model registry.

All settings load from environment / .env via pydantic-settings. The model
registry is the single source of truth for which Gemini models each tier of the
system uses — agents and the indexer reference these by tier, never by literal
ID, so a model swap is a one-line change here (PLAN.md §4.2).
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# ─────────────────────────────────────────────────────────────────────────────
# Gemini model registry
#
# Verified against ai.google.dev/gemini-api/docs on 2026-06-13. Re-verify model
# IDs and pricing at each release; do not edit these from memory elsewhere in the
# codebase (PLAN.md §4.2). Pricing is USD per 1M tokens, used for cost accounting.
#
#   Reasoning tier (planner / synthesizer / critic): gemini-3.5-flash is the
#     current GA "most intelligent for agentic/coding" model. The Gemini 3 Pro
#     tier (gemini-3.1-pro-preview) is still preview; switch REASONING to it once
#     it reaches GA if evals justify the cost.
#   Fast tier (explorers / summaries / router): gemini-3.1-flash-lite, the GA
#     cost-efficiency workhorse.
#   Embeddings: gemini-embedding-2, MRL-truncatable; we store 1536 dims
#     (recommended tier; halves storage vs the 3072 default at negligible quality
#     loss) for pgvector.
# ─────────────────────────────────────────────────────────────────────────────

MODEL_REASONING = "gemini-3.5-flash"
MODEL_FAST = "gemini-3.1-flash-lite"
MODEL_EMBEDDING = "gemini-embedding-2"

EMBEDDING_DIM = 1536

# Pricing (USD per 1M tokens), verified 2026-06-13. (input, output).
MODEL_PRICING: dict[str, tuple[float, float]] = {
    "gemini-3.5-flash": (0.30, 2.50),
    "gemini-3.1-flash-lite": (0.10, 0.40),
    "gemini-3.1-pro-preview": (1.25, 10.00),  # upgrade target for REASONING
}
# Embedding pricing (USD per 1M tokens). Output-only.
EMBEDDING_PRICE_PER_1M = 0.20


class Settings(BaseSettings):
    """Environment-driven settings. See .env.example for the canonical list."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        # pydantic reserves the `model_` prefix; we have no model_* fields, but
        # this keeps future-proofing explicit.
        protected_namespaces=(),
    )

    # ── Gemini ──
    gemini_api_key: str = Field(default="", description="Gemini API key")

    # ── Database ──
    database_url: str = Field(
        default="postgresql+asyncpg://cartograph:cartograph@localhost:5432/cartograph",
        description="SQLAlchemy async DSN",
    )

    # ── App ──
    cartograph_env: str = Field(default="local")
    log_level: str = Field(default="INFO")

    # ── Budgets / limits ──
    max_run_cost_usd: float = Field(default=2.00)
    max_repo_files: int = Field(default=5000)
    max_repo_mb: int = Field(default=500)
    max_agent_concurrency: int = Field(default=6)
    allowed_git_hosts: str = Field(default="github.com")

    @property
    def allowed_git_hosts_set(self) -> set[str]:
        return {h.strip().lower() for h in self.allowed_git_hosts.split(",") if h.strip()}

    @property
    def is_local(self) -> bool:
        return self.cartograph_env == "local"


@lru_cache
def get_settings() -> Settings:
    """Cached settings singleton. Import this, don't construct Settings directly."""
    return Settings()
