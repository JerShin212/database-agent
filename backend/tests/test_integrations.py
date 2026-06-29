"""Tests for the ingest-by-reference integration endpoints (mocked deps)."""

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

backend_path = Path(__file__).parent.parent
sys.path.insert(0, str(backend_path))

import src.api.v1.integrations as integrations_module
from src.api.deps import get_db
from src.config import settings


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------

class FakeScalarResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


class FakeDB:
    """Scripted AsyncSession: select statements pop from a result queue;
    DML statements are counted and return nothing."""

    def __init__(self, scalar_results):
        self.scalar_results = list(scalar_results)
        self.added = []
        self.deleted = []
        self.commits = 0
        self.dml_count = 0

    async def execute(self, stmt, params=None):
        if getattr(stmt, "is_select", False):
            return FakeScalarResult(self.scalar_results.pop(0))
        self.dml_count += 1
        return FakeScalarResult(None)

    async def commit(self):
        self.commits += 1

    async def refresh(self, obj):
        pass

    async def rollback(self):
        pass

    def add(self, obj):
        self.added.append(obj)

    async def delete(self, obj):
        self.deleted.append(obj)


class FakeMinio:
    def __init__(self):
        self.uploaded = []
        self.deleted = []

    def upload_file(self, key, content, mime_type):
        self.uploaded.append((key, len(content), mime_type))

    def delete_file(self, key):
        self.deleted.append(key)


class FakeProcessor:
    def __init__(self, db):
        pass

    async def process_document(self, document_id):
        pass


class FakeHTTPResponse:
    def __init__(self, content=b"hello world", content_type="text/plain", status_error=None):
        self.content = content
        self.headers = {"content-type": content_type}
        self._status_error = status_error

    def raise_for_status(self):
        if self._status_error:
            raise self._status_error


class FakeAsyncClient:
    response = FakeHTTPResponse()
    error = None

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def get(self, url):
        if FakeAsyncClient.error:
            raise FakeAsyncClient.error
        return FakeAsyncClient.response


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _build_app(db):
    app = FastAPI()
    app.include_router(integrations_module.router, prefix="/api/integrations")

    async def fake_db():
        yield db

    app.dependency_overrides[get_db] = fake_db
    return app


@pytest.fixture
def fake_minio(monkeypatch):
    minio = FakeMinio()
    monkeypatch.setattr(integrations_module, "minio_service", minio)
    return minio


@pytest.fixture(autouse=True)
def patch_externals(monkeypatch):
    monkeypatch.setattr(settings, "integration_api_key", "test-secret")
    monkeypatch.setattr(integrations_module, "DocumentProcessor", FakeProcessor)
    monkeypatch.setattr(integrations_module.httpx, "AsyncClient", FakeAsyncClient)
    FakeAsyncClient.response = FakeHTTPResponse()
    FakeAsyncClient.error = None
    yield


def _ingest_payload(**overrides):
    payload = {
        "source_url": "https://kb.example.com/files/doc1.txt",
        "external_id": "kb-doc-1",
        "filename": "doc1.txt",
    }
    payload.update(overrides)
    return payload


HEADERS = {"X-API-Key": "test-secret"}


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

def test_missing_api_key_rejected(fake_minio):
    client = TestClient(_build_app(FakeDB([])))
    response = client.post("/api/integrations/documents", json=_ingest_payload())
    assert response.status_code == 401


def test_wrong_api_key_rejected(fake_minio):
    client = TestClient(_build_app(FakeDB([])))
    response = client.post(
        "/api/integrations/documents", json=_ingest_payload(), headers={"X-API-Key": "nope"}
    )
    assert response.status_code == 401


def test_unconfigured_key_disables_endpoints(fake_minio, monkeypatch):
    monkeypatch.setattr(settings, "integration_api_key", "")
    client = TestClient(_build_app(FakeDB([])))
    response = client.post("/api/integrations/documents", json=_ingest_payload(), headers=HEADERS)
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def test_unreachable_url_returns_422(fake_minio):
    import httpx

    FakeAsyncClient.error = httpx.ConnectError("unreachable")
    client = TestClient(_build_app(FakeDB([])))
    response = client.post("/api/integrations/documents", json=_ingest_payload(), headers=HEADERS)
    assert response.status_code == 422


