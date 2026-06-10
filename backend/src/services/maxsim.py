"""
MaxSim (late-interaction) scoring for ColQwen2 multi-vector retrieval.

ColQwen2 (ColPali family) produces one embedding per token/patch. The
late-interaction score between a query and a page is:

    MaxSim(q, d) = sum_i max_j (q_i . d_j)

i.e. each query token is matched to its most similar page patch, and the
similarities are summed. This preserves token-level signal that mean-pooled
single-vector cosine similarity discards.

Used as stage 2 of a two-stage retrieval: stage 1 retrieves candidates by
ANN cosine search over mean-pooled vectors, stage 2 reranks them with MaxSim.
"""

from __future__ import annotations

import numpy as np

EMBEDDING_DIM = 128


def maxsim_score(query: np.ndarray, page: np.ndarray) -> float:
    """
    Late-interaction score between a query multi-vector (n_q, 128) and a
    page multi-vector (n_p, 128). Both float32.
    """
    return float((query @ page.T).max(axis=1).sum())


def decode_multivector(buffer: bytes, n_vectors: int) -> np.ndarray:
    """Decode a float16 row-major buffer into a float32 (n_vectors, 128) array."""
    return (
        np.frombuffer(buffer, dtype=np.float16)
        .reshape(n_vectors, EMBEDDING_DIM)
        .astype(np.float32)
    )


def rerank_pages_maxsim(
    query_multivector: list[list[float]],
    candidates: list[dict],
    top_k: int,
) -> list[dict]:
    """
    Rerank candidate pages by MaxSim against the query multi-vector.

    Each candidate dict must carry "multi_embedding" (bytes or None) and
    "n_vectors". Candidates without a stored multi-vector (documents ingested
    before the MaxSim migration) keep their original pooled-cosine order and
    are appended after the MaxSim-scored ones.

    Returns top_k candidates; scored ones gain a "maxsim" field.
    """
    query = np.array(query_multivector, dtype=np.float32)

    scored = []
    unscored = []
    for candidate in candidates:
        buffer = candidate.get("multi_embedding")
        n_vectors = candidate.get("n_vectors")
        if buffer and n_vectors:
            page = decode_multivector(buffer, n_vectors)
            scored.append({**candidate, "maxsim": maxsim_score(query, page)})
        else:
            unscored.append(candidate)

    scored.sort(key=lambda c: c["maxsim"], reverse=True)
    return (scored + unscored)[:top_k]
