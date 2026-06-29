"""Retrieval hit-rate eval: ingest small fixture documents into a scratch
collection (real Postgres + real ColQwen2 embeddings), then check that hybrid
search returns the gold document in the top-k for each query.

Requires RUN_RETRIEVAL_EVALS=1, Postgres on :5433, and Modal endpoints.
The scratch collection is deleted afterwards.
"""

import sys
import uuid
from pathlib import Path

import pytest

backend_path = Path(__file__).parent.parent.parent
sys.path.insert(0, str(backend_path))

from src.db.database import AsyncSessionLocal
from src.models.collection import Collection, Document
from src.processing.chunking.semantic import SemanticChunker
from src.services.embedding_service import EmbeddingService
from src.services.vector_db import VectorDBService

pytestmark = [pytest.mark.eval, pytest.mark.eval_retrieval]

TOP_K = 5

FIXTURE_DOCS = {
    "warranty_policy.txt": (
        "Warranty Policy. All residential air conditioning units carry a five year "
        "warranty on the compressor and a two year warranty on all other parts. "
        "Warranty claims must be filed within 30 days of discovering the defect, "
        "and require the original proof of purchase. Unauthorized repairs void the "
        "warranty entirely. Extended warranty plans can be purchased within the "
        "first 90 days after installation."
    ),
    "installation_guide.txt": (
        "Installation Guide. The outdoor condenser unit must be mounted on a level "
        "concrete pad with at least 60 centimeters of clearance on all sides. "
        "Refrigerant lines should be insulated and must not exceed 15 meters in "
        "length without an additional charge calculation. The electrical supply "
        "requires a dedicated 20 amp circuit breaker. After installation, a vacuum "
        "test must be performed before releasing refrigerant into the lines."
    ),
    "maintenance_schedule.txt": (
        "Maintenance Schedule. Air filters should be cleaned every two weeks during "
        "peak season and replaced every three months. The condenser coils require "
        "professional cleaning twice per year. Quarterly inspections must check "
        "refrigerant pressure, drain line blockage, and electrical connections. "
        "Annual servicing includes a full system diagnostic and thermostat calibration."
    ),
}

# (query, gold filename)
RETRIEVAL_CASES = [
    ("how long is the compressor warranty", "warranty_policy.txt"),
    ("what voids the warranty", "warranty_policy.txt"),
    ("clearance needed around the outdoor unit", "installation_guide.txt"),
    ("circuit breaker requirement for installation", "installation_guide.txt"),
    ("how often should air filters be replaced", "maintenance_schedule.txt"),
    ("what do quarterly inspections cover", "maintenance_schedule.txt"),
]


async def _ingest_fixtures(db, collection_id):
    chunker = SemanticChunker()
    embedder = EmbeddingService()
    vector_db = VectorDBService(db)

    for filename, content in FIXTURE_DOCS.items():
        document = Document(
            collection_id=collection_id,
            filename=filename,
            mime_type="text/plain",
            file_size=len(content),
            minio_object_key=f"eval/{collection_id}/{filename}",
            status="completed",
            extracted_text=content,
        )
        db.add(document)
        await db.commit()
        await db.refresh(document)

        chunks = chunker.chunk(content)
        embeddings = await embedder.embed_batch([c.content for c in chunks])
        rows = [
            {
                "id": uuid.uuid4(),
                "document_id": document.id,
                "collection_id": collection_id,
                "chunk_index": chunk.index,
                "content": chunk.content,
                "start_char": chunk.start_char,
                "end_char": chunk.end_char,
                "embedding": embedding,
            }
            for chunk, embedding in zip(chunks, embeddings)
            if embedding
        ]
        await vector_db.insert_chunks(rows)


async def test_retrieval_hit_rate():
    async with AsyncSessionLocal() as db:
        collection = Collection(name=f"eval-scratch-{uuid.uuid4().hex[:8]}")
        db.add(collection)
        await db.commit()
        await db.refresh(collection)
        collection_id = collection.id

        try:
            await _ingest_fixtures(db, collection_id)

            embedder = EmbeddingService()
            vector_db = VectorDBService(db)
            passed = 0
            failures = []

            for query, gold_filename in RETRIEVAL_CASES:
                query_embedding = await embedder.embed_text(query)
                results = await vector_db.search_hybrid(
                    query_text=query,
                    query_embedding=query_embedding,
                    collection_ids=[collection_id],
                    limit=TOP_K,
                )
                filenames = [r["filename"] for r in results]
                ok = gold_filename in filenames
                if ok:
                    passed += 1
                else:
                    failures.append(f"  {query!r}: expected {gold_filename}, got {filenames}")
                print(f"[retrieval] {'PASS' if ok else 'FAIL'} :: {query}")

            score = passed / len(RETRIEVAL_CASES)
            print(f"\n[retrieval] SCORE: {passed}/{len(RETRIEVAL_CASES)} = {score:.0%}")
            assert score >= 0.8, "Retrieval hit-rate below 80%:\n" + "\n".join(failures)
        finally:
            await vector_db_cleanup(db, collection_id)


async def vector_db_cleanup(db, collection_id):
    from sqlalchemy import text

    await db.execute(
        text("DELETE FROM document_chunks WHERE collection_id = :cid"), {"cid": str(collection_id)}
    )
    await db.execute(
        text("DELETE FROM documents WHERE collection_id = :cid"), {"cid": str(collection_id)}
    )
    await db.execute(text("DELETE FROM collections WHERE id = :cid"), {"cid": str(collection_id)})
    await db.commit()
