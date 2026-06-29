"""Unit tests for create_chart spec validation and the chart SSE event."""

import json
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

backend_path = Path(__file__).parent.parent
sys.path.insert(0, str(backend_path))

import src.api.v1.chat as chat_module
from src.agent.tools.chart_tools import CHART_SUCCESS_PREFIX, create_chart
from src.api.deps import get_db


# ---------------------------------------------------------------------------
# Spec validation
# ---------------------------------------------------------------------------

def test_valid_bar_chart():
    result = create_chart(
        chart_type="bar",
        title="Monthly orders",
        labels=["Jan", "Feb"],
        datasets=[{"label": "Orders", "data": [10, 20]}],
    )
    assert result.startswith(CHART_SUCCESS_PREFIX)


def test_valid_scatter_without_labels():
    result = create_chart(
        chart_type="scatter",
        title="Price vs stock",
        datasets=[{"label": "Products", "data": [{"x": 1, "y": 2}, {"x": 3, "y": 4}]}],
    )
    assert result.startswith(CHART_SUCCESS_PREFIX)


@pytest.mark.parametrize(
    "kwargs,expected_fragment",
    [
        ({"chart_type": "donut", "title": "t", "labels": ["a"], "datasets": [{"label": "d", "data": [1]}]}, "chart_type"),
        ({"chart_type": "bar", "title": " ", "labels": ["a"], "datasets": [{"label": "d", "data": [1]}]}, "title"),
        ({"chart_type": "bar", "title": "t", "labels": [], "datasets": [{"label": "d", "data": [1]}]}, "labels"),
        ({"chart_type": "bar", "title": "t", "labels": ["a"], "datasets": []}, "datasets"),
        ({"chart_type": "bar", "title": "t", "labels": ["a", "b"], "datasets": [{"label": "d", "data": [1]}]}, "must match"),
        ({"chart_type": "bar", "title": "t", "labels": ["a"], "datasets": [{"label": "d", "data": ["x"]}]}, "numbers"),
        ({"chart_type": "pie", "title": "t", "labels": ["a"], "datasets": [{"label": "d", "data": [1]}, {"label": "e", "data": [2]}]}, "pie"),
        ({"chart_type": "scatter", "title": "t", "datasets": [{"label": "d", "data": [1, 2]}]}, "scatter"),
    ],
)
def test_invalid_specs_return_error(kwargs, expected_fragment):
    result = create_chart(**kwargs)
    assert result.startswith("Error:")
    assert expected_fragment.lower() in result.lower()


def test_too_many_datasets_rejected():
    datasets = [{"label": f"d{i}", "data": [1]} for i in range(5)]
    result = create_chart(chart_type="bar", title="t", labels=["a"], datasets=datasets)
    assert result.startswith("Error:")


# ---------------------------------------------------------------------------
# Chart SSE event passes through the stream endpoint
# ---------------------------------------------------------------------------

class StubFramework:
    def __init__(self, chunks):
        self.chunks = chunks

    async def chat(self, **kwargs):
        for chunk in self.chunks:
            yield chunk


def test_chart_event_streams_to_client(monkeypatch):
    spec = {
        "chart_type": "bar",
        "title": "Monthly orders",
        "labels": ["Jan", "Feb"],
        "datasets": [{"label": "Orders", "data": [10, 20]}],
    }
    chunks = [
        {"type": "metadata", "conversation_id": "conv-1"},
        {"type": "tool_call", "tool": "create_chart", "args": spec,
         "result": f"{CHART_SUCCESS_PREFIX}: 'Monthly orders' (bar).", "agent": "orchestrator"},
        {"type": "chart", "spec": spec},
        {"type": "content", "content": "Orders doubled in February."},
        {"type": "done", "conversation_id": "conv-1"},
    ]
    monkeypatch.setattr(chat_module, "agent_framework", StubFramework(chunks))

    app = FastAPI()
    app.include_router(chat_module.router, prefix="/api/chat")

    async def fake_db():
        yield None

    app.dependency_overrides[get_db] = fake_db

    client = TestClient(app)
    response = client.post("/api/chat/stream", json={"message": "plot orders"})
    assert response.status_code == 200

    body = response.text.replace("\r\n", "\n")
    chart_frames = [
        frame for frame in body.strip().split("\n\n") if "event: chart" in frame
    ]
    assert len(chart_frames) == 1
    data_line = next(line for line in chart_frames[0].split("\n") if line.startswith("data:"))
    payload = json.loads(data_line[len("data:"):].strip())
    assert payload["spec"] == spec
