"""
AgentRuntime — single-agent agentic loop using the Anthropic API directly.

Adapted from tool_agent.py for use within the backend package.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Callable, Generator


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

    def add_user(self, text: str) -> None:
        self.messages.append({"role": "user", "content": text})

    def add_assistant(self, content: list[dict[str, Any]]) -> None:
        self.messages.append({"role": "assistant", "content": content})

    def add_tool_results(self, results: list[dict[str, Any]]) -> None:
        self.messages.append({"role": "user", "content": results})

    def track_usage(self, usage: Any) -> None:
        self.input_tokens += getattr(usage, "input_tokens", 0)
        self.output_tokens += getattr(usage, "output_tokens", 0)

    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def clear(self) -> None:
        self.messages = []
        self.input_tokens = 0
        self.output_tokens = 0


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
    ) -> None:
        try:
            import anthropic
        except ImportError:
            raise ImportError("Run: pip install anthropic")

        self._client = anthropic.Anthropic(api_key=api_key or os.environ["ANTHROPIC_API_KEY"])
        self.model = model
        self.system = system
        self.max_tokens = max_tokens
        self.max_iter = max_iter

        self.registry = ToolRegistry()
        self.session = Session()

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

    def run(self, user_input: str) -> str:
        """
        Run one conversational turn. May call tools multiple times internally.
        Returns the final text response from the model.
        """
        self.session.add_user(user_input)

        for _ in range(self.max_iter):
            response = self._client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                system=self.system,
                tools=self.registry.api_specs(),
                messages=self.session.messages,
            )

            self.session.track_usage(response.usage)

            content_blocks = [self._block_to_dict(block) for block in response.content]
            self.session.add_assistant(content_blocks)

            if response.stop_reason != "tool_use":
                return self._extract_text(response.content)

            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    output, is_error = self.registry.execute(
                        block.name,
                        json.dumps(block.input),
                    )
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": output,
                        **({"is_error": True} if is_error else {}),
                    })

            self.session.add_tool_results(tool_results)

        return "[Max iterations reached without a final response]"

    def stream(self, user_input: str) -> Generator[str, None, None]:
        """Stream a turn, yielding text chunks as they arrive."""
        self.session.add_user(user_input)

        for _ in range(self.max_iter):
            with self._client.messages.stream(
                model=self.model,
                max_tokens=self.max_tokens,
                system=self.system,
                tools=self.registry.api_specs(),
                messages=self.session.messages,
            ) as stream:
                response = stream.get_final_message()

            self.session.track_usage(response.usage)
            content_blocks = [self._block_to_dict(block) for block in response.content]
            self.session.add_assistant(content_blocks)

            if response.stop_reason != "tool_use":
                for block in response.content:
                    if block.type == "text":
                        yield block.text
                return

            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    output, is_error = self.registry.execute(
                        block.name,
                        json.dumps(block.input),
                    )
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": output,
                        **({"is_error": True} if is_error else {}),
                    })

            self.session.add_tool_results(tool_results)

        yield "[Max iterations reached without a final response]"

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
