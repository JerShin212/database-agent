"""Unit tests for the read_document tool (stubbed DB session)."""

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

backend_path = Path(__file__).parent.parent
sys.path.insert(0, str(backend_path))

import src.db.database as db_module
from src.agent.sdk.descriptor import Descriptor
from src.agent.tools.document_tools import read_document

# read_document now takes the descriptor explicitly (no ContextVar). No collection
# filter -> matches any document.
CTX = Descriptor()


class FakeResult:
    def __init__(self, documents):
        self._documents = documents

    def scalars(self):
        return self

    def all(self):
        return self._documents


class FakeSession:
    documents = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def execute(self, stmt):
        return FakeResult(FakeSession.documents)


def _doc(filename, text):
    return SimpleNamespace(filename=filename, status="completed", extracted_text=text)


@pytest.fixture(autouse=True)
def fake_session(monkeypatch):
    monkeypatch.setattr(db_module, "SyncSessionLocal", FakeSession)
    FakeSession.documents = []
    yield


def test_reads_document_with_header():
    FakeSession.documents = [_doc("manual.pdf", "warranty is five years")]
    result = read_document("manual", CTX)
    assert "[manual.pdf — 22 chars total, showing 0..22]" in result
    assert "warranty is five years" in result
    assert "More content follows" not in result


def test_pagination_header_and_slicing():
    FakeSession.documents = [_doc("manual.pdf", "x" * 30_000)]
    result = read_document("manual", CTX, start_char=0, length=10_000)
    assert "showing 0..10000" in result
    assert "call read_document with start_char=10000" in result

    result2 = read_document("manual", CTX, start_char=10_000, length=20_000)
    assert "showing 10000..30000" in result2
    assert "More content follows" not in result2


def test_length_capped_at_max():
    FakeSession.documents = [_doc("manual.pdf", "x" * 50_000)]
    result = read_document("manual", CTX, length=99_999)
    assert "showing 0..20000" in result


def test_start_beyond_end_errors():
    FakeSession.documents = [_doc("manual.pdf", "short")]
    result = read_document("manual", CTX, start_char=100)
    assert result.startswith("Error:")


def test_no_match_returns_no_results():
    FakeSession.documents = []
    result = read_document("nonexistent", CTX)
    assert result.startswith("NO_RESULTS")


def test_multiple_matches_lists_candidates():
    FakeSession.documents = [
        _doc("manual_v1.pdf", "a"),
        _doc("manual_v2.pdf", "b"),
    ]
    result = read_document("manual", CTX)
    assert "Multiple documents match" in result
    assert "manual_v1.pdf" in result and "manual_v2.pdf" in result


def test_exact_filename_disambiguates():
    FakeSession.documents = [
        _doc("manual.pdf", "exact content"),
        _doc("manual_v2.pdf", "other content"),
    ]
    result = read_document("manual.pdf", CTX)
    assert "exact content" in result
    assert "Multiple documents" not in result
