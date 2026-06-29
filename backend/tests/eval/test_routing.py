"""Routing-accuracy eval: does the orchestrator delegate to the right worker?

Only the orchestrator (Sonnet) hits the API — workers are recording stubs that
return canned, plausible answers. This isolates routing quality from tool quality.
"""

import sys
from pathlib import Path

import pytest

backend_path = Path(__file__).parent.parent.parent
sys.path.insert(0, str(backend_path))

from src.agent.orchestrator import AgentPool, OrchestratorAgent
from src.agent.prompts import ORCHESTRATOR_SYSTEM_PROMPT

from .conftest import get_api_key

pytestmark = pytest.mark.eval

# (question, set of workers that MUST be called, allow_extra_workers)
ROUTING_CASES = [
    ("How many orders were placed last month?", {"database_agent"}, False),
    ("List the top 5 customers by total spending.", {"database_agent"}, False),
    ("What is the average order value?", {"database_agent"}, False),
    ("How many products are currently out of stock?", {"database_agent"}, False),
    ("What is the warranty period mentioned in the manual?", {"text_search_agent"}, True),
    ("Summarize the installation requirements from the installation guide.", {"text_search_agent"}, True),
    ("What does the maintenance policy say about quarterly inspections?", {"text_search_agent"}, True),
    ("According to the specification document, what materials are required?", {"text_search_agent"}, True),
    ("Show me the wiring diagram for the outdoor unit.", {"visual_search_agent"}, True),
    ("Find the page with the refrigerant piping flowchart.", {"visual_search_agent"}, True),
    ("Which figure shows the overall system architecture?", {"visual_search_agent"}, True),
    (
        "Compare last quarter's sales numbers with the targets described in the strategy report.",
        {"database_agent", "text_search_agent"},
        True,
    ),
]

_CANNED_ANSWERS = {
    "database_agent": (
        "Query executed. Result: 42 rows matched; top value is 'Janet Lee' with total 6,120.00."
    ),
    "text_search_agent": (
        "According to manual.pdf: the requested information is covered in section 3 — "
        "the warranty period is 5 years and quarterly inspections are mandatory."
    ),
    "visual_search_agent": (
        "Found matching pages: manual.pdf page 12 (wiring diagram), spec.pdf page 4 (flowchart)."
    ),
}


class RecordingStubWorker:
    def __init__(self, name: str, description: str):
        self.name = name
        self.system = description
        self.calls: list[str] = []

    def run(self, prompt: str) -> str:
        self.calls.append(prompt)
        return _CANNED_ANSWERS[self.name]


def _build_orchestrator():
    workers = {
        "database_agent": RecordingStubWorker(
            "database_agent", "SQL queries, schema exploration, structured data analysis"
        ),
        "text_search_agent": RecordingStubWorker(
            "text_search_agent", "full-text and semantic search over uploaded documents"
        ),
        "visual_search_agent": RecordingStubWorker(
            "visual_search_agent", "visual search over PDF pages (diagrams, figures, charts)"
        ),
    }
    pool = AgentPool()
    for name, worker in workers.items():
        pool.register(name, worker)
    orchestrator = OrchestratorAgent(
        pool=pool,
        system=ORCHESTRATOR_SYSTEM_PROMPT,
        api_key=get_api_key(),
        model="claude-sonnet-4-6",
        max_tokens=4096,
        max_iter=8,
    )
    return orchestrator, workers


def test_routing_accuracy():
    passed = 0
    failures = []

    for question, expected, allow_extra in ROUTING_CASES:
        orchestrator, workers = _build_orchestrator()
        orchestrator.run(question)
        called = {name for name, w in workers.items() if w.calls}

        ok = expected.issubset(called) and (allow_extra or called == expected)
        if ok:
            passed += 1
        else:
            failures.append(f"  {question!r}: expected {sorted(expected)}, called {sorted(called)}")
        print(f"[routing] {'PASS' if ok else 'FAIL'} expected={sorted(expected)} called={sorted(called)} :: {question}")

    score = passed / len(ROUTING_CASES)
    print(f"\n[routing] SCORE: {passed}/{len(ROUTING_CASES)} = {score:.0%}")
    assert score >= 0.8, "Routing accuracy below 80%:\n" + "\n".join(failures)
