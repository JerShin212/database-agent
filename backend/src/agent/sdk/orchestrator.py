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

from src.agent.prompts import ORCHESTRATOR_SYSTEM_PROMPT
from src.agent.sdk.servers import build_orchestrator_server, make_options
from src.agent.sdk.worker import run_worker, MAX_ITER_SENTINEL

logger = logging.getLogger(__name__)

ORCHESTRATOR_MODEL = "claude-sonnet-4-6"
ESCALATION_MODEL = "claude-sonnet-4-6"
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
                escalated = await run_worker(
                    agent, task, self.descriptor, self.emit, model=ESCALATION_MODEL
                )

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


WORKER_NAMES = {"database_agent", "text_search_agent", "visual_search_agent"}


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
) -> AsyncGenerator[dict, None]:
    """Drive the orchestrator query() and yield one ordered event stream:
      {"type":"content","content": str}
      {"type":"tool_call", ...}          (orchestrator + forwarded worker calls)
      {"type":"chart","spec": {...}}
      {"type":"action", ...}
      {"type":"error","error": str}
      {"type":"notice","text": str}      (max turns / non-success result)
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
    )

    async def drive() -> None:
        streamed: list[str] = []
        try:
            async for msg in query(prompt=prompt_input, options=options):
                if isinstance(msg, StreamEvent):
                    text = _text_delta(msg)
                    if text:
                        streamed.append(text)
                        emit({"type": "content", "content": text})
                elif isinstance(msg, ResultMessage):
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
