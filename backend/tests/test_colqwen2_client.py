"""Unit tests for the ColQwen2 HTTP client (mocked httpx)."""

import sys
from pathlib import Path

import httpx
import numpy as np
import pytest

backend_path = Path(__file__).parent.parent
sys.path.insert(0, str(backend_path))

import src.services.colqwen2_client as colqwen2_module
from src.services.colqwen2_client import ColQwen2Client


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


class FakeHttpClient:
    """Replaces httpx.Client; records calls and returns canned responses."""

    calls: list[dict] = []
    responses: list = []

    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def post(self, url, **kwargs):
        FakeHttpClient.calls.append({"url": url, **kwargs})
        response = FakeHttpClient.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(colqwen2_module.httpx, "Client", FakeHttpClient)
    FakeHttpClient.calls = []
    FakeHttpClient.responses = []
    c = ColQwen2Client()
    c.text_endpoint = "http://test/text"
    c.image_endpoint = "http://test/image"
    return c


def test_mean_pool_2d_to_128():
    c = ColQwen2Client()
    multi = np.ones((10, 128), dtype=np.float32) * 2.0
    pooled = c._mean_pool(multi.tolist())
    assert len(pooled) == 128
    assert pooled[0] == pytest.approx(2.0)


def test_embed_text_sync_pools_multivector(client):
    multi = [[1.0] * 128, [3.0] * 128]
    FakeHttpClient.responses = [FakeResponse({"embeddings": multi})]

    pooled = client.embed_text_sync("hello")

    assert len(pooled) == 128
    assert pooled[0] == pytest.approx(2.0)
    assert FakeHttpClient.calls[0]["json"] == {"text": "hello"}


def test_embed_image_multivector_unwraps_batch_dim(client):
    multi = [[0.5] * 128, [1.5] * 128]
    # Modal returns shape (1, n_tokens, 128) for a single image
    FakeHttpClient.responses = [FakeResponse({"embeddings": [multi]})]

    result = client.embed_image_multivector_sync(b"fakebytes", "image/jpeg")

    assert result == multi


def test_embed_image_filename_extension_matches_media_type(client):
    # Modal validates the multipart filename extension
    FakeHttpClient.responses = [FakeResponse({"embeddings": [[[0.0] * 128]]})]

    client.embed_image_multivector_sync(b"fakebytes", "image/jpeg")

    filename, content, media_type = FakeHttpClient.calls[0]["files"]["file"]
    assert filename.endswith(".jpg")
    assert content == b"fakebytes"
    assert media_type == "image/jpeg"


def test_embed_image_unknown_media_type_defaults_to_png(client):
    FakeHttpClient.responses = [FakeResponse({"embeddings": [[[0.0] * 128]]})]
    client.embed_image_multivector_sync(b"fakebytes", "image/x-weird")
    filename, _, _ = FakeHttpClient.calls[0]["files"]["file"]
    assert filename.endswith(".png")


def test_retry_recovers_from_transient_http_error(client):
    multi = [[1.0] * 128]
    FakeHttpClient.responses = [
        httpx.ConnectError("cold start"),
        FakeResponse({"embeddings": multi}),
    ]

    result = client.embed_text_multivector_sync("hello")

    assert result == multi
    assert len(FakeHttpClient.calls) == 2


def test_embed_text_cache_skips_second_http_call(client):
    multi = [[1.0] * 128]
    FakeHttpClient.responses = [FakeResponse({"embeddings": multi})]

    first = client.embed_text_multivector_sync("same query")
    second = client.embed_text_multivector_sync("same query")

    assert first == second == multi
    assert len(FakeHttpClient.calls) == 1


def test_embed_text_cache_distinct_queries_both_fetch(client):
    multi_a = [[1.0] * 128]
    multi_b = [[2.0] * 128]
    FakeHttpClient.responses = [
        FakeResponse({"embeddings": multi_a}),
        FakeResponse({"embeddings": multi_b}),
    ]

    assert client.embed_text_multivector_sync("query a") == multi_a
    assert client.embed_text_multivector_sync("query b") == multi_b
    assert len(FakeHttpClient.calls) == 2


def test_embed_text_cache_evicts_oldest(client):
    client._TEXT_CACHE_MAX = 2
    FakeHttpClient.responses = [
        FakeResponse({"embeddings": [[float(i)] * 128]}) for i in range(4)
    ]

    client.embed_text_multivector_sync("q0")
    client.embed_text_multivector_sync("q1")
    client.embed_text_multivector_sync("q2")  # evicts q0
    client.embed_text_multivector_sync("q0")  # must re-fetch

    assert len(FakeHttpClient.calls) == 4


def test_unconfigured_endpoints_return_empty():
    c = ColQwen2Client()
    c.text_endpoint = ""
    c.image_endpoint = ""
    assert c.embed_text_sync("x") == []
    assert c.embed_image_sync(b"x") == []
