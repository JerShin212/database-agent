"""Visual document processor — generates ColQwen2 page embeddings for PDFs."""

from __future__ import annotations

from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.services.colqwen2_client import colqwen2_client
from src.services.vector_db import VectorDBService


class VisualDocumentProcessor:
    """Generates and stores per-page ColQwen2 visual embeddings for PDF documents."""

    def __init__(self, db: AsyncSession) -> None:
        self.vector_db = VectorDBService(db)

    async def process_pdf(
        self,
        document_id: UUID,
        collection_id: UUID,
        pdf_bytes: bytes,
        filename: str,
    ) -> None:
        """
        Send PDF to ColQwen2 endpoint and store one visual embedding per page.

        Silently skips if colqwen2_pdf_endpoint is not configured so the text
        processing pipeline works without visual search set up.
        Errors from the endpoint are logged but do not fail document processing.
        """
        if not settings.colqwen2_pdf_endpoint:
            return

        try:
            page_embeddings = await colqwen2_client.embed_pdf(pdf_bytes, filename)
        except Exception as exc:
            print(f"[VisualDocumentProcessor] ColQwen2 failed for {filename}: {exc}")
            return

        if not page_embeddings:
            return

        page_records = [
            {
                "id": uuid4(),
                "document_id": document_id,
                "collection_id": collection_id,
                "page_number": page_num,
                "visual_embedding": embedding,
            }
            for page_num, embedding in enumerate(page_embeddings, start=1)
        ]

        await self.vector_db.insert_pages(page_records)
