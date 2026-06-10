"""Unit tests for schema catalog serialization and value-token extraction."""

import sys
from pathlib import Path

import numpy as np

backend_path = Path(__file__).parent.parent
sys.path.insert(0, str(backend_path))

from src.services.schema_serializer import (
    build_column_text,
    build_table_text,
    extract_value_tokens,
    humanize_identifier,
)


# ---------------------------------------------------------------------------
# humanize_identifier
# ---------------------------------------------------------------------------

def test_humanize_snake_case():
    assert humanize_identifier("customer_id") == "customer id"
    assert humanize_identifier("stock_quantity") == "stock quantity"


def test_humanize_camel_case():
    assert humanize_identifier("createdAt") == "created at"
    assert humanize_identifier("OrderItems") == "order items"


def test_humanize_digits_and_empty():
    assert humanize_identifier("address2") == "address 2"
    assert humanize_identifier("") == ""


# ---------------------------------------------------------------------------
# build_column_text / build_table_text
# ---------------------------------------------------------------------------

def test_column_text_full():
    text = build_column_text(
        table_name="orders",
        column_name="customer_id",
        data_type="INTEGER",
        patterns=["identifier"],
        definition="Links each order to the customer who placed it.",
        sample_values=["1", "42", "17"],
        fk_target="customers.id",
    )
    assert text == (
        "column orders.customer_id (orders customer id) | type: INTEGER | "
        "patterns: identifier | references customers.id | "
        "Links each order to the customer who placed it. | examples: 1, 42, 17"
    )


def test_column_text_omits_missing_parts():
    text = build_column_text(
        table_name="customers",
        column_name="notes",
        data_type=None,
        patterns=[],
        definition="Free-form notes.",
        sample_values=None,
    )
    assert text == "column customers.notes (customers notes) | Free-form notes."
    assert "type:" not in text
    assert "references" not in text
    assert "examples:" not in text


def test_column_text_truncates_and_caps_samples():
    long_value = "x" * 200
    text = build_column_text(
        "t", "c", "TEXT", [], "Def.", [long_value] + [f"v{i}" for i in range(20)]
    )
    # values truncated to 60 chars, max 10 samples included
    assert "x" * 60 in text and "x" * 61 not in text
    assert "v8" in text and "v10" not in text


def test_table_text_full():
    text = build_table_text(
        table_name="order_items",
        definition="Line items within an order.",
        column_names=["id", "order_id", "quantity"],
        row_count=1500,
    )
    assert text == (
        "table order_items (order items) | columns: id, order_id, quantity | "
        "rows: ~1500 | Line items within an order."
    )


# ---------------------------------------------------------------------------
# extract_value_tokens
# ---------------------------------------------------------------------------

def test_extracts_literal_name():
    assert "janet" in extract_value_tokens("person name Janet")


def test_drops_stopwords():
    tokens = extract_value_tokens("find the name of the person called Janet")
    assert tokens == ["janet"]


def test_quoted_phrases_kept_verbatim():
    tokens = extract_value_tokens('customers in "New York" with status shipped')
    assert "new york" in tokens
    assert "shipped" in tokens


def test_emails_and_short_words():
    tokens = extract_value_tokens("user with email alice@example.com or id 42")
    assert "alice@example.com" in tokens
    assert "42" not in tokens  # under 3 chars


def test_dedupe_and_cap():
    tokens = extract_value_tokens("janet janet janet " + " ".join(f"word{i}" for i in range(20)))
    assert tokens.count("janet") == 1
    assert len(tokens) <= 8


# ---------------------------------------------------------------------------
# float16 round-trip: indexer packing -> maxsim decoding
# ---------------------------------------------------------------------------

def test_indexer_packing_roundtrips_through_maxsim_decoder():
    from src.services.maxsim import decode_multivector
    from src.workers.schema_indexer import _pack_multivector

    multivector = np.random.rand(12, 128).astype(np.float32).tolist()
    pooled, packed, n_vectors = _pack_multivector(multivector)

    assert n_vectors == 12
    assert len(pooled) == 128
    decoded = decode_multivector(packed, n_vectors)
    np.testing.assert_allclose(
        decoded, np.array(multivector, dtype=np.float16).astype(np.float32)
    )


def test_pack_empty_multivector():
    from src.workers.schema_indexer import _pack_multivector

    assert _pack_multivector([]) == (None, None, None)
