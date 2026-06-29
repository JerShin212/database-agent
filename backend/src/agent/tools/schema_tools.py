"""
Schema catalog search tools for semantic database exploration.

Retrieval architecture (v2):
  Signal 1: BM25 full-text search over names, definitions, and enriched text
  Signal 2: cosine similarity over mean-pooled ColQwen2 embeddings
  Signal 3: value match — query tokens against stored sample values, so a
            query containing a literal ("Janet") finds the column whose
            DATA contains it
  -> Reciprocal Rank Fusion (k=60)
  -> MaxSim late-interaction rerank over full multi-vectors (top 30)
  -> join-aware formatting: results grouped by table with FK JOIN hints
"""

from __future__ import annotations

import logging
from uuid import UUID

import numpy as np
from sqlalchemy import text

from src.db.database import SyncSessionLocal
from src.services.rrf import reciprocal_rank_fusion
from src.services.schema_serializer import extract_value_tokens

logger = logging.getLogger(__name__)

_SELECT_COLS = """id, definition_type, table_name, column_name, data_type,
       semantic_definition, sample_values, multi_embedding, n_vectors"""

_MAXSIM_CANDIDATES = 30


def _row_to_entry(row, score) -> dict:
    return {
        "definition_id": row[0],
        "definition_type": row[1],
        "table_name": row[2],
        "column_name": row[3],
        "data_type": row[4],
        "semantic_definition": row[5],
        "sample_values": row[6],
        "multi_embedding": row[7],
        "n_vectors": row[8],
        "score": float(score or 0.0),
    }


def retrieve_schema_entries(
    query: str,
    connector_uuid: UUID,
    limit: int = 5,
    *,
    use_value_signal: bool = True,
    use_maxsim: bool = True,
) -> list[dict]:
    """
    Pure retrieval core (no formatting) — also used by the evaluation harness.
    The keyword arguments are ablation toggles for measuring each component's
    contribution to accuracy.
    """
    from src.services.colqwen2_client import colqwen2_client
    from src.services.maxsim import rerank_pages_maxsim

    query_multivector = colqwen2_client.embed_text_multivector_sync(query)
    if not query_multivector:
        raise RuntimeError("Text embedding endpoint is not configured.")
    pooled = np.array(query_multivector, dtype=np.float32).mean(axis=0).tolist()

    fetch_limit = max(limit * 6, _MAXSIM_CANDIDATES)

    with SyncSessionLocal() as db:
        # Signal 1: BM25 keyword search (FTS covers names, definitions, and
        # the enriched embedding_text at weight C)
        keyword_sql = text(f"""
            SELECT {_SELECT_COLS},
                   COALESCE(bm25_rank(search_vector, websearch_to_tsquery('english', :query),
                             content_length, 500.0, 1.2, 0.75), 0.0) as score
            FROM schema_definitions
            WHERE search_vector @@ websearch_to_tsquery('english', :query)
            AND connector_id = :connector_id
            ORDER BY score DESC
            LIMIT :limit
        """)
        keyword_rows = db.execute(keyword_sql, {
            "query": query,
            "connector_id": str(connector_uuid),
            "limit": fetch_limit,
        }).fetchall()
        keyword_results = [_row_to_entry(r, r[9]) for r in keyword_rows]

        # Signal 2: semantic cosine search over mean-pooled embeddings.
        # embedding IS NOT NULL guards rows whose embedding failed at index
        # time (previously caused float(None) crashes).
        embedding_literal = "ARRAY[" + ",".join(str(x) for x in pooled) + "]::vector"
        semantic_sql = text(f"""
            SELECT {_SELECT_COLS},
                   (1.0 - (embedding <=> {embedding_literal})) as score
            FROM schema_definitions
            WHERE connector_id = :connector_id
            AND embedding IS NOT NULL
            ORDER BY embedding <=> {embedding_literal}
            LIMIT :limit
        """)
        semantic_rows = db.execute(semantic_sql, {
            "connector_id": str(connector_uuid),
            "limit": fetch_limit,
        }).fetchall()
        semantic_results = [_row_to_entry(r, r[9]) for r in semantic_rows]

        # Signal 3: value match — does any stored sample value contain a
        # token from the query? Catches literal-value queries like "Janet".
        value_results: list[dict] = []
        tokens = extract_value_tokens(query) if use_value_signal else []
        if tokens:
            patterns = [f"%{t}%" for t in tokens]
            value_sql = text(f"""
                SELECT {_SELECT_COLS},
                       (SELECT count(*) FROM unnest(CAST(:patterns AS text[])) p
                        WHERE sample_values::text ILIKE p) as score
                FROM schema_definitions
                WHERE connector_id = :connector_id
                AND definition_type = 'column'
                AND sample_values IS NOT NULL
                AND sample_values::text ILIKE ANY(CAST(:patterns AS text[]))
                ORDER BY score DESC
                LIMIT :limit
            """)
            value_rows = db.execute(value_sql, {
                "patterns": patterns,
                "connector_id": str(connector_uuid),
                "limit": fetch_limit,
            }).fetchall()
            value_results = [_row_to_entry(r, r[9]) for r in value_rows]

    result_lists = [lst for lst in (keyword_results, semantic_results, value_results) if lst]
    if not result_lists:
        return []

    fused = reciprocal_rank_fusion(
        result_lists=result_lists,
        key_fn=lambda x: x["definition_id"],
        k=60,
    )
    candidates = fused[:_MAXSIM_CANDIDATES]

    if use_maxsim:
        results = rerank_pages_maxsim(query_multivector, candidates, top_k=limit)
    else:
        results = candidates[:limit]

    # Strip the raw buffers before returning
    return [
        {k: v for k, v in r.items() if k not in ("multi_embedding", "n_vectors")}
        for r in results
    ]


