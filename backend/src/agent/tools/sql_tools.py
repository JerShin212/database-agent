from src.agent.tools.context import get_tool_context
from src.services.sqlite_service import sqlite_service


def execute_sql_query(sql: str) -> str:
    """
    Execute a SQL query against the SQLite database.
    Only SELECT statements are allowed for safety.

    Args:
        sql: The SQL query to execute (SELECT only)

    Returns:
        Query results as formatted text
    """
    context = get_tool_context()
    if not context:
        return "Error: No database context available"

    if not context.database_path:
        return "Error: No database selected. Please select a database first."

    if not context.database_path.exists():
        return f"Error: Database file not found at {context.database_path}"

    # Execute query
    result = sqlite_service.execute_query(context.database_path, sql)

    if result.error:
        return f"Error: {result.error}"

    if not result.rows:
        return "Query returned no results."

    # Format as table
    lines = []
    lines.append(" | ".join(result.columns))
    lines.append("-" * len(lines[0]))
    for row in result.rows[:50]:  # Limit display to 50 rows
        lines.append(" | ".join(str(v) if v is not None else "NULL" for v in row))

    if result.row_count > 50:
        lines.append(f"... ({result.row_count} total rows, showing first 50)")

    return "\n".join(lines)


def get_database_schema() -> str:
    """
    Get the complete schema of the database including all tables,
    columns, types, and relationships.

    Returns:
        Formatted schema information
    """
    context = get_tool_context()
    if not context:
        return "Error: No database context available"

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


def list_tables() -> str:
    """
    List all tables in the database with basic info.

    Returns:
        Table names with row counts and column counts
    """
    context = get_tool_context()
    if not context:
        return "Error: No database context available"

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


def get_table_info(table_name: str) -> str:
    """
    Get detailed information about a specific table.

    Args:
        table_name: Name of the table to inspect

    Returns:
        Column definitions, keys, and sample data
    """
    context = get_tool_context()
    if not context:
        return "Error: No database context available"

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
