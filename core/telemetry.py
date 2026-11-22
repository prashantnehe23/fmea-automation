"""
core/telemetry.py — Lightweight pipeline observability.

Usage in fmea_pipeline.py:

    from core.telemetry import set_scan_context, agent_span

    set_scan_context(scan_id=workspace_id, workspace_id=workspace_id)

    with agent_span("saboteur"):
        failures = run_saboteur(...)

Design:
  - Thread-local context stores (scan_id, workspace_id) for the running pipeline.
  - agent_span() is a context manager that times the block and captures the
    token-usage delta from core.llm for that specific agent call.
  - All DB writes are best-effort: any exception is silently swallowed so a
    telemetry failure can never crash the pipeline.
"""

from __future__ import annotations

import contextvars
import threading
import time
import uuid
from contextlib import contextmanager

from core.provider_block import ProviderBlocked

_ctx = threading.local()
_stage: contextvars.ContextVar[str] = contextvars.ContextVar("fmea_stage", default="")


def current_stage() -> str:
    """The pipeline stage (agent) now running, so a provider block can say where it happened (B-040)."""
    return _stage.get()


def set_scan_context(scan_id: int | None, workspace_id: int | None) -> None:
    """
    Store (scan_id, workspace_id) in thread-local state for agent_span() to read.
    Generates a fresh run_id UUID so all spans in this pipeline run are linked.
    Captures the active model at scan start for per-span cost attribution.
    """
    from core.llm import get_model_name
    _ctx.scan_id = scan_id
    _ctx.workspace_id = workspace_id
    _ctx.run_id = str(uuid.uuid4())
    _ctx.model = get_model_name()


def update_scan_id(scan_id: int) -> None:
    """Call after save_scan() to store the real scan_id in context."""
    _ctx.scan_id = scan_id


def get_run_id() -> str | None:
    """Return the run_id for the current pipeline run."""
    return getattr(_ctx, "run_id", None)


def clear_scan_context() -> None:
    """Clear thread-local context after a pipeline run."""
    _ctx.scan_id = None
    _ctx.workspace_id = None
    _ctx.run_id = None


@contextmanager
def agent_span(agent_name: str):
    """
    Context manager that measures wall-clock duration and token usage for one agent.

    Token delta is computed as the difference in cumulative counters from core.llm
    before and after the block — so each span captures only its own LLM calls.
    """
    from core.llm import get_token_usage
    before_p, before_c = get_token_usage()
    t0 = time.perf_counter()
    error_msg: str | None = None
    stage_token = _stage.set(agent_name)
    try:
        yield
    except ProviderBlocked:
        error_msg = "provider_blocked"
        raise
    except Exception as exc:
        error_msg = str(exc)
        raise
    finally:
        _stage.reset(stage_token)
        duration_ms = (time.perf_counter() - t0) * 1000
        after_p, after_c = get_token_usage()
        _record(
            agent=agent_name,
            duration_ms=duration_ms,
            prompt_tokens=after_p - before_p,
            completion_tokens=after_c - before_c,
            error=error_msg,
        )


def _record(
    agent: str,
    duration_ms: float,
    prompt_tokens: int,
    completion_tokens: int,
    error: str | None,
) -> None:
    """Write one telemetry span to SQLite. Silently ignored on any error."""
    try:
        from core.costs import compute_cost
        import memory.db as _db
        model = getattr(_ctx, "model", None) or "gpt-5.1"
        cost_usd = compute_cost(model, prompt_tokens, completion_tokens)
        _db.save_telemetry_span(
            run_id=getattr(_ctx, "run_id", None),
            scan_id=getattr(_ctx, "scan_id", None),
            workspace_id=getattr(_ctx, "workspace_id", None),
            agent=agent,
            duration_ms=duration_ms,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            error=error,
            cost_usd=cost_usd,
        )
    except Exception:
        pass  # telemetry must never crash the pipeline
