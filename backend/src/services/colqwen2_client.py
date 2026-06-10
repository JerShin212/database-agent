"""ColQwen2 client for visual document embeddings via Modal endpoint."""

from __future__ import annotations

import numpy as np
import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_fixed

from src.config import settings

# Modal endpoints can fail transiently on cold starts — retry once after 2s
_retry_on_http_error = retry(
    stop=stop_after_attempt(2),
    wait=wait_fixed(2),
    retry=retry_if_exception_type(httpx.HTTPError),
    reraise=True,
)

# The Modal image endpoint validates filename extensions, so map media types
# to extensions it accepts.
_EXT_BY_MIME = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
    "image/bmp": ".bmp",
    "image/tiff": ".tiff",
}


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
        self.image_endpoint = settings.colqwen2_image_endpoint

    def _mean_pool(self, embedding: list) -> list[float]:
        """Mean-pool a 2D multi-vector (n_tokens, 128) → (128,) or pass through 1D."""
        arr = np.array(embedding, dtype=np.float32)
        if arr.ndim == 2:
            return arr.mean(axis=0).tolist()
        return arr.tolist()

    @_retry_on_http_error
    def embed_text_multivector_sync(self, text: str) -> list[list[float]]:
        """
        Synchronously embed a query string and return the full multi-vector
        (n_query_tokens, 128), or [] if endpoint not configured.
        """
        if not self.text_endpoint:
            return []
        with httpx.Client(timeout=120.0) as client:
            resp = client.post(self.text_endpoint, json={"text": text})
            resp.raise_for_status()
            return resp.json()["embeddings"]

    def embed_text_sync(self, text: str) -> list[float]:
        """
        Synchronously embed a query string via ColQwen2 text encoder.
        Returns a 128-dim mean-pooled vector, or [] if endpoint not configured.
        Called from sync tool handlers running inside the executor thread.
        """
        multi_vector = self.embed_text_multivector_sync(text)
        return self._mean_pool(multi_vector) if multi_vector else []

    async def embed_text(self, text: str) -> list[float]:
        """Async version of embed_text_sync."""
        if not self.text_endpoint:
            return []
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(self.text_endpoint, json={"text": text})
            resp.raise_for_status()
            return self._mean_pool(resp.json()["embeddings"])

    async def embed_batch(self, texts: list[str], concurrency: int = 10) -> list[list[float]]:
        """
        Embed multiple texts concurrently via the ColQwen2 text endpoint.
        Returns a list of 128-dim mean-pooled vectors.
        """
        import asyncio

        if not self.text_endpoint:
            return [[] for _ in texts]

        semaphore = asyncio.Semaphore(concurrency)

        async def _embed_one(text: str) -> list[float]:
            async with semaphore:
                async with httpx.AsyncClient(timeout=120.0) as client:
                    resp = await client.post(self.text_endpoint, json={"text": text})
                    resp.raise_for_status()
                    return self._mean_pool(resp.json()["embeddings"])

        return await asyncio.gather(*[_embed_one(t) for t in texts])

    @_retry_on_http_error
    def embed_image_multivector_sync(
        self, image_bytes: bytes, media_type: str = "image/png"
    ) -> list[list[float]]:
        """
        Synchronously embed an image via the ColQwen2 image encoder.
        Returns the full multi-vector (n_tokens, 128), or [] if endpoint not configured.

        The Modal endpoint validates the uploaded filename's extension, so the
        multipart filename must match the media type.
        """
        if not self.image_endpoint:
            return []
        ext = _EXT_BY_MIME.get(media_type, ".png")
        # 180s: Modal cold starts can take 30-60s before inference begins
        with httpx.Client(timeout=180.0) as client:
            resp = client.post(
                self.image_endpoint,
                files={"file": (f"query{ext}", image_bytes, media_type)},
            )
            resp.raise_for_status()
            embeddings = resp.json()["embeddings"]  # shape (1, n_tokens, 128)
            return embeddings[0] if embeddings else []

    def embed_image_sync(self, image_bytes: bytes, media_type: str = "image/png") -> list[float]:
        """Mean-pooled 128-dim embedding of an image, or [] if endpoint not configured."""
        multi_vector = self.embed_image_multivector_sync(image_bytes, media_type)
        return self._mean_pool(multi_vector) if multi_vector else []

    @_retry_on_http_error
    async def embed_pdf_full(
        self, pdf_bytes: bytes, filename: str
    ) -> list[tuple[list[float], list[list[float]]]]:
        """
        Send a PDF to the Modal endpoint and return, per page, both the
        mean-pooled 128-dim vector (for ANN search) and the full multi-vector
        (n_tokens, 128) (for MaxSim rerank). Returns [] if not configured.
        """
        if not self.pdf_endpoint:
            return []
        async with httpx.AsyncClient(timeout=180.0) as client:
            resp = await client.post(
                self.pdf_endpoint,
                files={"file": (filename, pdf_bytes, "application/pdf")},
            )
            resp.raise_for_status()
            data = resp.json()
            # data["embeddings"][i] is the multi-vector embedding for page i
            return [(self._mean_pool(page_emb), page_emb) for page_emb in data["embeddings"]]

    async def embed_pdf(self, pdf_bytes: bytes, filename: str) -> list[list[float]]:
        """
        Send a PDF to the Modal endpoint and return one 128-dim vector per page.
        Returns [] if endpoint not configured.
        """
        pages = await self.embed_pdf_full(pdf_bytes, filename)
        return [pooled for pooled, _ in pages]


# Singleton — imported by tools and processors
colqwen2_client = ColQwen2Client()
