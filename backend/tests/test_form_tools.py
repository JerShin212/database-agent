"""Unit tests for the form catalog, suggest_form validation, and action event."""

import json
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

backend_path = Path(__file__).parent.parent
sys.path.insert(0, str(backend_path))

import src.agent.tools.form_tools as form_tools_module
import src.api.v1.chat as chat_module
from src.agent.tools.form_tools import (
    FORM_SUGGESTION_PREFIX,
    build_suggest_form_description,
    suggest_form,
)
from src.api.deps import get_db
from src.services.form_catalog import JsonFormCatalog

FORMS = [
    {
        "id": "warranty-claim",
        "name": "Warranty Claim Form",
        "description": "File a warranty claim.",
        "url": "/forms/warranty-claim",
        "fields": [
            {"name": "customer_name", "label": "Customer Name", "type": "text", "required": True},
            {"name": "order_id", "label": "Order ID", "type": "text", "required": True},
        ],
    },
    {
        "id": "maintenance-request",
        "name": "Maintenance Request Form",
        "description": "Schedule maintenance.",
        "url": "/forms/maintenance-request",
        "fields": [{"name": "address", "label": "Address", "type": "text", "required": True}],
    },
]


@pytest.fixture
def catalog(tmp_path, monkeypatch):
    forms_file = tmp_path / "forms.json"
    forms_file.write_text(json.dumps(FORMS))
    catalog = JsonFormCatalog(forms_file)
    monkeypatch.setattr(form_tools_module, "form_catalog", catalog)
    return catalog


# ---------------------------------------------------------------------------
# Catalog
# ---------------------------------------------------------------------------

def test_json_catalog_lists_and_gets(catalog):
    assert [f["id"] for f in catalog.list_forms()] == ["warranty-claim", "maintenance-request"]
    assert catalog.get_form("warranty-claim")["name"] == "Warranty Claim Form"
    assert catalog.get_form("missing") is None


def test_json_catalog_missing_file_returns_empty(tmp_path):
    catalog = JsonFormCatalog(tmp_path / "nope.json")
    assert catalog.list_forms() == []


def test_repo_forms_json_is_valid():
    repo_catalog = JsonFormCatalog(backend_path / "data" / "forms.json")
    forms = repo_catalog.list_forms()
    assert len(forms) >= 3
    for form in forms:
        assert {"id", "name", "description", "url", "fields"} <= set(form)


# ---------------------------------------------------------------------------
# suggest_form validation
# ---------------------------------------------------------------------------

def test_suggest_form_valid(catalog):
    result = suggest_form("warranty-claim", {"order_id": "1023"})
    assert result.startswith(FORM_SUGGESTION_PREFIX)
    assert "Warranty Claim Form" in result


def test_suggest_form_no_prefill(catalog):
    assert suggest_form("maintenance-request").startswith(FORM_SUGGESTION_PREFIX)


def test_suggest_form_unknown_id_lists_available(catalog):
    result = suggest_form("nonexistent")
    assert result.startswith("Error:")
    assert "warranty-claim" in result


def test_suggest_form_unknown_prefill_field(catalog):
    result = suggest_form("warranty-claim", {"not_a_field": "x"})
    assert result.startswith("Error:")
    assert "not_a_field" in result
    assert "order_id" in result  # valid fields listed for self-correction


def test_tool_description_lists_forms(catalog):
    description = build_suggest_form_description()
    assert "warranty-claim" in description
    assert "maintenance-request" in description


# ---------------------------------------------------------------------------
# action event passes through the stream endpoint
# ---------------------------------------------------------------------------

class StubFramework:
    def __init__(self, chunks):
        self.chunks = chunks

    async def chat(self, **kwargs):
        for chunk in self.chunks:
            yield chunk


def test_action_event_streams_to_client(monkeypatch):
    action = {
        "type": "action",
        "action": "form_suggestion",
        "form_id": "warranty-claim",
        "form_name": "Warranty Claim Form",
        "redirect_url": "/forms/warranty-claim",
        "prefill": {"order_id": "1023"},
    }
    chunks = [
        {"type": "metadata", "conversation_id": "conv-1"},
        action,
        {"type": "content", "content": "I've suggested the warranty claim form."},
        {"type": "done", "conversation_id": "conv-1"},
    ]
    monkeypatch.setattr(chat_module, "agent_framework", StubFramework(chunks))

    app = FastAPI()
    app.include_router(chat_module.router, prefix="/api/chat")

    async def fake_db():
        yield None

    app.dependency_overrides[get_db] = fake_db

    client = TestClient(app)
    response = client.post("/api/chat/stream", json={"message": "file a warranty claim"})
    assert response.status_code == 200

    body = response.text.replace("\r\n", "\n")
    action_frames = [f for f in body.strip().split("\n\n") if "event: action" in f]
    assert len(action_frames) == 1
    data_line = next(line for line in action_frames[0].split("\n") if line.startswith("data:"))
    payload = json.loads(data_line[len("data:"):].strip())
    assert payload["form_id"] == "warranty-claim"
    assert payload["prefill"] == {"order_id": "1023"}
