"""
Schema catalog search tools for semantic database exploration.

Enables agents to search schema definitions using hybrid search (BM25 + semantic + RRF)
to understand database structure and generate accurate SQL queries.
"""

from uuid import UUID

from src.agent.tools.context import get_tool_context
from src.db.database import SyncSessionLocal
from sqlalchemy import text
from src.services.rrf import reciprocal_rank_fusion


def search_schema_catalog(query: str, connector_id: str = None, limit: int = 5) -> str:
    """
    Search schema catalog using hybrid search (keyword + semantic + RRF).

    Use this tool to understand database schema before generating SQL queries.
    It returns table and column definitions with business context to help
    you write accurate queries.

    This tool works automatically with the currently selected database if it has
    a semantic catalog indexed.

    Args:
        query: Natural language query describing what you're looking for
               (e.g., "customer email address", "order total amount")
        connector_id: Optional UUID of connector to search (auto-detected from context)
        limit: Maximum number of results to return (default 5)

    Returns:
        Formatted schema definitions with semantic context and sample values
    """
    context = get_tool_context()
    if not context:
        return "Error: No context available"

    # Determine connector ID from parameter or context
    target_connector_id = connector_id or (context.connector_id if context else None)

    if not target_connector_id:
        # Check if we have a database_id and can look up the connector
        if context and context.database_id:
            return (
                f"Info: The current database does not have a semantic catalog indexed yet. "
                f"You can still use get_database_schema() to see the raw schema, or ask the user "
                f"to index the schema for semantic search capabilities."
            )
        return "Error: No database or connector selected. Please select a database first."

    # Handle both UUID objects and string UUIDs
    try:
        if isinstance(target_connector_id, UUID):
            connector_uuid = target_connector_id
        else:
            connector_uuid = UUID(str(target_connector_id))
    except (ValueError, TypeError):
        return f"Error: Invalid connector ID: {target_connector_id}"

    try:
        # Generate embedding for semantic search via ColQwen2
        from src.services.colqwen2_client import colqwen2_client
        query_embedding = colqwen2_client.embed_text_sync(query)
        if not query_embedding:
            return "Error: Text embedding endpoint is not configured."

        # Use sync session for database access
        with SyncSessionLocal() as db:
            fetch_limit = limit * 3

            # 1. BM25-like Keyword search (PostgreSQL FTS)
            keyword_sql = text("""
                SELECT id, connector_id, definition_type, table_name, column_name,
                       data_type, semantic_definition, sample_values,
                       bm25_rank(search_vector, websearch_to_tsquery('english', :query),
                                 content_length, 500.0, 1.2, 0.75) as score
                FROM schema_definitions
                WHERE search_vector @@ websearch_to_tsquery('english', :query)
                AND connector_id = :connector_id
                ORDER BY score DESC
                LIMIT :limit
            """)
            keyword_result = db.execute(keyword_sql, {
                "query": query,
                "connector_id": str(connector_uuid),
                "limit": fetch_limit
            })
            keyword_rows = keyword_result.fetchall()

            # 2. Cosine Similarity Semantic search
            embedding_literal = "ARRAY[" + ",".join(str(x) for x in query_embedding) + "]::vector"
            semantic_sql = text(f"""
                SELECT id, connector_id, definition_type, table_name, column_name,
                       data_type, semantic_definition, sample_values,
                       (1.0 - (embedding <=> {embedding_literal})) as score
                FROM schema_definitions
                WHERE connector_id = :connector_id
                ORDER BY embedding <=> {embedding_literal}
                LIMIT :limit
            """)
            semantic_result = db.execute(semantic_sql, {
                "connector_id": str(connector_uuid),
                "limit": fetch_limit
            })
            semantic_rows = semantic_result.fetchall()

            # Convert to dict format
            keyword_results = [
                {
                    "definition_id": row[0],
                    "definition_type": row[2],
                    "table_name": row[3],
                    "column_name": row[4],
                    "data_type": row[5],
                    "semantic_definition": row[6],
                    "sample_values": row[7],
                    "score": float(row[8])
                }
                for row in keyword_rows
            ]
            semantic_results = [
                {
                    "definition_id": row[0],
                    "definition_type": row[2],
                    "table_name": row[3],
                    "column_name": row[4],
                    "data_type": row[5],
                    "semantic_definition": row[6],
                    "sample_values": row[7],
                    "score": float(row[8])
                }
                for row in semantic_rows
            ]

            # 3. Apply Reciprocal Rank Fusion
            combined = reciprocal_rank_fusion(
                result_lists=[keyword_results, semantic_results],
                key_fn=lambda x: x["definition_id"],
                k=60,
            )

            # Take top results
            results = combined[:limit]

            if not results:
                return f"No schema definitions found matching '{query}'."

            # Format results
            lines = [f"# Schema Search Results for: {query}", ""]

            for i, result in enumerate(results, 1):
                score = result.get("score", 0.0)
                definition_type = result.get("definition_type", "unknown")
                table_name = result.get("table_name", "")
                column_name = result.get("column_name", "")
                data_type = result.get("data_type", "")
                semantic_definition = result.get("semantic_definition", "")
                sample_values = result.get("sample_values", [])

                lines.append(f"## Result {i} (relevance: {score:.3f})")

                if definition_type == "table":
                    lines.append(f"**Table**: {table_name}")
                    lines.append(f"**Description**: {semantic_definition}")
                elif definition_type == "column":
                    lines.append(f"**Column**: {table_name}.{column_name} ({data_type})")
                    lines.append(f"**Description**: {semantic_definition}")

                    if sample_values:
                        sample_str = ", ".join(str(v) for v in sample_values[:3])
                        lines.append(f"**Examples**: {sample_str}")

                lines.append("")

            lines.append("---")
            lines.append(f"Showing top {len(results)} of {limit} requested results.")
            lines.append("Use this context to generate accurate SQL queries.")

            return "\n".join(lines)

    except Exception as e:
        return f"Error searching schema catalog: {str(e)}"
