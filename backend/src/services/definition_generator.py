"""
Definition generator using LLM.

Generates human-readable semantic definitions for tables and columns.
"""

import json
from typing import Any

from openai import AsyncOpenAI

from src.config import settings


class DefinitionGenerator:
    """Singleton service for generating semantic definitions using LLM."""

    _instance = None
    _client = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialize()
        return cls._instance

    def _initialize(self):
        """Initialize OpenAI client."""
        self._client = AsyncOpenAI(api_key=settings.openai_api_key)

    async def generate_column_definition(
        self,
        table_name: str,
        column_name: str,
        data_type: str,
        nullable: bool,
        patterns: list[str],
        sample_values: list[Any],
        foreign_key_info: dict | None = None,
    ) -> str:
        """
        Generate semantic definition for a database column.

        Args:
            table_name: Name of the table
            column_name: Name of the column
            data_type: SQL data type
            nullable: Whether column accepts NULL
            patterns: Detected patterns (e.g., ['email', 'identifier'])
            sample_values: Sample values from the column
            foreign_key_info: Optional FK information

        Returns:
            Human-readable semantic definition
        """
        # Build context
        context_parts = [
            f"Table: {table_name}",
            f"Column: {column_name}",
            f"Data Type: {data_type}",
            f"Nullable: {nullable}",
        ]

        if patterns:
            context_parts.append(f"Detected Patterns: {', '.join(patterns)}")

        if sample_values:
            # Convert to strings and limit length
            sample_str = ", ".join(str(v)[:50] for v in sample_values[:5])
            context_parts.append(f"Sample Values: {sample_str}")

        if foreign_key_info:
            context_parts.append(
                f"Foreign Key: References {foreign_key_info['to_table']}.{foreign_key_info['to_column']}"
            )

        context = "\n".join(context_parts)

        # Generate definition
        prompt = f"""You are a database documentation expert. Generate a concise, human-readable definition for this database column.

{context}

Write a 1-2 sentence definition that explains:
1. What this column represents in business terms (not just technical description)
2. What kind of data it stores and how it's used

Be specific and practical. Focus on business meaning, not just repeating the technical details.

Example good definitions:
- "User's primary email address for login and notifications"
- "Unique identifier for the order, used to track purchases across the system"
- "Timestamp when the user account was created, used for analytics and user tenure calculations"

Definition:"""

        try:
            response = await self._client.chat.completions.create(
                model=settings.openai_api_key and "gpt-4o-mini" or "gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": "You are a database documentation expert."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,  # Lower temperature for more consistent output
                max_tokens=150,
            )

            definition = response.choices[0].message.content.strip()
            return definition

        except Exception as e:
            # Fallback to basic definition
            return f"{column_name} ({data_type}): {', '.join(patterns) if patterns else 'Column in ' + table_name}"

    async def generate_table_definition(
        self,
        table_name: str,
        columns: list[dict],
        row_count: int | None,
        foreign_keys: list[dict],
    ) -> str:
        """
        Generate semantic definition for a database table.

        Args:
            table_name: Name of the table
            columns: List of column information
            row_count: Approximate row count
            foreign_keys: List of foreign key relationships

        Returns:
            Human-readable semantic definition
        """
        # Build context
        context_parts = [
            f"Table Name: {table_name}",
            f"Number of Columns: {len(columns)}",
        ]

        if row_count is not None:
            context_parts.append(f"Approximate Row Count: {row_count:,}")

        # Key columns
        key_columns = [col["name"] for col in columns[:5]]  # First 5 columns
        context_parts.append(f"Key Columns: {', '.join(key_columns)}")

        # Primary key
        pk_cols = [col["name"] for col in columns if col.get("primary_key")]
        if pk_cols:
            context_parts.append(f"Primary Key: {', '.join(pk_cols)}")

        # Foreign keys
        if foreign_keys:
            fk_summary = []
            for fk in foreign_keys[:3]:  # Show first 3 FKs
                fk_summary.append(
                    f"{', '.join(fk['from_columns'])} → {fk['to_table']}.{', '.join(fk['to_columns'])}"
                )
            context_parts.append(f"Foreign Keys:\n  " + "\n  ".join(fk_summary))

        context = "\n".join(context_parts)

        # Generate definition
        prompt = f"""You are a database documentation expert. Generate a concise, human-readable definition for this database table.

{context}

Write 2-3 sentences that explain:
1. What business entity or concept this table represents
2. What is its primary purpose in the system
3. How it relates to other parts of the database (if foreign keys are present)

Focus on business meaning and practical usage.

Example good definitions:
- "Stores user account information including login credentials and profile data. Central table for user identity across the application. Links to orders, sessions, and preferences."
- "Records individual product orders with pricing and quantities. Each order belongs to a user and contains multiple order items. Used for transaction history and reporting."

Definition:"""

        try:
            response = await self._client.chat.completions.create(
                model=settings.openai_api_key and "gpt-4o-mini" or "gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": "You are a database documentation expert."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,
                max_tokens=200,
            )

            definition = response.choices[0].message.content.strip()
            return definition

        except Exception as e:
            # Fallback to basic definition
            return f"Table storing {table_name} data with {len(columns)} columns"

    async def generate_relationship_description(
        self,
        from_table: str,
        from_column: str,
        to_table: str,
        to_column: str,
    ) -> str:
        """
        Generate description for a foreign key relationship.

        Args:
            from_table: Source table name
            from_column: Source column name
            to_table: Target table name
            to_column: Target column name

        Returns:
            Human-readable relationship description
        """
        prompt = f"""Describe this database relationship in one sentence:

{from_table}.{from_column} → {to_table}.{to_column}

Focus on the business meaning (e.g., "Each order belongs to a user" or "Products reference their category").

Description:"""

        try:
            response = await self._client.chat.completions.create(
                model=settings.openai_api_key and "gpt-4o-mini" or "gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": "You are a database documentation expert."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,
                max_tokens=50,
            )

            description = response.choices[0].message.content.strip()
            return description

        except Exception as e:
            return f"{from_table} references {to_table}"


# Singleton instance
definition_generator = DefinitionGenerator()
