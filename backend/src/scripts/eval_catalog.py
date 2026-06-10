"""
Semantic catalog retrieval evaluation — hit@k over a gold set of
(natural language query -> expected table.column) pairs against the
sample sales database.

Run inside the backend environment (needs PostgreSQL + the ColQwen2 text
endpoint):

    docker compose exec backend python -m src.scripts.eval_catalog
    # or locally:
    cd backend && .venv/bin/python -m src.scripts.eval_catalog

Flags:
    --connector-id UUID   connector to evaluate (default: newest 'ready' one)
    --k 1 3 5             cutoffs for hit@k (default 1 3 5)
    --no-value-signal     ablation: disable the sample-value match signal
    --no-maxsim           ablation: disable MaxSim reranking
    --ablation            run all four signal/rerank combinations

The ablation table is intended for the FYP report: it isolates how much the
value-aware signal and the MaxSim rerank each contribute to accuracy.
"""

from __future__ import annotations

import argparse
import sys
from uuid import UUID

from sqlalchemy import text

from src.agent.tools.schema_tools import retrieve_schema_entries
from src.db.database import SyncSessionLocal

# Gold set against the sample sales DB (create_sample_db.py):
# customers(name,email,phone,city,country), products(name,category,price,
# stock_quantity,description), sales_reps(name,email,region,hire_date),
# orders(customer_id,sales_rep_id,order_date,total_amount,status,
# shipping_address), order_items(order_id,product_id,quantity,unit_price),
# customer_sales_rep(customer_id,sales_rep_id,assigned_date).
#
# Expected values: "table.column" for column entries, "table" for table entries.
GOLD_SET: list[tuple[str, str]] = [
    # Paraphrase queries (no shared keywords with the identifier)
    ("how much inventory is left for each product", "products.stock_quantity"),
    ("total money spent on an order", "orders.total_amount"),
    ("when was the salesperson hired", "sales_reps.hire_date"),
    ("where should the order be delivered", "orders.shipping_address"),
    ("how many units of each product were bought", "order_items.quantity"),
    ("price of each item at purchase time", "order_items.unit_price"),
    # Keyword-friendly queries
    ("customer contact email", "customers.email"),
    ("date the order was placed", "orders.order_date"),
    ("which region does the rep cover", "sales_reps.region"),
    # Value queries (literal data values; need the value-match signal)
    ("customer named Jennifer", "customers.name"),
    ("orders that have been shipped", "orders.status"),
    ("customers living in Chicago", "customers.city"),
    ("products in the Electronics category", "products.category"),
    # Join/table-level queries
    ("which sales rep handles which customer", "customer_sales_rep"),
    ("table that links orders to the products inside them", "order_items"),
]


def _matches(result: dict, expected: str) -> bool:
    if "." in expected:
        table, column = expected.split(".", 1)
        return (
            result["definition_type"] == "column"
            and result["table_name"] == table
            and result["column_name"] == column
        )
    return result["table_name"] == expected and result["definition_type"] == "table"


def _table_matches(result: dict, expected: str) -> bool:
    """Looser metric: is the top result at least from the right table?
    (Tool output is grouped by table, so same-table near-misses still put
    the correct table first for the SQL agent.)"""
    expected_table = expected.split(".", 1)[0]
    return result["table_name"] == expected_table


def _find_default_connector() -> UUID | None:
    with SyncSessionLocal() as db:
        row = db.execute(text(
            "SELECT id FROM connectors WHERE status = 'ready' ORDER BY created_at DESC LIMIT 1"
        )).fetchone()
    return row[0] if row else None


def evaluate(
    connector_id: UUID,
    ks: list[int],
    use_value_signal: bool,
    use_maxsim: bool,
    verbose: bool = True,
) -> dict[int, float]:
    max_k = max(ks)
    hits = {k: 0 for k in ks}
    table_hits_at_1 = 0
    misses: list[tuple[str, str, list[str]]] = []

    for query, expected in GOLD_SET:
        results = retrieve_schema_entries(
            query, connector_id, limit=max_k,
            use_value_signal=use_value_signal, use_maxsim=use_maxsim,
        )
        rank = next(
            (i for i, r in enumerate(results, 1) if _matches(r, expected)), None
        )
        for k in ks:
            if rank is not None and rank <= k:
                hits[k] += 1
        if results and _table_matches(results[0], expected):
            table_hits_at_1 += 1
        if rank is None or rank > 1:
            top = [
                f"{r['table_name']}.{r['column_name']}" if r["column_name"] else r["table_name"]
                for r in results[:3]
            ]
            misses.append((query, expected, top))

    total = len(GOLD_SET)
    scores = {k: hits[k] / total for k in ks}
    scores["table@1"] = table_hits_at_1 / total

    if verbose:
        config = (f"value_signal={'on' if use_value_signal else 'off'}, "
                  f"maxsim={'on' if use_maxsim else 'off'}")
        print(f"\n=== {config} ===")
        for k in ks:
            print(f"  hit@{k}: {hits[k]}/{total} = {scores[k]:.2%}")
        print(f"  table@1: {table_hits_at_1}/{total} = {scores['table@1']:.2%}"
              "  (top result from the correct table)")
        if misses:
            print("  Not ranked #1:")
            for query, expected, top in misses:
                print(f"    '{query}' -> expected {expected}, got top-3: {top}")

    return scores


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate schema catalog retrieval")
    parser.add_argument("--connector-id", type=UUID, default=None)
    parser.add_argument("--k", type=int, nargs="+", default=[1, 3, 5])
    parser.add_argument("--no-value-signal", action="store_true")
    parser.add_argument("--no-maxsim", action="store_true")
    parser.add_argument("--ablation", action="store_true",
                        help="Run all 4 combinations of value-signal x maxsim")
    args = parser.parse_args()

    connector_id = args.connector_id or _find_default_connector()
    if not connector_id:
        print("No ready connector found. Index a database first "
              "(POST /api/connectors/{id}/index).", file=sys.stderr)
        return 1

    print(f"Evaluating connector {connector_id} on {len(GOLD_SET)} gold queries")

    if args.ablation:
        header_ks = " | ".join(f"hit@{k}" for k in args.k)
        print(f"\n| value signal | maxsim | {header_ks} | table@1 |")
        print("|---" * (3 + len(args.k)) + "|")
        for value_signal in (False, True):
            for maxsim in (False, True):
                scores = evaluate(connector_id, args.k, value_signal, maxsim, verbose=False)
                cells = " | ".join(f"{scores[k]:.2%}" for k in args.k)
                print(f"| {'on' if value_signal else 'off'} | "
                      f"{'on' if maxsim else 'off'} | {cells} | {scores['table@1']:.2%} |")
    else:
        evaluate(
            connector_id, args.k,
            use_value_signal=not args.no_value_signal,
            use_maxsim=not args.no_maxsim,
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
