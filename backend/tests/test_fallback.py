"""Unit tests for the deterministic SQL<->RAG fallback + Haiku->Sonnet escalation,
now implemented by the async Delegator (src/agent/sdk/orchestrator.py).

run_worker is monkeypatched with a fake so these tests exercise the routing logic
without spawning the CLI / hitting the API.
"""

import asyncio
import sys
from pathlib import Path

backend_path = Path(__file__).parent.parent
sys.path.insert(0, str(backend_path))

import src.agent.sdk.orchestrator as orch
from src.agent.sdk.orchestrator import Delegator, ESCALATION_MODEL
from src.agent.sdk.descriptor import Descriptor

MAX_ITER_SENTINEL = "[Max iterations reached without a final response]"


class FakeWorkers:
    """Drives Delegator: per-agent queues for normal runs and escalated (model set) runs."""

    def __init__(self, normal=None, escalated=None):
        self.normal = {k: list(v) for k, v in (normal or {}).items()}
        self.escalated = {k: list(v) for k, v in (escalated or {}).items()}
        self.calls = []  # (name, task, model)

    async def run_worker(self, name, task, descriptor, emit, *, model=None):
        self.calls.append((name, task, model))
        if model is not None:
            return self.escalated.get(name, []).pop(0)
        return self.normal[name].pop(0)

    def normal_calls(self, name):
        return [task for (n, task, model) in self.calls if n == name and model is None]

    def escalated_calls(self, name):
        return [task for (n, task, model) in self.calls if n == name and model is not None]


def _delegate(fakes, monkeypatch, agent, task):
    monkeypatch.setattr(orch, "run_worker", fakes.run_worker)
    return asyncio.run(Delegator(Descriptor(), lambda e: None).delegate(agent, task))


# --- cross-agent fallback ----------------------------------------------------

def test_no_results_triggers_fallback_to_alternate_worker(monkeypatch):
    fakes = FakeWorkers(normal={
        "database_agent": ["NO_RESULTS: no matching rows for warranty period."],
        "text_search_agent": ["The warranty period is 5 years (manual.pdf)."],
    })
    result = _delegate(fakes, monkeypatch, "database_agent", "what is the warranty period?")
    assert "[Automatic fallback to text_search_agent]" in result
    assert "The warranty period is 5 years" in result
    assert "NO_RESULTS" in result  # original preserved for synthesis
    assert fakes.normal_calls("text_search_agent") == ["what is the warranty period?"]


def test_successful_result_does_not_fall_back(monkeypatch):
    fakes = FakeWorkers(normal={"database_agent": ["There are 42 orders."]})
    result = _delegate(fakes, monkeypatch, "database_agent", "how many orders?")
    assert result == "There are 42 orders."
    assert fakes.normal_calls("text_search_agent") == []


def test_fallback_is_one_shot_per_agent(monkeypatch):
    # Every worker can escalate (as in production), so the first call's double
    # NO_RESULTS also escalates once — give it an escalated response. The second
    # call must NOT fall back again (one-shot) and so returns its plain result.
    fakes = FakeWorkers(
        normal={
            "database_agent": ["NO_RESULTS: first try.", "NO_RESULTS: second try."],
            "text_search_agent": ["NO_RESULTS: nothing in documents either."],
        },
        escalated={"database_agent": ["NO_RESULTS: escalated nothing either."]},
    )
    monkeypatch.setattr(orch, "run_worker", fakes.run_worker)
    delegator = Delegator(Descriptor(), lambda e: None)
    first = asyncio.run(delegator.delegate("database_agent", "find x"))
    second = asyncio.run(delegator.delegate("database_agent", "find x again"))
    assert "[Automatic fallback to text_search_agent]" in first
    assert second == "NO_RESULTS: second try."  # no second fallback
    assert len(fakes.normal_calls("text_search_agent")) == 1


# --- model escalation --------------------------------------------------------

def test_worker_crash_triggers_escalation(monkeypatch):
    fakes = FakeWorkers(
        normal={"database_agent": ["[Worker database_agent failed: boom]"]},
        escalated={"database_agent": ["There are 42 orders."]},
    )
    result = _delegate(fakes, monkeypatch, "database_agent", "how many orders?")
    assert f"[Escalated database_agent to {ESCALATION_MODEL}]" in result
    assert "There are 42 orders." in result
    assert "[Worker database_agent failed:" in result  # original failure preserved
    assert fakes.escalated_calls("database_agent") == ["how many orders?"]


def test_max_iterations_triggers_escalation(monkeypatch):
    fakes = FakeWorkers(
        normal={"database_agent": [MAX_ITER_SENTINEL]},
        escalated={"database_agent": ["Done: 7 rows."]},
    )
    result = _delegate(fakes, monkeypatch, "database_agent", "complex question")
    assert f"[Escalated database_agent to {ESCALATION_MODEL}]" in result
    assert fakes.escalated_calls("database_agent") == ["complex question"]


def test_successful_result_does_not_escalate(monkeypatch):
    fakes = FakeWorkers(normal={"database_agent": ["There are 42 orders."]})
    result = _delegate(fakes, monkeypatch, "database_agent", "how many orders?")
    assert result == "There are 42 orders."
    assert fakes.escalated_calls("database_agent") == []


def test_no_results_alone_does_not_escalate_when_fallback_succeeds(monkeypatch):
    fakes = FakeWorkers(normal={
        "database_agent": ["NO_RESULTS: nothing in the database."],
        "text_search_agent": ["The warranty is 5 years (manual.pdf)."],
    })
    result = _delegate(fakes, monkeypatch, "database_agent", "warranty period?")
    assert "[Automatic fallback to text_search_agent]" in result
    assert fakes.escalated_calls("database_agent") == []


def test_double_no_results_escalates_after_fallback(monkeypatch):
    fakes = FakeWorkers(
        normal={
            "database_agent": ["NO_RESULTS: nothing found."],
            "text_search_agent": ["NO_RESULTS: nothing in documents either."],
        },
        escalated={"database_agent": ["Found it with a smarter query: 3 rows."]},
    )
    result = _delegate(fakes, monkeypatch, "database_agent", "find x")
    assert "[Automatic fallback to text_search_agent]" in result
    assert f"[Escalated database_agent to {ESCALATION_MODEL}]" in result
    assert "Found it with a smarter query" in result


def test_escalation_is_one_shot_per_agent(monkeypatch):
    fakes = FakeWorkers(
        normal={"database_agent": [MAX_ITER_SENTINEL, MAX_ITER_SENTINEL]},
        escalated={"database_agent": ["answer one", "answer two"]},
    )
    monkeypatch.setattr(orch, "run_worker", fakes.run_worker)
    delegator = Delegator(Descriptor(), lambda e: None)
    first = asyncio.run(delegator.delegate("database_agent", "q1"))
    second = asyncio.run(delegator.delegate("database_agent", "q2"))
    assert "[Escalated database_agent" in first
    assert "[Escalated database_agent" not in second
    assert fakes.escalated_calls("database_agent") == ["q1"]