def _fetch_table_context(db, connector_uuid: UUID, table_names: list[str]) -> tuple[dict, list]:
    """Table-level definitions and FK relationships for the matched tables."""
    if not table_names:
        return {}, []

    table_defs = db.execute(text("""
        SELECT table_name, semantic_definition
        FROM schema_definitions
        WHERE connector_id = :connector_id
        AND definition_type = 'table'
        AND table_name = ANY(CAST(:tables AS text[]))
    """), {"connector_id": str(connector_uuid), "tables": table_names}).fetchall()

    relationships = db.execute(text("""
        SELECT from_table, from_column, to_table, to_column
        FROM schema_relationships
        WHERE connector_id = :connector_id
        AND (from_table = ANY(CAST(:tables AS text[]))
             OR to_table = ANY(CAST(:tables AS text[])))
    """), {"connector_id": str(connector_uuid), "tables": table_names}).fetchall()

    return {row[0]: row[1] for row in table_defs}, relationships


def search_schema_catalog(query: str, context, connector_id: str = None, limit: int = 5) -> str:
    """
    Search the semantic schema catalog using hybrid retrieval
    (keyword + semantic + data-value match, fused with RRF, MaxSim reranked).

    Use this tool to understand database schema before generating SQL queries.
    Include literal values from the user's question (names, emails, statuses)
    in your query — the catalog matches query words against actual column data.

    Results are grouped by table, include column types, descriptions, example
    values, and `JOIN hint:` lines listing foreign keys between matched tables.

    Args:
        query: Natural language query — concepts AND literal values
               (e.g., "customer email address", "customer name Janet")
        connector_id: Optional UUID of connector to search (auto-detected from context)
        limit: Maximum number of results to return (default 5)

    Returns:
        Schema definitions grouped by table with join hints
    """
    if not context:
        return "Error: No context available"

    target_connector_id = connector_id or (context.connector_id if context else None)

    if not target_connector_id:
        if context and context.database_id:
            return (
                "Info: The current database does not have a semantic catalog indexed yet. "
                "You can still use get_database_schema() to see the raw schema, or ask the user "
                "to index the schema for semantic search capabilities."
            )
        return "Error: No database or connector selected. Please select a database first."

    try:
        if isinstance(target_connector_id, UUID):
            connector_uuid = target_connector_id
        else:
            connector_uuid = UUID(str(target_connector_id))
    except (ValueError, TypeError):
        return f"Error: Invalid connector ID: {target_connector_id}"

    try:
        results = retrieve_schema_entries(query, connector_uuid, limit)

        if not results:
            return f"NO_RESULTS: No schema definitions found matching '{query}'."

        # Group results by table, preserving best-rank order of tables
        tables_in_order: list[str] = []
        by_table: dict[str, list[dict]] = {}
        for result in results:
            table = result["table_name"]
            if table not in by_table:
                by_table[table] = []
                tables_in_order.append(table)
            by_table[table].append(result)

        with SyncSessionLocal() as db:
            table_definitions, relationships = _fetch_table_context(
                db, connector_uuid, tables_in_order
            )

        lines = [f"# Schema Search Results for: {query}", ""]

        for table in tables_in_order:
            lines.append(f"## Table: {table}")
            table_def = table_definitions.get(table)
            # Table-level match may carry the definition itself
            if not table_def:
                for r in by_table[table]:
                    if r["definition_type"] == "table":
                        table_def = r["semantic_definition"]
                        break
            if table_def:
                lines.append(table_def)

            column_matches = [r for r in by_table[table] if r["definition_type"] == "column"]
            if column_matches:
                lines.append("")
                lines.append("Matched columns:")
                for r in column_matches:
                    data_type = f" ({r['data_type']})" if r["data_type"] else ""
                    lines.append(f"- {table}.{r['column_name']}{data_type}")
                    if r["semantic_definition"]:
                        lines.append(f"  {r['semantic_definition']}")
                    if r["sample_values"]:
                        samples = ", ".join(str(v) for v in r["sample_values"][:5])
                        lines.append(f"  Examples: {samples}")
            lines.append("")

        if relationships:
            lines.append("## Join hints (foreign keys)")
            seen = set()
            for from_table, from_column, to_table, to_column in relationships:
                hint = f"- JOIN hint: {from_table}.{from_column} = {to_table}.{to_column}"
                if hint not in seen:
                    seen.add(hint)
                    lines.append(hint)
            lines.append("")

        lines.append("---")
        lines.append("Use the exact table/column names above in SQL. "
                      "Use the JOIN hints when combining tables.")

        return "\n".join(lines)

    except Exception as e:
        logger.error("[search_schema_catalog] %s", e, exc_info=True)
        return f"Error searching schema catalog: {str(e)}"
