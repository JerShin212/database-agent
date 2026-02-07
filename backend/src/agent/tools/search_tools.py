from uuid import UUID

from src.agent.tools.context import get_tool_context
from src.db.database import SyncSessionLocal
from src.models.collection import Collection


def search_collections(query: str, collection_ids: str = None, limit: int = 5) -> str:
    """
    Search document collections using semantic vector search.

    Args:
        query: Natural language search query
        collection_ids: Optional comma-separated list of collection IDs to search
        limit: Maximum number of results (default 5)

    Returns:
        Relevant document chunks with citations
    """
    from sqlalchemy import text
    from src.config import settings
    import openai

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
        # Generate embedding for query
        client = openai.OpenAI(api_key=settings.openai_api_key)
        response = client.embeddings.create(
            model=settings.embedding_model,
            input=query,
        )
        query_embedding = response.data[0].embedding

        # Search using sync session
        with SyncSessionLocal() as db:
            # Format embedding as PostgreSQL array literal
            embedding_literal = "ARRAY[" + ",".join(str(x) for x in query_embedding) + "]::vector"

            if coll_ids:
                coll_ids_str = ",".join(f"'{str(cid)}'" for cid in coll_ids)
                sql = text(f"""
                    SELECT dc.content, dc.chunk_index, d.filename,
                           1.0 / (1.0 + (dc.embedding <-> {embedding_literal})::float) as score
                    FROM document_chunks dc
                    JOIN documents d ON dc.document_id = d.id
                    WHERE dc.collection_id IN ({coll_ids_str})
                    ORDER BY dc.embedding <-> {embedding_literal}
                    LIMIT :limit
                """)
            else:
                sql = text(f"""
                    SELECT dc.content, dc.chunk_index, d.filename,
                           1.0 / (1.0 + (dc.embedding <-> {embedding_literal})::float) as score
                    FROM document_chunks dc
                    JOIN documents d ON dc.document_id = d.id
                    ORDER BY dc.embedding <-> {embedding_literal}
                    LIMIT :limit
                """)

            result = db.execute(sql, {"limit": limit})
            rows = result.fetchall()

            if not rows:
                return "No relevant documents found for your query."

            lines = [f"Found {len(rows)} relevant document chunks:", ""]
            for i, row in enumerate(rows, 1):
                content, chunk_index, filename, score = row
                lines.append(f"### Result {i} (Score: {score:.3f})")
                lines.append(f"**Source:** {filename}")
                lines.append(f"**Content:** {content[:500]}...")
                lines.append("")

            return "\n".join(lines)

    except Exception as e:
        return f"Error searching collections: {str(e)}"


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
