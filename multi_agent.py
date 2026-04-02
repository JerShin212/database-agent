"""
multi_agent.py — Multi-agent patterns built on top of tool_agent.py

Three patterns included:

  1. OrchestratorAgent  — one "boss" agent delegates tasks to specialist workers
  2. Pipeline           — agents run in sequence, each receives the previous output
  3. ParallelSwarm      — all agents run the same prompt concurrently, results merged

Usage:
    from multi_agent import OrchestratorAgent, Pipeline, ParallelSwarm
    from tool_agent import AgentRuntime

Requirements:
    pip install anthropic
"""

from __future__ import annotations

import concurrent.futures
import json
from dataclasses import dataclass, field
from typing import Any, Callable

from tool_agent import AgentRuntime, Session


# ---------------------------------------------------------------------------
# AgentPool — shared registry of named agents
# ---------------------------------------------------------------------------

class AgentPool:
    """
    Registry that maps agent names to AgentRuntime instances.
    Agents can be looked up by name and invoked by any orchestrator.

    Example:
        pool = AgentPool()
        pool.register("researcher", AgentRuntime(system="You research topics."))
        pool.register("writer",     AgentRuntime(system="You write reports."))
        result = pool.run("researcher", "Find info on black holes")
    """

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
        return agent.run(prompt)

    def describe(self) -> str:
        lines = []
        for name, agent in self._agents.items():
            lines.append(f"- {name}: {agent.system[:80]}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Pattern 1: OrchestratorAgent
# ---------------------------------------------------------------------------
# The orchestrator has one special tool — `delegate` — that lets it call
# any worker agent by name. The orchestrator decides *which* worker to use
# and *what* to ask them. Workers are independent AgentRuntime instances
# with their own tools, system prompts, and sessions.
#
# Flow:
#   user → orchestrator → delegate("researcher", "...") → worker runs → result
#                       → delegate("writer", "...") → worker runs → result
#                       → final answer assembled by orchestrator
# ---------------------------------------------------------------------------

class OrchestratorAgent:
    """
    A "boss" agent that delegates sub-tasks to specialist workers.

    The orchestrator is itself an AgentRuntime. It is given a `delegate`
    tool at construction time — pointing to the AgentPool — so it can call
    any worker transparently.

    Example:
        pool = AgentPool()
        pool.register("coder",    AgentRuntime(system="You write Python code."))
        pool.register("reviewer", AgentRuntime(system="You review code for bugs."))

        orch = OrchestratorAgent(
            pool=pool,
            system="You are a senior engineer. Break tasks down and delegate.",
        )
        result = orch.run("Write and review a function that checks if a number is prime.")
        print(result)
    """

    def __init__(
        self,
        pool: AgentPool,
        system: str | None = None,
        api_key: str | None = None,
        model: str = "claude-opus-4-6",
        max_tokens: int = 4096,
        max_iter: int = 20,
    ) -> None:
        self.pool = pool

        worker_list = pool.describe()
        default_system = (
            "You are an orchestrator agent. You break down complex tasks and delegate "
            "them to specialist worker agents using the `delegate` tool. "
            "Always delegate — never try to do a specialist's job yourself.\n\n"
            f"Available workers:\n{worker_list}"
        )

        self.agent = AgentRuntime(
            api_key=api_key,
            model=model,
            system=system or default_system,
            max_tokens=max_tokens,
            max_iter=max_iter,
        )

        # Remove built-in tools from the orchestrator — it should only delegate
        self.agent.registry._tools.clear()

        # Register the delegate tool
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
        return self.pool.run(agent, task)

    def run(self, user_input: str) -> str:
        return self.agent.run(user_input)

    def stream(self, user_input: str):
        yield from self.agent.stream(user_input)

    def add_tool(self, *args, **kwargs) -> None:
        """Add extra tools to the orchestrator (e.g. a web search tool)."""
        self.agent.add_tool(*args, **kwargs)


# ---------------------------------------------------------------------------
# Pattern 2: Pipeline
# ---------------------------------------------------------------------------
# Agents are chained: output of agent[0] becomes input of agent[1], and so on.
# Each agent can transform, enrich, summarize, or validate the data.
#
# Flow:
#   user_input → agent[0] → output[0] → agent[1] → output[1] → ... → final
# ---------------------------------------------------------------------------

@dataclass
class PipelineStep:
    name: str
    agent: AgentRuntime
    prompt_template: str = "{input}"  # Use {input} to inject previous output

    def build_prompt(self, previous_output: str) -> str:
        return self.prompt_template.format(input=previous_output)


class Pipeline:
    """
    Chain agents sequentially — output of each step feeds into the next.

    Each step can have a prompt_template that wraps the previous output.
    Use `{input}` in the template to inject it.

    Example:
        pipeline = Pipeline()
        pipeline.add_step(
            name="researcher",
            agent=AgentRuntime(system="You are a researcher."),
            prompt_template="Research this topic thoroughly: {input}",
        )
        pipeline.add_step(
            name="summarizer",
            agent=AgentRuntime(system="You write concise summaries."),
            prompt_template="Summarize the following research into 3 bullet points: {input}",
        )
        pipeline.add_step(
            name="formatter",
            agent=AgentRuntime(system="You format text as markdown."),
            prompt_template="Format this as a clean markdown document: {input}",
        )
        result = pipeline.run("Quantum computing")
        print(result.final_output)
    """

    def __init__(self) -> None:
        self.steps: list[PipelineStep] = []

    def add_step(
        self,
        name: str,
        agent: AgentRuntime,
        prompt_template: str = "{input}",
    ) -> "Pipeline":
        """Add a step. Returns self for chaining."""
        self.steps.append(PipelineStep(name=name, agent=agent, prompt_template=prompt_template))
        return self

    def run(self, initial_input: str, verbose: bool = False) -> "PipelineResult":
        """Run all steps in sequence. Returns a PipelineResult with all outputs."""
        outputs: dict[str, str] = {}
        current = initial_input

        for step in self.steps:
            prompt = step.build_prompt(current)
            if verbose:
                print(f"[Pipeline] Running step '{step.name}'...")
            output = step.agent.run(prompt)
            outputs[step.name] = output
            current = output

        return PipelineResult(
            initial_input=initial_input,
            step_outputs=outputs,
            final_output=current,
        )


@dataclass
class PipelineResult:
    initial_input: str
    step_outputs: dict[str, str]
    final_output: str

    def get_step(self, name: str) -> str | None:
        return self.step_outputs.get(name)

    def __str__(self) -> str:
        return self.final_output


# ---------------------------------------------------------------------------
# Pattern 3: ParallelSwarm
# ---------------------------------------------------------------------------
# All agents run the same prompt at the same time (via threads).
# A merge function (or a "judge" agent) combines their outputs.
#
# Use cases:
#   - Get multiple perspectives on the same question
#   - Run specialist agents in parallel, then synthesize
#   - Majority vote / best-of-N selection
#
# Flow:
#   user_input ──┬──→ agent[0] → output[0] ──┐
#                ├──→ agent[1] → output[1] ──┤→ merge → final
#                └──→ agent[2] → output[2] ──┘
# ---------------------------------------------------------------------------

@dataclass
class SwarmResult:
    prompt: str
    agent_outputs: dict[str, str]  # {agent_name: output}
    merged_output: str

    def __str__(self) -> str:
        return self.merged_output


class ParallelSwarm:
    """
    Run all registered agents on the same prompt simultaneously (via threads),
    then merge their outputs with a merge function or a judge agent.

    Example:
        swarm = ParallelSwarm()
        swarm.add("optimist",  AgentRuntime(system="You see the best in everything."))
        swarm.add("pessimist", AgentRuntime(system="You identify risks and downsides."))
        swarm.add("realist",   AgentRuntime(system="You give balanced, practical views."))

        result = swarm.run("Should I switch careers to AI?")
        print(result.merged_output)
    """

    def __init__(
        self,
        merge_fn: Callable[[dict[str, str]], str] | None = None,
        judge: AgentRuntime | None = None,
        max_workers: int = 5,
    ) -> None:
        """
        Args:
            merge_fn:    Custom function that takes {agent_name: output} → merged string.
                         If None and no judge is provided, outputs are concatenated.
            judge:       An AgentRuntime that receives all outputs and produces the final answer.
                         Takes priority over merge_fn if both are given.
            max_workers: Max parallel threads.
        """
        self._agents: dict[str, AgentRuntime] = {}
        self.merge_fn = merge_fn
        self.judge = judge
        self.max_workers = max_workers

    def add(self, name: str, agent: AgentRuntime) -> "ParallelSwarm":
        """Add an agent. Returns self for chaining."""
        self._agents[name] = agent
        return self

    def run(self, prompt: str, verbose: bool = False) -> SwarmResult:
        """Run all agents in parallel and merge results."""
        if not self._agents:
            raise ValueError("No agents registered in the swarm.")

        outputs: dict[str, str] = {}

        with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {
                executor.submit(agent.run, prompt): name
                for name, agent in self._agents.items()
            }
            for future in concurrent.futures.as_completed(futures):
                name = futures[future]
                try:
                    outputs[name] = future.result()
                except Exception as exc:
                    outputs[name] = f"[Agent error] {exc}"
                if verbose:
                    print(f"[Swarm] Agent '{name}' finished.")

        merged = self._merge(prompt, outputs)
        return SwarmResult(prompt=prompt, agent_outputs=outputs, merged_output=merged)

    def _merge(self, prompt: str, outputs: dict[str, str]) -> str:
        # Judge agent takes priority
        if self.judge is not None:
            combined = "\n\n".join(
                f"### {name}\n{output}" for name, output in outputs.items()
            )
            judge_prompt = (
                f"Original question: {prompt}\n\n"
                f"The following agents each answered independently:\n\n{combined}\n\n"
                "Synthesize their answers into one clear, final response."
            )
            return self.judge.run(judge_prompt)

        # Custom merge function
        if self.merge_fn is not None:
            return self.merge_fn(outputs)

        # Default: concatenate with labels
        parts = [f"### {name}\n{output}" for name, output in outputs.items()]
        return "\n\n---\n\n".join(parts)


# ---------------------------------------------------------------------------
# Bonus: HandoffChain — agents pass context + decide who goes next
# ---------------------------------------------------------------------------
# This is a dynamic pipeline where each agent can decide to hand off
# to another agent (or stop). Useful for routing workflows.
#
# Flow:
#   user → agent_A → decides to hand off to agent_B with context
#                  → agent_B → decides to stop → final answer
# ---------------------------------------------------------------------------

@dataclass
class HandoffResult:
    final_output: str
    trace: list[dict[str, str]]  # [{"agent": name, "output": text}, ...]


class HandoffChain:
    """
    Dynamic routing: each agent can hand off to another agent by returning
    a special JSON payload. If it returns plain text, the chain stops.

    Each agent's system prompt should include instructions like:
        "If you need to hand off to another agent, respond ONLY with:
         {"handoff": "<agent_name>", "context": "<what to pass on>"}
         Otherwise, respond with your final answer normally."

    Example:
        chain = HandoffChain()
        chain.register("triage",   triage_agent)
        chain.register("billing",  billing_agent)
        chain.register("support",  support_agent)

        result = chain.run("triage", "I was charged twice for my subscription.")
        print(result.final_output)
    """

    HANDOFF_INSTRUCTIONS = (
        "\n\nIMPORTANT: If this task requires a specialist, hand off by responding "
        "with ONLY this JSON (no other text):\n"
        '{"handoff": "<agent_name>", "context": "<full context to pass>"}\n'
        "Otherwise, answer directly."
    )

    def __init__(self, max_hops: int = 5) -> None:
        self._agents: dict[str, AgentRuntime] = {}
        self.max_hops = max_hops

    def register(self, name: str, agent: AgentRuntime) -> "HandoffChain":
        # Append handoff instructions to each agent's system prompt
        agent.system = agent.system + self.HANDOFF_INSTRUCTIONS
        self._agents[name] = agent
        return self

    def run(self, start_agent: str, user_input: str) -> HandoffResult:
        trace: list[dict[str, str]] = []
        current_agent = start_agent
        current_input = user_input

        for hop in range(self.max_hops):
            agent = self._agents.get(current_agent)
            if agent is None:
                output = f"[HandoffChain error] No agent named '{current_agent}'."
                trace.append({"agent": current_agent, "output": output})
                return HandoffResult(final_output=output, trace=trace)

            output = agent.run(current_input)
            trace.append({"agent": current_agent, "output": output})

            # Check if the agent wants to hand off
            handoff = self._parse_handoff(output)
            if handoff is None:
                # Final answer
                return HandoffResult(final_output=output, trace=trace)

            next_agent, context = handoff
            if next_agent not in self._agents:
                final = (
                    f"[HandoffChain error] Agent '{current_agent}' tried to hand off "
                    f"to unknown agent '{next_agent}'."
                )
                trace.append({"agent": current_agent, "output": final})
                return HandoffResult(final_output=final, trace=trace)

            current_agent = next_agent
            current_input = context

        final = f"[HandoffChain] Max hops ({self.max_hops}) reached."
        trace.append({"agent": current_agent, "output": final})
        return HandoffResult(final_output=final, trace=trace)

    @staticmethod
    def _parse_handoff(output: str) -> tuple[str, str] | None:
        """Returns (agent_name, context) if output is a handoff, else None."""
        stripped = output.strip()
        if not stripped.startswith("{"):
            return None
        try:
            data = json.loads(stripped)
            if "handoff" in data and "context" in data:
                return data["handoff"], data["context"]
        except json.JSONDecodeError:
            pass
        return None


# ---------------------------------------------------------------------------
# Example usage (run this file directly)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import os

    api_key = os.environ.get("ANTHROPIC_API_KEY")

    # --- Pattern 1: Orchestrator + Workers ---
    print("=" * 60)
    print("PATTERN 1: Orchestrator + Workers")
    print("=" * 60)

    pool = AgentPool()
    pool.register(
        "researcher",
        AgentRuntime(
            api_key=api_key,
            model="claude-haiku-4-5-20251001",
            system="You are a research assistant. Provide factual, concise summaries.",
        ),
    )
    pool.register(
        "writer",
        AgentRuntime(
            api_key=api_key,
            model="claude-haiku-4-5-20251001",
            system="You are a technical writer. Turn research into clear, readable prose.",
        ),
    )

    orch = OrchestratorAgent(
        pool=pool,
        api_key=api_key,
        model="claude-haiku-4-5-20251001",
    )
    result = orch.run("Write a short explainer on how LLMs work.")
    print(result)

    # --- Pattern 2: Pipeline ---
    print("\n" + "=" * 60)
    print("PATTERN 2: Pipeline")
    print("=" * 60)

    pipeline = Pipeline()
    pipeline.add_step(
        "researcher",
        AgentRuntime(
            api_key=api_key,
            model="claude-haiku-4-5-20251001",
            system="You research topics and provide detailed notes.",
        ),
        prompt_template="Research this topic: {input}",
    )
    pipeline.add_step(
        "summarizer",
        AgentRuntime(
            api_key=api_key,
            model="claude-haiku-4-5-20251001",
            system="You write concise bullet-point summaries.",
        ),
        prompt_template="Summarize this into 3 bullet points:\n{input}",
    )

    pr = pipeline.run("transformer architecture in machine learning", verbose=True)
    print("Final:", pr.final_output)

    # --- Pattern 3: Parallel Swarm ---
    print("\n" + "=" * 60)
    print("PATTERN 3: Parallel Swarm")
    print("=" * 60)

    judge = AgentRuntime(
        api_key=api_key,
        model="claude-haiku-4-5-20251001",
        system="You synthesize multiple perspectives into one balanced answer.",
    )
    swarm = ParallelSwarm(judge=judge)
    swarm.add(
        "optimist",
        AgentRuntime(
            api_key=api_key,
            model="claude-haiku-4-5-20251001",
            system="You focus on opportunities and positive outcomes.",
        ),
    )
    swarm.add(
        "skeptic",
        AgentRuntime(
            api_key=api_key,
            model="claude-haiku-4-5-20251001",
            system="You identify risks and challenge assumptions.",
        ),
    )

    sr = swarm.run("Is AI going to replace most software engineers?", verbose=True)
    print("Merged:", sr.merged_output)
