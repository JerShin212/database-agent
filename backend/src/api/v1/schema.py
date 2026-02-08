"""
API endpoints for schema catalog search and exploration.

Provides semantic search over schema definitions and table/column browsing.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.database import get_db
from src.models.connector import SchemaDefinition, Connector
from src.services.embedding_service import embedding_service
from src.services.vector_db import VectorDBService


router = APIRouter()


# ===== Request/Response Models =====

class SchemaSearchRequest(BaseModel):
    """Request to search schema catalog."""
    query: str
    connector_id: str
    limit: int = 5


class SchemaDefinitionResponse(BaseModel):
    """Response model for schema definition."""
    id: str
    definition_type: str
    table_name: str
    column_name: str | None
    data_type: str | None
    semantic_definition: str
    sample_values: list | None
    score: float | None


class TableInfo(BaseModel):
    """Table information."""
    name: str
    column_count: int


class ColumnInfo(BaseModel):
    """Column information."""
    name: str
    data_type: str
    semantic_definition: str
    sample_values: list | None


class TableSchemaResponse(BaseModel):
    """Detailed table schema response."""
    table_name: str
    table_definition: str | None
    columns: list[ColumnInfo]


# ===== Endpoints =====

@router.post("/schema/search", response_model=list[SchemaDefinitionResponse])
async def search_schema(
    request: SchemaSearchRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Search schema catalog using hybrid search (keyword + semantic + RRF).

    Returns relevant table and column definitions with business context.
    """
    try:
        connector_id = UUID(request.connector_id)

        # Verify connector exists and is ready
        stmt = select(Connector).where(Connector.id == connector_id)
        result = await db.execute(stmt)
        connector = result.scalar_one_or_none()

        if not connector:
            raise HTTPException(status_code=404, detail="Connector not found")

        if connector.status != "ready":
            raise HTTPException(
                status_code=400,
                detail=f"Connector is not ready (status: {connector.status})"
            )

        # Perform hybrid search
        vector_db = VectorDBService(db)
        query_embedding = await embedding_service.embed_text(request.query)

        results = await vector_db.search_schema_hybrid(
            query_text=request.query,
            query_embedding=query_embedding,
            connector_id=connector_id,
            limit=request.limit,
        )

        return [
            SchemaDefinitionResponse(
                id=str(r["definition_id"]),
                definition_type=r["definition_type"],
                table_name=r["table_name"],
                column_name=r.get("column_name"),
                data_type=r.get("data_type"),
                semantic_definition=r["semantic_definition"],
                sample_values=r.get("sample_values"),
                score=r.get("score"),
            )
            for r in results
        ]

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/schema/tables/{connector_id}", response_model=list[TableInfo])
async def list_tables(
    connector_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """List all tables in a connector's database."""
    try:
        # Verify connector exists
        stmt = select(Connector).where(Connector.id == connector_id)
        result = await db.execute(stmt)
        connector = result.scalar_one_or_none()

        if not connector:
            raise HTTPException(status_code=404, detail="Connector not found")

        # Get table list
        stmt = select(
            SchemaDefinition.table_name,
            func.count(SchemaDefinition.id).label("column_count")
        ).where(
            SchemaDefinition.connector_id == connector_id,
            SchemaDefinition.definition_type == "column"
        ).group_by(SchemaDefinition.table_name).order_by(SchemaDefinition.table_name)

        result = await db.execute(stmt)
        tables = result.fetchall()

        return [
            TableInfo(name=name, column_count=count)
            for name, count in tables
        ]

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/schema/tables/{connector_id}/{table_name}", response_model=TableSchemaResponse)
async def get_table_schema(
    connector_id: UUID,
    table_name: str,
    db: AsyncSession = Depends(get_db),
):
    """Get detailed schema for a specific table including semantic definitions."""
    try:
        # Verify connector exists
        stmt = select(Connector).where(Connector.id == connector_id)
        result = await db.execute(stmt)
        connector = result.scalar_one_or_none()

        if not connector:
            raise HTTPException(status_code=404, detail="Connector not found")

        # Get schema definitions for this table
        stmt = select(SchemaDefinition).where(
            SchemaDefinition.connector_id == connector_id,
            SchemaDefinition.table_name == table_name
        ).order_by(SchemaDefinition.definition_type)

        result = await db.execute(stmt)
        definitions = list(result.scalars().all())

        if not definitions:
            raise HTTPException(
                status_code=404,
                detail=f"Table '{table_name}' not found in connector"
            )

        # Extract table definition
        table_def = next(
            (d for d in definitions if d.definition_type == "table"),
            None
        )

        # Extract column definitions
        columns = [
            ColumnInfo(
                name=d.column_name,
                data_type=d.data_type,
                semantic_definition=d.semantic_definition,
                sample_values=d.sample_values,
            )
            for d in definitions
            if d.definition_type == "column"
        ]

        return TableSchemaResponse(
            table_name=table_name,
            table_definition=table_def.semantic_definition if table_def else None,
            columns=columns,
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
