"""Unit tests for the deterministic SQL<->RAG fallback in the orchestrator."""

import sys
from pathlib import Path

backend_path = Path(__file__).parent.parent
sys.path.insert(0, str(backend_path))

from src.agent.orchestrator import AgentPool, OrchestratorAgent


class StubAgent:
    """Duck-typed stand-in for AgentRuntime in the pool."""

    def __init__(self, responses):
        self.system = "stub agent"
        self.responses = list(responses)
        self.calls = []

    def run(self, prompt: str) -> str:
        self.calls.append(prompt)
        return self.responses.pop(0)


class CrashingAgent(StubAgent):
    def run(self, prompt: str) -> str:
        raise RuntimeError("boom")


def _build_orchestrator(database_agent, text_agent):
    pool = AgentPool()
    pool.register("database_agent", database_agent)
    pool.register("text_search_agent", text_agent)
    return OrchestratorAgent(pool=pool, api_key="test-key")


def test_no_results_triggers_fallback_to_alternate_worker():
    db_agent = StubAgent(["NO_RESULTS: no matching rows for warranty period."])
    text_agent = StubAgent(["The warranty period is 5 years (manual.pdf)."])
    orchestrator = _build_orchestrator(db_agent, text_agent)

    result = orchestrator._delegate_handler("database_agent", "what is the warranty period?")

    assert "[Automatic fallback to text_search_agent]" in result
    assert "The warranty period is 5 years" in result
    assert "NO_RESULTS" in result  # original response preserved for synthesis
    assert text_agent.calls == ["what is the warranty period?"]


def test_successful_result_does_not_fall_back():
    db_agent = StubAgent(["There are 42 orders."])
    text_agent = StubAgent([])
    orchestrator = _build_orchestrator(db_agent, text_agent)

    result = orchestrator._delegate_handler("database_agent", "how many orders?")

    assert result == "There are 42 orders."
    assert text_agent.calls == []


def test_fallback_is_one_shot_per_agent():
    db_agent = StubAgent(["NO_RESULTS: first try.", "NO_RESULTS: second try."])
    text_agent = StubAgent(["NO_RESULTS: nothing in documents either."])
    orchestrator = _build_orchestrator(db_agent, text_agent)

    first = orchestrator._delegate_handler("database_agent", "find x")
    second = orchestrator._delegate_handler("database_agent", "find x again")

    assert "[Automatic fallback to text_search_agent]" in first
    # Guard: the second NO_RESULTS from the same agent must not fall back again
    assert second == "NO_RESULTS: second try."
    assert len(text_agent.calls) == 1


def test_fresh_orchestrator_resets_fallback_guard():
    db_agent = StubAgent(["NO_RESULTS: nope."])
    text_agent = StubAgent(["found it."])
    orchestrator = _build_orchestrator(db_agent, text_agent)
    assert orchestrator._fallbacks_used == set()


def test_worker_crash_returns_error_string_not_exception():
    pool = AgentPool()
    pool.register("database_agent", CrashingAgent([]))
    result = pool.run("database_agent", "anything")
    assert result.startswith("[Worker database_agent failed:")
    assert "boom" in result


def test_unknown_agent_returns_pool_error():
    pool = AgentPool()
    assert pool.run("nonexistent", "task").startswith("[AgentPool error]")
