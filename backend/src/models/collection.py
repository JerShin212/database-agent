from datetime import datetime
from typing import Optional
from uuid import UUID, uuid4
from sqlalchemy import Column, String, Integer, LargeBinary, Text, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from pgvector.sqlalchemy import Vector
from src.db.database import Base


class Collection(Base):
    __tablename__ = "collections"

    id: UUID = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    name: str = Column(String(255), nullable=False)
    description: Optional[str] = Column(Text, nullable=True)
    document_count: int = Column(Integer, default=0)
    created_at: datetime = Column(DateTime, default=datetime.utcnow)
    updated_at: datetime = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Document(Base):
    __tablename__ = "documents"

    id: UUID = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    collection_id: UUID = Column(
        PGUUID(as_uuid=True), ForeignKey("collections.id", ondelete="CASCADE"), nullable=False
    )
    filename: str = Column(String(500), nullable=False)
    mime_type: str = Column(String(100), nullable=False)
    file_size: int = Column(Integer, nullable=False)
    page_count: Optional[int] = Column(Integer, nullable=True)
    minio_object_key: str = Column(String(1000), nullable=False)
    status: str = Column(String(50), default="pending")  # pending, processing, completed, failed
    error_message: Optional[str] = Column(Text, nullable=True)
    extracted_text: Optional[str] = Column(Text, nullable=True)
    summary: Optional[str] = Column(Text, nullable=True)
    # Ingest-by-reference (knowledge base integration) — see migrations/add_external_documents.sql
    external_id: Optional[str] = Column(String(255), nullable=True, unique=True)
    source_url: Optional[str] = Column(Text, nullable=True)
    source_metadata: Optional[dict] = Column(JSONB, nullable=True)
    created_at: datetime = Column(DateTime, default=datetime.utcnow)
    updated_at: datetime = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class DocumentChunk(Base):
    __tablename__ = "document_chunks"

    id: UUID = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    document_id: UUID = Column(
        PGUUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    collection_id: UUID = Column(
        PGUUID(as_uuid=True), ForeignKey("collections.id", ondelete="CASCADE"), nullable=False
    )
    chunk_index: int = Column(Integer, nullable=False)
    content: str = Column(Text, nullable=False)
    start_char: Optional[int] = Column(Integer, nullable=True)
    end_char: Optional[int] = Column(Integer, nullable=True)
    embedding = Column(Vector(128), nullable=True)
    created_at: datetime = Column(DateTime, default=datetime.utcnow)


class DocumentPage(Base):
    __tablename__ = "document_pages"

    id: UUID = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    document_id: UUID = Column(
        PGUUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    collection_id: UUID = Column(
        PGUUID(as_uuid=True), ForeignKey("collections.id", ondelete="CASCADE"), nullable=False
    )
    page_number: int = Column(Integer, nullable=False)
    visual_embedding = Column(Vector(128), nullable=True)
    # Full ColQwen2 multi-vector (n_vectors x 128, float16, row-major) for MaxSim rerank
    multi_embedding = Column(LargeBinary, nullable=True)
    n_vectors: Optional[int] = Column(Integer, nullable=True)
    created_at: datetime = Column(DateTime, default=datetime.utcnow)
