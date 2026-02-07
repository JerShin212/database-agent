from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from src.services.embedding_service import embedding_service
from src.services.vector_db import VectorDBService
from src.schemas.collection import SearchResult


class SearchService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.vector_db = VectorDBService(db)

    async def search(
        self,
        query: str,
        collection_ids: list[UUID] | None = None,
        limit: int = 5,
        mode: str = "hybrid",
    ) -> list[SearchResult]:
        """Search for relevant document chunks.

        Args:
            query: Natural language search query
            collection_ids: Optional filter by collections
            limit: Maximum results
            mode: Search mode - "hybrid" (default), "semantic", or "keyword"

        Returns:
            Ranked search results
        """
        if mode == "keyword":
            # Keyword-only search using BM25
            results = await self.vector_db.search_keyword(
                query_text=query,
                collection_ids=collection_ids,
                limit=limit,
            )
        elif mode == "semantic":
            # Semantic-only search (existing behavior)
            query_embedding = await embedding_service.embed_text(query)
            results = await self.vector_db.search_similar(
                query_embedding=query_embedding,
                collection_ids=collection_ids,
                limit=limit,
            )
        else:  # "hybrid"
            # Hybrid search with RRF (default)
            query_embedding = await embedding_service.embed_text(query)
            results = await self.vector_db.search_hybrid(
                query_text=query,
                query_embedding=query_embedding,
                collection_ids=collection_ids,
                limit=limit,
            )

        # Convert to response schema
        return [
            SearchResult(
                chunk_id=result["chunk_id"],
                document_id=result["document_id"],
                collection_id=result["collection_id"],
                filename=result["filename"],
                content=result["content"],
                score=result["score"],
            )
            for result in results
        ]
