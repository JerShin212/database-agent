"""Tests for the SSE chat streaming endpoint (stubbed agent framework)."""

import json
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

backend_path = Path(__file__).parent.parent
sys.path.insert(0, str(backend_path))

import src.api.v1.chat as chat_module
from src.api.deps import get_db


class StubFramework:
    """Yields a fixed event sequence in the framework's chunk format."""

    def __init__(self, chunks):
        self.chunks = chunks

    async def chat(self, **kwargs):
        for chunk in self.chunks:
            yield chunk


@pytest.fixture
def app(monkeypatch):
    chunks = [
        {"type": "metadata", "conversation_id": "conv-1"},
        {"type": "tool_call", "tool": "execute_sql_query", "args": {"sql": "SELECT 1"},
         "result": "1 row", "agent": "database_agent"},
        {"type": "content", "content": "There is "},
        {"type": "content", "content": "1 row."},
        {"type": "done", "conversation_id": "conv-1"},
    ]
    monkeypatch.setattr(chat_module, "agent_framework", StubFramework(chunks))

    app = FastAPI()
    app.include_router(chat_module.router, prefix="/api/chat")

    async def fake_db():
        yield None

    app.dependency_overrides[get_db] = fake_db
    return app


def _parse_sse(body: str) -> list[tuple[str, dict]]:
    events = []
    # sse-starlette emits \r\n line endings — normalize before splitting frames
    body = body.replace("\r\n", "\n")
    for frame in body.strip().split("\n\n"):
        event_name = None
        data_lines = []
        for line in frame.split("\n"):
            if line.startswith("event:"):
                event_name = line[len("event:"):].strip()
            elif line.startswith("data:"):
                data_lines.append(line[len("data:"):].strip())
        if data_lines:
            events.append((event_name, json.loads("".join(data_lines))))
    return events


def test_stream_endpoint_emits_all_chunks_in_order(app):
    client = TestClient(app)
    response = client.post("/api/chat/stream", json={"message": "how many rows?"})

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")

    events = _parse_sse(response.text)
    types = [name for name, _ in events]
    assert types == ["metadata", "tool_call", "content", "content", "done"]

    metadata = events[0][1]
    assert metadata["conversation_id"] == "conv-1"

    tool_call = events[1][1]
    assert tool_call["tool"] == "execute_sql_query"
    assert tool_call["agent"] == "database_agent"

    contents = [data["content"] for name, data in events if name == "content"]
    assert "".join(contents) == "There is 1 row."


def test_stream_endpoint_accepts_image_attachment(app):
    client = TestClient(app)
    response = client.post(
        "/api/chat/stream",
        json={
            "message": "what is this?",
            "image": {"data": "aGVsbG8=", "media_type": "image/jpeg"},
        },
    )
    assert response.status_code == 200


def test_blocking_endpoint_accumulates_chunks(app):
    client = TestClient(app)
    response = client.post("/api/chat/", json={"message": "how many rows?"})

    assert response.status_code == 200
    body = response.json()
    assert body["conversation_id"] == "conv-1"
    assert body["content"] == "There is 1 row."
    assert len(body["tool_calls"]) == 1
    assert body["tool_calls"][0]["tool"] == "execute_sql_query"
    assert body["error"] is None
