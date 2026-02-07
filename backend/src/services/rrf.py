"""Reciprocal Rank Fusion (RRF) for combining ranked result lists.

RRF is an effective algorithm for combining multiple ranked lists without
requiring score normalization. It's particularly useful for hybrid search
where different retrieval methods (BM25, semantic search) produce scores
on different scales.

Reference: Cormack, G. V., Clarke, C. L., & Buettcher, S. (2009).
"Reciprocal rank fusion outperforms condorcet and individual rank learning methods."
"""

from typing import Any, Callable


def reciprocal_rank_fusion(
    result_lists: list[list[dict]],
    key_fn: Callable[[dict], Any] = lambda x: x["chunk_id"],
    k: int = 60,
) -> list[dict]:
    """Combine multiple ranked result lists using Reciprocal Rank Fusion.

    RRF formula: RRF_score(d) = Σ 1/(k + rank_i(d))
    where rank_i(d) is the rank of document d in result list i.

    The algorithm works by:
    1. Assigning each document a score based on its rank in each list
    2. Summing scores across all lists where the document appears
    3. Sorting by the combined RRF score

    Benefits:
    - No need to normalize scores from different retrieval methods
    - Documents appearing in multiple lists get boosted
    - Robust to outliers and score scale differences
    - Simple and computationally efficient

    Args:
        result_lists: List of ranked result lists (each list is ranked by position).
                     Each item in a list should be a dict with at least the key
                     specified by key_fn.
        key_fn: Function to extract unique identifier from result dict.
                Default extracts "chunk_id".
        k: RRF constant (default 60, from research literature).
           Higher k = less emphasis on top-ranked items.
           Lower k = more emphasis on top-ranked items.

    Returns:
        Combined ranked list sorted by RRF score (highest first).
        Each result dict includes a "score" field with the RRF score.

    Example:
        >>> semantic_results = [
        ...     {"chunk_id": "A", "content": "..."},
        ...     {"chunk_id": "B", "content": "..."}
        ... ]
        >>> keyword_results = [
        ...     {"chunk_id": "B", "content": "..."},
        ...     {"chunk_id": "C", "content": "..."}
        ... ]
        >>> combined = reciprocal_rank_fusion([semantic_results, keyword_results])
        >>> # "B" will rank highest because it appears in both lists
    """
    rrf_scores: dict[Any, float] = {}
    item_map: dict[Any, dict] = {}

    # Calculate RRF scores by iterating through each result list
    for result_list in result_lists:
        for rank, item in enumerate(result_list, start=1):
            key = key_fn(item)

            # Accumulate RRF score: 1 / (k + rank)
            # Documents appearing in multiple lists accumulate higher scores
            rrf_scores[key] = rrf_scores.get(key, 0.0) + (1.0 / (k + rank))

            # Keep first occurrence of each item (preserves original metadata)
            # This ensures we don't duplicate entries and keep the first
            # encountered metadata (e.g., from the higher-ranking list)
            if key not in item_map:
                item_map[key] = item

    # Sort by RRF score (descending) and reconstruct results
    sorted_keys = sorted(rrf_scores.keys(), key=lambda k: rrf_scores[k], reverse=True)

    # Return results with RRF score added
    return [
        {**item_map[key], "score": rrf_scores[key]}
        for key in sorted_keys
    ]
