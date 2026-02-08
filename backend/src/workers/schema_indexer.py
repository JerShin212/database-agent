"""
Schema indexer for background processing.

Introspects database schemas and generates semantic definitions with embeddings.
"""

import asyncio
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from src.models.connector import Connector, SchemaDefinition, SchemaRelationship
from src.services.connector_service import ConnectorService
from src.services.definition_generator import definition_generator
from src.services.embedding_service import embedding_service
from src.services.schema_inspector import SchemaInspector


class SchemaIndexer:
    """Singleton service for indexing database schemas."""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    async def index_connector_schema(
        self,
        db: AsyncSession,
        connector_id: UUID,
    ) -> None:
        """
        Index a connector's database schema.

        Pipeline:
        1. Update status to "indexing"
        2. Introspect schema
        3. For each table:
           - Generate and embed table definition
           - For each column:
             - Generate and embed column definition
           - Update progress
        4. Store foreign key relationships
        5. Update status to "ready" or "failed"

        Args:
            db: AsyncSession for database operations
            connector_id: UUID of connector to index
        """
        connector_service = ConnectorService(db)

        try:
            # Get connector
            connector = await connector_service.get_connector(connector_id)
            if not connector:
                raise ValueError(f"Connector {connector_id} not found")

            # Update status to indexing
            await connector_service.update_connector_status(
                connector_id,
                status="indexing",
                progress={"stage": "starting", "current": 0, "total": 0}
            )

            # Get database connector
            db_connector = connector_service.get_database_connector(connector)

            # Stage 1: Introspect schema
            await connector_service.update_connector_status(
                connector_id,
                status="indexing",
                progress={"stage": "introspection", "current": 0, "total": 0}
            )

            inspector = SchemaInspector(db_connector)
            schema_info = inspector.introspect_full_schema()
            tables = schema_info["tables"]

            if not tables:
                await connector_service.update_connector_status(
                    connector_id,
                    status="failed",
                    error_message="No tables found in database"
                )
                return

            # Stage 2: Generate and store definitions
            total_items = len(tables) + sum(len(t["columns"]) for t in tables)
            current_item = 0

            for table in tables:
                table_name = table["name"]

                # Generate table definition
                await connector_service.update_connector_status(
                    connector_id,
                    status="indexing",
                    progress={
                        "stage": "generating_definitions",
                        "current": current_item,
                        "total": total_items,
                        "table": table_name,
                        "item": "table"
                    }
                )

                table_definition = await definition_generator.generate_table_definition(
                    table_name=table_name,
                    columns=table["columns"],
                    row_count=table.get("row_count"),
                    foreign_keys=table["foreign_keys"],
                )

                # Embed table definition
                table_embedding_text = f"{table_name}: {table_definition}"
                table_embedding = await embedding_service.embed_text(table_embedding_text)

                # Store table definition
                table_def = SchemaDefinition(
                    connector_id=connector_id,
                    definition_type="table",
                    table_name=table_name,
                    semantic_definition=table_definition,
                    embedding=table_embedding,
                )
                db.add(table_def)
                current_item += 1

                # Generate column definitions
                for column in table["columns"]:
                    column_name = column["name"]

                    await connector_service.update_connector_status(
                        connector_id,
                        status="indexing",
                        progress={
                            "stage": "generating_definitions",
                            "current": current_item,
                            "total": total_items,
                            "table": table_name,
                            "column": column_name,
                            "item": "column"
                        }
                    )

                    # Find FK info for this column
                    fk_info = None
                    for fk in table["foreign_keys"]:
                        if column_name in fk["from_columns"]:
                            fk_info = {
                                "to_table": fk["to_table"],
                                "to_column": fk["to_columns"][0] if fk["to_columns"] else None
                            }
                            break

                    # Generate column definition
                    column_definition = await definition_generator.generate_column_definition(
                        table_name=table_name,
                        column_name=column_name,
                        data_type=column["type"],
                        nullable=column["nullable"],
                        patterns=column.get("patterns", []),
                        sample_values=column.get("sample_values", []),
                        foreign_key_info=fk_info,
                    )

                    # Embed column definition
                    column_embedding_text = f"{table_name}.{column_name}: {column_definition}"
                    column_embedding = await embedding_service.embed_text(column_embedding_text)

                    # Convert sample values to JSON-serializable format
                    sample_values_json = [
                        str(v) if v is not None else None
                        for v in column.get("sample_values", [])
                    ]

                    # Store column definition
                    column_def = SchemaDefinition(
                        connector_id=connector_id,
                        definition_type="column",
                        table_name=table_name,
                        column_name=column_name,
                        data_type=column["type"],
                        semantic_definition=column_definition,
                        sample_values=sample_values_json,
                        embedding=column_embedding,
                    )
                    db.add(column_def)
                    current_item += 1

                # Commit after each table
                await db.commit()

            # Stage 3: Store foreign key relationships
            await connector_service.update_connector_status(
                connector_id,
                status="indexing",
                progress={
                    "stage": "storing_relationships",
                    "current": current_item,
                    "total": total_items
                }
            )

            for table in tables:
                for fk in table["foreign_keys"]:
                    relationship = SchemaRelationship(
                        connector_id=connector_id,
                        from_table=table["name"],
                        from_column=",".join(fk["from_columns"]),
                        to_table=fk["to_table"],
                        to_column=",".join(fk["to_columns"]),
                        relationship_type="foreign_key",
                    )
                    db.add(relationship)

            await db.commit()

            # Stage 4: Mark as ready
            await connector_service.update_connector_status(
                connector_id,
                status="ready",
                progress={
                    "stage": "completed",
                    "current": total_items,
                    "total": total_items
                }
            )

        except Exception as e:
            # Mark as failed
            error_message = f"Schema indexing failed: {str(e)}"
            await connector_service.update_connector_status(
                connector_id,
                status="failed",
                error_message=error_message
            )
            raise


# Singleton instance
schema_indexer = SchemaIndexer()
