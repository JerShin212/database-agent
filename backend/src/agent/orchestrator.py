"""
OrchestratorAgent and AgentPool — multi-agent delegation pattern.

Adapted from multi_agent.py for use within the backend package.
Only AgentPool and OrchestratorAgent are included; Pipeline, ParallelSwarm,
and HandoffChain are omitted as they are not used in this project.
"""

from __future__ import annotations

from typing import Any, Generator

from src.agent.agent_runtime import AgentRuntime


# ---------------------------------------------------------------------------
# AgentPool — shared registry of named worker agents
# ---------------------------------------------------------------------------

class AgentPool:
    """Registry that maps agent names to AgentRuntime instances."""

    def __init__(self) -> None:
        self._agents: dict[str, AgentRuntime] = {}

    def register(self, name: str, agent: AgentRuntime) -> None:
        self._agents[name] = agent

    def get(self, name: str) -> AgentRuntime | None:
        return self._agents.get(name)

    def names(self) -> list[str]:
        return list(self._agents.keys())

    def run(self, name: str, prompt: str) -> str:
        agent = self._agents.get(name)
        if agent is None:
            return f"[AgentPool error] No agent named '{name}'. Available: {self.names()}"
        try:
            return agent.run(prompt)
        except Exception as exc:
            # A crashed worker must not kill the orchestrator's turn
            return f"[Worker {name} failed: {exc}]"

    def describe(self) -> str:
        lines = []
        for name, agent in self._agents.items():
            lines.append(f"- {name}: {agent.system[:80]}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# OrchestratorAgent
# ---------------------------------------------------------------------------

# When a worker reports NO_RESULTS, automatically retry the task with this
# alternate worker (deterministic SQL <-> RAG fallback).
_FALLBACK_AGENT = {
    "database_agent": "text_search_agent",
    "text_search_agent": "database_agent",
    "visual_search_agent": "text_search_agent",
}

# Worker responses starting with this token signal "nothing found"
NO_RESULTS_TOKEN = "NO_RESULTS"


class OrchestratorAgent:
    """
    A coordinator agent that delegates sub-tasks to specialist workers.

    The orchestrator's only tool is `delegate(agent, task)` which routes
    to any registered worker in the pool. It never executes tasks itself.

    If a worker's response starts with NO_RESULTS, the delegate handler
    automatically retries the task with the alternate worker (SQL <-> RAG
    fallback) and returns both labeled responses for synthesis. Each agent
    falls back at most once per orchestrator instance (one per request).
    """

    def __init__(
        self,
        pool: AgentPool,
        system: str | None = None,
        api_key: str | None = None,
        model: str = "claude-sonnet-4-6",
        max_tokens: int = 4096,
        max_iter: int = 20,
    ) -> None:
        self.pool = pool
        self._fallbacks_used: set[str] = set()

        worker_list = pool.describe()
        default_system = (
            "You are an orchestrator agent. Break down tasks and delegate "
            "them to specialist worker agents using the `delegate` tool.\n\n"
            f"Available workers:\n{worker_list}"
        )

        self.agent = AgentRuntime(
            api_key=api_key,
            model=model,
            system=system or default_system,
            max_tokens=max_tokens,
            max_iter=max_iter,
            name="orchestrator",
        )

        # Orchestrator only gets the delegate tool — remove everything else
        self.agent.registry._tools.clear()

        self.agent.add_tool(
            name="delegate",
            description=(
                "Send a task to a specialist worker agent and get back its response. "
                f"Available agents: {pool.names()}"
            ),
            handler=self._delegate_handler,
            params={
                "agent": {
                    "type": "string",
                    "description": f"Name of the worker agent. One of: {pool.names()}",
                },
                "task": {
                    "type": "string",
                    "description": "The full task description to send to the worker.",
                },
            },
            required=["agent", "task"],
        )

    def _delegate_handler(self, agent: str, task: str) -> str:
        result = self.pool.run(agent, task)

        alternate = _FALLBACK_AGENT.get(agent)
        if (
            alternate
            and result.lstrip().startswith(NO_RESULTS_TOKEN)
            and agent not in self._fallbacks_used
        ):
            self._fallbacks_used.add(agent)
            alternate_result = self.pool.run(alternate, task)
            return (
                f"[{agent}] {result}\n\n"
                f"[Automatic fallback to {alternate}]\n"
                f"[{alternate}] {alternate_result}"
            )

        return result

    def run(self, user_input: str | list[dict[str, Any]]) -> str:
        return self.agent.run(user_input)

    def run_events(
        self, user_input: str | list[dict[str, Any]]
    ) -> Generator[dict[str, Any], None, None]:
        """Event-stream variant of run() — see AgentRuntime.run_events."""
        yield from self.agent.run_events(user_input)

    def add_tool(self, *args: Any, **kwargs: Any) -> None:
        """Add extra tools to the orchestrator beyond `delegate`."""
        self.agent.add_tool(*args, **kwargs)
