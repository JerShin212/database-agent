"""
MLflow tracing setup for the agent stack (ported from the mlflow-agent-tracing
skill's reference wrapper).

Design goals:
  - Tracing must NEVER break the app: every entry point is non-fatal, and the
    module stays importable when mlflow isn't installed (everything no-ops).
  - Spans are availability-gated: `span()` returns a real MLflow span context
    manager only when init_mlflow() ran AND the server is reachable, otherwise
    `nullcontext(None)` — so the pytest suite (which never calls init) creates
    no traces, and requests stay zero-overhead when MLflow is down.

Usage:
    from src.services.mlflow_tracing import init_mlflow, flush_traces, span
    init_mlflow()            # at process startup (FastAPI lifespan)
    ...
    stop_health_probe()      # at graceful shutdown
    flush_traces()           # drain batched async export before exit

Env vars:
    MLFLOW_TRACKING_URI            (default http://localhost:5000)
    MLFLOW_EXPERIMENT              (default "database-agent")
    MLFLOW_TRACKING_USERNAME/_PASSWORD   (basic auth; read natively by MLflow)
    MLFLOW_HEALTH_PROBE_INTERVAL_S (default 30)
    MLFLOW_HEALTH_PROBE_TIMEOUT_S  (default 3)
"""

from __future__ import annotations

import logging
import os
import threading
from contextlib import nullcontext
from typing import Optional

log = logging.getLogger("mlflow_tracing")

try:
    import mlflow
    from mlflow.entities import SpanType

    _MLFLOW_AVAILABLE = True
except ImportError:  # keep the app (and tests) importable without mlflow
    mlflow = None  # type: ignore[assignment]
    _MLFLOW_AVAILABLE = False

    class SpanType:  # matches mlflow.entities.SpanType string constants
        AGENT = "AGENT"
        TOOL = "TOOL"
        LLM = "LLM"
        CHAIN = "CHAIN"


_initialized = False
_reachable = False
_probe_thread: Optional[threading.Thread] = None
_probe_stop = threading.Event()


def _tracking_uri() -> str:
    return os.environ.get("MLFLOW_TRACKING_URI", "http://localhost:5000")


def _probe_timeout() -> float:
    return float(os.environ.get("MLFLOW_HEALTH_PROBE_TIMEOUT_S", "3"))


def _probe_health(uri: str) -> bool:
    """Cheap reachability check against MLflow's /health. Never raises."""
    try:
        import urllib.request

        with urllib.request.urlopen(
            f"{uri.rstrip('/')}/health", timeout=_probe_timeout()
        ) as r:
            return 200 <= getattr(r, "status", r.getcode()) < 300
    except Exception:
        return False


def init_mlflow(experiment: Optional[str] = None) -> None:
    """Initialize MLflow tracing. Non-fatal: logs and continues on any failure."""
    global _initialized, _reachable
    if _initialized:
        return
    if not _MLFLOW_AVAILABLE:
        log.warning("mlflow is not installed — tracing disabled")
        return
    uri = _tracking_uri()
    experiment = experiment or os.environ.get("MLFLOW_EXPERIMENT", "database-agent")
    try:
        mlflow.set_tracking_uri(uri)
        _reachable = _probe_health(uri)
        if _reachable:
            mlflow.set_experiment(experiment)
        else:
            log.warning(
                "MLflow unreachable at %s at boot — tracing no-ops until it recovers",
                uri,
            )
        _initialized = True
        _start_health_probe(uri)
        log.info(
            "MLflow tracing initialized (uri=%s, experiment=%s, reachable=%s)",
            uri,
            experiment,
            _reachable,
        )
    except Exception as e:  # non-fatal — the app must run without tracing
        log.warning("MLflow init failed (%s) — continuing without tracing", e)


def is_ready() -> bool:
    """True only when initialized AND the server is currently reachable."""
    return _initialized and _reachable


def _start_health_probe(uri: str) -> None:
    """Background thread that flips `_reachable` so an outage auto-recovers."""
    global _probe_thread
    if _probe_thread is not None:
        return
    interval = float(os.environ.get("MLFLOW_HEALTH_PROBE_INTERVAL_S", "30"))

    def loop() -> None:
        global _reachable
        while not _probe_stop.wait(interval):
            ok = _probe_health(uri)
            if ok != _reachable:
                log.info("MLflow reachability changed: %s -> %s", _reachable, ok)
            _reachable = ok

    _probe_thread = threading.Thread(
        target=loop, name="mlflow-health-probe", daemon=True
    )
    _probe_thread.start()


def stop_health_probe() -> None:
    _probe_stop.set()


def flush_traces() -> None:
    """Drain batched async trace export. Call at graceful shutdown. Non-fatal."""
    if not _initialized:
        return
    try:
        mlflow.flush_trace_async_logging()
    except Exception as e:
        log.warning("MLflow flush failed: %s", e)


def trace_metadata(
    *,
    session: Optional[str] = None,
    user: Optional[str] = None,
    extra: Optional[dict] = None,
) -> None:
    """Attach trace-level grouping metadata to the CURRENT trace.

    Call inside the root span. `session`/`user` populate MLflow's reserved keys so
    the UI can group/filter by conversation and user.
    """
    if not is_ready():
        return
    md: dict = {}
    if session:
        md["mlflow.trace.session"] = str(session)
    if user:
        md["mlflow.trace.user"] = str(user)
    if extra:
        md.update(extra)
    if md:
        try:
            mlflow.update_current_trace(metadata=md)
        except Exception as e:
            log.debug("update_current_trace failed: %s", e)


def attach_usage(s, result_msg, *, model: str) -> None:
    """Set token/cost attributes on span `s` from an SDK ResultMessage. Non-fatal."""
    if s is None:
        return
    try:
        usage = getattr(result_msg, "usage", None) or {}
        s.set_attributes({
            "llm.model": model,
            "tokens.input": usage.get("input_tokens"),
            "tokens.output": usage.get("output_tokens"),
            "llm.usage.cache_read_input_tokens": usage.get("cache_read_input_tokens"),
            "llm.usage.cache_creation_input_tokens": usage.get("cache_creation_input_tokens"),
            "llm.cost_usd": getattr(result_msg, "total_cost_usd", None),
            "llm.num_turns": getattr(result_msg, "num_turns", None),
        })
    except Exception as e:
        log.debug("attach_usage failed: %s", e)


def span(name: str, span_type=None, **kwargs):
    """Availability-gated span.

    Returns a real MLflow span context manager when ready, else a no-op
    (`nullcontext(None)`) — callers guard with `as s: if s: s.set_inputs(...)`.
    """
    if not is_ready():
        return nullcontext(None)
    try:
        return mlflow.start_span(name=name, span_type=span_type, **kwargs)
    except Exception as e:  # span creation must never break a request
        log.debug("mlflow.start_span failed: %s", e)
        return nullcontext(None)
