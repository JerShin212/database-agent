"""Unit tests for batched multi-row inserts in VectorDBService."""

import asyncio
import sys
import uuid
from pathlib import Path

backend_path = Path(__file__).parent.parent
sys.path.insert(0, str(backend_path))

from src.services.vector_db import VectorDBService, _INSERT_BATCH_SIZE


class FakeAsyncSession:
    def __init__(self):
        self.executes = []
        self.commits = 0

    async def execute(self, stmt, params=None):
        self.executes.append((str(stmt), params))

    async def commit(self):
        self.commits += 1


def _make_chunk(index):
    return {
        "id": uuid.uuid4(),
        "document_id": uuid.uuid4(),
        "collection_id": uuid.uuid4(),
        "chunk_index": index,
        "content": f"chunk {index}",
        "start_char": index * 10,
        "end_char": index * 10 + 9,
        "embedding": [0.1] * 4,
    }


def _make_page(number):
    return {
        "id": uuid.uuid4(),
        "document_id": uuid.uuid4(),
        "collection_id": uuid.uuid4(),
        "page_number": number,
        "visual_embedding": [0.2] * 4,
        "multi_embedding": b"\x00\x01",
        "n_vectors": 2,
    }


def test_insert_chunks_batches_into_multirow_statements():
    db = FakeAsyncSession()
    service = VectorDBService(db)
    chunks = [_make_chunk(i) for i in range(_INSERT_BATCH_SIZE * 2 + 50)]

    asyncio.run(service.insert_chunks(chunks))

    # 250 chunks -> 3 statements (100 + 100 + 50), one commit
    assert len(db.executes) == 3
    assert db.commits == 1

    first_sql, first_params = db.executes[0]
    assert first_sql.count("ARRAY[") == _INSERT_BATCH_SIZE
    assert first_params["content_0"] == "chunk 0"
    assert first_params[f"content_{_INSERT_BATCH_SIZE - 1}"] == f"chunk {_INSERT_BATCH_SIZE - 1}"

    last_sql, last_params = db.executes[-1]
    assert last_sql.count("ARRAY[") == 50
    assert last_params["content_0"] == f"chunk {_INSERT_BATCH_SIZE * 2}"


def test_insert_chunks_empty_is_noop():
    db = FakeAsyncSession()
    asyncio.run(VectorDBService(db).insert_chunks([]))
    assert db.executes == []
    assert db.commits == 0


def test_insert_pages_batches_and_binds_multi_embedding():
    db = FakeAsyncSession()
    service = VectorDBService(db)
    pages = [_make_page(i) for i in range(5)]

    asyncio.run(service.insert_pages(pages))

    assert len(db.executes) == 1
    assert db.commits == 1
    sql, params = db.executes[0]
    assert sql.count("ARRAY[") == 5
    assert params["multi_embedding_0"] == b"\x00\x01"
    assert params["n_vectors_4"] == 2
