import logging
from uuid import UUID

from src.agent.tools.context import get_tool_context
from src.db.database import SyncSessionLocal
from src.models.collection import Collection

logger = logging.getLogger(__name__)


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
    from src.services.colqwen2_client import colqwen2_client
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
        # Generate embedding for semantic search via ColQwen2
        query_embedding = colqwen2_client.embed_text_sync(query)
        if not query_embedding:
            return "Error: Text embedding endpoint is not configured."

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
                return "NO_RESULTS: No relevant documents found for your query."

            lines = [f"Found {len(final_results)} relevant document chunks (hybrid search):", ""]
            for i, result in enumerate(final_results, 1):
                lines.append(f"### Result {i} (RRF Score: {result['score']:.3f})")
                lines.append(f"**Source:** {result['filename']}")
                lines.append(f"**Content:** {result['content'][:500]}...")
                lines.append("")

            return "\n".join(lines)

    except Exception as e:
        logger.error("[search_collections] %s", e, exc_info=True)
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
    from src.services.colqwen2_client import colqwen2_client
    from src.db.database import SyncSessionLocal

    if not colqwen2_client.text_endpoint:
        return (
            "Visual document search is not configured. "
            "Set COLQWEN2_TEXT_ENDPOINT in environment to enable this capability."
        )

    coll_ids, err = _parse_collection_ids(collection_ids)
    if err:
        return err

    try:
        query_multivector = colqwen2_client.embed_text_multivector_sync(query)
        if not query_multivector:
            return "Visual search unavailable: failed to generate query embedding."

        with SyncSessionLocal() as db:
            results = _two_stage_page_search(db, query_multivector, coll_ids, limit)

        if not results:
            return "NO_RESULTS: No visually relevant document pages found for your query."

        lines = [f"Found {len(results)} visually relevant pages (MaxSim reranked):", ""]
        for i, result in enumerate(results, 1):
            score = result.get("maxsim", result["score"])
            lines.append(f"### Result {i} (score: {score:.3f})")
            lines.append(f"**Source:** {result['filename']}, Page {result['page_number']}")
            lines.append("")

        return "\n".join(lines)

    except Exception as e:
        logger.error("[search_visual_documents] %s", e, exc_info=True)
        return f"Error searching visual documents: {str(e)}"


def _parse_collection_ids(collection_ids: str = None) -> tuple[list[UUID] | None, str | None]:
    """Resolve collection IDs from the argument or the tool context. Returns (ids, error)."""
    context = get_tool_context()
    if collection_ids:
        try:
            return [UUID(cid.strip()) for cid in collection_ids.split(",")], None
        except ValueError:
            return None, "Error: Invalid collection ID format"
    if context and context.collection_ids:
        return context.collection_ids, None
    return None, None


# Stage-1 ANN candidate pool size for MaxSim reranking
_MAXSIM_CANDIDATES = 30


def _search_pages_by_embedding(
    db, query_embedding: list[float], coll_ids: list[UUID] | None, limit: int
) -> list[dict]:
    """Cosine search over document_pages with a pooled query embedding."""
    from sqlalchemy import text as sa_text

    embedding_literal = "ARRAY[" + ",".join(str(x) for x in query_embedding) + "]::vector"

    if coll_ids:
        coll_ids_str = ",".join(f"'{str(cid)}'" for cid in coll_ids)
        coll_filter = f"AND dp.collection_id IN ({coll_ids_str})"
    else:
        coll_filter = ""

    stmt = sa_text(f"""
        SELECT
            dp.id,
            dp.page_number,
            d.filename,
            1.0 - (dp.visual_embedding <=> {embedding_literal}) as similarity,
            dp.multi_embedding,
            dp.n_vectors
        FROM document_pages dp
        JOIN documents d ON dp.document_id = d.id
        WHERE dp.visual_embedding IS NOT NULL
        {coll_filter}
        ORDER BY dp.visual_embedding <=> {embedding_literal}
        LIMIT :limit
    """)
    rows = db.execute(stmt, {"limit": limit}).fetchall()
    return [
        {
            "page_id": row[0],
            "page_number": row[1],
            "filename": row[2],
            "score": float(row[3]),
            "multi_embedding": row[4],
            "n_vectors": row[5],
        }
        for row in rows
    ]


