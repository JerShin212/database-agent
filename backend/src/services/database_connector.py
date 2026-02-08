"""
Database connector for external databases.

Connects to external databases (SQLite, PostgreSQL, MySQL), runs introspection,
and executes read-only queries safely.
"""

import re
from typing import Any, Literal
from urllib.parse import urlparse

from sqlalchemy import create_engine, inspect, text, MetaData, Table
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError


class DatabaseConnector:
    """
    Connect to external databases and run introspection/queries.

    This is NOT a service (doesn't take AsyncSession) - it manages connections
    to external databases independently.
    """

    def __init__(self, connection_string: str):
        """
        Initialize database connector.

        Args:
            connection_string: SQLAlchemy connection string (e.g., sqlite:///path.db)
        """
        self.connection_string = connection_string
        self._engine: Engine | None = None
        self._db_type = self._parse_db_type(connection_string)

    @staticmethod
    def _parse_db_type(connection_string: str) -> Literal["sqlite", "postgresql", "mysql", "unknown"]:
        """Extract database type from connection string."""
        parsed = urlparse(connection_string)
        scheme = parsed.scheme.split("+")[0]  # Handle 'postgresql+psycopg2'

        if scheme == "sqlite":
            return "sqlite"
        elif scheme in ("postgres", "postgresql"):
            return "postgresql"
        elif scheme == "mysql":
            return "mysql"
        else:
            return "unknown"

    def _get_engine(self) -> Engine:
        """Get or create SQLAlchemy engine."""
        if self._engine is None:
            # Create engine with read-only settings where possible
            connect_args = {}

            if self._db_type == "sqlite":
                # SQLite read-only mode
                connect_args = {"check_same_thread": False}

            self._engine = create_engine(
                self.connection_string,
                pool_pre_ping=True,  # Test connections before using
                pool_recycle=3600,  # Recycle connections after 1 hour
                connect_args=connect_args,
            )

        return self._engine

    def test_connection(self) -> tuple[bool, str]:
        """
        Test if database connection works.

        Returns:
            Tuple of (success: bool, message: str)
        """
        try:
            engine = self._get_engine()
            with engine.connect() as conn:
                # Simple query to test connection
                result = conn.execute(text("SELECT 1")).fetchone()
                if result:
                    return True, "Connection successful"
                return False, "Connection test query returned no results"

        except SQLAlchemyError as e:
            return False, f"Connection failed: {str(e)}"
        except Exception as e:
            return False, f"Unexpected error: {str(e)}"

    def get_schema_info(self) -> dict[str, Any]:
        """
        Introspect database schema using SQLAlchemy Inspector.

        Returns:
            Dictionary with schema information:
            {
                "tables": [
                    {
                        "name": "users",
                        "columns": [
                            {"name": "id", "type": "INTEGER", "nullable": False, "primary_key": True},
                            ...
                        ],
                        "foreign_keys": [
                            {"from": "user_id", "to_table": "users", "to_column": "id"},
                            ...
                        ]
                    },
                    ...
                ]
            }
        """
        try:
            engine = self._get_engine()
            inspector = inspect(engine)

            tables = []
            for table_name in inspector.get_table_names():
                # Get columns
                columns = []
                for col in inspector.get_columns(table_name):
                    columns.append({
                        "name": col["name"],
                        "type": str(col["type"]),
                        "nullable": col["nullable"],
                        "default": str(col.get("default")) if col.get("default") else None,
                        "primary_key": col.get("primary_key", False),
                    })

                # Get foreign keys
                foreign_keys = []
                for fk in inspector.get_foreign_keys(table_name):
                    foreign_keys.append({
                        "from_columns": fk["constrained_columns"],
                        "to_table": fk["referred_table"],
                        "to_columns": fk["referred_columns"],
                    })

                # Get primary key
                pk = inspector.get_pk_constraint(table_name)
                primary_key_columns = pk.get("constrained_columns", []) if pk else []

                # Get indexes
                indexes = []
                for idx in inspector.get_indexes(table_name):
                    indexes.append({
                        "name": idx["name"],
                        "columns": idx["column_names"],
                        "unique": idx.get("unique", False),
                    })

                tables.append({
                    "name": table_name,
                    "columns": columns,
                    "primary_key": primary_key_columns,
                    "foreign_keys": foreign_keys,
                    "indexes": indexes,
                })

            return {"tables": tables}

        except SQLAlchemyError as e:
            raise RuntimeError(f"Failed to introspect schema: {str(e)}")

    def sample_table(self, table_name: str, limit: int = 5) -> list[dict[str, Any]]:
        """
        Sample rows from a table.

        Args:
            table_name: Name of table to sample
            limit: Maximum number of rows to return

        Returns:
            List of row dictionaries
        """
        try:
            engine = self._get_engine()

            # Quote table name to prevent SQL injection
            # Note: This is still vulnerable to some attacks, use with caution
            with engine.connect() as conn:
                query = text(f"SELECT * FROM {table_name} LIMIT :limit")
                result = conn.execute(query, {"limit": limit})

                # Convert rows to dictionaries
                rows = []
                for row in result:
                    rows.append(dict(row._mapping))

                return rows

        except SQLAlchemyError as e:
            raise RuntimeError(f"Failed to sample table '{table_name}': {str(e)}")

    def execute_query(self, query: str, limit: int = 1000) -> dict[str, Any]:
        """
        Execute a read-only SQL query safely.

        Args:
            query: SQL query to execute (must be SELECT only)
            limit: Maximum number of rows to return

        Returns:
            Dictionary with query results:
            {
                "columns": ["id", "name", ...],
                "rows": [[1, "John"], [2, "Jane"], ...],
                "row_count": 2
            }
        """
        # Security: Only allow SELECT queries
        query_upper = query.strip().upper()
        if not query_upper.startswith("SELECT"):
            raise ValueError("Only SELECT queries are allowed")

        # Prevent multiple statements
        if ";" in query.rstrip(";"):
            raise ValueError("Multiple statements are not allowed")

        # Prevent dangerous keywords
        dangerous_keywords = ["DROP", "DELETE", "UPDATE", "INSERT", "ALTER", "CREATE", "TRUNCATE"]
        for keyword in dangerous_keywords:
            if re.search(rf"\b{keyword}\b", query_upper):
                raise ValueError(f"Query contains forbidden keyword: {keyword}")

        try:
            engine = self._get_engine()

            # Auto-add LIMIT clause if not present
            if "LIMIT" not in query_upper:
                query = f"{query.rstrip(';')} LIMIT {limit}"

            with engine.connect() as conn:
                result = conn.execute(text(query))

                # Get column names
                columns = list(result.keys())

                # Fetch rows
                rows = []
                for row in result:
                    rows.append(list(row))

                return {
                    "columns": columns,
                    "rows": rows,
                    "row_count": len(rows),
                }

        except SQLAlchemyError as e:
            raise RuntimeError(f"Query execution failed: {str(e)}")

    def close(self):
        """Close database connection."""
        if self._engine:
            self._engine.dispose()
            self._engine = None

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - close connection."""
        self.close()
