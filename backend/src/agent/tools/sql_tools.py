"""
Unified SQL tools that work with both local SQLite and external connectors.

Tools accept either database_id (for local SQLite) or connector_id (for external databases).
When semantic definitions are available from the schema catalog, they're included in results.
"""

from uuid import UUID

from src.services.sqlite_service import sqlite_service

# Markers of SQL errors the agent can fix itself given the right context
_FIXABLE_ERROR_MARKERS = (
    "no such table",
    "no such column",
    "syntax error",
    "does not exist",       # PostgreSQL: relation/column does not exist
    "unknown column",       # MySQL
    "unknown table",        # MySQL
)

_DIALECT_HINTS = {
    "sqlite": (
        "This database is SQLite — use strftime() for dates, || for string "
        "concatenation, LIMIT (not TOP), and avoid RIGHT/FULL OUTER JOIN."
    ),
    "postgresql": (
        "This database is PostgreSQL — use date_trunc()/TO_CHAR() for dates, "
        "|| for concatenation, ILIKE for case-insensitive matching, and "
        "double quotes only for case-sensitive identifiers."
    ),
    "mysql": (
        "This database is MySQL — use DATE_FORMAT() for dates, CONCAT() "
        "instead of ||, and backticks for reserved-word identifiers."
    ),
}


def _fetch_connector_sync(connector_id: UUID):
    """Fetch a Connector row on a fresh sync session.

    Tool handlers run in worker threads (possibly several concurrently), so
    they must not share the request's AsyncSession — each call opens its own
    short-lived sync session, mirroring search_tools.py.
    """
    from sqlalchemy import select
    from src.db.database import SyncSessionLocal
    from src.models.connector import Connector

    with SyncSessionLocal() as db:
        return db.execute(
            select(Connector).where(Connector.id == connector_id)
        ).scalar_one_or_none()


def _build_database_connector(connector):
    """Build a DatabaseConnector with the decrypted connection string."""
    from src.services.database_connector import DatabaseConnector
    from src.utils.encryption import encryption_service

    return DatabaseConnector(encryption_service.decrypt(connector.connection_string))


def _is_fixable_sql_error(error: str) -> bool:
    lowered = error.lower()
    return any(marker in lowered for marker in _FIXABLE_ERROR_MARKERS)


def _enrich_sqlite_error(error: str, context) -> str:
    """Append dialect + schema hints so the agent can correct itself in one retry."""
    parts = [f"Error: {error}", f"Hint: {_DIALECT_HINTS['sqlite']}"]
    lowered = error.lower()
    if "no such table" in lowered or "no such column" in lowered:
        try:
            tables = sqlite_service.list_tables(context.database_path)
            names = ", ".join(t["name"] for t in tables)
            parts.append(
                f"Available tables: {names}. "
                "Call get_table_info(<table>) to confirm exact column names."
            )
        except Exception:
            pass
    return "\n".join(parts)


def execute_sql_query(sql: str, context, database_id: str = None, connector_id: str = None) -> str:
    """
    Execute a SQL query against a database (local SQLite or external connector).
    Only SELECT statements are allowed for safety.

    Args:
        sql: The SQL query to execute (SELECT only)
        database_id: Optional UUID of local SQLite database
        connector_id: Optional UUID of external connector

    Returns:
        Query results as formatted text
    """
    if not context:
        return "Error: No context available"

    # Determine which database to use
    target_database_id = database_id or (context.database_id if context else None)
    target_connector_id = connector_id or (context.connector_id if context else None)

    # SQLite path
    if target_database_id or (context and context.database_path):
        return _execute_sql_sqlite(sql, context)

    # External connector path
    elif target_connector_id:
        return _execute_sql_connector(sql, UUID(target_connector_id), context)

    else:
        return "Error: No database or connector specified. Please select a database or connector first."


