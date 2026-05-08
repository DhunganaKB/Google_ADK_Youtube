FROM python:3.13-slim

WORKDIR /app

# Bring in the uv binary
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Install packages into the system Python (no venv needed inside container)
ENV UV_SYSTEM_PYTHON=1 \
    UV_NO_CACHE=1

# ── Layer 1: install dependencies (cached until lock file changes) ────────────
COPY pyproject.toml uv.lock uv.toml ./
RUN uv sync --frozen --no-dev --no-install-project

# ── Layer 2: install the local package (cached until source changes) ──────────
COPY youtube_analyst/ ./youtube_analyst/
RUN uv sync --frozen --no-dev

# Cloud Run injects PORT at runtime; default to 8080 for local docker runs
ENV PORT=8080
EXPOSE 8080

CMD ["sh", "-c", "uvicorn youtube_analyst.main:app --host 0.0.0.0 --port $PORT"]
