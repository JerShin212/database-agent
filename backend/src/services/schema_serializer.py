"""
Schema catalog serialization — builds the enriched text that gets embedded
and searched for each table/column catalog entry, and extracts candidate
data-value tokens from user queries for value-aware retrieval.

The serialization deliberately packs every retrieval-relevant signal into one
string: humanized identifier tokens (so "customer id" matches customer_id),
data types, detected patterns, FK targets, the LLM definition, and sample
values (so a query containing a literal like "Janet" can match the column
whose data contains it).
"""

from __future__ import annotations

import re

# Words too generic to act as value-match tokens in a schema search query
_STOPWORDS = {
    "the", "and", "for", "with", "from", "that", "this", "what", "which",
    "who", "whose", "where", "when", "how", "many", "much", "all", "any",
    "are", "was", "were", "has", "have", "had", "does", "did", "not",
    "name", "named", "called", "value", "values", "find", "show", "list",
    "get", "give", "person", "table", "column", "data", "record", "records",
    "info", "information", "about", "their", "there",
}

_MAX_SAMPLE_CHARS = 60  # per-sample truncation inside embedded text
_MAX_SAMPLES_IN_TEXT = 10


def humanize_identifier(name: str) -> str:
    """
    Convert a SQL identifier into space-separated words:
    "customer_id" -> "customer id", "createdAt" -> "created at",
    "OrderItems" -> "order items".
    """
    if not name:
        return ""
    # snake/kebab separators -> spaces
    text = re.sub(r"[_\-]+", " ", name)
    # split camelCase / PascalCase boundaries
    text = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", text)
    # split letter-digit boundaries (address2 -> address 2)
    text = re.sub(r"(?<=[A-Za-z])(?=\d)", " ", text)
    return " ".join(text.lower().split())


def _format_samples(sample_values: list | None) -> str:
    if not sample_values:
        return ""
    truncated = [
        str(v)[:_MAX_SAMPLE_CHARS]
        for v in sample_values[:_MAX_SAMPLES_IN_TEXT]
        if v is not None
    ]
    return ", ".join(truncated)


def build_column_text(
    table_name: str,
    column_name: str,
    data_type: str | None,
    patterns: list[str] | None,
    definition: str,
    sample_values: list | None,
    fk_target: str | None = None,
) -> str:
    """
    Enriched embedding/search text for a column catalog entry.

    Example:
        column orders.customer_id (orders customer id) | type: INTEGER |
        patterns: identifier | references customers.id |
        Links each order to the customer who placed it. | examples: 1, 42, 17
    """
    parts = [
        f"column {table_name}.{column_name} "
        f"({humanize_identifier(table_name)} {humanize_identifier(column_name)})"
    ]
    if data_type:
        parts.append(f"type: {data_type}")
    if patterns:
        parts.append(f"patterns: {', '.join(patterns)}")
    if fk_target:
        parts.append(f"references {fk_target}")
    if definition:
        parts.append(definition.strip())
    samples = _format_samples(sample_values)
    if samples:
        parts.append(f"examples: {samples}")
    return " | ".join(parts)


def build_table_text(
    table_name: str,
    definition: str,
    column_names: list[str],
    row_count: int | None = None,
) -> str:
    """
    Enriched embedding/search text for a table catalog entry.

    Example:
        table orders (orders) | columns: id, customer_id, order_date, status |
        rows: ~1000 | Records individual product orders with pricing...
    """
    parts = [f"table {table_name} ({humanize_identifier(table_name)})"]
    if column_names:
        parts.append(f"columns: {', '.join(column_names)}")
    if row_count is not None:
        parts.append(f"rows: ~{row_count}")
    if definition:
        parts.append(definition.strip())
    return " | ".join(parts)


def extract_value_tokens(query: str, max_tokens: int = 8) -> list[str]:
    """
    Extract candidate data-value tokens from a natural language query, for
    matching against stored sample values ("person name Janet" -> ["janet"]).

    Quoted phrases are kept verbatim; remaining words of 3+ chars are kept
    unless they're generic stopwords.
    """
    tokens: list[str] = []

    # Quoted phrases first ('Janet Smith', "New York")
    for match in re.findall(r"""["']([^"']{2,80})["']""", query):
        tokens.append(match.strip().lower())
    unquoted = re.sub(r"""["'][^"']{2,80}["']""", " ", query)

    for word in re.findall(r"[A-Za-z0-9@.\-']{3,}", unquoted):
        lowered = word.lower().strip(".-'")
        if len(lowered) >= 3 and lowered not in _STOPWORDS:
            tokens.append(lowered)

    # Dedupe preserving order
    seen: set[str] = set()
    unique = [t for t in tokens if not (t in seen or seen.add(t))]
    return unique[:max_tokens]
