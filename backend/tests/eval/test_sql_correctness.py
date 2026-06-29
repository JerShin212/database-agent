"""SQL-correctness eval: the real database_agent (Haiku + real SQL tools)
answers questions against a known SQLite fixture; answers must contain the
expected values.

search_schema_catalog is removed for this eval — it needs the Postgres
semantic catalog; the agent falls back to the raw schema tools, which is the
documented behavior when the catalog is unavailable.
"""

import sqlite3
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

backend_path = Path(__file__).parent.parent.parent
sys.path.insert(0, str(backend_path))

import asyncio
import os

from src.agent.sdk.descriptor import Descriptor
from src.agent.sdk.worker import run_worker

from .conftest import get_api_key

pytestmark = pytest.mark.eval

# (question, list of substrings — ANY one matching counts as correct)
SQL_CASES = [
    ("How many customers are there in total?", ["4"]),
    ("What is the total amount across all orders?", ["1,250", "1250"]),
    ("Which customer has placed the most orders?", ["Janet"]),
    ("How many products are out of stock?", ["1"]),
    ("Which city does Amir live in?", ["Penang"]),
    ("What is the most expensive product?", ["Air Purifier", "899"]),
    ("How many orders were placed in February 2026?", ["2"]),
    ("List the names of customers who have never placed an order.", ["Wei Ling"]),
]


@pytest.fixture(scope="module")
def fixture_db(tmp_path_factory):
    db_path = tmp_path_factory.mktemp("evaldb") / "shop.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE customers (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            city TEXT NOT NULL
        );
        CREATE TABLE products (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            price REAL NOT NULL,
            stock_quantity INTEGER NOT NULL
        );
        CREATE TABLE orders (
            id INTEGER PRIMARY KEY,
            customer_id INTEGER NOT NULL REFERENCES customers(id),
            product_id INTEGER NOT NULL REFERENCES products(id),
            amount REAL NOT NULL,
            order_date TEXT NOT NULL
        );
        INSERT INTO customers VALUES
            (1, 'Janet Lee', 'Kuala Lumpur'),
            (2, 'Amir Hassan', 'Penang'),
            (3, 'Mei Chen', 'Johor Bahru'),
            (4, 'Wei Ling', 'Kuala Lumpur');
        INSERT INTO products VALUES
            (1, 'Ceiling Fan', 120.0, 15),
            (2, 'Air Purifier', 899.0, 0),
            (3, 'Thermostat', 75.0, 32);
        INSERT INTO orders VALUES
            (1, 1, 1, 120.0, '2026-01-15'),
            (2, 1, 3, 75.0, '2026-02-02'),
            (3, 1, 3, 150.0, '2026-03-10'),
            (4, 2, 2, 830.0, '2026-02-20'),
            (5, 3, 1, 75.0, '2026-03-25');
        """
    )
    conn.commit()
    conn.close()
    return db_path


def _answer(question, fixture_db):
    # database_path set, no connector_id -> SQLite path; search_schema_catalog
    # returns a harmless "no catalog" message (no Postgres in this eval) and the
    # agent falls back to the raw schema tools, the documented behavior.
    os.environ["ANTHROPIC_API_KEY"] = get_api_key()
    descriptor = Descriptor(database_path=fixture_db, database_name="shop")
    return asyncio.run(run_worker("database_agent", question, descriptor, lambda e: None))


def test_sql_correctness(fixture_db):
    passed = 0
    failures = []

    for question, expected_any in SQL_CASES:
        answer = _answer(question, fixture_db)

        ok = any(expected in answer for expected in expected_any)
        if ok:
            passed += 1
        else:
            failures.append(f"  {question!r}: expected one of {expected_any}, got: {answer[:200]}")
        print(f"[sql] {'PASS' if ok else 'FAIL'} :: {question}")

    score = passed / len(SQL_CASES)
    print(f"\n[sql] SCORE: {passed}/{len(SQL_CASES)} = {score:.0%}")
    assert score >= 0.75, "SQL correctness below 75%:\n" + "\n".join(failures)
