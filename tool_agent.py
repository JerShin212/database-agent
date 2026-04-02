"""
tool_agent.py — Drop-in tool-calling agentic AI for Python projects.

Usage:
    from tool_agent import AgentRuntime, tool

    agent = AgentRuntime(api_key="...", model="claude-opus-4-6")

    @agent.tool(description="Read a file", params={"path": {"type": "string"}})
    def read_file(path: str) -> str:
        with open(path) as f:
            return f.read()

    response = agent.run("What's in README.md?")
    print(response)

Requirements:
    pip install anthropic
"""

from __future__ import annotations

import json
import os
import subprocess
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

    def compact(self, keep_last: int = 10) -> None:
        """Drop old messages to stay within token budget."""
        if len(self.messages) > keep_last:
            self.messages = self.messages[-keep_last:]

    def clear(self) -> None:
        self.messages = []
        self.input_tokens = 0
        self.output_tokens = 0

    def save(self, path: str) -> None:
        with open(path, "w") as f:
            json.dump({
                "messages": self.messages,
                "input_tokens": self.input_tokens,
                "output_tokens": self.output_tokens,
            }, f, indent=2)

    @classmethod
    def load(cls, path: str) -> "Session":
        with open(path) as f:
            data = json.load(f)
        s = cls()
        s.messages = data.get("messages", [])
        s.input_tokens = data.get("input_tokens", 0)
        s.output_tokens = data.get("output_tokens", 0)
        return s


# ---------------------------------------------------------------------------
# Agent runtime — the turn loop
# ---------------------------------------------------------------------------

class AgentRuntime:
    """
    Core agentic loop:
        user input → LLM → tool calls → tool results → LLM → ... → final response

    Args:
        api_key:      Anthropic API key (falls back to ANTHROPIC_API_KEY env var)
        model:        Model ID to use
        system:       System prompt
        max_tokens:   Max tokens per LLM response
        max_iter:     Max tool-call iterations per turn (prevents infinite loops)
        auto_compact: Compact session history when token count exceeds threshold
        compact_at:   Token threshold that triggers compaction
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "claude-opus-4-6",
        system: str = "You are a helpful AI assistant.",
        max_tokens: int = 4096,
        max_iter: int = 10,
        auto_compact: bool = True,
        compact_at: int = 50_000,
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
        self.auto_compact = auto_compact
        self.compact_at = compact_at

        self.registry = ToolRegistry()
        self.session = Session()

        # Register built-in tools by default
        self._register_builtin_tools()

    # ------------------------------------------------------------------
    # Decorator for registering tools
    # ------------------------------------------------------------------

    def tool(
        self,
        description: str,
        params: dict[str, dict[str, Any]] | None = None,
        required: list[str] | None = None,
        name: str | None = None,
    ) -> Callable:
        """
        Decorator to register a function as a tool.

        Example:
            @agent.tool(
                description="Search the web",
                params={"query": {"type": "string", "description": "Search query"}},
                required=["query"],
            )
            def web_search(query: str) -> str:
                ...
        """
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

    # ------------------------------------------------------------------
    # Permission control
    # ------------------------------------------------------------------

    def deny_tools(self, *names: str) -> None:
        """Block specific tools from executing."""
        self.registry.deny(*names)

    def allow_tools(self, *names: str) -> None:
        """Unblock previously denied tools."""
        self.registry.allow(*names)

    # ------------------------------------------------------------------
    # Run a turn (the core loop)
    # ------------------------------------------------------------------

    def run(self, user_input: str) -> str:
        """
        Run one conversational turn. May call tools multiple times internally.
        Returns the final text response from the model.
        """
        self.session.add_user(user_input)

        if self.auto_compact and self.session.total_tokens() > self.compact_at:
            self.session.compact()

        for iteration in range(self.max_iter):
            response = self._client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                system=self.system,
                tools=self.registry.api_specs(),
                messages=self.session.messages,
            )

            self.session.track_usage(response.usage)

            # Serialize assistant message content blocks
            content_blocks = [self._block_to_dict(block) for block in response.content]
            self.session.add_assistant(content_blocks)

            # Done — model produced a final text response
            if response.stop_reason != "tool_use":
                return self._extract_text(response.content)

            # Execute all tool calls and collect results
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
        """
        Stream a turn, yielding text chunks as they arrive.
        Tool calls are executed silently; only final text is streamed.

        Example:
            for chunk in agent.stream("Summarize README.md"):
                print(chunk, end="", flush=True)
        """
        self.session.add_user(user_input)

        for _ in range(self.max_iter):
            with self._client.messages.stream(
                model=self.model,
                max_tokens=self.max_tokens,
                system=self.system,
                tools=self.registry.api_specs(),
                messages=self.session.messages,
            ) as stream:
                # Collect full message for session history
                response = stream.get_final_message()

            self.session.track_usage(response.usage)
            content_blocks = [self._block_to_dict(block) for block in response.content]
            self.session.add_assistant(content_blocks)

            if response.stop_reason != "tool_use":
                # Stream the final text
                for block in response.content:
                    if block.type == "text":
                        yield block.text
                return

            # Execute tools silently
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

    # ------------------------------------------------------------------
    # Built-in tools
    # ------------------------------------------------------------------

    def _register_builtin_tools(self) -> None:
        self.add_tool(
            name="read_file",
            description="Read the contents of a file from the filesystem.",
            handler=self._builtin_read_file,
            params={
                "path": {"type": "string", "description": "Absolute or relative path to the file"},
            },
            required=["path"],
        )
        self.add_tool(
            name="write_file",
            description="Write text content to a file, overwriting if it exists.",
            handler=self._builtin_write_file,
            params={
                "path": {"type": "string", "description": "Path to write"},
                "content": {"type": "string", "description": "Content to write"},
            },
            required=["path", "content"],
        )
        self.add_tool(
            name="bash",
            description="Run a shell command and return its output. Use with caution.",
            handler=self._builtin_bash,
            params={
                "command": {"type": "string", "description": "Shell command to run"},
            },
            required=["command"],
        )
        self.add_tool(
            name="list_directory",
            description="List files and directories at a given path.",
            handler=self._builtin_list_directory,
            params={
                "path": {"type": "string", "description": "Directory path (defaults to current dir)"},
            },
            required=[],
        )

    @staticmethod
    def _builtin_read_file(path: str) -> str:
        return open(path).read()

    @staticmethod
    def _builtin_write_file(path: str, content: str) -> str:
        with open(path, "w") as f:
            f.write(content)
        return f"Written {len(content)} chars to {path}"

    @staticmethod
    def _builtin_bash(command: str) -> str:
        result = subprocess.run(
            command, shell=True, capture_output=True, text=True, timeout=30
        )
        out = result.stdout + result.stderr
        return out.strip() or "(no output)"

    @staticmethod
    def _builtin_list_directory(path: str = ".") -> str:
        import os
        entries = os.listdir(path)
        return "\n".join(sorted(entries))

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Example usage (run this file directly to try it out)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent = AgentRuntime(
        system="You are a helpful coding assistant. Use tools when needed.",
    )

    # Deny the bash tool for safety in this example
    agent.deny_tools("bash")

    # Add a custom tool
    @agent.tool(
        description="Get the current date and time",
        params={},
    )
    def get_datetime() -> str:
        from datetime import datetime
        return datetime.now().isoformat()

    print("Tools registered:", agent.registry.names())
    print()

    # Single-turn example
    response = agent.run("List the files in the current directory.")
    print("Response:", response)
    print()
    print(f"Tokens used: {agent.session.total_tokens()}")
