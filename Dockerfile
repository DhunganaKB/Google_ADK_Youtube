# ── Stage 1: dependency install ──────────────────────────────────────────────
FROM python:3.13-slim AS builder

WORKDIR /app

# Copy uv binary from the official image
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

ENV UV_SYSTEM_PYTHON=1 \
    UV_NO_CACHE=1

# Install deps first (layer cached until pyproject/lock changes)
COPY pyproject.toml uv.lock uv.toml ./
RUN uv sync --frozen --no-dev

# ── Stage 2: runtime image ────────────────────────────────────────────────────
FROM python:3.13-slim

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /usr/local/lib/python3.13 /usr/local/lib/python3.13
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy application source
COPY youtube_analyst/ ./youtube_analyst/

# Cloud Run injects PORT; default to 8080 for local docker runs
ENV PORT=8080

EXPOSE 8080

CMD ["sh", "-c", "uvicorn youtube_analyst.main:app --host 0.0.0.0 --port $PORT"]
