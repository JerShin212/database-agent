import sqlite3
import os
from pathlib import Path
from typing import Any
from uuid import UUID
from src.config import settings
from src.schemas.database import TableInfo, ColumnInfo, SchemaResponse, QueryResponse


class SQLiteService:
    def __init__(self):
        self.data_path = Path(settings.sqlite_data_path)
        self.data_path.mkdir(parents=True, exist_ok=True)

    def get_db_path(self, database_id: UUID | str, file_path: str = None) -> Path:
        """Get the path to a SQLite database file."""
        if file_path:
            return self.data_path / file_path
        return self.data_path / f"{database_id}.db"

    def get_connection(self, db_path: Path) -> sqlite3.Connection:
        """Get a connection to a SQLite database."""
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def get_schema(self, db_path: Path, database_id: UUID, database_name: str) -> SchemaResponse:
        """Get the complete schema of a SQLite database."""
        conn = self.get_connection(db_path)
        cursor = conn.cursor()

        # Get all tables
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
        tables = cursor.fetchall()

        table_infos = []
        for (table_name,) in tables:
            table_info = self._get_table_info(cursor, table_name)
            table_infos.append(table_info)

        conn.close()

        return SchemaResponse(
            database_id=database_id,
            database_name=database_name,
            tables=table_infos,
        )

    def _get_table_info(self, cursor: sqlite3.Cursor, table_name: str) -> TableInfo:
        """Get detailed information about a table."""
        # Get column info
        cursor.execute(f"PRAGMA table_info({table_name})")
        columns_data = cursor.fetchall()

        # Get foreign keys
        cursor.execute(f"PRAGMA foreign_key_list({table_name})")
        fk_data = cursor.fetchall()
        fk_map = {row[3]: f"{row[2]}.{row[4]}" for row in fk_data}  # from_col -> to_table.to_col

        columns = []
        for col in columns_data:
            columns.append(
                ColumnInfo(
                    name=col[1],
                    type=col[2],
                    nullable=not col[3],
                    primary_key=bool(col[5]),
                    foreign_key=fk_map.get(col[1]),
                )
            )

        # Get row count
        cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
        row_count = cursor.fetchone()[0]

        # Get sample data (5 rows)
        cursor.execute(f"SELECT * FROM {table_name} LIMIT 5")
        sample_rows = cursor.fetchall()
        sample_data = [dict(row) for row in sample_rows] if sample_rows else None

        return TableInfo(
            name=table_name,
            columns=columns,
            row_count=row_count,
            sample_data=sample_data,
        )

    def execute_query(self, db_path: Path, sql: str, max_rows: int = 1000) -> QueryResponse:
        """Execute a SQL query and return results."""
        # Validate query is SELECT only
        sql_upper = sql.strip().upper()
        if not sql_upper.startswith("SELECT"):
            return QueryResponse(
                columns=[],
                rows=[],
                row_count=0,
                error="Only SELECT queries are allowed",
            )

        # Check for dangerous keywords
        dangerous_keywords = ["DROP", "DELETE", "INSERT", "UPDATE", "ALTER", "CREATE", "TRUNCATE"]
        for keyword in dangerous_keywords:
            if keyword in sql_upper:
                return QueryResponse(
                    columns=[],
                    rows=[],
                    row_count=0,
                    error=f"Query contains forbidden keyword: {keyword}",
                )

        try:
            conn = self.get_connection(db_path)
            cursor = conn.cursor()
            cursor.execute(sql)

            # Get column names
            columns = [description[0] for description in cursor.description] if cursor.description else []

            # Fetch rows with limit
            rows = []
            for i, row in enumerate(cursor):
                if i >= max_rows:
                    break
                rows.append(list(row))

            row_count = len(rows)
            conn.close()

            return QueryResponse(
                columns=columns,
                rows=rows,
                row_count=row_count,
            )

        except sqlite3.Error as e:
            return QueryResponse(
                columns=[],
                rows=[],
                row_count=0,
                error=str(e),
            )

    def list_tables(self, db_path: Path) -> list[dict]:
        """List all tables in the database with basic info."""
        conn = self.get_connection(db_path)
        cursor = conn.cursor()

        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
        tables = cursor.fetchall()

        result = []
        for (table_name,) in tables:
            cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
            row_count = cursor.fetchone()[0]

            cursor.execute(f"PRAGMA table_info({table_name})")
            column_count = len(cursor.fetchall())

            result.append({
                "name": table_name,
                "row_count": row_count,
                "column_count": column_count,
            })

        conn.close()
        return result


# Singleton instance
sqlite_service = SQLiteService()