def _two_stage_page_search(
    db, query_multivector: list[list[float]], coll_ids: list[UUID] | None, limit: int
) -> list[dict]:
    """
    Two-stage visual page retrieval:
      1. ANN cosine search over mean-pooled vectors (fast, approximate)
      2. MaxSim late-interaction rerank over full multi-vectors (exact)

    Pages without stored multi-vectors keep their pooled-cosine order.
    """
    import numpy as np
    from src.services.maxsim import rerank_pages_maxsim

    pooled = np.array(query_multivector, dtype=np.float32).mean(axis=0).tolist()
    candidates = _search_pages_by_embedding(db, pooled, coll_ids, _MAXSIM_CANDIDATES)
    reranked = rerank_pages_maxsim(query_multivector, candidates, limit)
    # Drop the raw buffers before returning results to callers
    return [
        {k: v for k, v in r.items() if k not in ("multi_embedding", "n_vectors")}
        for r in reranked
    ]


def search_by_image(text_query: str = None, limit: int = 5) -> str:
    """
    Search document pages using the image the user attached to their message.

    Embeds the attached image with ColQwen2 and finds the most visually similar
    PDF pages (e.g., find the manual page showing the machine in the photo).
    Optionally pass text_query (a short description of what the image shows) to
    fuse a text-based page search with the image search for better results.

    Args:
        text_query: Optional short description of the image content
        limit: Maximum number of page results (default 5)

    Returns:
        Relevant document pages with filename, page number, and relevance score
    """
    from src.services.colqwen2_client import colqwen2_client
    from src.services.rrf import reciprocal_rank_fusion

    context = get_tool_context()
    if not context or not context.image_bytes:
        return (
            "NO_RESULTS: No image is attached to the current message. "
            "Ask the user to attach an image, or use search_visual_documents with a text description."
        )

    if not colqwen2_client.image_endpoint:
        return (
            "Image search is not configured. "
            "Set COLQWEN2_IMAGE_ENDPOINT in environment to enable this capability."
        )

    coll_ids, err = _parse_collection_ids()
    if err:
        return err

    try:
        image_multivector = colqwen2_client.embed_image_multivector_sync(
            context.image_bytes, context.image_media_type or "image/png"
        )
        if not image_multivector:
            return "Image search unavailable: failed to generate image embedding."

        with SyncSessionLocal() as db:
            fetch_limit = limit * 3
            image_results = _two_stage_page_search(db, image_multivector, coll_ids, fetch_limit)

            if text_query:
                text_multivector = colqwen2_client.embed_text_multivector_sync(text_query)
                if text_multivector:
                    text_results = _two_stage_page_search(db, text_multivector, coll_ids, fetch_limit)
                    fused = reciprocal_rank_fusion(
                        result_lists=[image_results, text_results],
                        key_fn=lambda x: x["page_id"],
                        k=60,
                    )
                    final_results = fused[:limit]
                else:
                    final_results = image_results[:limit]
            else:
                final_results = image_results[:limit]

        if not final_results:
            return "NO_RESULTS: No document pages matched the attached image."

        lines = [f"Found {len(final_results)} pages matching the attached image (MaxSim reranked):", ""]
        for i, result in enumerate(final_results, 1):
            lines.append(f"### Result {i} (score: {result['score']:.3f})")
            lines.append(f"**Source:** {result['filename']}, Page {result['page_number']}")
            lines.append("")

        return "\n".join(lines)

    except Exception as e:
        logger.error("[search_by_image] %s", e, exc_info=True)
        return f"Error searching by image: {str(e)}"


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
        logger.error("[list_collections] %s", e, exc_info=True)
        return f"Error listing collections: {str(e)}"
