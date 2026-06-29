"""Injection / safety tests for the execute_sql_query input guard."""

import sys
from pathlib import Path

backend_path = Path(__file__).parent.parent
sys.path.insert(0, str(backend_path))

import pytest

from src.agent.sdk.sql_safety import validate_sql, ensure_limit


REJECTED = [
    "DROP TABLE users",
    "delete from orders",
    "INSERT INTO t VALUES (1)",
    "UPDATE t SET x = 1",
    "TRUNCATE t",
    "ALTER TABLE t ADD COLUMN x int",
    "CREATE TABLE t (id int)",
    "SELECT 1; DELETE FROM t",                 # stacked statements
    "SELECT 1 -- comment",                     # sql comment
    "SELECT 1 /* block */",                    # block comment
    "SELECT pg_read_file('/etc/passwd')",      # dangerous function
    "SELECT pg_sleep(10)",
    "SELECT * FROM t; SELECT * FROM u",        # multiple statements
    "GRANT ALL ON t TO public",
    "COPY t FROM '/etc/passwd'",
    "WITH x AS (DELETE FROM t RETURNING *) SELECT * FROM x",  # data-modifying CTE
    "",
    "   ",
]

ACCEPTED = [
    "SELECT * FROM customers",
    "select id, name from orders where amount > 100",
    "WITH recent AS (SELECT * FROM orders ORDER BY order_date DESC LIMIT 10) SELECT * FROM recent",
    "SELECT count(*) FROM products WHERE stock_quantity = 0",
    "SELECT c.name FROM customers c JOIN orders o ON o.customer_id = c.id",
    "SELECT * FROM t LIMIT ALL",               # bypass attempt — still read-only; outer LIMIT caps it
]


@pytest.mark.parametrize("sql", REJECTED)
def test_rejects_unsafe(sql):
    ok, reason = validate_sql(sql)
    assert not ok, f"should have rejected: {sql!r}"
    assert reason


@pytest.mark.parametrize("sql", ACCEPTED)
def test_accepts_select(sql):
    ok, reason = validate_sql(sql)
    assert ok, f"should have accepted {sql!r} (reason: {reason})"


def test_ensure_limit_wraps_and_caps():
    wrapped = ensure_limit("SELECT * FROM t", 100)
    assert wrapped.lstrip().lower().startswith("select * from (")
    assert wrapped.rstrip().endswith("LIMIT 100")


def test_ensure_limit_neutralizes_limit_all():
    # The model's own `LIMIT ALL` is wrapped inside a subquery with a hard outer
    # LIMIT, so it cannot return unbounded rows.
    wrapped = ensure_limit("SELECT * FROM t LIMIT ALL", 50)
    assert wrapped.rstrip().endswith("LIMIT 50")
    assert "LIMIT ALL" in wrapped  # inner query preserved, but outer cap wins


def test_ensure_limit_strips_trailing_semicolon():
    wrapped = ensure_limit("SELECT 1;", 10)
    assert ";" not in wrapped.replace("LIMIT 10", "")
