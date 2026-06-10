"""
Schema indexer for background processing.

Introspects database schemas and generates semantic definitions with embeddings.
"""

import asyncio
from uuid import UUID

import numpy as np
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.connector import Connector, SchemaDefinition, SchemaRelationship
from src.services.colqwen2_client import colqwen2_client
from src.services.connector_service import ConnectorService
from src.services.definition_generator import definition_generator
from src.services.schema_inspector import SchemaInspector
from src.services.schema_serializer import build_column_text, build_table_text


def _pack_multivector(multivector: list[list[float]]) -> tuple[list[float] | None, bytes | None, int | None]:
    """(pooled 128-dim, float16 bytes, n_vectors) from a multi-vector; Nones if empty."""
    if not multivector:
        return None, None, None
    arr = np.array(multivector, dtype=np.float32)
    pooled = arr.mean(axis=0).tolist()
    packed = arr.astype(np.float16).tobytes()
    return pooled, packed, arr.shape[0]


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

            # Re-indexing replaces the catalog — remove any previous entries
            # (without this, every re-index duplicated all definitions)
            await db.execute(
                delete(SchemaDefinition).where(SchemaDefinition.connector_id == connector_id)
            )
            await db.execute(
                delete(SchemaRelationship).where(SchemaRelationship.connector_id == connector_id)
            )
            await db.commit()

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

                # Enriched serialization — this is what gets embedded AND
                # matched by FTS (weight C), so it includes humanized name
                # tokens, types, patterns, FK targets, and sample values.
                table_text = build_table_text(
                    table_name=table_name,
                    definition=table_definition,
                    column_names=[c["name"] for c in table["columns"]],
                    row_count=table.get("row_count"),
                )
                current_item += 1

                # Generate column definitions (LLM, serial) and enriched texts
                column_entries = []
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

                    column_definition = await definition_generator.generate_column_definition(
                        table_name=table_name,
                        column_name=column_name,
                        data_type=column["type"],
                        nullable=column["nullable"],
                        patterns=column.get("patterns", []),
                        sample_values=column.get("sample_values", []),
                        foreign_key_info=fk_info,
                    )

                    sample_values_json = [
                        str(v) if v is not None else None
                        for v in column.get("sample_values", [])
                    ]

                    fk_target = None
                    if fk_info and fk_info.get("to_column"):
                        fk_target = f"{fk_info['to_table']}.{fk_info['to_column']}"

                    column_text = build_column_text(
                        table_name=table_name,
                        column_name=column_name,
                        data_type=column["type"],
                        patterns=column.get("patterns", []),
                        definition=column_definition,
                        sample_values=sample_values_json,
                        fk_target=fk_target,
                    )

                    column_entries.append({
                        "column": column,
                        "definition": column_definition,
                        "embedding_text": column_text,
                        "sample_values": sample_values_json,
                    })
                    current_item += 1

                # One batched Modal call per table: table text + all column texts.
                # Multi-vectors give us both the pooled ANN vector and the
                # MaxSim rerank representation from a single round-trip each.
                texts = [table_text] + [e["embedding_text"] for e in column_entries]
                multivectors = await colqwen2_client.embed_batch_multivector(texts)

                pooled, packed, n_vec = _pack_multivector(multivectors[0])
                db.add(SchemaDefinition(
                    connector_id=connector_id,
                    definition_type="table",
                    table_name=table_name,
                    semantic_definition=table_definition,
                    embedding=pooled,
                    embedding_text=table_text,
                    multi_embedding=packed,
                    n_vectors=n_vec,
                ))

                for entry, multivector in zip(column_entries, multivectors[1:]):
                    pooled, packed, n_vec = _pack_multivector(multivector)
                    db.add(SchemaDefinition(
                        connector_id=connector_id,
                        definition_type="column",
                        table_name=table_name,
                        column_name=entry["column"]["name"],
                        data_type=entry["column"]["type"],
                        semantic_definition=entry["definition"],
                        sample_values=entry["sample_values"],
                        embedding=pooled,
                        embedding_text=entry["embedding_text"],
                        multi_embedding=packed,
                        n_vectors=n_vec,
                    ))

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


async def index_connector_schema_background(connector_id: UUID) -> None:
    """
    Run schema indexing as a FastAPI background task.

    Opens its own database session because the request-scoped session is
    closed by the time background tasks execute. Failures are recorded on
    the connector status by index_connector_schema itself.
    """
    from src.db.database import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        try:
            await schema_indexer.index_connector_schema(session, connector_id)
        except Exception:
            # Status is already set to "failed" with the error message;
            # nothing useful to do here beyond not crashing the task runner.
            pass
