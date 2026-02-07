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
    ) -> list[SearchResult]:
        """Search for relevant document chunks using semantic search."""
        # Generate query embedding
        query_embedding = await embedding_service.embed_text(query)

        # Search vector database
        results = await self.vector_db.search_similar(
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
