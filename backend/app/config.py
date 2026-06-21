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

# NOTE: Cartograph maintains NO model price table. Cost is computed by LangSmith
# (it maintains current prices for all providers) and read back per run via
# run.total_cost, then stored in our Postgres. We only ever record token COUNTS
# locally (from provider usage_metadata); the dollar cost comes from LangSmith.
# See PLAN.md §7.1.


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

    # Max LLM requests/minute, applied across all model calls. Keep at/under your
    # provider tier's RPM. Gemini free tier is ~10-15 RPM — the default 10 is safe
    # for free; raise it (e.g. 1000) on a paid tier for full throughput.
    llm_rpm: int = Field(default=10)

    # ── Provider API keys (set whichever providers your model strings use) ──
    # LangChain provider packages read their own canonical env vars
    # (GOOGLE_API_KEY, OPENAI_API_KEY, ANTHROPIC_API_KEY). We surface them here so
    # they load from .env and can be validated; llm.py exports them to the
    # environment for the provider SDKs.
    google_api_key: str = Field(default="")
    openai_api_key: str = Field(default="")
    anthropic_api_key: str = Field(default="")

    @property
    def llm_available(self) -> bool:
        """True if a key is configured for the providers the chosen models need.

        Used to gate the semantic layer (summaries/embeddings): without a key, the
        static graph still indexes fully — the LLM enrichment is simply skipped.
        """
        providers = {
            self.reasoning_model.split(":", 1)[0],
            self.fast_model.split(":", 1)[0],
            self.embedding_model.split(":", 1)[0],
        }
        key_for = {
            "google_genai": self.google_api_key,
            "openai": self.openai_api_key,
            "anthropic": self.anthropic_api_key,
        }
        # Every provider the models reference must have a key.
        return all(key_for.get(p) for p in providers if p in key_for)

    # ── Upstash Redis (session storage) ──
    upstash_redis_rest_url: str = Field(default="")
    upstash_redis_rest_token: str = Field(default="")

    # ── Auth ──
    # Supabase JWT secret for validating access tokens on the backend.
    # Found under Supabase Dashboard → Settings → API → JWT Secret.
    # Required for the backend to authenticate signed-in users.
    supabase_jwt_secret: str = Field(default="")

    # ── LangSmith (tracing + cost computation; opt-in, off by default) ──
    # When tracing is on, LangChain auto-traces every model call to LangSmith,
    # which computes cost. We read run.total_cost back into our DB. With it off,
    # cost is recorded as null (never fabricated) — see PLAN.md §7.1.
    langsmith_tracing: bool = Field(default=False)
    langsmith_api_key: str = Field(default="")
    langsmith_project: str = Field(default="cartograph")

    @property
    def langsmith_enabled(self) -> bool:
        return self.langsmith_tracing and bool(self.langsmith_api_key)

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
