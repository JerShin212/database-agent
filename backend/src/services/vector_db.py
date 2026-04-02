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
        """Search for similar document chunks using cosine similarity (VectorChord).

        Args:
            query_embedding: Query vector embedding
            collection_ids: Optional filter by collection IDs
            limit: Maximum results to return

        Returns:
            List of similar chunks with cosine similarity scores
        """
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

        # Use <=> for cosine distance (matches vchordrq index with vector_cosine_ops)
        # Cosine distance range: 0 (identical) to 2 (opposite)
        # Cosine similarity = 1 - cosine_distance (range: -1 to 1, typically 0-1 for normalized vectors)
        stmt = text(f"""
            SELECT
                dc.id,
                dc.document_id,
                dc.collection_id,
                dc.chunk_index,
                dc.content,
                d.filename,
                dc.embedding <=> {embedding_literal} as distance,
                1.0 - (dc.embedding <=> {embedding_literal}) as similarity
            FROM document_chunks dc
            JOIN documents d ON dc.document_id = d.id
            WHERE dc.embedding IS NOT NULL
            {collection_filter}
            ORDER BY dc.embedding <=> {embedding_literal}
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
                "distance": float(row[6]),
                "score": float(row[7]),  # Use similarity as score (1.0 - distance)
            }
            for row in rows
        ]

    async def search_keyword(
        self,
        query_text: str,
        collection_ids: list[UUID] | None = None,
        limit: int = 5,
    ) -> list[dict]:
        """Search for document chunks using BM25-like ranking (PostgreSQL FTS).

        Args:
            query_text: Natural language query for keyword matching
            collection_ids: Optional filter by collection IDs
            limit: Maximum results to return

        Returns:
            List of matching chunks with BM25-like ranking scores
        """
        # Build collection filter
        if collection_ids:
            collection_filter = "AND dc.collection_id = ANY(:collection_ids)"
            params = {
                "collection_ids": [str(cid) for cid in collection_ids],
                "limit": limit,
            }
        else:
            collection_filter = ""
            params = {"limit": limit}

        # PostgreSQL FTS with BM25-like scoring using custom function
        # websearch_to_tsquery converts natural language to tsquery
        # bm25_rank function provides BM25-like scoring with length normalization
        stmt = text(f"""
            SELECT
                dc.id,
                dc.document_id,
                dc.collection_id,
                dc.chunk_index,
                dc.content,
                d.filename,
                bm25_rank(
                    dc.search_vector,
                    websearch_to_tsquery('english', :query),
                    dc.content_length,
                    500.0,  -- avg_length parameter
                    1.2,    -- k1 parameter (term saturation)
                    0.75    -- b parameter (length normalization)
                ) as score
            FROM document_chunks dc
            JOIN documents d ON dc.document_id = d.id
            WHERE dc.search_vector @@ websearch_to_tsquery('english', :query)
            {collection_filter}
            ORDER BY score DESC
            LIMIT :limit
        """)

        params["query"] = query_text
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
                "score": float(row[6]),
            }
            for row in rows
        ]

    async def search_hybrid(
        self,
        query_text: str,
        query_embedding: list[float],
        collection_ids: list[UUID] | None = None,
        limit: int = 5,
        rrf_k: int = 60,
    ) -> list[dict]:
        """Search using hybrid retrieval (keyword + semantic) with RRF.

        Combines BM25 keyword search and cosine similarity semantic search
        using Reciprocal Rank Fusion for optimal results across different
        query types (exact matches, conceptual queries, and mixed queries).

        Args:
            query_text: Natural language query for keyword search
            query_embedding: Query embedding vector for semantic search
            collection_ids: Optional filter by collection IDs
            limit: Maximum results to return after fusion
            rrf_k: RRF constant parameter (default 60)

        Returns:
            Combined ranked results using Reciprocal Rank Fusion
        """
        from src.services.rrf import reciprocal_rank_fusion

        # Fetch more results from each method for better fusion
        # Using 3x multiplier to ensure good candidate pool
        fetch_limit = limit * 3

        # Execute both searches
        # Note: Could be parallelized with asyncio.gather() for better performance
        keyword_results = await self.search_keyword(
            query_text=query_text,
            collection_ids=collection_ids,
            limit=fetch_limit,
        )

        semantic_results = await self.search_similar(
            query_embedding=query_embedding,
            collection_ids=collection_ids,
            limit=fetch_limit,
        )

        # Apply Reciprocal Rank Fusion
        combined_results = reciprocal_rank_fusion(
            result_lists=[keyword_results, semantic_results],
            key_fn=lambda x: x["chunk_id"],
            k=rrf_k,
        )

        # Return top-k after fusion
        return combined_results[:limit]

    async def insert_pages(self, pages: list[dict]) -> None:
        """Insert document pages with ColQwen2 visual embeddings."""
        if not pages:
            return

        for page in pages:
            embedding = page["visual_embedding"]
            embedding_literal = "ARRAY[" + ",".join(str(x) for x in embedding) + "]::vector"

            stmt = text(f"""
                INSERT INTO document_pages
                (id, document_id, collection_id, page_number, visual_embedding)
                VALUES (:id, :document_id, :collection_id, :page_number, {embedding_literal})
            """)
            await self.db.execute(
                stmt,
                {
                    "id": str(page["id"]),
                    "document_id": str(page["document_id"]),
                    "collection_id": str(page["collection_id"]),
                    "page_number": page["page_number"],
                },
            )
        await self.db.commit()

    async def search_visual_similar(
        self,
        query_embedding: list[float],
        collection_ids: list[UUID] | None = None,
        limit: int = 5,
    ) -> list[dict]:
        """Search document pages using ColQwen2 visual embeddings (cosine similarity)."""
        embedding_literal = "ARRAY[" + ",".join(str(x) for x in query_embedding) + "]::vector"

        if collection_ids:
            collection_filter = "AND dp.collection_id = ANY(:collection_ids)"
            params = {
                "collection_ids": [str(cid) for cid in collection_ids],
                "limit": limit,
            }
        else:
            collection_filter = ""
            params = {"limit": limit}

        stmt = text(f"""
            SELECT
                dp.id,
                dp.document_id,
                dp.collection_id,
                dp.page_number,
                d.filename,
                dp.visual_embedding <=> {embedding_literal} as distance,
                1.0 - (dp.visual_embedding <=> {embedding_literal}) as similarity
            FROM document_pages dp
            JOIN documents d ON dp.document_id = d.id
            WHERE dp.visual_embedding IS NOT NULL
            {collection_filter}
            ORDER BY dp.visual_embedding <=> {embedding_literal}
            LIMIT :limit
        """)

        result = await self.db.execute(stmt, params)
        rows = result.fetchall()

        return [
            {
                "page_id": row[0],
                "document_id": row[1],
                "collection_id": row[2],
                "page_number": row[3],
                "filename": row[4],
                "distance": float(row[5]),
                "score": float(row[6]),
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

    # ===== Schema Catalog Search Methods =====

    async def search_schema_keyword(
        self,
        query_text: str,
        connector_id: UUID,
        limit: int = 5,
    ) -> list[dict]:
        """Search schema definitions using BM25-like keyword search.

        Args:
            query_text: Natural language query for keyword matching
            connector_id: Filter by connector ID
            limit: Maximum results to return

        Returns:
            List of matching schema definitions with BM25 scores
        """
        # PostgreSQL FTS with BM25-like scoring
        stmt = text("""
            SELECT
                sd.id,
                sd.definition_type,
                sd.table_name,
                sd.column_name,
                sd.data_type,
                sd.semantic_definition,
                sd.sample_values,
                bm25_rank(
                    sd.search_vector,
                    websearch_to_tsquery('english', :query),
                    sd.content_length,
                    500.0,  -- avg_length parameter
                    1.2,    -- k1 parameter
                    0.75    -- b parameter
                ) as score
            FROM schema_definitions sd
            WHERE sd.connector_id = :connector_id
              AND sd.search_vector @@ websearch_to_tsquery('english', :query)
            ORDER BY score DESC
            LIMIT :limit
        """)

        params = {
            "query": query_text,
            "connector_id": str(connector_id),
            "limit": limit,
        }

        result = await self.db.execute(stmt, params)
        rows = result.fetchall()

        return [
            {
                "definition_id": row[0],
                "definition_type": row[1],
                "table_name": row[2],
                "column_name": row[3],
                "data_type": row[4],
                "semantic_definition": row[5],
                "sample_values": row[6],
                "score": float(row[7]),
            }
            for row in rows
        ]

    async def search_schema_semantic(
        self,
        query_embedding: list[float],
        connector_id: UUID,
        limit: int = 5,
    ) -> list[dict]:
        """Search schema definitions using cosine similarity.

        Args:
            query_embedding: Query vector embedding
            connector_id: Filter by connector ID
            limit: Maximum results to return

        Returns:
            List of similar schema definitions with cosine similarity scores
        """
        # Format embedding as PostgreSQL array literal
        embedding_literal = "ARRAY[" + ",".join(str(x) for x in query_embedding) + "]::vector"

        # Use <=> for cosine distance (matches vchordrq index)
        stmt = text(f"""
            SELECT
                sd.id,
                sd.definition_type,
                sd.table_name,
                sd.column_name,
                sd.data_type,
                sd.semantic_definition,
                sd.sample_values,
                sd.embedding <=> {embedding_literal} as distance,
                1.0 - (sd.embedding <=> {embedding_literal}) as similarity
            FROM schema_definitions sd
            WHERE sd.connector_id = :connector_id
              AND sd.embedding IS NOT NULL
            ORDER BY sd.embedding <=> {embedding_literal}
            LIMIT :limit
        """)

        params = {
            "connector_id": str(connector_id),
            "limit": limit,
        }

        result = await self.db.execute(stmt, params)
        rows = result.fetchall()

        return [
            {
                "definition_id": row[0],
                "definition_type": row[1],
                "table_name": row[2],
                "column_name": row[3],
                "data_type": row[4],
                "semantic_definition": row[5],
                "sample_values": row[6],
                "distance": float(row[7]),
                "score": float(row[8]),  # Use similarity as score
            }
            for row in rows
        ]

    async def search_schema_hybrid(
        self,
        query_text: str,
        query_embedding: list[float],
        connector_id: UUID,
        limit: int = 5,
        rrf_k: int = 60,
    ) -> list[dict]:
        """Search schema definitions using hybrid retrieval (keyword + semantic + RRF).

        Combines BM25 keyword search and cosine similarity semantic search
        using Reciprocal Rank Fusion.

        Args:
            query_text: Natural language query for keyword search
            query_embedding: Query embedding vector for semantic search
            connector_id: Filter by connector ID
            limit: Maximum results to return after fusion
            rrf_k: RRF constant parameter (default 60)

        Returns:
            Combined ranked results using Reciprocal Rank Fusion
        """
        from src.services.rrf import reciprocal_rank_fusion

        # Fetch more results from each method for better fusion
        fetch_limit = limit * 3

        # Execute both searches in parallel
        import asyncio
        keyword_results, semantic_results = await asyncio.gather(
            self.search_schema_keyword(
                query_text=query_text,
                connector_id=connector_id,
                limit=fetch_limit,
            ),
            self.search_schema_semantic(
                query_embedding=query_embedding,
                connector_id=connector_id,
                limit=fetch_limit,
            ),
        )

        # Apply Reciprocal Rank Fusion
        combined_results = reciprocal_rank_fusion(
            result_lists=[keyword_results, semantic_results],
            key_fn=lambda x: x["definition_id"],
            k=rrf_k,
        )

        # Return top-k after fusion
        return combined_results[:limit]