def _execute_sql_sqlite(sql: str, context) -> str:
    """Execute SQL on local SQLite database."""
    if not context.database_path:
        return "Error: No database selected. Please select a database first."

    if not context.database_path.exists():
        return f"Error: Database file not found at {context.database_path}"

    # Execute query
    result = sqlite_service.execute_query(context.database_path, sql)

    if result.error:
        if _is_fixable_sql_error(result.error):
            return _enrich_sqlite_error(result.error, context)
        return f"Error: {result.error}"

    if not result.rows:
        return "NO_RESULTS: Query returned no results."

    # Format as table
    lines = []
    lines.append(" | ".join(result.columns))
    lines.append("-" * len(lines[0]))
    for row in result.rows[:50]:  # Limit display to 50 rows
        lines.append(" | ".join(str(v) if v is not None else "NULL" for v in row))

    if result.row_count > 50:
        lines.append(f"... ({result.row_count} total rows, showing first 50)")

    return "\n".join(lines)


def _execute_sql_connector(sql: str, connector_id: UUID, context) -> str:
    """Execute SQL on external connector database."""
    connector = None
    try:
        connector = _fetch_connector_sync(connector_id)

        if not connector:
            return f"Error: Connector {connector_id} not found"

        if connector.status != "ready":
            return f"Error: Connector '{connector.name}' is not ready (status: {connector.status})"

        db_connector = _build_database_connector(connector)

        # Execute query
        result = db_connector.execute_query(sql, limit=1000)

        if not result["rows"]:
            return "NO_RESULTS: Query returned no results."

        # Format as table
        lines = []
        lines.append(" | ".join(result["columns"]))
        lines.append("-" * len(lines[0]))
        for row in result["rows"][:50]:  # Limit display to 50 rows
            lines.append(" | ".join(str(v) if v is not None else "NULL" for v in row))

        if result["row_count"] > 50:
            lines.append(f"... ({result['row_count']} total rows, showing first 50)")

        return "\n".join(lines)

    except Exception as e:
        message = f"Error executing query: {str(e)}"
        if connector is not None and _is_fixable_sql_error(str(e)):
            hint = _DIALECT_HINTS.get((connector.db_type or "").lower())
            if hint:
                message += f"\nHint: {hint}"
            message += "\nCall list_tables or get_table_info to verify table and column names."
        return message


def get_database_schema(context, database_id: str = None, connector_id: str = None) -> str:
    """
    Get the complete schema of the database including all tables,
    columns, types, and relationships.

    For external connectors with semantic catalog, includes LLM-generated definitions.

    Args:
        database_id: Optional UUID of local SQLite database
        connector_id: Optional UUID of external connector

    Returns:
        Formatted schema information
    """
    if not context:
        return "Error: No context available"

    # Determine which database to use
    target_database_id = database_id or (context.database_id if context else None)
    target_connector_id = connector_id or (context.connector_id if context else None)

    # SQLite path
    if target_database_id or (context and context.database_path):
        return _get_schema_sqlite(context)

    # External connector path - fetch from semantic catalog
    elif target_connector_id:
        return _get_schema_connector(UUID(target_connector_id), context)

    else:
        return "Error: No database or connector specified."


def _get_schema_sqlite(context) -> str:
    """Get schema for local SQLite database."""
    if not context.database_path:
        return "Error: No database selected. Please select a database first."

    if not context.database_path.exists():
        return f"Error: Database file not found at {context.database_path}"

    schema = sqlite_service.get_schema(
        context.database_path,
        context.database_id,
        context.database_name or "Database"
    )

    lines = [f"# Database: {schema.database_name}", ""]
    for table in schema.tables:
        lines.append(f"## Table: {table.name} ({table.row_count} rows)")
        lines.append("Columns:")
        for col in table.columns:
            pk = " [PK]" if col.primary_key else ""
            fk = f" -> {col.foreign_key}" if col.foreign_key else ""
            nullable = " (nullable)" if col.nullable else ""
            lines.append(f"  - {col.name}: {col.type}{pk}{fk}{nullable}")
        if table.sample_data:
            lines.append("Sample data (first 3 rows):")
            for row in table.sample_data[:3]:
                lines.append(f"  {row}")
        lines.append("")

    return "\n".join(lines)


