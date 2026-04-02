"""ColQwen2 client for visual document embeddings via Modal endpoint."""

from __future__ import annotations

import numpy as np
import httpx

from src.config import settings


class ColQwen2Client:
    """
    HTTP client for the deployed ColQwen2 Modal endpoint.

    ColQwen2 outputs multi-vector embeddings: (n_tokens, 128) per image page
    and (n_query_tokens, 128) for text. Both are mean-pooled to (128,) for storage.

    Sync methods (embed_text_sync) are used by agent tools which run in a
    synchronous context. Async methods are used by the document processor.
    """

    def __init__(self) -> None:
        self.pdf_endpoint = settings.colqwen2_pdf_endpoint
        self.text_endpoint = settings.colqwen2_text_endpoint

    def _mean_pool(self, embedding: list) -> list[float]:
        """Mean-pool a 2D multi-vector (n_tokens, 128) → (128,) or pass through 1D."""
        arr = np.array(embedding, dtype=np.float32)
        if arr.ndim == 2:
            return arr.mean(axis=0).tolist()
        return arr.tolist()

    def embed_text_sync(self, text: str) -> list[float]:
        """
        Synchronously embed a query string via ColQwen2 text encoder.
        Returns a 128-dim mean-pooled vector, or [] if endpoint not configured.
        Called from sync tool handlers running inside the executor thread.
        """
        if not self.text_endpoint:
            return []
        with httpx.Client(timeout=30.0) as client:
            resp = client.post(self.text_endpoint, json={"text": text})
            resp.raise_for_status()
            return self._mean_pool(resp.json()["embeddings"])

    async def embed_text(self, text: str) -> list[float]:
        """Async version of embed_text_sync."""
        if not self.text_endpoint:
            return []
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(self.text_endpoint, json={"text": text})
            resp.raise_for_status()
            return self._mean_pool(resp.json()["embeddings"])

    async def embed_pdf(self, pdf_bytes: bytes, filename: str) -> list[list[float]]:
        """
        Send a PDF to the Modal endpoint and return one 128-dim vector per page.
        Returns [] if endpoint not configured.
        """
        if not self.pdf_endpoint:
            return []
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(
                self.pdf_endpoint,
                files={"file": (filename, pdf_bytes, "application/pdf")},
            )
            resp.raise_for_status()
            data = resp.json()
            # data["embeddings"][i] is the multi-vector embedding for page i
            return [self._mean_pool(page_emb) for page_emb in data["embeddings"]]


# Singleton — imported by tools and processors
colqwen2_client = ColQwen2Client()
