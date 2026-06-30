"""
LangSmith tracing for the workbench orchestrator.

Provides zero-overhead tracing when LangSmith is not configured,
and full-span tracing when environment variables are set.

Configuration:
    LANGSMITH_API_KEY   — required to enable tracing
    LANGSMITH_PROJECT   — project name (default: "workbench")
    LANGSMITH_ENDPOINT  — API endpoint (default: standard LangSmith)

Usage:
    from .tracing import trace_node, trace_llm_call

    with trace_node("classify_request", state) as span:
        # ... node logic ...
        span.set_metadata("task_type", "implementation")
"""

from __future__ import annotations

import contextlib
import logging
import os
import time
from typing import Optional

logger = logging.getLogger(__name__)

# ── LangSmith availability ────────────────────────────────────────────

_langsmith_available: Optional[bool] = None
_trace_context: Optional[dict] = None  # shared trace context for run-level metadata


def _check_langsmith() -> bool:
    """Check if LangSmith is configured and available. Cached result."""
    global _langsmith_available
    if _langsmith_available is not None:
        return _langsmith_available

    api_key = os.environ.get("LANGSMITH_API_KEY", "")
    if not api_key:
        _langsmith_available = False
        return False

    try:
        import langsmith  # noqa: F401
        _langsmith_available = True
        logger.info("langsmith tracing enabled (project=%s)", _get_project_name())
        return True
    except ImportError:
        logger.debug("langsmith not installed, tracing disabled")
        _langsmith_available = False
        return False


def _get_project_name() -> str:
    """Get the LangSmith project name from env or default."""
    return os.environ.get("LANGSMITH_PROJECT", "workbench")


def is_tracing_enabled() -> bool:
    """Check if LangSmith tracing is active."""
    return _check_langsmith()


def set_run_metadata(session_id: str, project_id: str) -> None:
    """Set top-level run metadata shared across all spans in a session."""
    global _trace_context
    _trace_context = {
        "session_id": session_id,
        "project_id": project_id,
    }


# ── Trace context manager ─────────────────────────────────────────────


@contextlib.contextmanager
def trace_node(node_name: str, state: dict | None = None):
    """
    Context manager for tracing a graph node execution.

    Usage:
        with trace_node("primary_review", state) as span:
            # ... node implementation ...
            span.set_metadata("decision", result.decision)

    When LangSmith is not configured, this is a no-op that returns
    a dummy span with no-op methods.
    """
    if not _check_langsmith():
        yield _NoOpSpan()
        return

    import langsmith as ls

    metadata = {
        "node": node_name,
    }

    if _trace_context:
        metadata.update(_trace_context)

    if state:
        metadata["task_type"] = state.get("task_type", "")
        metadata["escalation_tier"] = state.get("escalation_tier", "")
        metadata["revision_count"] = state.get("revision_count", 0)
        metadata["task_filename"] = state.get("current_task_filename", "")

    start = time.time()

    try:
        with ls.trace(
            name=node_name,
            project_name=_get_project_name(),
            metadata=metadata,
            tags=["workbench", "node", node_name],
        ) as span:
            span._start_time = start  # track manually for elapsed
            yield _LiveSpan(span, start)
    except Exception:
        # Trace failure should never crash the workflow
        logger.debug("trace_node %s failed, continuing without trace", node_name)
        yield _NoOpSpan()


@contextlib.contextmanager
def trace_llm_call(
    role: str,
    nickname: str,
    prompt_chars: int = 0,
):
    """
    Context manager for tracing an LLM call.

    Usage:
        with trace_llm_call("classifier", "classifier", len(prompt)) as span:
            result = model.invoke(messages)
            span.set_metadata("tokens", 150)

    When LangSmith is not configured, this is a no-op.
    """
    if not _check_langsmith():
        yield _NoOpSpan()
        return

    import langsmith as ls

    metadata = {
        "role": role,
        "nickname": nickname,
        "prompt_chars": prompt_chars,
    }

    if _trace_context:
        metadata.update(_trace_context)

    start = time.time()

    try:
        with ls.trace(
            name=f"llm_call.{role}",
            project_name=_get_project_name(),
            metadata=metadata,
            tags=["workbench", "llm_call", role],
        ) as span:
            yield _LiveSpan(span, start)
    except Exception:
        logger.debug("trace_llm_call %s failed, continuing without trace", role)
        yield _NoOpSpan()


# ── Span wrappers ─────────────────────────────────────────────────────


class _NoOpSpan:
    """No-op span used when tracing is disabled."""

    def set_metadata(self, key: str, value) -> None:
        pass

    def set_output(self, output: dict) -> None:
        pass

    def set_error(self, error: str) -> None:
        pass

    def add_metadata(self, metadata: dict) -> None:
        pass


class _LiveSpan:
    """Wraps a real LangSmith span with convenience methods."""

    def __init__(self, span, start_time: float):
        self._span = span
        self._start = start_time

    def set_metadata(self, key: str, value) -> None:
        """Set a single metadata key-value pair on the span."""
        try:
            if hasattr(self._span, "metadata"):
                self._span.metadata[key] = value
        except Exception:
            pass

    def set_output(self, output: dict) -> None:
        """Record the node's output/decision."""
        self.set_metadata("output", output)
        try:
            elapsed = time.time() - self._start
            self.set_metadata("latency_seconds", round(elapsed, 3))
        except Exception:
            pass

    def set_error(self, error: str) -> None:
        """Record an error on the span."""
        self.set_metadata("error", error)
        try:
            if hasattr(self._span, "add_event"):
                self._span.add_event("error", {"message": error})
        except Exception:
            pass

    def add_metadata(self, metadata: dict) -> None:
        """Add multiple metadata key-value pairs."""
        for k, v in metadata.items():
            self.set_metadata(k, v)
