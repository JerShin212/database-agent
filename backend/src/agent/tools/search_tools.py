from uuid import UUID

from src.agent.tools.context import get_tool_context
from src.db.database import SyncSessionLocal
from src.models.collection import Collection


def search_collections(query: str, collection_ids: str = None, limit: int = 5) -> str:
    """
    Search document collections using hybrid search (keyword + semantic with RRF).

    Combines BM25 keyword search and cosine similarity semantic search for optimal
    results across different query types:
    - Exact matches (model codes, IDs, names)
    - Semantic queries (concepts, questions)
    - Mixed queries

    Args:
        query: Natural language search query
        collection_ids: Optional comma-separated list of collection IDs to search
        limit: Maximum number of results (default 5)

    Returns:
        Relevant document chunks with citations and relevance scores
    """
    from sqlalchemy import text
    from src.config import settings
    import openai
    from src.services.rrf import reciprocal_rank_fusion

    context = get_tool_context()

    # Parse collection IDs
    coll_ids = None
    if collection_ids:
        try:
            coll_ids = [UUID(cid.strip()) for cid in collection_ids.split(",")]
        except ValueError:
            return "Error: Invalid collection ID format"
    elif context and context.collection_ids:
        coll_ids = context.collection_ids

    try:
        # Generate embedding for semantic search
        client = openai.OpenAI(api_key=settings.openai_api_key)
        response = client.embeddings.create(
            model=settings.embedding_model,
            input=query,
        )
        query_embedding = response.data[0].embedding

        with SyncSessionLocal() as db:
            fetch_limit = limit * 3

            # Build collection filter
            if coll_ids:
                coll_ids_str = ",".join(f"'{str(cid)}'" for cid in coll_ids)
                coll_filter_bm25 = f"AND dc.collection_id IN ({coll_ids_str})"
                coll_filter_semantic = f"WHERE dc.collection_id IN ({coll_ids_str})"
            else:
                coll_filter_bm25 = ""
                coll_filter_semantic = ""

            # 1. BM25-like Keyword search (PostgreSQL FTS)
            keyword_sql = text(f"""
                SELECT dc.id, dc.content, dc.chunk_index, d.filename,
                       bm25_rank(dc.search_vector, websearch_to_tsquery('english', :query),
                                 dc.content_length, 500.0, 1.2, 0.75) as score
                FROM document_chunks dc
                JOIN documents d ON dc.document_id = d.id
                WHERE dc.search_vector @@ websearch_to_tsquery('english', :query)
                {coll_filter_bm25}
                ORDER BY score DESC
                LIMIT :limit
            """)
            keyword_result = db.execute(keyword_sql, {"query": query, "limit": fetch_limit})
            keyword_rows = keyword_result.fetchall()

            # 2. Cosine Similarity Semantic search
            embedding_literal = "ARRAY[" + ",".join(str(x) for x in query_embedding) + "]::vector"
            semantic_sql = text(f"""
                SELECT dc.id, dc.content, dc.chunk_index, d.filename,
                       (1.0 - (dc.embedding <=> {embedding_literal})) as score
                FROM document_chunks dc
                JOIN documents d ON dc.document_id = d.id
                {coll_filter_semantic}
                ORDER BY dc.embedding <=> {embedding_literal}
                LIMIT :limit
            """)
            semantic_result = db.execute(semantic_sql, {"limit": fetch_limit})
            semantic_rows = semantic_result.fetchall()

            # Convert to dict format
            keyword_results = [
                {"chunk_id": row[0], "content": row[1], "chunk_index": row[2],
                 "filename": row[3], "score": float(row[4])}
                for row in keyword_rows
            ]
            semantic_results = [
                {"chunk_id": row[0], "content": row[1], "chunk_index": row[2],
                 "filename": row[3], "score": float(row[4])}
                for row in semantic_rows
            ]

            # 3. Apply Reciprocal Rank Fusion
            combined = reciprocal_rank_fusion(
                result_lists=[keyword_results, semantic_results],
                key_fn=lambda x: x["chunk_id"],
                k=60,
            )

            # Take top results
            final_results = combined[:limit]

            if not final_results:
                return "No relevant documents found for your query."

            lines = [f"Found {len(final_results)} relevant document chunks (hybrid search):", ""]
            for i, result in enumerate(final_results, 1):
                lines.append(f"### Result {i} (RRF Score: {result['score']:.3f})")
                lines.append(f"**Source:** {result['filename']}")
                lines.append(f"**Content:** {result['content'][:500]}...")
                lines.append("")

            return "\n".join(lines)

    except Exception as e:
        return f"Error searching collections: {str(e)}"


