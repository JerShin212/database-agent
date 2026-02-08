"""
Connector service for managing external database connections.

Handles CRUD operations for connectors with encrypted credentials.
"""

from typing import Literal
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.connector import Connector
from src.services.database_connector import DatabaseConnector
from src.utils.encryption import encryption_service


class ConnectorService:
    """Service for managing database connectors (instance-based)."""

    def __init__(self, db: AsyncSession):
        """
        Initialize connector service.

        Args:
            db: AsyncSession for database operations
        """
        self.db = db

    async def create_connector(
        self,
        user_id: UUID,
        name: str,
        db_type: Literal["sqlite", "postgresql", "mysql"],
        connection_string: str,
    ) -> Connector:
        """
        Create a new database connector.

        Args:
            user_id: User ID who owns this connector
            name: Human-readable name for the connector
            db_type: Database type
            connection_string: Plaintext connection string (will be encrypted)

        Returns:
            Created Connector object
        """
        # Encrypt connection string
        encrypted_connection_string = encryption_service.encrypt(connection_string)

        # Create connector
        connector = Connector(
            user_id=user_id,
            name=name,
            db_type=db_type,
            connection_string=encrypted_connection_string,
            status="pending",
        )

        self.db.add(connector)
        await self.db.commit()
        await self.db.refresh(connector)

        return connector

    async def test_connector(self, connector_id: UUID) -> tuple[bool, str]:
        """
        Test if connector can connect to database.

        Args:
            connector_id: UUID of connector to test

        Returns:
            Tuple of (success: bool, message: str)
        """
        # Get connector
        connector = await self.get_connector(connector_id)
        if not connector:
            return False, "Connector not found"

        # Decrypt connection string
        try:
            connection_string = encryption_service.decrypt(connector.connection_string)
        except Exception as e:
            return False, f"Failed to decrypt connection string: {str(e)}"

        # Test connection
        db_connector = DatabaseConnector(connection_string)
        return db_connector.test_connection()

    async def update_connector_status(
        self,
        connector_id: UUID,
        status: Literal["pending", "indexing", "ready", "failed"],
        progress: dict | None = None,
        error_message: str | None = None,
    ) -> None:
        """
        Update connector status and progress.

        Args:
            connector_id: UUID of connector to update
            status: New status
            progress: Optional progress information
            error_message: Optional error message (for failed status)
        """
        update_values = {"status": status}

        if progress is not None:
            update_values["indexing_progress"] = progress

        if error_message is not None:
            update_values["error_message"] = error_message

        stmt = (
            update(Connector)
            .where(Connector.id == connector_id)
            .values(**update_values)
        )

        await self.db.execute(stmt)
        await self.db.commit()

    async def get_connector(self, connector_id: UUID) -> Connector | None:
        """
        Get connector by ID.

        Args:
            connector_id: UUID of connector

        Returns:
            Connector object or None if not found
        """
        stmt = select(Connector).where(Connector.id == connector_id)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def list_connectors(
        self,
        user_id: UUID | None = None,
        status: str | None = None,
    ) -> list[Connector]:
        """
        List connectors with optional filters.

        Args:
            user_id: Filter by user ID
            status: Filter by status

        Returns:
            List of Connector objects
        """
        stmt = select(Connector)

        if user_id:
            stmt = stmt.where(Connector.user_id == user_id)

        if status:
            stmt = stmt.where(Connector.status == status)

        stmt = stmt.order_by(Connector.created_at.desc())

        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def delete_connector(self, connector_id: UUID) -> bool:
        """
        Delete a connector and all associated schema data.

        Args:
            connector_id: UUID of connector to delete

        Returns:
            True if deleted, False if not found
        """
        connector = await self.get_connector(connector_id)
        if not connector:
            return False

        await self.db.delete(connector)
        await self.db.commit()

        return True

    def get_database_connector(self, connector: Connector) -> DatabaseConnector:
        """
        Get DatabaseConnector instance for a connector.

        Args:
            connector: Connector object

        Returns:
            DatabaseConnector instance with decrypted connection string
        """
        connection_string = encryption_service.decrypt(connector.connection_string)
        return DatabaseConnector(connection_string)