def test_unsupported_mime_returns_415(fake_minio):
    FakeAsyncClient.response = FakeHTTPResponse(content_type="application/x-zip")
    client = TestClient(_build_app(FakeDB([])))
    response = client.post("/api/integrations/documents", json=_ingest_payload(), headers=HEADERS)
    assert response.status_code == 415


def test_oversized_file_returns_413(fake_minio):
    FakeAsyncClient.response = FakeHTTPResponse(content=b"x" * (51 * 1024 * 1024))
    client = TestClient(_build_app(FakeDB([])))
    response = client.post("/api/integrations/documents", json=_ingest_payload(), headers=HEADERS)
    assert response.status_code == 413


# ---------------------------------------------------------------------------
# Ingest flow
# ---------------------------------------------------------------------------

def test_fresh_ingest_uploads_and_creates_document(fake_minio):
    collection = SimpleNamespace(id="coll-1", name="Knowledge Base", document_count=0)
    # selects: existing doc by external_id (None), collection by name
    db = FakeDB([None, collection])
    client = TestClient(_build_app(db))

    response = client.post(
        "/api/integrations/documents",
        json=_ingest_payload(metadata={"origin": "kb"}),
        headers=HEADERS,
    )

    assert response.status_code == 202
    body = response.json()
    assert body["external_id"] == "kb-doc-1"
    assert body["replaced"] is False

    assert len(fake_minio.uploaded) == 1
    document = next(d for d in db.added if getattr(d, "external_id", None) == "kb-doc-1")
    assert document.source_url.startswith("https://kb.example.com")
    assert document.source_metadata == {"origin": "kb"}
    assert document.mime_type == "text/plain"


def test_reingest_same_external_id_replaces(fake_minio):
    existing = SimpleNamespace(
        id="doc-old",
        collection_id="coll-1",
        minio_object_key="coll-1/old/doc1.txt",
        external_id="kb-doc-1",
    )
    collection = SimpleNamespace(id="coll-1", name="Knowledge Base", document_count=1)
    db = FakeDB([existing, collection])
    client = TestClient(_build_app(db))

    response = client.post("/api/integrations/documents", json=_ingest_payload(), headers=HEADERS)

    assert response.status_code == 202
    assert response.json()["replaced"] is True
    assert fake_minio.deleted == ["coll-1/old/doc1.txt"]
    assert existing in db.deleted
    assert len(fake_minio.uploaded) == 1


# ---------------------------------------------------------------------------
# Status + delete
# ---------------------------------------------------------------------------

def test_status_endpoint(fake_minio):
    doc = SimpleNamespace(id="doc-1", status="completed")
    client = TestClient(_build_app(FakeDB([doc])))
    response = client.get("/api/integrations/documents/kb-doc-1/status", headers=HEADERS)
    assert response.status_code == 200
    assert response.json()["status"] == "completed"


def test_status_unknown_external_id_404(fake_minio):
    client = TestClient(_build_app(FakeDB([None])))
    response = client.get("/api/integrations/documents/missing/status", headers=HEADERS)
    assert response.status_code == 404


def test_delete_endpoint(fake_minio):
    doc = SimpleNamespace(
        id="doc-1", collection_id="coll-1", minio_object_key="coll-1/x/doc1.txt"
    )
    db = FakeDB([doc])
    client = TestClient(_build_app(db))
    response = client.delete("/api/integrations/documents/kb-doc-1", headers=HEADERS)
    assert response.status_code == 200
    assert fake_minio.deleted == ["coll-1/x/doc1.txt"]
    assert doc in db.deleted


def test_delete_unknown_external_id_404(fake_minio):
    client = TestClient(_build_app(FakeDB([None])))
    response = client.delete("/api/integrations/documents/missing", headers=HEADERS)
    assert response.status_code == 404
