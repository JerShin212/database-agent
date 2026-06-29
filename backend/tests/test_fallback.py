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


# ---------------------------------------------------------------------------
# Model escalation (Haiku -> Sonnet retry)
# ---------------------------------------------------------------------------

MAX_ITER_SENTINEL = "[Max iterations reached without a final response]"


class EscalatedStub(StubAgent):
    def __init__(self, responses, model="claude-sonnet-4-6"):
        super().__init__(responses)
        self.model = model


def _build_orchestrator_with_escalation(database_agent, text_agent, escalated_responses):
    escalated = EscalatedStub(escalated_responses)
    pool = AgentPool()
    pool.register("database_agent", database_agent, escalated_factory=lambda: escalated)
    pool.register("text_search_agent", text_agent)
    orchestrator = OrchestratorAgent(pool=pool, api_key="test-key")
    return orchestrator, escalated


def test_worker_crash_triggers_escalation():
    db_agent = CrashingAgent([])
    text_agent = StubAgent([])
    orchestrator, escalated = _build_orchestrator_with_escalation(
        db_agent, text_agent, ["There are 42 orders."]
    )

    result = orchestrator._delegate_handler("database_agent", "how many orders?")

    assert "[Escalated database_agent to claude-sonnet-4-6]" in result
    assert "There are 42 orders." in result
    assert "[Worker database_agent failed:" in result  # original failure preserved
    assert escalated.calls == ["how many orders?"]


def test_max_iterations_triggers_escalation():
    db_agent = StubAgent([MAX_ITER_SENTINEL])
    text_agent = StubAgent([])
    orchestrator, escalated = _build_orchestrator_with_escalation(
        db_agent, text_agent, ["Done: 7 rows."]
    )

    result = orchestrator._delegate_handler("database_agent", "complex question")

    assert "[Escalated database_agent to claude-sonnet-4-6]" in result
    assert escalated.calls == ["complex question"]


def test_successful_result_does_not_escalate():
    db_agent = StubAgent(["There are 42 orders."])
    text_agent = StubAgent([])
    orchestrator, escalated = _build_orchestrator_with_escalation(db_agent, text_agent, [])

    result = orchestrator._delegate_handler("database_agent", "how many orders?")

    assert result == "There are 42 orders."
    assert escalated.calls == []


def test_no_results_alone_does_not_escalate_when_fallback_succeeds():
    # NO_RESULTS routes to the cross-agent fallback; if that finds the answer,
    # there is nothing to escalate.
    db_agent = StubAgent(["NO_RESULTS: nothing in the database."])
    text_agent = StubAgent(["The warranty is 5 years (manual.pdf)."])
    orchestrator, escalated = _build_orchestrator_with_escalation(db_agent, text_agent, [])

    result = orchestrator._delegate_handler("database_agent", "warranty period?")

    assert "[Automatic fallback to text_search_agent]" in result
    assert escalated.calls == []


def test_double_no_results_escalates_after_fallback():
    db_agent = StubAgent(["NO_RESULTS: nothing found."])
    text_agent = StubAgent(["NO_RESULTS: nothing in documents either."])
    orchestrator, escalated = _build_orchestrator_with_escalation(
        db_agent, text_agent, ["Found it with a smarter query: 3 rows."]
    )

    result = orchestrator._delegate_handler("database_agent", "find x")

    assert "[Automatic fallback to text_search_agent]" in result
    assert "[Escalated database_agent to claude-sonnet-4-6]" in result
    assert "Found it with a smarter query" in result


def test_escalation_is_one_shot_per_agent():
    db_agent = StubAgent([MAX_ITER_SENTINEL, MAX_ITER_SENTINEL])
    text_agent = StubAgent([])
    orchestrator, escalated = _build_orchestrator_with_escalation(
        db_agent, text_agent, ["answer one", "answer two"]
    )

    first = orchestrator._delegate_handler("database_agent", "q1")
    second = orchestrator._delegate_handler("database_agent", "q2")

    assert "[Escalated database_agent" in first
    assert "[Escalated database_agent" not in second
    assert escalated.calls == ["q1"]


def test_no_escalation_registered_keeps_old_behavior():
    db_agent = CrashingAgent([])
    pool = AgentPool()
    pool.register("database_agent", db_agent)
    pool.register("text_search_agent", StubAgent([]))
    orchestrator = OrchestratorAgent(pool=pool, api_key="test-key")

    result = orchestrator._delegate_handler("database_agent", "anything")

    assert result.startswith("[Worker database_agent failed:")
    assert "[Escalated" not in result
