"""
API endpoints for database connector management.

Handles creating, listing, testing, indexing, and deleting external database connectors.
"""

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.database import get_db
from src.services.connector_service import ConnectorService
from src.workers.schema_indexer import schema_indexer


router = APIRouter()


# ===== Request/Response Models =====

class CreateConnectorRequest(BaseModel):
    """Request to create a new connector."""
    name: str
    db_type: Literal["sqlite", "postgresql", "mysql"]
    connection_string: str
    user_id: str  # In production, this would come from authentication


class ConnectorResponse(BaseModel):
    """Response model for connector."""
    id: str
    user_id: str
    name: str
    db_type: str
    status: str
    indexing_progress: dict | None
    error_message: str | None
    created_at: str
    updated_at: str


class TestConnectionResponse(BaseModel):
    """Response for connection test."""
    success: bool
    message: str


# ===== Endpoints =====

@router.post("/connectors", response_model=ConnectorResponse)
async def create_connector(
    request: CreateConnectorRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Create a new database connector.

    The connection string will be encrypted before storage.
    """
    try:
        connector_service = ConnectorService(db)

        # Create connector
        connector = await connector_service.create_connector(
            user_id=UUID(request.user_id),
            name=request.name,
            db_type=request.db_type,
            connection_string=request.connection_string,
        )

        return ConnectorResponse(
            id=str(connector.id),
            user_id=str(connector.user_id),
            name=connector.name,
            db_type=connector.db_type,
            status=connector.status,
            indexing_progress=connector.indexing_progress,
            error_message=connector.error_message,
            created_at=connector.created_at.isoformat(),
            updated_at=connector.updated_at.isoformat(),
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/connectors", response_model=list[ConnectorResponse])
async def list_connectors(
    user_id: str = None,
    status: str = None,
    db: AsyncSession = Depends(get_db),
):
    """List all connectors with optional filters."""
    try:
        connector_service = ConnectorService(db)

        user_uuid = UUID(user_id) if user_id else None
        connectors = await connector_service.list_connectors(
            user_id=user_uuid,
            status=status,
        )

        return [
            ConnectorResponse(
                id=str(c.id),
                user_id=str(c.user_id),
                name=c.name,
                db_type=c.db_type,
                status=c.status,
                indexing_progress=c.indexing_progress,
                error_message=c.error_message,
                created_at=c.created_at.isoformat(),
                updated_at=c.updated_at.isoformat(),
            )
            for c in connectors
        ]

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/connectors/{connector_id}", response_model=ConnectorResponse)
async def get_connector(
    connector_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Get connector details by ID."""
    try:
        connector_service = ConnectorService(db)
        connector = await connector_service.get_connector(connector_id)

        if not connector:
            raise HTTPException(status_code=404, detail="Connector not found")

        return ConnectorResponse(
            id=str(connector.id),
            user_id=str(connector.user_id),
            name=connector.name,
            db_type=connector.db_type,
            status=connector.status,
            indexing_progress=connector.indexing_progress,
            error_message=connector.error_message,
            created_at=connector.created_at.isoformat(),
            updated_at=connector.updated_at.isoformat(),
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/connectors/{connector_id}/test", response_model=TestConnectionResponse)
async def test_connector(
    connector_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Test if connector can connect to database."""
    try:
        connector_service = ConnectorService(db)
        success, message = await connector_service.test_connector(connector_id)

        return TestConnectionResponse(
            success=success,
            message=message,
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/connectors/{connector_id}/index")
async def index_connector_schema(
    connector_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """
    Trigger schema indexing for a connector.

    This will:
    1. Introspect the database schema
    2. Generate semantic definitions using LLM
    3. Embed definitions for search
    4. Store in schema catalog

    Returns immediately while indexing runs in background.
    """
    try:
        connector_service = ConnectorService(db)
        connector = await connector_service.get_connector(connector_id)

        if not connector:
            raise HTTPException(status_code=404, detail="Connector not found")

        # Test connection first
        success, message = await connector_service.test_connector(connector_id)
        if not success:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot index: Connection test failed - {message}"
            )

        # Start indexing (runs synchronously for now)
        # In production, this would be a background task
        await schema_indexer.index_connector_schema(db, connector_id)

        return {
            "message": "Schema indexing completed",
            "connector_id": str(connector_id),
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/connectors/{connector_id}")
async def delete_connector(
    connector_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """
    Delete a connector and all associated schema data.

    This will cascade delete:
    - Schema definitions
    - Schema relationships
    """
    try:
        connector_service = ConnectorService(db)
        deleted = await connector_service.delete_connector(connector_id)

        if not deleted:
            raise HTTPException(status_code=404, detail="Connector not found")

        return {
            "message": "Connector deleted successfully",
            "connector_id": str(connector_id),
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
