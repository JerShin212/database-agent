"""Unit tests for dialect-aware SQL error enrichment in sql_tools."""

import sqlite3
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

backend_path = Path(__file__).parent.parent
sys.path.insert(0, str(backend_path))

from src.agent.tools.sql_tools import (
    _enrich_sqlite_error,
    _execute_sql_sqlite,
    _is_fixable_sql_error,
)


@pytest.fixture
def sqlite_db(tmp_path):
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE customers (id INTEGER PRIMARY KEY, name TEXT)")
    conn.execute("CREATE TABLE orders (id INTEGER PRIMARY KEY, customer_id INTEGER)")
    conn.execute("INSERT INTO customers (name) VALUES ('Janet')")
    conn.commit()
    conn.close()
    return db_path


def _context(db_path):
    return SimpleNamespace(
        database_path=db_path,
        database_id="test-id",
        database_name="test",
    )


def test_bad_column_error_includes_hint_and_table_list(sqlite_db):
    result = _execute_sql_sqlite("SELECT email FROM customers", _context(sqlite_db))

    assert "no such column" in result
    assert "SQLite" in result
    assert "customers" in result and "orders" in result
    assert "get_table_info" in result


def test_bad_table_error_includes_table_list(sqlite_db):
    result = _execute_sql_sqlite("SELECT * FROM invoices", _context(sqlite_db))

    assert "no such table" in result
    assert "Available tables:" in result


def test_valid_query_unaffected(sqlite_db):
    result = _execute_sql_sqlite("SELECT name FROM customers", _context(sqlite_db))
    assert "Janet" in result
    assert "Hint" not in result


def test_non_sql_errors_not_enriched():
    assert not _is_fixable_sql_error("Only SELECT queries are allowed")
    assert not _is_fixable_sql_error("Query contains forbidden keyword: DROP")
    assert _is_fixable_sql_error("no such table: foo")
    assert _is_fixable_sql_error('column "email" does not exist')
    assert _is_fixable_sql_error("Unknown column 'email' in 'field list'")


def test_enrich_syntax_error_has_dialect_hint_but_no_table_list(sqlite_db):
    enriched = _enrich_sqlite_error('near "FORM": syntax error', _context(sqlite_db))
    assert "SQLite" in enriched
    assert "Available tables" not in enriched