def search_visual_documents(query: str, collection_ids: str = None, limit: int = 5) -> str:
    """
    Search document pages visually using ColQwen2 embeddings.

    Finds the most visually relevant PDF pages based on the query. Use this for
    queries about diagrams, figures, charts, tables, schematics, or any content
    where visual layout matters and plain text search may miss it.

    Args:
        query: Natural language description of the visual content to find
        collection_ids: Optional comma-separated list of collection IDs to search
        limit: Maximum number of page results (default 5)

    Returns:
        Relevant document pages with filename, page number, and similarity score
    """
    from sqlalchemy import text as sa_text
    from src.services.colqwen2_client import colqwen2_client
    from src.db.database import SyncSessionLocal

    if not colqwen2_client.text_endpoint:
        return (
            "Visual document search is not configured. "
            "Set COLQWEN2_TEXT_ENDPOINT in environment to enable this capability."
        )

    context = get_tool_context()

    coll_ids = None
    if collection_ids:
        try:
            coll_ids = [UUID(cid.strip()) for cid in collection_ids.split(",")]
        except ValueError:
            return "Error: Invalid collection ID format"
    elif context and context.collection_ids:
        coll_ids = context.collection_ids

    try:
        query_embedding = colqwen2_client.embed_text_sync(query)
        if not query_embedding:
            return "Visual search unavailable: failed to generate query embedding."

        embedding_literal = "ARRAY[" + ",".join(str(x) for x in query_embedding) + "]::vector"

        with SyncSessionLocal() as db:
            if coll_ids:
                coll_ids_str = ",".join(f"'{str(cid)}'" for cid in coll_ids)
                coll_filter = f"AND dp.collection_id IN ({coll_ids_str})"
            else:
                coll_filter = ""

            stmt = sa_text(f"""
                SELECT
                    dp.page_number,
                    d.filename,
                    1.0 - (dp.visual_embedding <=> {embedding_literal}) as similarity
                FROM document_pages dp
                JOIN documents d ON dp.document_id = d.id
                WHERE dp.visual_embedding IS NOT NULL
                {coll_filter}
                ORDER BY dp.visual_embedding <=> {embedding_literal}
                LIMIT :limit
            """)
            result = db.execute(stmt, {"limit": limit})
            rows = result.fetchall()

        if not rows:
            return "No visually relevant document pages found for your query."

        lines = [f"Found {len(rows)} visually relevant pages:", ""]
        for i, row in enumerate(rows, 1):
            page_number, filename, similarity = row
            lines.append(f"### Result {i} (similarity: {float(similarity):.3f})")
            lines.append(f"**Source:** {filename}, Page {page_number}")
            lines.append("")

        return "\n".join(lines)

    except Exception as e:
        return f"Error searching visual documents: {str(e)}"


def list_collections() -> str:
    """
    List all available document collections.

    Returns:
        Collection names, descriptions, and document counts
    """
    try:
        with SyncSessionLocal() as db:
            from sqlalchemy import select
            result = db.execute(
                select(Collection).order_by(Collection.created_at.desc())
            )
            collections = result.scalars().all()

            if not collections:
                return "No document collections found."

            lines = ["Available Document Collections:", ""]
            for coll in collections:
                desc = f" - {coll.description}" if coll.description else ""
                lines.append(f"- **{coll.name}** (ID: {coll.id})")
                lines.append(f"  Documents: {coll.document_count}{desc}")
                lines.append("")

            return "\n".join(lines)

    except Exception as e:
        return f"Error listing collections: {str(e)}"
