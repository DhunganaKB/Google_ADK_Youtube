FROM python:3.13-slim

WORKDIR /app

# Bring in the uv binary
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

ENV UV_NO_CACHE=1

# ── Layer 1: install dependencies (cached until lock file changes) ────────────
COPY pyproject.toml uv.lock uv.toml ./
RUN uv sync --frozen --no-dev --no-install-project

# ── Layer 2: install the local package (cached until source changes) ──────────
# README.md is required by uv_build (referenced in pyproject.toml)
COPY README.md ./
COPY youtube_analyst/ ./youtube_analyst/
RUN uv sync --frozen --no-dev

# Put the venv's binaries (uvicorn, python, etc.) first in PATH
ENV PATH="/app/.venv/bin:$PATH" \
    PORT=8080

EXPOSE 8080

CMD ["sh", "-c", "uvicorn youtube_analyst.main:app --host 0.0.0.0 --port $PORT"]