def _get_schema_connector(connector_id: UUID, context) -> str:
    """Get schema for external connector from semantic catalog."""
    try:
        from sqlalchemy import select
        from src.db.database import SyncSessionLocal
        from src.models.connector import SchemaDefinition

        connector = _fetch_connector_sync(connector_id)

        if not connector:
            return f"Error: Connector {connector_id} not found"

        # Fetch schema definitions from catalog
        with SyncSessionLocal() as db:
            stmt = select(SchemaDefinition).where(
                SchemaDefinition.connector_id == connector_id
            ).order_by(SchemaDefinition.table_name, SchemaDefinition.definition_type)
            definitions = list(db.execute(stmt).scalars().all())

        if not definitions:
            return f"Error: No schema definitions found for connector '{connector.name}'. Has it been indexed?"

        # Group by table
        tables = {}
        for defn in definitions:
            if defn.table_name not in tables:
                tables[defn.table_name] = {"table_def": None, "columns": []}

            if defn.definition_type == "table":
                tables[defn.table_name]["table_def"] = defn
            else:
                tables[defn.table_name]["columns"].append(defn)

        # Format output with semantic definitions
        lines = [f"# Database: {connector.name} ({connector.db_type})", ""]

        for table_name, table_data in tables.items():
            table_def = table_data["table_def"]
            if table_def:
                lines.append(f"## Table: {table_name}")
                lines.append(f"**Description**: {table_def.semantic_definition}")
                lines.append("")

            lines.append("Columns:")
            for col_def in table_data["columns"]:
                lines.append(f"  - **{col_def.column_name}** ({col_def.data_type})")
                lines.append(f"    {col_def.semantic_definition}")
                if col_def.sample_values:
                    sample_str = ", ".join(str(v) for v in col_def.sample_values[:3])
                    lines.append(f"    Examples: {sample_str}")
            lines.append("")

        return "\n".join(lines)

    except Exception as e:
        return f"Error fetching schema: {str(e)}"


def list_tables(context, database_id: str = None, connector_id: str = None) -> str:
    """
    List all tables in the database with basic info.

    Args:
        database_id: Optional UUID of local SQLite database
        connector_id: Optional UUID of external connector

    Returns:
        Table names with row counts and column counts
    """
    if not context:
        return "Error: No context available"

    # Determine which database to use
    target_database_id = database_id or (context.database_id if context else None)
    target_connector_id = connector_id or (context.connector_id if context else None)

    # SQLite path
    if target_database_id or (context and context.database_path):
        return _list_tables_sqlite(context)

    # External connector path
    elif target_connector_id:
        return _list_tables_connector(UUID(target_connector_id), context)

    else:
        return "Error: No database or connector specified."


def _list_tables_sqlite(context) -> str:
    """List tables in local SQLite database."""
    if not context.database_path:
        return "Error: No database selected. Please select a database first."

    if not context.database_path.exists():
        return f"Error: Database file not found at {context.database_path}"

    tables = sqlite_service.list_tables(context.database_path)

    if not tables:
        return "No tables found in database."

    lines = [f"Tables in database '{context.database_name or 'Database'}':", ""]
    for table in tables:
        lines.append(f"- {table['name']}: {table['row_count']} rows, {table['column_count']} columns")

    return "\n".join(lines)


def _list_tables_connector(connector_id: UUID, context) -> str:
    """List tables in external connector."""
    try:
        from sqlalchemy import select, func
        from src.db.database import SyncSessionLocal
        from src.models.connector import SchemaDefinition

        connector = _fetch_connector_sync(connector_id)

        if not connector:
            return f"Error: Connector {connector_id} not found"

        # Get table definitions
        with SyncSessionLocal() as db:
            stmt = select(
                SchemaDefinition.table_name,
                func.count(SchemaDefinition.id).label("column_count")
            ).where(
                SchemaDefinition.connector_id == connector_id,
                SchemaDefinition.definition_type == "column"
            ).group_by(SchemaDefinition.table_name).order_by(SchemaDefinition.table_name)

            tables = db.execute(stmt).fetchall()

        if not tables:
            return f"No tables found in connector '{connector.name}'."

        lines = [f"Tables in database '{connector.name}' ({connector.db_type}):", ""]
        for table_name, column_count in tables:
            lines.append(f"- {table_name}: {column_count} columns")

        return "\n".join(lines)

    except Exception as e:
        return f"Error listing tables: {str(e)}"


