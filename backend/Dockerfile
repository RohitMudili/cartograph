# Multi-stage build using the official uv image for fast, reproducible installs.
# Stage 1 resolves and installs deps into a venv; stage 2 is a slim runtime that
# copies only the venv + app — no build tools, no uv cache in the final image.

FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv

WORKDIR /app

# Install dependencies first (cached layer): copy only the lockfiles, not source.
COPY pyproject.toml uv.lock* ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --no-install-project --no-dev

# Now copy source and install the project itself.
COPY . .
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --no-dev


FROM python:3.12-slim-bookworm AS runtime

# git is needed at runtime for the repo cloner.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

# Run as non-root (defense in depth — the worker handles untrusted repos).
RUN useradd --create-home --uid 1000 cartograph
WORKDIR /app

COPY --from=builder --chown=cartograph:cartograph /app/.venv /app/.venv
COPY --from=builder --chown=cartograph:cartograph /app /app

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

USER cartograph
EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
