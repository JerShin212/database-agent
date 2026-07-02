"""
run_worker — drive one specialist worker as a Claude Agent SDK query() loop.

Each worker gets a narrow, locked-down in-process MCP server (only its own tools).
Worker tool calls are forwarded to the shared `emit` so the chat UI still shows
"<worker> used <tool>" with a truncated result, exactly as the old AgentRuntime
on_event did. The worker's final text is returned to the orchestrator's delegate.

Return-string sentinels are preserved for the orchestrator's fallback/escalation:
  - a worker that crashes -> "[Worker <name> failed: ...]"
  - a worker that exhausts its turns / errors -> MAX_ITER_SENTINEL
  - "NO_RESULTS ..." passes straight through from the worker's final message.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from claude_agent_sdk import (
    query,
    AssistantMessage,
    UserMessage,
    ResultMessage,
    ToolUseBlock,
    ToolResultBlock,
)

from src.config import settings
from src.agent.prompts import (
    DATABASE_AGENT_PROMPT,
    TEXT_SEARCH_AGENT_PROMPT,
    VISUAL_SEARCH_AGENT_PROMPT,
)
from src.agent.sdk.servers import (
    build_database_server,
    build_doc_server,
    build_visual_server,
    make_options,
)

logger = logging.getLogger(__name__)

WORKER_MODEL = settings.worker_model
MAX_ITER_SENTINEL = "[Max iterations reached without a final response]"

# name -> (server factory, system prompt, max_turns)
WORKER_REGISTRY: dict[str, tuple[Callable, str, int]] = {
    "database_agent": (build_database_server, DATABASE_AGENT_PROMPT, 10),
    "text_search_agent": (build_doc_server, TEXT_SEARCH_AGENT_PROMPT, 8),
    "visual_search_agent": (build_visual_server, VISUAL_SEARCH_AGENT_PROMPT, 6),
}


def _short_tool(name: str) -> str:
    """mcp__database-ops__execute_sql_query -> execute_sql_query"""
    return name.split("__")[-1] if name.startswith("mcp__") else name


def _result_text(content: Any) -> str:
    """Flatten a ToolResultBlock.content (str | list of blocks) to text."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for b in content:
            if isinstance(b, dict):
                parts.append(b.get("text", ""))
            else:
                parts.append(getattr(b, "text", "") or "")
        return "".join(parts)
    return str(content) if content is not None else ""


async def run_worker(
    name: str,
    task: str,
    descriptor,
    emit: Callable[[dict], None],
    *,
    model: str | None = None,
) -> str:
    """Run `task` on worker `name`; forward its tool calls; return final text."""
    spec = WORKER_REGISTRY.get(name)
    if spec is None:
        return f"[Worker {name} failed: no such worker]"
    build, system_prompt, max_turns = spec

    server, tool_names = build(descriptor)
    options = make_options(
        server=server, tool_names=tool_names, system_prompt=system_prompt,
        model=model or WORKER_MODEL, max_turns=max_turns,
    )

    pending: dict[str, dict] = {}  # tool_use_id -> {tool, args}
    final = ""
    try:
        async for msg in query(prompt=task, options=options):
            if isinstance(msg, AssistantMessage):
                for block in msg.content:
                    if isinstance(block, ToolUseBlock):
                        pending[block.id] = {"tool": _short_tool(block.name),
                                             "args": block.input}
            elif isinstance(msg, UserMessage):
                content = msg.content if isinstance(msg.content, list) else []
                for block in content:
                    if isinstance(block, ToolResultBlock):
                        info = pending.pop(block.tool_use_id, {"tool": "?", "args": {}})
                        text = _result_text(block.content)
                        emit({"type": "tool_call", "agent": name,
                              "tool": info["tool"], "args": info["args"],
                              "result": text[:500], "is_error": bool(block.is_error)})
            elif isinstance(msg, ResultMessage):
                logger.info(
                    "[worker:%s] model=%s subtype=%s turns=%s duration_ms=%s cost_usd=%s",
                    name, model or WORKER_MODEL, msg.subtype, msg.num_turns,
                    msg.duration_ms, msg.total_cost_usd,
                )
                if msg.subtype == "success":
                    final = msg.result or ""
    except Exception as exc:
        logger.error("[run_worker:%s] %s", name, exc, exc_info=True)
        return f"[Worker {name} failed: {exc}]"

    return final if final else MAX_ITER_SENTINEL
