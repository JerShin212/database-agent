"""
Definition generator using LLM.

Generates human-readable semantic definitions for tables and columns.
"""

from typing import Any

from anthropic import AsyncAnthropic

from src.config import settings

_MODEL = "claude-haiku-4-5"
_SYSTEM = "You are a database documentation expert."


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
        """Initialize Anthropic client."""
        self._client = AsyncAnthropic(api_key=settings.anthropic_api_key)

    async def _complete(self, prompt: str, max_tokens: int) -> str:
        """Run a single prompt through Haiku and return the text response."""
        response = await self._client.messages.create(
            model=_MODEL,
            max_tokens=max_tokens,
            system=_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        return next(
            (block.text for block in response.content if block.type == "text"), ""
        ).strip()

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
        prompt = f"""You are a database documentation expert. Generate a definition for this database column that will be used by a search engine to match users' natural language questions to the right column.

{context}

Write a 2-3 sentence definition that explains:
1. What this column represents in business terms (not just a technical restatement of its name)
2. What kind of data it stores — infer the format, units, or meaning from the sample values
3. If it references another table, what that relationship means

CRITICAL for searchability: naturally weave in 2-4 alternative words or phrases a person
might use when asking about this data. For example, a stock_quantity column should mention
"inventory", "units available", "how much is left in stock"; a total_amount column should
mention "price", "cost", "money spent", "order value". Think: what would a non-technical
user type when they need this column?

Be specific and practical. Do not invent facts the context doesn't support.
Respond with plain prose only — no markdown headers, bullets, or bold text.

Example good definitions:
- "The customer's primary email address, used for login, contact, and notifications. Search terms like contact details, e-mail, or reaching the customer all refer to this field."
- "Number of units of the product currently available in inventory. Answers questions about stock levels, availability, how much is left, or whether an item is out of stock."

Definition:"""

        try:
            return await self._complete(prompt, max_tokens=200)

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

        # All column names give the model the full picture of what the table holds
        column_names = [col["name"] for col in columns[:30]]
        context_parts.append(f"Columns: {', '.join(column_names)}")

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
        prompt = f"""You are a database documentation expert. Generate a definition for this database table that will be used by a search engine to match users' natural language questions to the right table.

{context}

Write 2-4 sentences that explain:
1. What business entity or concept this table represents
2. What typical questions this table answers (e.g., "who bought what", "how much revenue", "which rep covers which region")
3. How it relates to other tables via its foreign keys — name the related tables and what the link means

CRITICAL for searchability: naturally include alternative words a person might use for this
entity (e.g., an orders table should mention purchases, transactions, sales; a sales_reps
table should mention salesperson, account manager, representative). Think: what would a
non-technical user say when they need data from this table?

Do not invent facts the context doesn't support.
Respond with plain prose only — no markdown headers, bullets, or bold text.

Example good definitions:
- "Records individual customer purchases (orders, transactions, sales) with date, status, and total amount. Answers questions like who bought what, how much was spent, and whether an order has shipped. Each order belongs to a customer and a sales rep, and its line items live in order_items."
- "Junction table assigning customers to their sales representatives (account managers). Answers which salesperson handles which customer and since when. Links customers to sales_reps."

Definition:"""

        try:
            return await self._complete(prompt, max_tokens=250)

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
            return await self._complete(prompt, max_tokens=50)

        except Exception as e:
            return f"{from_table} references {to_table}"


# Singleton instance
definition_generator = DefinitionGenerator()
