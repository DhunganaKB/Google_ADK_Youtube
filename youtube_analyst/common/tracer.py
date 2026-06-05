"""
Langfuse tracer singleton for the YouTube Analyst application.

Wraps the LangfuseTracer abstraction from mathpackage
(github.com/DhunganaKB/math-package-tutorial) and exposes a single
pre-configured instance that the rest of the app imports.

Usage
-----
from youtube_analyst.common.tracer import tracer

# Trace a full chat request:
trace = tracer.start_trace(
    name="chat-request",
    input={"message": user_message, "session_id": session_id},
    metadata={"user_id": user_id},
)

# Add a generation span for the agent's LLM call:
trace.generation(
    name="agent-response",
    model="gemini-flash",
    input=[{"role": "user", "content": user_message}],
    output=response_text,
)

tracer.flush()

Environment variables
---------------------
LANGFUSE_PUBLIC_KEY  — from https://us.cloud.langfuse.com → Settings → API Keys
LANGFUSE_SECRET_KEY  — from the same settings page
LANGFUSE_HOST        — defaults to https://us.cloud.langfuse.com
LANGFUSE_ENABLED     — set to "false" to disable tracing (e.g. in CI)
"""

import logging

from mathpackage import LangfuseTracer

from ..config import config

logger = logging.getLogger(__name__)


def _build_tracer() -> LangfuseTracer:
    """
    Initialise LangfuseTracer from application config.
    If keys are missing, tracing is silently disabled — the app keeps running.
    """
    enabled = config.LANGFUSE_ENABLED

    if enabled and (not config.LANGFUSE_PUBLIC_KEY or not config.LANGFUSE_SECRET_KEY):
        logger.warning(
            "Langfuse tracing is enabled but LANGFUSE_PUBLIC_KEY or "
            "LANGFUSE_SECRET_KEY is not set. Tracing will be disabled. "
            "Add the keys to your .env file or Kubernetes Secret."
        )
        enabled = False

    if enabled:
        logger.info("Langfuse tracing enabled → host: %s", config.LANGFUSE_HOST)
    else:
        logger.info("Langfuse tracing disabled.")

    return LangfuseTracer(
        public_key=config.LANGFUSE_PUBLIC_KEY or None,
        secret_key=config.LANGFUSE_SECRET_KEY or None,
        host=config.LANGFUSE_HOST,
        enabled=enabled,
    )


# Single application-wide tracer instance.
# Import this anywhere in the app:  from youtube_analyst.common.tracer import tracer
tracer: LangfuseTracer = _build_tracer()
