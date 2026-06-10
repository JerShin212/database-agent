"""Unit tests for MaxSim late-interaction scoring and reranking."""

import sys
from pathlib import Path

import numpy as np

backend_path = Path(__file__).parent.parent
sys.path.insert(0, str(backend_path))

from src.services.maxsim import (
    EMBEDDING_DIM,
    decode_multivector,
    maxsim_score,
    rerank_pages_maxsim,
)


def test_maxsim_score_hand_computed():
    # query token 0 best matches page token 1 (dot 2.0)
    # query token 1 best matches page token 0 (dot 3.0)
    query = np.zeros((2, EMBEDDING_DIM), dtype=np.float32)
    page = np.zeros((2, EMBEDDING_DIM), dtype=np.float32)
    query[0, 0] = 1.0
    query[1, 1] = 1.0
    page[0, 1] = 3.0  # matches query token 1
    page[1, 0] = 2.0  # matches query token 0
    assert maxsim_score(query, page) == 5.0


def test_maxsim_score_prefers_token_match_over_pooled():
    # Two pages with identical mean vectors but different token structure
    query = np.zeros((1, EMBEDDING_DIM), dtype=np.float32)
    query[0, 0] = 1.0

    focused = np.zeros((2, EMBEDDING_DIM), dtype=np.float32)
    focused[0, 0] = 2.0  # one strongly matching token

    diffuse = np.zeros((2, EMBEDDING_DIM), dtype=np.float32)
    diffuse[0, 0] = 1.0
    diffuse[1, 0] = 1.0  # same mean, weaker best token

    assert maxsim_score(query, focused) > maxsim_score(query, diffuse)


def test_decode_multivector_roundtrip():
    original = np.random.rand(7, EMBEDDING_DIM).astype(np.float16)
    decoded = decode_multivector(original.tobytes(), 7)
    assert decoded.shape == (7, EMBEDDING_DIM)
    assert decoded.dtype == np.float32
    np.testing.assert_allclose(decoded, original.astype(np.float32))


def _candidate(name: str, multivector: np.ndarray | None, score: float) -> dict:
    return {
        "filename": name,
        "score": score,
        "multi_embedding": multivector.astype(np.float16).tobytes() if multivector is not None else None,
        "n_vectors": multivector.shape[0] if multivector is not None else None,
    }


def test_rerank_orders_by_maxsim():
    query = np.zeros((1, EMBEDDING_DIM), dtype=np.float32)
    query[0, 0] = 1.0

    weak = np.zeros((1, EMBEDDING_DIM), dtype=np.float32)
    weak[0, 0] = 0.5
    strong = np.zeros((1, EMBEDDING_DIM), dtype=np.float32)
    strong[0, 0] = 2.0

    # Pooled cosine ranked "weak" first; MaxSim must flip the order
    candidates = [_candidate("weak.pdf", weak, 0.9), _candidate("strong.pdf", strong, 0.8)]
    reranked = rerank_pages_maxsim(query.tolist(), candidates, top_k=2)

    assert [c["filename"] for c in reranked] == ["strong.pdf", "weak.pdf"]
    assert reranked[0]["maxsim"] > reranked[1]["maxsim"]


def test_rerank_null_multivector_falls_back_to_pooled_order():
    query = np.zeros((1, EMBEDDING_DIM), dtype=np.float32)
    query[0, 0] = 1.0

    scored_mv = np.zeros((1, EMBEDDING_DIM), dtype=np.float32)
    scored_mv[0, 0] = 1.0

    candidates = [
        _candidate("legacy-a.pdf", None, 0.95),  # pre-migration page
        _candidate("scored.pdf", scored_mv, 0.5),
        _candidate("legacy-b.pdf", None, 0.90),
    ]
    reranked = rerank_pages_maxsim(query.tolist(), candidates, top_k=3)

    # Scored pages come first; legacy pages keep their relative pooled order
    assert [c["filename"] for c in reranked] == ["scored.pdf", "legacy-a.pdf", "legacy-b.pdf"]
    assert "maxsim" not in reranked[1]


def test_rerank_respects_top_k():
    query = np.zeros((1, EMBEDDING_DIM), dtype=np.float32)
    candidates = [_candidate(f"p{i}.pdf", None, 1.0 - i * 0.1) for i in range(5)]
    assert len(rerank_pages_maxsim(query.tolist(), candidates, top_k=2)) == 2