def get_table_info(table_name: str, context, database_id: str = None, connector_id: str = None) -> str:
    """
    Get detailed information about a specific table.

    Args:
        table_name: Name of the table to inspect
        database_id: Optional UUID of local SQLite database
        connector_id: Optional UUID of external connector

    Returns:
        Column definitions, keys, and sample data
    """
    if not context:
        return "Error: No context available"

    # Determine which database to use
    target_database_id = database_id or (context.database_id if context else None)
    target_connector_id = connector_id or (context.connector_id if context else None)

    # SQLite path
    if target_database_id or (context and context.database_path):
        return _get_table_info_sqlite(table_name, context)

    # External connector path
    elif target_connector_id:
        return _get_table_info_connector(table_name, UUID(target_connector_id), context)

    else:
        return "Error: No database or connector specified."


def _get_table_info_sqlite(table_name: str, context) -> str:
    """Get table info from local SQLite database."""
    if not context.database_path:
        return "Error: No database selected. Please select a database first."

    if not context.database_path.exists():
        return f"Error: Database file not found at {context.database_path}"

    schema = sqlite_service.get_schema(
        context.database_path,
        context.database_id,
        context.database_name or "Database"
    )

    for table in schema.tables:
        if table.name.lower() == table_name.lower():
            lines = [f"# Table: {table.name}", f"Row count: {table.row_count}", "", "Columns:"]
            for col in table.columns:
                pk = " [PRIMARY KEY]" if col.primary_key else ""
                fk = f" -> {col.foreign_key}" if col.foreign_key else ""
                nullable = " (nullable)" if col.nullable else " (NOT NULL)"
                lines.append(f"  - {col.name}: {col.type}{pk}{fk}{nullable}")

            if table.sample_data:
                lines.append("")
                lines.append("Sample data (first 5 rows):")
                for row in table.sample_data[:5]:
                    lines.append(f"  {row}")

            return "\n".join(lines)

    return f"Table '{table_name}' not found in database."


def _get_table_info_connector(table_name: str, connector_id: UUID, context) -> str:
    """Get table info from external connector with semantic definitions."""
    try:
        from sqlalchemy import select
        from src.db.database import SyncSessionLocal
        from src.models.connector import SchemaDefinition

        connector = _fetch_connector_sync(connector_id)

        if not connector:
            return f"Error: Connector {connector_id} not found"

        # Fetch schema definitions for this table
        with SyncSessionLocal() as db:
            stmt = select(SchemaDefinition).where(
                SchemaDefinition.connector_id == connector_id,
                SchemaDefinition.table_name == table_name
            ).order_by(SchemaDefinition.definition_type)
            definitions = list(db.execute(stmt).scalars().all())

        if not definitions:
            return f"Table '{table_name}' not found in connector '{connector.name}'."

        # Format output
        lines = [f"# Table: {table_name}"]

        # Table definition
        table_def = next((d for d in definitions if d.definition_type == "table"), None)
        if table_def:
            lines.append(f"**Description**: {table_def.semantic_definition}")
        lines.append("")

        # Column definitions
        lines.append("Columns:")
        for col_def in [d for d in definitions if d.definition_type == "column"]:
            lines.append(f"  - **{col_def.column_name}** ({col_def.data_type})")
            lines.append(f"    {col_def.semantic_definition}")
            if col_def.sample_values:
                sample_str = ", ".join(str(v) for v in col_def.sample_values[:3])
                lines.append(f"    Examples: {sample_str}")

        return "\n".join(lines)

    except Exception as e:
        return f"Error fetching table info: {str(e)}"
