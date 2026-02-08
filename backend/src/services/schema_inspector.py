"""
Schema inspector for analyzing database structure.

Extracts tables, columns, relationships, and detects data patterns.
"""

import re
from typing import Any

from src.services.database_connector import DatabaseConnector


class SchemaInspector:
    """Analyze database schema structure and detect patterns."""

    def __init__(self, db_connector: DatabaseConnector):
        """
        Initialize schema inspector.

        Args:
            db_connector: DatabaseConnector instance
        """
        self.db_connector = db_connector

    def introspect_full_schema(self) -> dict[str, Any]:
        """
        Extract complete schema information including patterns.

        Returns:
            Dictionary with enriched schema information:
            {
                "tables": [
                    {
                        "name": "users",
                        "columns": [
                            {
                                "name": "email",
                                "type": "VARCHAR(255)",
                                "nullable": False,
                                "patterns": ["email"],
                                "sample_values": ["user@example.com", ...]
                            },
                            ...
                        ],
                        "foreign_keys": [...],
                        "row_count": 1000
                    },
                    ...
                ]
            }
        """
        # Get base schema info
        schema_info = self.db_connector.get_schema_info()

        # Enrich with samples and patterns
        enriched_tables = []
        for table in schema_info["tables"]:
            table_name = table["name"]

            # Sample data from table
            try:
                sample_rows = self.db_connector.sample_table(table_name, limit=10)
            except Exception as e:
                print(f"Warning: Failed to sample table '{table_name}': {e}")
                sample_rows = []

            # Enrich columns with patterns and samples
            enriched_columns = []
            for col in table["columns"]:
                col_name = col["name"]

                # Extract sample values for this column
                sample_values = [
                    row.get(col_name)
                    for row in sample_rows
                    if row.get(col_name) is not None
                ][:5]  # Keep first 5 non-null values

                # Detect patterns
                patterns = self._detect_value_patterns(col_name, col["type"], sample_values)

                enriched_columns.append({
                    **col,
                    "sample_values": sample_values,
                    "patterns": patterns,
                })

            # Try to get row count (approximate)
            try:
                result = self.db_connector.execute_query(
                    f"SELECT COUNT(*) as count FROM {table_name}",
                    limit=1
                )
                row_count = result["rows"][0][0] if result["rows"] else 0
            except Exception:
                row_count = None

            enriched_tables.append({
                **table,
                "columns": enriched_columns,
                "row_count": row_count,
            })

        return {"tables": enriched_tables}

    def _detect_value_patterns(
        self,
        column_name: str,
        data_type: str,
        sample_values: list[Any]
    ) -> list[str]:
        """
        Detect patterns in column name and sample values.

        Args:
            column_name: Name of column
            data_type: SQL data type
            sample_values: Sample values from column

        Returns:
            List of detected patterns (e.g., ['email', 'identifier'])
        """
        patterns = []
        col_lower = column_name.lower()

        # Pattern detection based on column name
        if any(term in col_lower for term in ["email", "mail"]):
            patterns.append("email")
        elif any(term in col_lower for term in ["phone", "mobile", "tel"]):
            patterns.append("phone")
        elif any(term in col_lower for term in ["url", "link", "website"]):
            patterns.append("url")
        elif any(term in col_lower for term in ["date", "time", "created", "updated"]):
            patterns.append("timestamp")
        elif any(term in col_lower for term in ["id", "_id"]) or col_lower.endswith("_id"):
            patterns.append("identifier")
        elif any(term in col_lower for term in ["uuid", "guid"]):
            patterns.append("uuid")
        elif any(term in col_lower for term in ["status", "state"]):
            patterns.append("status")
        elif any(term in col_lower for term in ["name", "title"]):
            patterns.append("name")
        elif any(term in col_lower for term in ["description", "comment", "notes"]):
            patterns.append("description")
        elif any(term in col_lower for term in ["amount", "price", "cost", "total"]):
            patterns.append("monetary")
        elif any(term in col_lower for term in ["count", "quantity", "number"]):
            patterns.append("numeric")

        # Pattern detection based on sample values
        if sample_values and len(sample_values) > 0:
            # Check first few sample values
            sample_strings = [str(v) for v in sample_values[:3] if v is not None]

            # Email pattern
            if any(self._is_email(s) for s in sample_strings):
                if "email" not in patterns:
                    patterns.append("email")

            # Phone pattern
            if any(self._is_phone(s) for s in sample_strings):
                if "phone" not in patterns:
                    patterns.append("phone")

            # URL pattern
            if any(self._is_url(s) for s in sample_strings):
                if "url" not in patterns:
                    patterns.append("url")

            # UUID pattern
            if any(self._is_uuid(s) for s in sample_strings):
                if "uuid" not in patterns:
                    patterns.append("uuid")

            # Boolean pattern
            if all(v in [True, False, 0, 1, "true", "false", "yes", "no"] for v in sample_values if v is not None):
                patterns.append("boolean")

        # Data type hints
        data_type_upper = data_type.upper()
        if "BOOL" in data_type_upper:
            if "boolean" not in patterns:
                patterns.append("boolean")
        elif any(t in data_type_upper for t in ["DATE", "TIME", "TIMESTAMP"]):
            if "timestamp" not in patterns:
                patterns.append("timestamp")
        elif any(t in data_type_upper for t in ["INT", "NUMERIC", "DECIMAL", "FLOAT", "DOUBLE"]):
            if not patterns or patterns == ["identifier"]:
                patterns.append("numeric")

        return patterns

    @staticmethod
    def _is_email(value: str) -> bool:
        """Check if value looks like an email."""
        email_pattern = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
        return bool(re.match(email_pattern, value))

    @staticmethod
    def _is_phone(value: str) -> bool:
        """Check if value looks like a phone number."""
        # Remove common separators
        cleaned = re.sub(r"[\s\-\(\)\.]", "", value)
        # Check if it's mostly digits and reasonable length
        return cleaned.isdigit() and 7 <= len(cleaned) <= 15

    @staticmethod
    def _is_url(value: str) -> bool:
        """Check if value looks like a URL."""
        url_pattern = r"^https?://[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"
        return bool(re.match(url_pattern, value))

    @staticmethod
    def _is_uuid(value: str) -> bool:
        """Check if value looks like a UUID."""
        uuid_pattern = r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
        return bool(re.match(uuid_pattern, value.lower()))
