"""
SQLAlchemy models for database connectors and schema catalog.

Models:
- Connector: External database connection configurations
- SchemaDefinition: Semantic catalog of tables/columns with embeddings
- SchemaRelationship: Foreign key relationships between tables
"""

from datetime import datetime
from typing import Optional
from uuid import UUID

from pgvector.sqlalchemy import Vector
from sqlalchemy import Column, Computed, ForeignKey, String, Text, Integer, TIMESTAMP, Index
from sqlalchemy.dialects.postgresql import UUID as PGUUID, JSONB, TSVECTOR
from sqlalchemy.orm import relationship

from src.db.database import Base


class Connector(Base):
    """External database connection configuration."""

    __tablename__ = "connectors"

    id = Column(PGUUID(as_uuid=True), primary_key=True, server_default="gen_random_uuid()")
    user_id = Column(PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(255), nullable=False)
    db_type = Column(String(50), nullable=False)  # 'sqlite', 'postgresql', 'mysql'
    connection_string = Column(Text, nullable=False)  # Encrypted with Fernet
    status = Column(String(50), nullable=False, default="pending")  # pending, indexing, ready, failed
    indexing_progress = Column(JSONB)  # {"stage": "...", "current": X, "total": Y, "table": "..."}
    error_message = Column(Text)
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default="CURRENT_TIMESTAMP")
    updated_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default="CURRENT_TIMESTAMP")

    # Relationships
    user = relationship("User", back_populates="connectors")
    schema_definitions = relationship("SchemaDefinition", back_populates="connector", cascade="all, delete-orphan")
    schema_relationships = relationship("SchemaRelationship", back_populates="connector", cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_connectors_user_id", "user_id"),
        Index("idx_connectors_status", "status"),
    )

    def __repr__(self) -> str:
        return f"<Connector(id={self.id}, name={self.name}, db_type={self.db_type}, status={self.status})>"


class SchemaDefinition(Base):
    """Semantic catalog entry for a table or column with LLM-generated definition."""

    __tablename__ = "schema_definitions"

    id = Column(PGUUID(as_uuid=True), primary_key=True, server_default="gen_random_uuid()")
    connector_id = Column(PGUUID(as_uuid=True), ForeignKey("connectors.id", ondelete="CASCADE"), nullable=False)
    definition_type = Column(String(20), nullable=False)  # 'table' or 'column'
    table_name = Column(String(255), nullable=False)
    column_name = Column(String(255))  # NULL for table-level definitions
    data_type = Column(String(100))  # e.g., 'VARCHAR(255)', 'INTEGER', 'TIMESTAMP'
    semantic_definition = Column(Text, nullable=False)  # LLM-generated description
    sample_values = Column(JSONB)  # Sample data for context
    embedding = Column(Vector(1536))  # OpenAI text-embedding-3-small
    search_vector = Column(TSVECTOR, Computed(
        "setweight(to_tsvector('english', COALESCE(table_name, '')), 'A') || "
        "setweight(to_tsvector('english', COALESCE(column_name, '')), 'A') || "
        "setweight(to_tsvector('english', COALESCE(semantic_definition, '')), 'B')",
        persisted=True
    ))  # Generated column for FTS
    content_length = Column(Integer, Computed(
        "length(COALESCE(table_name, '')) + "
        "length(COALESCE(column_name, '')) + "
        "length(COALESCE(semantic_definition, ''))",
        persisted=True
    ))  # Generated column for BM25
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default="CURRENT_TIMESTAMP")
    updated_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default="CURRENT_TIMESTAMP")

    # Relationships
    connector = relationship("Connector", back_populates="schema_definitions")

    __table_args__ = (
        Index("idx_schema_definitions_connector_id", "connector_id"),
        Index("idx_schema_definitions_table_name", "connector_id", "table_name"),
        Index("idx_schema_definitions_type", "definition_type"),
        Index("idx_schema_definitions_fts", "search_vector", postgresql_using="gin"),
        Index("idx_schema_definitions_vector", "embedding", postgresql_using="vchordrq", postgresql_ops={"embedding": "vector_cosine_ops"}),
    )

    def __repr__(self) -> str:
        if self.definition_type == "table":
            return f"<SchemaDefinition(table={self.table_name}, type=table)>"
        else:
            return f"<SchemaDefinition(table={self.table_name}, column={self.column_name}, type=column)>"


class SchemaRelationship(Base):
    """Foreign key relationship between tables."""

    __tablename__ = "schema_relationships"

    id = Column(PGUUID(as_uuid=True), primary_key=True, server_default="gen_random_uuid()")
    connector_id = Column(PGUUID(as_uuid=True), ForeignKey("connectors.id", ondelete="CASCADE"), nullable=False)
    from_table = Column(String(255), nullable=False)
    from_column = Column(String(255), nullable=False)
    to_table = Column(String(255), nullable=False)
    to_column = Column(String(255), nullable=False)
    relationship_type = Column(String(50), default="foreign_key")  # 'foreign_key', 'one_to_many', etc.
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default="CURRENT_TIMESTAMP")

    # Relationships
    connector = relationship("Connector", back_populates="schema_relationships")

    __table_args__ = (
        Index("idx_schema_relationships_connector_id", "connector_id"),
        Index("idx_schema_relationships_from_table", "connector_id", "from_table"),
        Index("idx_schema_relationships_to_table", "connector_id", "to_table"),
    )

    def __repr__(self) -> str:
        return f"<SchemaRelationship({self.from_table}.{self.from_column} -> {self.to_table}.{self.to_column})>"
