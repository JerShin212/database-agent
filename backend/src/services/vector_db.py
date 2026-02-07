from uuid import UUID
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from pgvector.sqlalchemy import Vector


class VectorDBService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def insert_chunks(
        self,
        chunks: list[dict],
    ) -> None:
        """Insert document chunks with embeddings into the database."""
        if not chunks:
            return

        # Insert chunks one by one using raw SQL with proper vector formatting
        for chunk in chunks:
            # Format embedding as PostgreSQL array literal
            embedding = chunk["embedding"]
            embedding_literal = "ARRAY[" + ",".join(str(x) for x in embedding) + "]::vector"

            # Use string formatting for the vector (safe since it's just floats)
            # But use parameters for user-provided content
            stmt = text(f"""
                INSERT INTO document_chunks
                (id, document_id, collection_id, chunk_index, content, start_char, end_char, embedding)
                VALUES (:id, :document_id, :collection_id, :chunk_index, :content, :start_char, :end_char, {embedding_literal})
            """)
            await self.db.execute(
                stmt,
                {
                    "id": str(chunk["id"]),
                    "document_id": str(chunk["document_id"]),
                    "collection_id": str(chunk["collection_id"]),
                    "chunk_index": chunk["chunk_index"],
                    "content": chunk["content"],
                    "start_char": chunk.get("start_char"),
                    "end_char": chunk.get("end_char"),
                },
            )
        await self.db.commit()

    async def search_similar(
        self,
        query_embedding: list[float],
        collection_ids: list[UUID] | None = None,
        limit: int = 5,
    ) -> list[dict]:
        """Search for similar document chunks using L2 distance (VectorChord)."""
        # Format embedding as PostgreSQL array literal
        embedding_literal = "ARRAY[" + ",".join(str(x) for x in query_embedding) + "]::vector"

        # Build query with optional collection filter
        if collection_ids:
            collection_filter = "AND dc.collection_id = ANY(:collection_ids)"
            params = {
                "collection_ids": [str(cid) for cid in collection_ids],
                "limit": limit,
            }
        else:
            collection_filter = ""
            params = {"limit": limit}

        # Use <-> for L2 distance (matches vchordrq index with vector_l2_ops)
        stmt = text(f"""
            SELECT
                dc.id,
                dc.document_id,
                dc.collection_id,
                dc.chunk_index,
                dc.content,
                d.filename,
                dc.embedding <-> {embedding_literal} as distance
            FROM document_chunks dc
            JOIN documents d ON dc.document_id = d.id
            WHERE dc.embedding IS NOT NULL
            {collection_filter}
            ORDER BY dc.embedding <-> {embedding_literal}
            LIMIT :limit
        """)

        result = await self.db.execute(stmt, params)
        rows = result.fetchall()

        return [
            {
                "chunk_id": row[0],
                "document_id": row[1],
                "collection_id": row[2],
                "chunk_index": row[3],
                "content": row[4],
                "filename": row[5],
                "score": 1.0 / (1.0 + float(row[6])),  # Convert distance to similarity score
            }
            for row in rows
        ]

    async def delete_by_document(self, document_id: UUID) -> None:
        """Delete all chunks for a document."""
        stmt = text("DELETE FROM document_chunks WHERE document_id = :document_id")
        await self.db.execute(stmt, {"document_id": str(document_id)})
        await self.db.commit()

    async def delete_by_collection(self, collection_id: UUID) -> None:
        """Delete all chunks for a collection."""
        stmt = text("DELETE FROM document_chunks WHERE collection_id = :collection_id")
        await self.db.execute(stmt, {"collection_id": str(collection_id)})
        await self.db.commit()
