"""
AgentRuntime — single-agent agentic loop using the Anthropic API directly.

Adapted from tool_agent.py for use within the backend package.
"""

from __future__ import annotations

import concurrent.futures
import contextvars
import json
import logging
import os
import threading
from dataclasses import dataclass, field
from typing import Any, Callable, Generator

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Tool definition
# ---------------------------------------------------------------------------

@dataclass
class ToolDefinition:
    name: str
    description: str
    input_schema: dict[str, Any]
    handler: Callable[..., str]
    required: list[str] = field(default_factory=list)
    denied: bool = False

    def to_api_spec(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": {
                "type": "object",
                "properties": self.input_schema,
                "required": self.required,
            },
        }

    def execute(self, **kwargs: Any) -> str:
        if self.denied:
            return f"[Permission denied] Tool '{self.name}' is blocked."
        try:
            return str(self.handler(**kwargs))
        except Exception as exc:
            return f"[Tool error] {exc}"


# ---------------------------------------------------------------------------
# Tool registry
# ---------------------------------------------------------------------------

class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}

    def register(self, tool: ToolDefinition) -> None:
        self._tools[tool.name] = tool

    def deny(self, *names: str) -> None:
        for name in names:
            if name in self._tools:
                self._tools[name].denied = True

    def allow(self, *names: str) -> None:
        for name in names:
            if name in self._tools:
                self._tools[name].denied = False

    def execute(self, name: str, input_json: str) -> tuple[str, bool]:
        """Returns (output, is_error)."""
        tool = self._tools.get(name)
        if tool is None:
            return f"[Unknown tool] '{name}'", True
        try:
            kwargs = json.loads(input_json) if input_json else {}
        except json.JSONDecodeError:
            return f"[Invalid JSON input for tool '{name}']", True
        return tool.execute(**kwargs), False

    def api_specs(self) -> list[dict[str, Any]]:
        return [t.to_api_spec() for t in self._tools.values()]

    def names(self) -> list[str]:
        return list(self._tools.keys())


# ---------------------------------------------------------------------------
# Session (conversation history)
# ---------------------------------------------------------------------------

@dataclass
class Session:
    messages: list[dict[str, Any]] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0

    def add_user(self, content: str | list[dict[str, Any]]) -> None:
        """Accepts plain text or a list of content blocks (e.g. image + text).

        Plain text is normalized to block form so cache_control markers can
        be attached to any message.
        """
        if isinstance(content, str):
            content = [{"type": "text", "text": content}]
        self.messages.append({"role": "user", "content": content})

    def add_assistant(self, content: list[dict[str, Any]]) -> None:
        self.messages.append({"role": "assistant", "content": content})

    def add_tool_results(self, results: list[dict[str, Any]]) -> None:
        self.messages.append({"role": "user", "content": results})

    def track_usage(self, usage: Any) -> None:
        self.input_tokens += getattr(usage, "input_tokens", 0) or 0
        self.output_tokens += getattr(usage, "output_tokens", 0) or 0
        self.cache_read_tokens += getattr(usage, "cache_read_input_tokens", 0) or 0
        self.cache_creation_tokens += getattr(usage, "cache_creation_input_tokens", 0) or 0

    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def clear(self) -> None:
        self.messages = []
        self.input_tokens = 0
        self.output_tokens = 0
        self.cache_read_tokens = 0
        self.cache_creation_tokens = 0


# ---------------------------------------------------------------------------
# Agent runtime — the turn loop
# ---------------------------------------------------------------------------

