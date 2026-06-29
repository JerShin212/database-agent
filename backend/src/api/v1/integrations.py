"""
Module-to-module integration endpoints (see docs/integration-proposal.md).

Ingest-by-reference: the centralized knowledge base module owns document
storage and notifies this service with a fetchable URL instead of re-uploading
bytes. Documents are tracked by external_id (idempotency key): re-POSTing the
same external_id replaces the previous version; DELETE removes it.

Auth: shared secret in the X-API-Key header (settings.integration_api_key).
"""

import logging
from uuid import uuid4

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_db
from src.config import settings
from src.models.collection import Collection, Document, DocumentChunk, DocumentPage
from src.processing.document_processor import DocumentProcessor
from src.processing.extractors.factory import ExtractorFactory
from src.services.minio_service import minio_service

logger = logging.getLogger(__name__)

router = APIRouter()

_MAX_FILE_SIZE = 50 * 1024 * 1024  # matches the upload endpoint
_DEFAULT_COLLECTION = "Knowledge Base"
_DOWNLOAD_TIMEOUT = 60.0


async def require_api_key(x_api_key: str = Header(default="")) -> None:
    if not settings.integration_api_key:
        raise HTTPException(
            status_code=403,
            detail="Integration endpoints are disabled (INTEGRATION_API_KEY not configured)",
        )
    if x_api_key != settings.integration_api_key:
        raise HTTPException(status_code=401, detail="Invalid or missing X-API-Key")


class IngestByReferenceRequest(BaseModel):
    source_url: str = Field(..., description="Fetchable URL (presigned URLs are fine)")
    external_id: str = Field(..., min_length=1, max_length=255,
                             description="Caller's stable document ID (idempotency key)")
    filename: str = Field(..., min_length=1, max_length=500)
    mime_type: str | None = Field(None, description="Defaults to the response Content-Type")
    collection_name: str | None = Field(None, description=f"Defaults to '{_DEFAULT_COLLECTION}'")
    metadata: dict | None = Field(None, description="Opaque caller metadata, stored as-is")


class IngestResponse(BaseModel):
    document_id: str
    external_id: str
    status: str
    replaced: bool = False


async def _get_or_create_collection(db: AsyncSession, name: str) -> Collection:
    result = await db.execute(select(Collection).where(Collection.name == name))
    collection = result.scalar_one_or_none()
    if collection is None:
        collection = Collection(name=name, description="Documents synced from external modules")
        db.add(collection)
        await db.commit()
        await db.refresh(collection)
    return collection


async def _delete_document_data(db: AsyncSession, document: Document) -> None:
    """Remove a document's chunks, pages, MinIO object, and row."""
    try:
        minio_service.delete_file(document.minio_object_key)
    except Exception:
        pass
    await db.execute(delete(DocumentChunk).where(DocumentChunk.document_id == document.id))
    await db.execute(delete(DocumentPage).where(DocumentPage.document_id == document.id))
    await db.execute(
        update(Collection)
        .where(Collection.id == document.collection_id)
        .values(document_count=Collection.document_count - 1)
    )
    await db.delete(document)
    await db.commit()


@router.post("/documents", response_model=IngestResponse, status_code=202,
             dependencies=[Depends(require_api_key)])
async def ingest_document_by_reference(
    request: IngestByReferenceRequest,
    db: AsyncSession = Depends(get_db),
):
    """Fetch a document from a URL and run it through the ingestion pipeline."""
    # 1. Download (before touching existing data, so failures leave state intact)
    try:
        async with httpx.AsyncClient(timeout=_DOWNLOAD_TIMEOUT, follow_redirects=True) as client:
            response = await client.get(request.source_url)
            response.raise_for_status()
            content = response.content
    except httpx.HTTPError as e:
        raise HTTPException(status_code=422, detail=f"Could not fetch source_url: {e}")

    if len(content) > _MAX_FILE_SIZE:
        raise HTTPException(status_code=413, detail="File exceeds the 50MB limit")

    mime_type = request.mime_type or response.headers.get("content-type", "").split(";")[0].strip()
    if not ExtractorFactory.is_supported(mime_type):
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported MIME type '{mime_type}'. "
                   f"Supported: {ExtractorFactory.supported_types()}",
        )

    # 2. Idempotency: an existing document with this external_id is replaced
    result = await db.execute(
        select(Document).where(Document.external_id == request.external_id)
    )
    existing = result.scalar_one_or_none()
    replaced = existing is not None
    if existing is not None:
        await _delete_document_data(db, existing)

    # 3. Reuse the standard upload pipeline: MinIO -> Document row -> processor
    collection = await _get_or_create_collection(
        db, request.collection_name or _DEFAULT_COLLECTION
    )

    object_key = f"{collection.id}/{uuid4()}/{request.filename}"
    minio_service.upload_file(object_key, content, mime_type)

    document = Document(
        collection_id=collection.id,
        filename=request.filename,
        mime_type=mime_type,
        file_size=len(content),
        minio_object_key=object_key,
        status="pending",
        external_id=request.external_id,
        source_url=request.source_url,
        source_metadata=request.metadata,
    )
    db.add(document)
    await db.commit()
    await db.refresh(document)

    await db.execute(
        update(Collection)
        .where(Collection.id == collection.id)
        .values(document_count=Collection.document_count + 1)
    )
    await db.commit()

    try:
        processor = DocumentProcessor(db)
        await processor.process_document(document.id)
        await db.refresh(document)
    except Exception:
        logger.exception("Processing failed for external document %s", request.external_id)
        await db.rollback()
        result = await db.execute(select(Document).where(Document.id == document.id))
        document = result.scalar_one_or_none()

    return IngestResponse(
        document_id=str(document.id),
        external_id=request.external_id,
        status=document.status,
        replaced=replaced,
    )


@router.get("/documents/{external_id}/status", response_model=IngestResponse,
            dependencies=[Depends(require_api_key)])
async def get_external_document_status(
    external_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Poll processing status for an externally ingested document."""
    result = await db.execute(select(Document).where(Document.external_id == external_id))
    document = result.scalar_one_or_none()
    if not document:
        raise HTTPException(status_code=404, detail=f"No document with external_id '{external_id}'")
    return IngestResponse(
        document_id=str(document.id),
        external_id=external_id,
        status=document.status,
    )


@router.delete("/documents/{external_id}", dependencies=[Depends(require_api_key)])
async def delete_external_document(
    external_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Delete an externally ingested document (chunks, pages, file, row)."""
    result = await db.execute(select(Document).where(Document.external_id == external_id))
    document = result.scalar_one_or_none()
    if not document:
        raise HTTPException(status_code=404, detail=f"No document with external_id '{external_id}'")
    await _delete_document_data(db, document)
    return {"status": "deleted", "external_id": external_id}
