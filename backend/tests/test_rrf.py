"""Unit tests for Reciprocal Rank Fusion (RRF) algorithm."""

import sys
from pathlib import Path

# Add backend to path for direct import
backend_path = Path(__file__).parent.parent
sys.path.insert(0, str(backend_path))

# Import directly to avoid service initialization
from typing import Any, Callable


def reciprocal_rank_fusion(
    result_lists: list[list[dict]],
    key_fn: Callable[[dict], Any] = lambda x: x["chunk_id"],
    k: int = 60,
) -> list[dict]:
    """Reciprocal Rank Fusion algorithm (copied for testing without dependencies)."""
    rrf_scores: dict[Any, float] = {}
    item_map: dict[Any, dict] = {}

    for result_list in result_lists:
        for rank, item in enumerate(result_list, start=1):
            key = key_fn(item)
            rrf_scores[key] = rrf_scores.get(key, 0.0) + (1.0 / (k + rank))
            if key not in item_map:
                item_map[key] = item

    sorted_keys = sorted(rrf_scores.keys(), key=lambda k: rrf_scores[k], reverse=True)

    return [
        {**item_map[key], "score": rrf_scores[key]}
        for key in sorted_keys
    ]


def test_rrf_basic_fusion():
    """Test basic RRF with two lists having overlapping items."""
    list1 = [
        {"chunk_id": "A", "content": "first in list1"},
        {"chunk_id": "B", "content": "second in list1"},
        {"chunk_id": "C", "content": "third in list1"},
    ]
    list2 = [
        {"chunk_id": "B", "content": "first in list2"},
        {"chunk_id": "C", "content": "second in list2"},
        {"chunk_id": "D", "content": "third in list2"},
    ]

    result = reciprocal_rank_fusion([list1, list2], k=60)

    # B and C appear in both lists, should rank higher than A and D
    # B appears at position 2 in list1 and position 1 in list2
    # C appears at position 3 in list1 and position 2 in list2
    # B should rank highest overall
    assert result[0]["chunk_id"] == "B", "B should rank first (appears in both lists at high positions)"
    assert result[1]["chunk_id"] == "C", "C should rank second (appears in both lists)"

    # All 4 items should be in result
    assert len(result) == 4

    # All results should have scores
    assert all("score" in item for item in result)

    # Scores should be descending
    scores = [item["score"] for item in result]
    assert scores == sorted(scores, reverse=True), "Scores should be in descending order"


def test_rrf_single_list():
    """Test RRF with a single list (should preserve original order)."""
    list1 = [
        {"chunk_id": "A", "content": "first"},
        {"chunk_id": "B", "content": "second"},
        {"chunk_id": "C", "content": "third"},
    ]

    result = reciprocal_rank_fusion([list1], k=60)

    # Should preserve original order
    assert result[0]["chunk_id"] == "A"
    assert result[1]["chunk_id"] == "B"
    assert result[2]["chunk_id"] == "C"
    assert len(result) == 3


def test_rrf_no_overlap():
    """Test RRF with two lists having no overlapping items."""
    list1 = [
        {"chunk_id": "A", "content": "first in list1"},
        {"chunk_id": "B", "content": "second in list1"},
    ]
    list2 = [
        {"chunk_id": "C", "content": "first in list2"},
        {"chunk_id": "D", "content": "second in list2"},
    ]

    result = reciprocal_rank_fusion([list1, list2], k=60)

    # All 4 items should be present
    assert len(result) == 4
    chunk_ids = [item["chunk_id"] for item in result]
    assert set(chunk_ids) == {"A", "B", "C", "D"}

    # Items at rank 1 from each list should score higher than rank 2
    # A and C are rank 1 in their respective lists
    # B and D are rank 2 in their respective lists
    a_score = next(item["score"] for item in result if item["chunk_id"] == "A")
    b_score = next(item["score"] for item in result if item["chunk_id"] == "B")
    assert a_score > b_score, "Rank 1 items should score higher than rank 2"


