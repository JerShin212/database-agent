from uuid import UUID, uuid4
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.collection import Document, DocumentChunk
from src.services.minio_service import minio_service
from src.services.embedding_service import embedding_service
from src.services.vector_db import VectorDBService
from src.processing.extractors.factory import ExtractorFactory
from src.processing.chunking.semantic import SemanticChunker


class DocumentProcessor:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.vector_db = VectorDBService(db)
        self.chunker = SemanticChunker()

    async def process_document(self, document_id: UUID) -> None:
        """Process a document: extract text, chunk, embed, and store."""
        # Get document from database
        result = await self.db.execute(
            Document.__table__.select().where(Document.id == document_id)
        )
        document = result.fetchone()

        if not document:
            raise ValueError(f"Document not found: {document_id}")

        try:
            # Update status to processing
            await self._update_status(document_id, "processing")

            # Download file from MinIO
            file_content = minio_service.download_file(document.minio_object_key)

            # Extract text
            extractor = ExtractorFactory.get_extractor(document.mime_type)
            extracted = extractor.extract(file_content)

            # Update document with extracted text
            await self.db.execute(
                update(Document)
                .where(Document.id == document_id)
                .values(
                    extracted_text=extracted.content,
                    page_count=extracted.page_count,
                )
            )

            # Chunk the text
            chunks = self.chunker.chunk(extracted.content)

            if chunks:
                # Generate embeddings for all chunks
                chunk_texts = [chunk.content for chunk in chunks]
                embeddings = await embedding_service.embed_batch(chunk_texts)

                # Prepare chunk records
                chunk_records = []
                for i, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
                    chunk_records.append({
                        "id": uuid4(),
                        "document_id": document_id,
                        "collection_id": document.collection_id,
                        "chunk_index": i,
                        "content": chunk.content,
                        "start_char": chunk.start_char,
                        "end_char": chunk.end_char,
                        "embedding": embedding,
                    })

                # Insert chunks with embeddings
                await self.vector_db.insert_chunks(chunk_records)

            # Visual processing: generate per-page ColQwen2 embeddings for PDFs
            if document.mime_type == "application/pdf":
                from src.processing.visual_processor import VisualDocumentProcessor
                visual_proc = VisualDocumentProcessor(self.db)
                await visual_proc.process_pdf(
                    document_id=document_id,
                    collection_id=document.collection_id,
                    pdf_bytes=file_content,
                    filename=document.filename,
                )

            # Update status to completed
            await self._update_status(document_id, "completed")

        except Exception as e:
            # Update status to failed
            await self._update_status(document_id, "failed", str(e))
            raise

    async def _update_status(
        self, document_id: UUID, status: str, error_message: str = None
    ) -> None:
        """Update document status."""
        values = {"status": status}
        if error_message:
            values["error_message"] = error_message

        await self.db.execute(
            update(Document).where(Document.id == document_id).values(**values)
        )
        await self.db.commit()
