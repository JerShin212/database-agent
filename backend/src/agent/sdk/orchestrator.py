"""
Orchestrator runtime on top of the Claude Agent SDK.

The orchestrator runs as its own query() loop whose only tools are `delegate`,
`create_chart`, and `suggest_form` (the orchestrator-ops MCP server). `delegate`
calls run_worker() and preserves the bespoke routing logic ported verbatim from
the old OrchestratorAgent:

  * NO_RESULTS cross-agent fallback (database <-> text <-> visual), one-shot per
    agent per request.
  * Haiku -> Sonnet escalation on a capability failure (crash / max-turns), or
    when both the worker and its fallback came up empty/broken, one-shot per agent.

run_orchestrator_events() drives the orchestrator query() and yields a single
ordered event stream (content / tool_call / chart / action / error / notice) that
interleaves the orchestrator's own output with the worker tool calls surfaced by
run_worker — all funnelled through one asyncio.Queue.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, AsyncIterable, AsyncGenerator, Callable

from claude_agent_sdk import query, AssistantMessage, ResultMessage, StreamEvent

from src.config import settings
from src.agent.prompts import ORCHESTRATOR_SYSTEM_PROMPT
from src.agent.sdk.servers import build_orchestrator_server, make_options
from src.agent.sdk.worker import run_worker, MAX_ITER_SENTINEL
from src.services.mlflow_tracing import (
    SpanType,
    attach_usage as _attach_usage,
    span as tspan,
    trace_metadata,
)

logger = logging.getLogger(__name__)

ORCHESTRATOR_MODEL = settings.orchestrator_model
ESCALATION_MODEL = settings.escalation_model
ORCHESTRATOR_MAX_TURNS = 20

# When a worker reports NO_RESULTS, retry the task with this alternate worker.
_FALLBACK_AGENT = {
    "database_agent": "text_search_agent",
    "text_search_agent": "database_agent",
    "visual_search_agent": "text_search_agent",
}
NO_RESULTS_TOKEN = "NO_RESULTS"

WORKER_NAMES = {"database_agent", "text_search_agent", "visual_search_agent"}


def _is_capability_failure(result: str) -> bool:
    """True when a worker crashed or ran out of turns — failures a stronger model
    might fix, as opposed to data simply not existing."""
    stripped = (result or "").lstrip()
    return stripped.startswith("[Worker ") or stripped.startswith(MAX_ITER_SENTINEL)


class Delegator:
    """Holds per-request fallback/escalation bookkeeping and runs workers."""

    def __init__(self, descriptor, emit: Callable[[dict], None]):
        self.descriptor = descriptor
        self.emit = emit
        self._fallbacks_used: set[str] = set()
        self._escalations_used: set[str] = set()
        self._lock = asyncio.Lock()

    async def delegate(self, agent: str, task: str) -> str:
        result = await run_worker(agent, task, self.descriptor, self.emit)

        # 1. Cross-agent fallback on NO_RESULTS — the data may live in the other
        #    source. One-shot per agent per request.
        alternate = _FALLBACK_AGENT.get(agent)
        alternate_result = None
        if alternate and result.lstrip().startswith(NO_RESULTS_TOKEN):
            async with self._lock:
                use_fallback = agent not in self._fallbacks_used
                if use_fallback:
                    self._fallbacks_used.add(agent)
            if use_fallback:
                self.emit({"type": "tool_call", "agent": "orchestrator",
                           "tool": "delegate", "args": {"agent": alternate, "task": task},
                           "result": f"(automatic fallback from {agent} — running {alternate}…)",
                           "is_error": False})
                alternate_result = await run_worker(
                    alternate, task, self.descriptor, self.emit
                )

        # 2. Model escalation — retry the same worker on a stronger model for a
        #    capability failure, or when both worker and fallback came up empty.
        escalated = None
        if self._should_escalate(agent, result, alternate_result):
            async with self._lock:
                use_escalation = agent not in self._escalations_used
                if use_escalation:
                    self._escalations_used.add(agent)
            if use_escalation:
                self.emit({"type": "tool_call", "agent": "orchestrator",
                           "tool": "delegate", "args": {"agent": agent, "task": task},
                           "result": f"(escalating {agent} to {ESCALATION_MODEL}…)",
                           "is_error": False})
                escalated = await run_worker(
                    agent, task, self.descriptor, self.emit, model=ESCALATION_MODEL
                )
                # Measure whether escalation ever changes the outcome — if this
                # only ever logs 'still-empty', the double-NO_RESULTS trigger
                # is wasted spend and can be dropped.
                still_empty = _is_capability_failure(escalated) or \
                    escalated.lstrip().startswith(NO_RESULTS_TOKEN)
                logger.info("[escalation] agent=%s model=%s outcome=%s",
                            agent, ESCALATION_MODEL,
                            "still-empty" if still_empty else "produced-answer")

        if alternate_result is None and escalated is None:
            return result

        parts = [f"[{agent}] {result}"]
        if alternate_result is not None:
            parts.append(
                f"[Automatic fallback to {alternate}]\n[{alternate}] {alternate_result}"
            )
        if escalated is not None:
            parts.append(f"[Escalated {agent} to {ESCALATION_MODEL}]\n{escalated}")
        return "\n\n".join(parts)

    def _should_escalate(self, agent: str, result: str, alternate_result: str | None) -> bool:
        if agent not in WORKER_NAMES:
            return False
        if _is_capability_failure(result):
            return True
        if result.lstrip().startswith(NO_RESULTS_TOKEN) and alternate_result is not None:
            return _is_capability_failure(alternate_result) or \
                alternate_result.lstrip().startswith(NO_RESULTS_TOKEN)
        return False


def _text_delta(msg: StreamEvent) -> str | None:
    ev = getattr(msg, "event", None)
    if not isinstance(ev, dict) or ev.get("type") != "content_block_delta":
        return None
    delta = ev.get("delta") or {}
    if delta.get("type") == "text_delta":
        return delta.get("text") or ""
    return None


async def run_orchestrator_events(
    descriptor,
    prompt_input: str | AsyncIterable[dict],
    *,
    resume: str | None = None,
) -> AsyncGenerator[dict, None]:
    """Drive the orchestrator query() and yield one ordered event stream:
      {"type":"content","content": str}
      {"type":"tool_call", ...}          (orchestrator + forwarded worker calls)
      {"type":"chart","spec": {...}}
      {"type":"action", ...}
      {"type":"error","error": str}
      {"type":"notice","text": str}      (max turns / non-success result)
      {"type":"session","session_id": str}   (for multi-turn resume)
    """
    queue: asyncio.Queue = asyncio.Queue()

    def emit(event: dict | None) -> None:
        queue.put_nowait(event)

    delegator = Delegator(descriptor, emit)
    server, tool_names = build_orchestrator_server(descriptor, emit, delegator.delegate)
    options = make_options(
        server=server, tool_names=tool_names,
        system_prompt=ORCHESTRATOR_SYSTEM_PROMPT,
        model=ORCHESTRATOR_MODEL, max_turns=ORCHESTRATOR_MAX_TURNS,
        include_partial_messages=True,
        resume=resume,
    )

    async def drive() -> None:
        streamed: list[str] = []
        try:
            # One MLflow trace per orchestrator run; tool/worker spans opened in
            # the SDK's handler tasks auto-nest under this root via contextvars.
            with tspan("orchestrator", span_type=SpanType.AGENT) as root:
                if root:
                    root.set_inputs({"message": (
                        prompt_input[:2000] if isinstance(prompt_input, str)
                        else "[streaming input with image]"
                    )})
                    root.set_attributes({
                        "llm.model": ORCHESTRATOR_MODEL,
                        "resume": bool(resume),
                    })
                    trace_metadata(session=descriptor.conversation_id)
                async for msg in query(prompt=prompt_input, options=options):
                    if isinstance(msg, StreamEvent):
                        text = _text_delta(msg)
                        if text:
                            streamed.append(text)
                            emit({"type": "content", "content": text})
                    elif isinstance(msg, ResultMessage):
                        logger.info(
                            "[orchestrator] subtype=%s turns=%s duration_ms=%s cost_usd=%s",
                            msg.subtype, msg.num_turns, msg.duration_ms, msg.total_cost_usd,
                        )
                        if root:
                            _attach_usage(root, msg, model=ORCHESTRATOR_MODEL)
                        if msg.session_id:
                            emit({"type": "session", "session_id": msg.session_id})
                        if msg.subtype == "success":
                            # Text was already streamed via deltas; only emit the
                            # result if nothing streamed (defensive — no double text).
                            if not "".join(streamed).strip() and (msg.result or "").strip():
                                emit({"type": "content", "content": msg.result})
                        else:
                            emit({"type": "notice", "text": (
                                "\n\nI couldn't fully complete this within my step "
                                "limit — here's what I found so far."
                            )})
                if root:
                    root.set_outputs({"response": "".join(streamed)[:10000]})
        except Exception as exc:
            logger.error("[orchestrator] %s", exc, exc_info=True)
            emit({"type": "error", "error": str(exc)})
        finally:
            emit(None)  # sentinel: orchestrator finished

    task = asyncio.create_task(drive())
    try:
        while (event := await queue.get()) is not None:
            yield event
    finally:
        await task
