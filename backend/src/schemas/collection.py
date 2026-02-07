from datetime import datetime
from typing import Optional
from uuid import UUID
from pydantic import BaseModel


class CollectionCreate(BaseModel):
    name: str
    description: Optional[str] = None


class CollectionResponse(BaseModel):
    id: UUID
    name: str
    description: Optional[str] = None
    document_count: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class DocumentResponse(BaseModel):
    id: UUID
    collection_id: UUID
    filename: str
    mime_type: str
    file_size: int
    page_count: Optional[int] = None
    status: str
    error_message: Optional[str] = None
    summary: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class CollectionStatusResponse(BaseModel):
    total: int
    pending: int
    processing: int
    completed: int
    failed: int


class SearchRequest(BaseModel):
    query: str
    collection_ids: Optional[list[UUID]] = None
    limit: int = 5
    mode: str = "hybrid"  # "hybrid", "semantic", or "keyword"


class SearchResult(BaseModel):
    chunk_id: UUID
    document_id: UUID
    collection_id: UUID
    filename: str
    content: str
    score: float
