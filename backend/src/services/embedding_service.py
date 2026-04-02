from tenacity import retry, stop_after_attempt, wait_exponential
from src.services.colqwen2_client import colqwen2_client


class EmbeddingService:
    def __init__(self):
        self.client = colqwen2_client

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    async def embed_text(self, text: str) -> list[float]:
        """Generate embedding for a single text."""
        return await self.client.embed_text(text)

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    async def embed_batch(self, texts: list[str], batch_size: int = 100) -> list[list[float]]:
        """Generate embeddings for a batch of texts."""
        all_embeddings = []
        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            batch_embeddings = await self.client.embed_batch(batch)
            all_embeddings.extend(batch_embeddings)
        return all_embeddings


# Singleton instance
embedding_service = EmbeddingService()