class AgentRuntime:
    """
    Core agentic loop:
        user input → LLM → tool calls → tool results → LLM → ... → final response
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "claude-sonnet-4-6",
        system: str = "You are a helpful AI assistant.",
        max_tokens: int = 4096,
        max_iter: int = 10,
        name: str = "agent",
        on_event: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        try:
            import anthropic
        except ImportError:
            raise ImportError("Run: pip install anthropic")

        self._client = anthropic.Anthropic(
            api_key=api_key or os.environ["ANTHROPIC_API_KEY"],
            max_retries=3,
        )
        self.model = model
        self.system = system
        self.max_tokens = max_tokens
        self.max_iter = max_iter
        self.name = name
        # Optional observer for tool-call events; used to surface worker
        # activity (e.g. "agent used SQL") to the streaming chat UI.
        self.on_event = on_event

        self.registry = ToolRegistry()
        self.session = Session()

        # Serializes concurrent run() calls (e.g. two parallel delegations to
        # the same worker) — they would otherwise interleave one session.
        self._run_lock = threading.Lock()

        # Tools render before system in the prompt, so a single breakpoint on
        # the system block caches tool definitions + system prompt together.
        self._system_blocks = [
            {"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}
        ]

    def _mark_cache_breakpoint(self) -> None:
        """
        Keep exactly one ephemeral cache marker on the last content block of
        the last message, so each loop iteration reads the entire prior
        transcript (assistant turns + tool results) from cache.
        """
        for message in self.session.messages:
            content = message["content"]
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict):
                        block.pop("cache_control", None)
        if self.session.messages:
            content = self.session.messages[-1]["content"]
            if isinstance(content, list) and content and isinstance(content[-1], dict):
                content[-1]["cache_control"] = {"type": "ephemeral"}

    def _log_usage(self, usage: Any) -> None:
        logger.info(
            "[%s] usage: in=%s out=%s cache_read=%s cache_write=%s",
            self.name,
            getattr(usage, "input_tokens", 0),
            getattr(usage, "output_tokens", 0),
            getattr(usage, "cache_read_input_tokens", 0),
            getattr(usage, "cache_creation_input_tokens", 0),
        )

    def _emit(self, event: dict[str, Any]) -> None:
        if self.on_event is None:
            return
        try:
            self.on_event(event)
        except Exception:
            pass  # observers must never break the agent loop

    def tool(
        self,
        description: str,
        params: dict[str, dict[str, Any]] | None = None,
        required: list[str] | None = None,
        name: str | None = None,
    ) -> Callable:
        """Decorator to register a function as a tool."""
        def decorator(fn: Callable) -> Callable:
            tool_name = name or fn.__name__
            self.registry.register(ToolDefinition(
                name=tool_name,
                description=description,
                input_schema=params or {},
                handler=fn,
                required=required or list(params.keys()) if params else [],
            ))
            return fn
        return decorator

    def add_tool(
        self,
        name: str,
        description: str,
        handler: Callable[..., str],
        params: dict[str, dict[str, Any]] | None = None,
        required: list[str] | None = None,
    ) -> None:
        """Register a tool without using the decorator."""
        self.registry.register(ToolDefinition(
            name=name,
            description=description,
            input_schema=params or {},
            handler=handler,
            required=required or [],
        ))

    def deny_tools(self, *names: str) -> None:
        self.registry.deny(*names)

    def allow_tools(self, *names: str) -> None:
        self.registry.allow(*names)

    def _execute_tool_blocks(self, blocks: list[Any]) -> list[tuple[Any, str, bool]]:
        """
        Execute tool_use blocks — concurrently when there is more than one
        (e.g. the orchestrator delegating to several workers in one response).
        Returns (block, output, is_error) tuples in the original block order.

        Each task runs in a fresh copy of the calling thread's contextvars
        context, so ToolContext propagates into the worker threads.
        """
        if len(blocks) == 1:
            block = blocks[0]
            output, is_error = self.registry.execute(block.name, json.dumps(block.input))
            return [(block, output, is_error)]

        with concurrent.futures.ThreadPoolExecutor(max_workers=len(blocks)) as pool:
            futures = [
                pool.submit(
                    contextvars.copy_context().run,
                    self.registry.execute,
                    block.name,
                    json.dumps(block.input),
                )
                for block in blocks
            ]
            results = []
            for block, future in zip(blocks, futures):
                try:
                    output, is_error = future.result()
                except Exception as exc:  # registry.execute catches; this is a backstop
                    output, is_error = f"[Tool error] {exc}", True
                results.append((block, output, is_error))
        return results

    def run(self, user_input: str | list[dict[str, Any]]) -> str:
        """
        Run one conversational turn. May call tools multiple times internally.
        Returns the final text response from the model.

        user_input may be plain text or a list of content blocks (e.g. an
        image block followed by a text block, for vision-capable models).

        Thread-safe: concurrent calls serialize on a per-runtime lock.
        """
        with self._run_lock:
            return self._run_turn(user_input)

    def _run_turn(self, user_input: str | list[dict[str, Any]]) -> str:
        self.session.add_user(user_input)

        for _ in range(self.max_iter):
            self._mark_cache_breakpoint()
            response = self._client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                system=self._system_blocks,
                tools=self.registry.api_specs(),
                messages=self.session.messages,
            )

            self.session.track_usage(response.usage)
            self._log_usage(response.usage)

            content_blocks = [self._block_to_dict(block) for block in response.content]
            self.session.add_assistant(content_blocks)

            if response.stop_reason != "tool_use":
                return self._extract_text(response.content)

            tool_blocks = [b for b in response.content if b.type == "tool_use"]
            tool_results = []
            for block, output, is_error in self._execute_tool_blocks(tool_blocks):
                self._emit({
                    "type": "tool_call",
                    "agent": self.name,
                    "tool": block.name,
                    "args": block.input,
                    "result": output[:500],
                    "is_error": is_error,
                })
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": output,
                    **({"is_error": True} if is_error else {}),
                })

            self.session.add_tool_results(tool_results)

        return "[Max iterations reached without a final response]"

    def run_events(
        self, user_input: str | list[dict[str, Any]]
    ) -> Generator[dict[str, Any], None, None]:
        """
        Run one conversational turn as an event stream. Yields:
          {"type": "text_delta", "text": str}    — model text as it streams in
          {"type": "tool_call", "agent": str, "tool": str, "args": dict,
           "result": str (truncated), "is_error": bool}
          {"type": "final", "text": str}          — full text of the final message
          {"type": "max_iterations"}              — loop exhausted without an answer
        """
        self.session.add_user(user_input)

        for _ in range(self.max_iter):
            self._mark_cache_breakpoint()
            with self._client.messages.stream(
                model=self.model,
                max_tokens=self.max_tokens,
                system=self._system_blocks,
                tools=self.registry.api_specs(),
                messages=self.session.messages,
            ) as stream:
                for text in stream.text_stream:
                    yield {"type": "text_delta", "text": text}
                response = stream.get_final_message()

            self.session.track_usage(response.usage)
            self._log_usage(response.usage)
            content_blocks = [self._block_to_dict(block) for block in response.content]
            self.session.add_assistant(content_blocks)

            if response.stop_reason != "tool_use":
                yield {"type": "final", "text": self._extract_text(response.content)}
                return

            tool_blocks = [b for b in response.content if b.type == "tool_use"]
            tool_results = []
            for block, output, is_error in self._execute_tool_blocks(tool_blocks):
                yield {
                    "type": "tool_call",
                    "agent": self.name,
                    "tool": block.name,
                    "args": block.input,
                    "result": output[:500],
                    "is_error": is_error,
                }
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": output,
                    **({"is_error": True} if is_error else {}),
                })

            self.session.add_tool_results(tool_results)

        yield {"type": "max_iterations"}

    @staticmethod
    def _block_to_dict(block: Any) -> dict[str, Any]:
        if block.type == "text":
            return {"type": "text", "text": block.text}
        if block.type == "tool_use":
            return {"type": "tool_use", "id": block.id, "name": block.name, "input": block.input}
        return {"type": block.type}

    @staticmethod
    def _extract_text(content: list[Any]) -> str:
        parts = [block.text for block in content if block.type == "text"]
        return "\n".join(parts) if parts else ""
