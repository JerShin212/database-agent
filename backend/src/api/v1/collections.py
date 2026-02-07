from uuid import UUID, uuid4
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy import select, update, delete, func
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_db
from src.schemas.collection import (
    CollectionCreate,
    CollectionResponse,
    DocumentResponse,
    CollectionStatusResponse,
    SearchRequest,
    SearchResult,
)
from src.models.collection import Collection, Document, DocumentChunk
from src.services.minio_service import minio_service
from src.services.search_service import SearchService
from src.processing.document_processor import DocumentProcessor
from src.processing.extractors.factory import ExtractorFactory

router = APIRouter()


@router.post("", response_model=CollectionResponse)
async def create_collection(
    data: CollectionCreate,
    db: AsyncSession = Depends(get_db),
):
    """Create a new collection."""
    collection = Collection(
        name=data.name,
        description=data.description,
    )
    db.add(collection)
    await db.commit()
    await db.refresh(collection)
    return collection


@router.get("", response_model=list[CollectionResponse])
async def list_collections(
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
):
    """List all collections."""
    result = await db.execute(
        select(Collection)
        .order_by(Collection.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    return result.scalars().all()


@router.get("/{collection_id}", response_model=CollectionResponse)
async def get_collection(
    collection_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Get a collection by ID."""
    result = await db.execute(
        select(Collection).where(Collection.id == collection_id)
    )
    collection = result.scalar_one_or_none()

    if not collection:
        raise HTTPException(status_code=404, detail="Collection not found")

    return collection


@router.delete("/{collection_id}")
async def delete_collection(
    collection_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Delete a collection and all its documents."""
    result = await db.execute(
        select(Collection).where(Collection.id == collection_id)
    )
    collection = result.scalar_one_or_none()

    if not collection:
        raise HTTPException(status_code=404, detail="Collection not found")

    # Get all documents to delete from MinIO
    result = await db.execute(
        select(Document).where(Document.collection_id == collection_id)
    )
    documents = result.scalars().all()

    # Delete from MinIO
    for doc in documents:
        try:
            minio_service.delete_file(doc.minio_object_key)
        except Exception:
            pass  # Ignore MinIO errors

    # Delete chunks
    await db.execute(
        delete(DocumentChunk).where(DocumentChunk.collection_id == collection_id)
    )

    # Delete documents
    await db.execute(
        delete(Document).where(Document.collection_id == collection_id)
    )

    # Delete collection
    await db.delete(collection)
    await db.commit()

    return {"status": "deleted"}


@router.get("/{collection_id}/status", response_model=CollectionStatusResponse)
async def get_collection_status(
    collection_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Get processing status for a collection."""
    # Check collection exists
    result = await db.execute(
        select(Collection).where(Collection.id == collection_id)
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Collection not found")

    # Count by status
    result = await db.execute(
        select(Document.status, func.count(Document.id))
        .where(Document.collection_id == collection_id)
        .group_by(Document.status)
    )
    status_counts = {row[0]: row[1] for row in result.fetchall()}

    return CollectionStatusResponse(
        total=sum(status_counts.values()),
        pending=status_counts.get("pending", 0),
        processing=status_counts.get("processing", 0),
        completed=status_counts.get("completed", 0),
        failed=status_counts.get("failed", 0),
    )


@router.post("/{collection_id}/documents", response_model=list[DocumentResponse])
async def upload_documents(
    collection_id: UUID,
    files: list[UploadFile] = File(...),
    db: AsyncSession = Depends(get_db),
):
    """Upload documents to a collection."""
    # Check collection exists
    result = await db.execute(
        select(Collection).where(Collection.id == collection_id)
    )
    collection = result.scalar_one_or_none()
    if not collection:
        raise HTTPException(status_code=404, detail="Collection not found")

    # Validate file count
    if len(files) > 10:
        raise HTTPException(status_code=400, detail="Maximum 10 files per upload")

    created_documents = []
    processor = DocumentProcessor(db)

    for file in files:
        # Validate MIME type
        if not ExtractorFactory.is_supported(file.content_type):
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported file type: {file.content_type}",
            )

        # Read file content
        content = await file.read()

        # Validate file size (50MB max)
        if len(content) > 50 * 1024 * 1024:
            raise HTTPException(status_code=400, detail=f"File too large: {file.filename}")

        # Upload to MinIO
        object_key = f"{collection_id}/{uuid4()}/{file.filename}"
        minio_service.upload_file(object_key, content, file.content_type)

        # Create document record
        document = Document(
            collection_id=collection_id,
            filename=file.filename,
            mime_type=file.content_type,
            file_size=len(content),
            minio_object_key=object_key,
            status="pending",
        )
        db.add(document)
        await db.commit()
        await db.refresh(document)

        # Process document (async but run on main thread)
        try:
            await processor.process_document(document.id)
            await db.refresh(document)
        except Exception as e:
            # Rollback any failed transaction and refresh
            await db.rollback()
            # Re-fetch document to get updated status
            result = await db.execute(
                select(Document).where(Document.id == document.id)
            )
            document = result.scalar_one_or_none()

        created_documents.append(document)

    # Update document count
    await db.execute(
        update(Collection)
        .where(Collection.id == collection_id)
        .values(document_count=Collection.document_count + len(created_documents))
    )
    await db.commit()

    return created_documents


@router.get("/{collection_id}/documents", response_model=list[DocumentResponse])
async def list_documents(
    collection_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """List documents in a collection."""
    result = await db.execute(
        select(Document)
        .where(Document.collection_id == collection_id)
        .order_by(Document.created_at.desc())
    )
    return result.scalars().all()


@router.delete("/documents/{document_id}")
async def delete_document(
    document_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Delete a document."""
    result = await db.execute(
        select(Document).where(Document.id == document_id)
    )
    document = result.scalar_one_or_none()

    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    # Delete from MinIO
    try:
        minio_service.delete_file(document.minio_object_key)
    except Exception:
        pass

    # Delete chunks
    await db.execute(
        delete(DocumentChunk).where(DocumentChunk.document_id == document_id)
    )

    # Update collection count
    await db.execute(
        update(Collection)
        .where(Collection.id == document.collection_id)
        .values(document_count=Collection.document_count - 1)
    )

    # Delete document
    await db.delete(document)
    await db.commit()

    return {"status": "deleted"}


@router.get("/documents/{document_id}/download")
async def download_document(
    document_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Get a presigned URL for downloading a document."""
    result = await db.execute(
        select(Document).where(Document.id == document_id)
    )
    document = result.scalar_one_or_none()

    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    url = minio_service.get_presigned_url(document.minio_object_key)
    return {"url": url, "filename": document.filename}


@router.post("/search", response_model=list[SearchResult])
async def search_documents(
    request: SearchRequest,
    db: AsyncSession = Depends(get_db),
):
    """Search documents using semantic search."""
    search_service = SearchService(db)
    results = await search_service.search(
        query=request.query,
        collection_ids=request.collection_ids,
        limit=request.limit,
    )
    return results
