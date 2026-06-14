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
# Cartograph is provider-agnostic via LangChain's init_chat_model. Models are
# named as "<provider>:<model>" strings (provider ∈ google_genai | openai |
# anthropic) and are SERVER-CONFIGURED in .env — swapping a tier's provider is a
# one-line change with no code edits (PLAN.md §4.2). Defaults below use Gemini.
#
#   Reasoning tier  (planner / synthesizer / critic)  — the smart, costlier model.
#   Fast tier       (explorers / summaries / router)  — the cheap, high-volume one.
#   Embedding model (separate interface; provider may differ from the chat tiers).
#
# Pricing is USD per 1M tokens, keyed by the bare model id (the part after the
# "provider:" prefix), used for cost accounting. Verified 2026-06-13; re-verify at
# each model release and do not edit these from memory elsewhere in the codebase.
# ─────────────────────────────────────────────────────────────────────────────

DEFAULT_REASONING_MODEL = "google_genai:gemini-3.5-flash"
DEFAULT_FAST_MODEL = "google_genai:gemini-3.1-flash-lite"
DEFAULT_EMBEDDING_MODEL = "google_genai:gemini-embedding-2"

# pgvector column dimension. MUST match the embedding model's output size; if you
# switch to an embedding model with a different dimension, a migration is needed.
EMBEDDING_DIM = 1536

# Chat-model pricing (USD per 1M tokens), keyed by bare model id. (input, output).
MODEL_PRICING: dict[str, tuple[float, float]] = {
    # Google Gemini
    "gemini-3.5-flash": (0.30, 2.50),
    "gemini-3.1-flash-lite": (0.10, 0.40),
    "gemini-3.1-pro-preview": (1.25, 10.00),
    # OpenAI (verify ids/prices before relying on cost numbers for these)
    "gpt-5": (1.25, 10.00),
    "gpt-5-mini": (0.25, 2.00),
    # Anthropic
    "claude-sonnet-4-6": (3.00, 15.00),
    "claude-haiku-4-5": (1.00, 5.00),
}

# Embedding pricing (USD per 1M tokens), keyed by bare model id. Input-only.
EMBEDDING_PRICING: dict[str, float] = {
    "gemini-embedding-2": 0.20,
    "text-embedding-3-small": 0.02,
    "text-embedding-3-large": 0.13,
}


def split_model(model: str) -> tuple[str, str]:
    """Split a 'provider:model' string into (provider, bare_model_id).

    Falls back to ('', model) if no provider prefix is present.
    """
    if ":" in model:
        provider, bare = model.split(":", 1)
        return provider, bare
    return "", model


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

    # ── Models (provider-agnostic; "provider:model" strings) ──
    reasoning_model: str = Field(default=DEFAULT_REASONING_MODEL)
    fast_model: str = Field(default=DEFAULT_FAST_MODEL)
    embedding_model: str = Field(default=DEFAULT_EMBEDDING_MODEL)

    # ── Provider API keys (set whichever providers your model strings use) ──
    # LangChain provider packages read their own canonical env vars
    # (GOOGLE_API_KEY, OPENAI_API_KEY, ANTHROPIC_API_KEY). We surface them here so
    # they load from .env and can be validated; llm.py exports them to the
    # environment for the provider SDKs.
    google_api_key: str = Field(default="")
    openai_api_key: str = Field(default="")
    anthropic_api_key: str = Field(default="")

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
