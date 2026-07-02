"""
SQL input safety for the `execute_sql_query` MCP tool.

`execute_sql_query` is the only tool that accepts free-form, model-written SQL, so
it is the highest-risk surface. These checks run at the @tool boundary (see
sdk/servers.py) BEFORE the SQL reaches either the SQLite path or the external
connector path, giving both a single, uniform SELECT-only gate (previously only
the SQLite path enforced it).

Layered defenses (never rely on one):
  1. validate_sql()  — must be a single SELECT/WITH statement; block write/DDL
     keywords, statement-stacking, comments, and dangerous functions.
  2. ensure_limit()  — wrap as `SELECT * FROM (<query>) AS _limited LIMIT n`,
     which is immune to `LIMIT ALL` / `LIMIT $var` bypasses and caps row count
     regardless of what the model wrote.

The real query still runs against the existing read paths; this is defense in
depth, not a replacement for them.
"""

from __future__ import annotations

import re

# Keywords that must never appear as a statement verb. Matched as whole words so
# columns like "created_at" or "update_count" are not false-positives.
_BLOCKED_KEYWORDS = (
    "insert", "update", "delete", "drop", "alter", "create", "truncate",
    "replace", "merge", "grant", "revoke", "attach", "detach", "vacuum",
    "pragma", "copy", "do", "call", "execute", "exec", "set",
)

# Dangerous functions / access patterns (mostly PostgreSQL).
_BLOCKED_FUNCTIONS = (
    "pg_read_file", "pg_read_binary_file", "pg_write_file", "pg_ls_dir",
    "pg_stat_file", "pg_terminate_backend", "pg_sleep", "pg_cancel_backend",
    "lo_import", "lo_export", "dblink", "current_setting", "set_config",
    "load_extension", "readfile", "writefile", "sys_exec", "sys_eval",
)

_SELECT_COUNT_CAP = 20  # bound subquery complexity / pathological nesting

_DEFAULT_ROW_LIMIT = 1000


def validate_sql(sql: str) -> tuple[bool, str]:
    """Return (ok, reason). ok=True means the SQL is a safe read-only query."""
    if not sql or not sql.strip():
        return False, "empty query"

    stripped = sql.strip()

    # 2. No comments — they are a classic way to smuggle past keyword checks.
    if "--" in stripped or "/*" in stripped or "*/" in stripped:
        return False, (
            "SQL comments are not allowed (this also rejects '--' or '/*' inside "
            "string literals — rewrite the query without those character sequences)"
        )

    # 3. No statement stacking. A single trailing ';' is tolerated and stripped.
    body = stripped.rstrip().rstrip(";").strip()
    if ";" in body:
        return False, "multiple statements are not allowed"

    lowered = body.lower()

    # 1. Must start with SELECT or WITH (CTE that resolves to a SELECT).
    if not (lowered.startswith("select") or lowered.startswith("with")):
        return False, "only SELECT / WITH (read-only) queries are allowed"

    # A WITH must contain a SELECT and must not define a data-modifying CTE.
    if lowered.startswith("with") and "select" not in lowered:
        return False, "WITH query must resolve to a SELECT"

    # Whole-word keyword denylist.
    words = set(re.findall(r"[a-z_][a-z0-9_]*", lowered))
    for kw in _BLOCKED_KEYWORDS:
        if kw in words:
            return False, f"keyword '{kw.upper()}' is not allowed in a read-only query"

    # Dangerous function denylist (substring — function names are distinctive).
    for fn in _BLOCKED_FUNCTIONS:
        if fn in lowered:
            return False, f"function '{fn}' is not allowed"

    # Bound complexity.
    if len(re.findall(r"\bselect\b", lowered)) > _SELECT_COUNT_CAP:
        return False, "query is too complex (too many nested SELECTs)"

    return True, ""


def ensure_limit(sql: str, limit: int = _DEFAULT_ROW_LIMIT) -> str:
    """Wrap the query so at most `limit` rows can ever be returned.

    Assumes validate_sql() already passed (no trailing ';', no comments), so the
    subquery wrap is safe. Immune to `LIMIT ALL` / `LIMIT $var` bypasses because
    the outer LIMIT is a literal we control.

    Note: the SQL standard does not guarantee that an inner ORDER BY survives a
    subquery wrap, but SQLite, PostgreSQL and MySQL all preserve it in practice
    when the outer query is a bare SELECT * ... LIMIT.
    """
    inner = sql.strip().rstrip(";").strip()
    try:
        n = max(1, int(limit))
    except (TypeError, ValueError):
        n = _DEFAULT_ROW_LIMIT
    return f"SELECT * FROM (\n{inner}\n) AS _limited LIMIT {n}"