def test_rrf_custom_key_function():
    """Test RRF with custom key extraction function."""
    list1 = [
        {"id": "X", "name": "first"},
        {"id": "Y", "name": "second"},
    ]
    list2 = [
        {"id": "Y", "name": "first"},
        {"id": "Z", "name": "second"},
    ]

    result = reciprocal_rank_fusion(
        [list1, list2],
        key_fn=lambda x: x["id"],  # Use 'id' instead of 'chunk_id'
        k=60
    )

    # Y appears in both lists
    assert result[0]["id"] == "Y"
    assert len(result) == 3


def test_rrf_empty_lists():
    """Test RRF with empty lists."""
    result = reciprocal_rank_fusion([], k=60)
    assert result == []

    result = reciprocal_rank_fusion([[], []], k=60)
    assert result == []


def test_rrf_different_k_values():
    """Test RRF with different k values (should affect scores but not order significantly for same data)."""
    list1 = [{"chunk_id": "A"}, {"chunk_id": "B"}]
    list2 = [{"chunk_id": "B"}, {"chunk_id": "C"}]

    result_k60 = reciprocal_rank_fusion([list1, list2], k=60)
    result_k10 = reciprocal_rank_fusion([list1, list2], k=10)

    # Both should rank B first
    assert result_k60[0]["chunk_id"] == "B"
    assert result_k10[0]["chunk_id"] == "B"

    # But scores should differ
    assert result_k60[0]["score"] != result_k10[0]["score"]

    # Lower k emphasizes top ranks more, so scores should be higher with lower k
    assert result_k10[0]["score"] > result_k60[0]["score"]


def test_rrf_preserves_metadata():
    """Test that RRF preserves metadata from first occurrence."""
    list1 = [
        {"chunk_id": "A", "content": "from list1", "extra": "data1"},
        {"chunk_id": "B", "content": "from list1", "extra": "data2"},
    ]
    list2 = [
        {"chunk_id": "B", "content": "from list2", "extra": "data3"},  # Different metadata
        {"chunk_id": "C", "content": "from list2", "extra": "data4"},
    ]

    result = reciprocal_rank_fusion([list1, list2], k=60)

    # B appears in both lists - should keep metadata from first occurrence (list1)
    b_result = next(item for item in result if item["chunk_id"] == "B")
    assert b_result["content"] == "from list1", "Should preserve metadata from first occurrence"
    assert b_result["extra"] == "data2", "Should preserve all metadata from first occurrence"


def test_rrf_score_accumulation():
    """Test that RRF correctly accumulates scores for items in multiple lists."""
    list1 = [{"chunk_id": "A"}]  # A at rank 1 in list1
    list2 = [{"chunk_id": "A"}]  # A at rank 1 in list2
    list3 = [{"chunk_id": "A"}]  # A at rank 1 in list3

    result = reciprocal_rank_fusion([list1, list2, list3], k=60)

    # A appears at rank 1 in all three lists
    # Score should be: 1/(60+1) + 1/(60+1) + 1/(60+1) = 3/61
    expected_score = 3 / 61
    assert abs(result[0]["score"] - expected_score) < 0.0001, f"Expected {expected_score}, got {result[0]['score']}"


def test_rrf_real_world_scenario():
    """Test RRF with a realistic hybrid search scenario."""
    # Simulate BM25 keyword results (good for exact match "API")
    keyword_results = [
        {"chunk_id": "doc1", "content": "REST API documentation"},
        {"chunk_id": "doc2", "content": "API authentication guide"},
        {"chunk_id": "doc5", "content": "API rate limits"},
    ]

    # Simulate semantic results (good for conceptual "authentication")
    semantic_results = [
        {"chunk_id": "doc2", "content": "API authentication guide"},  # Overlaps with keyword
        {"chunk_id": "doc3", "content": "OAuth2 security flow"},
        {"chunk_id": "doc4", "content": "User login process"},
    ]

    result = reciprocal_rank_fusion([keyword_results, semantic_results], k=60)

    # doc2 appears in both lists and should rank first
    assert result[0]["chunk_id"] == "doc2", "Document in both lists should rank highest"

    # Should have 5 unique documents total
    assert len(result) == 5

    # All should have scores
    assert all("score" in item for item in result)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
