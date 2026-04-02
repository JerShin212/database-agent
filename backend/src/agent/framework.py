"""
OrchestratorAgent-based database agent framework.

Replaces the DSPy ReAct implementation with a 3-worker multi-agent architecture:
  - database_agent:      SQL queries and schema exploration
  - text_search_agent:   Hybrid text RAG (BM25 + semantic)
  - visual_search_agent: ColQwen2 visual page search

The public interface (agent_framework.chat() async generator, chunk types) is
unchanged so chat.py requires no modification.
"""

from __future__ import annotations

import asyncio
from typing import AsyncGenerator
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.models.connector import Connector
from src.models.conversation import Conversation, Message
from src.models.database import SQLiteDatabase
from src.services.sqlite_service import sqlite_service
from src.agent.agent_runtime import AgentRuntime
from src.agent.orchestrator import OrchestratorAgent, AgentPool
from src.agent.prompts import (
    ORCHESTRATOR_SYSTEM_PROMPT,
    DATABASE_AGENT_PROMPT,
    TEXT_SEARCH_AGENT_PROMPT,
    VISUAL_SEARCH_AGENT_PROMPT,
)
from src.agent.tools import (
    execute_sql_query,
    get_database_schema,
    list_tables,
    get_table_info,
    search_collections,
    list_collections,
    search_schema_catalog,
    search_visual_documents,
    ToolContext,
    set_tool_context,
)

_WORKER_MODEL = "claude-haiku-4-5-20251001"
_ORCHESTRATOR_MODEL = "claude-sonnet-4-6"
_BUILTIN_TOOLS = ("read_file", "write_file", "bash", "list_directory")


class DatabaseAgentFramework:
    """
    OrchestratorAgent-based framework. A fresh orchestrator and worker pool is
    created per chat() call to avoid session state leaking across requests.
    """

    # ------------------------------------------------------------------
    # Worker builders
    # ------------------------------------------------------------------

    def _build_database_worker(self, api_key: str) -> AgentRuntime:
        worker = AgentRuntime(
            api_key=api_key,
            model=_WORKER_MODEL,
            system=DATABASE_AGENT_PROMPT,
            max_tokens=4096,
            max_iter=10,
        )
        worker.deny_tools(*_BUILTIN_TOOLS)
        worker.add_tool(
            "search_schema_catalog",
            search_schema_catalog.__doc__ or "Search schema definitions semantically",
            search_schema_catalog,
            params={
                "query": {"type": "string", "description": "Natural language query about the schema (e.g. 'product stock quantity')"},
                "limit": {"type": "integer", "description": "Max results (default 5)"},
            },
            required=["query"],
        )
        worker.add_tool(
            "execute_sql_query",
            execute_sql_query.__doc__ or "Execute a SQL SELECT query",
            execute_sql_query,
            params={
                "sql": {"type": "string", "description": "SQL SELECT query to execute"},
            },
            required=["sql"],
        )
        worker.add_tool(
            "get_database_schema",
            get_database_schema.__doc__ or "Get full database schema",
            get_database_schema,
            params={},
            required=[],
        )
        worker.add_tool(
            "list_tables",
            list_tables.__doc__ or "List all tables in the database",
            list_tables,
            params={},
            required=[],
        )
        worker.add_tool(
            "get_table_info",
            get_table_info.__doc__ or "Get detailed info about a specific table",
            get_table_info,
            params={
                "table_name": {"type": "string", "description": "Name of the table"},
            },
            required=["table_name"],
        )
        return worker

    def _build_text_worker(self, api_key: str) -> AgentRuntime:
        worker = AgentRuntime(
            api_key=api_key,
            model=_WORKER_MODEL,
            system=TEXT_SEARCH_AGENT_PROMPT,
            max_tokens=4096,
            max_iter=6,
        )
        worker.deny_tools(*_BUILTIN_TOOLS)
        worker.add_tool(
            "search_collections",
            search_collections.__doc__ or "Search document collections with hybrid search",
            search_collections,
            params={
                "query": {"type": "string", "description": "Natural language search query"},
                "limit": {"type": "integer", "description": "Max results (default 5)"},
            },
            required=["query"],
        )
        worker.add_tool(
            "list_collections",
            list_collections.__doc__ or "List all document collections",
            list_collections,
            params={},
            required=[],
        )
        return worker

    def _build_visual_worker(self, api_key: str) -> AgentRuntime:
        worker = AgentRuntime(
            api_key=api_key,
            model=_WORKER_MODEL,
            system=VISUAL_SEARCH_AGENT_PROMPT,
            max_tokens=4096,
            max_iter=6,
        )
        worker.deny_tools(*_BUILTIN_TOOLS)
        worker.add_tool(
            "search_visual_documents",
            search_visual_documents.__doc__ or "Search document pages visually using ColQwen2",
            search_visual_documents,
            params={
                "query": {"type": "string", "description": "Description of the visual content to find"},
                "limit": {"type": "integer", "description": "Max results (default 5)"},
            },
            required=["query"],
        )
        worker.add_tool(
            "list_collections",
            list_collections.__doc__ or "List all document collections",
            list_collections,
            params={},
            required=[],
        )
        return worker

    def _build_orchestrator(self, api_key: str) -> OrchestratorAgent:
        pool = AgentPool()
        pool.register("database_agent", self._build_database_worker(api_key))
        pool.register("text_search_agent", self._build_text_worker(api_key))
        pool.register("visual_search_agent", self._build_visual_worker(api_key))

        return OrchestratorAgent(
            pool=pool,
            system=ORCHESTRATOR_SYSTEM_PROMPT,
            api_key=api_key,
            model=_ORCHESTRATOR_MODEL,
            max_tokens=8192,
            max_iter=20,
        )

    # ------------------------------------------------------------------
    # Main chat interface
    # ------------------------------------------------------------------

    async def chat(
        self,
        db: AsyncSession,
        message: str,
        conversation_id: UUID = None,
        database_id: UUID = None,
        collection_ids: list[UUID] = None,
    ) -> AsyncGenerator[dict, None]:
        """
        Process a chat message and yield response components.

        Yields chunks:
          {"type": "metadata", "conversation_id": str}
          {"type": "content",  "content": str}
          {"type": "error",    "error": str}
          {"type": "done",     "conversation_id": str}
        """
        # --- 1. Pre-fetch database info (same as before) ---
        db_path = None
        db_name = None
        connector_id = None

        if database_id:
            result = await db.execute(
                select(SQLiteDatabase).where(SQLiteDatabase.id == database_id)
            )
            sqlite_db = result.scalar_one_or_none()
            if sqlite_db:
                db_path = sqlite_service.get_db_path(sqlite_db.id, sqlite_db.file_path)
                db_name = sqlite_db.name

                result = await db.execute(
                    select(Connector).where(
                        Connector.name == f"{db_name} (Semantic Catalog)",
                        Connector.status == "ready",
                    )
                )
                connector = result.scalar_one_or_none()
                if connector:
                    connector_id = connector.id
        else:
            result = await db.execute(
                select(SQLiteDatabase).where(SQLiteDatabase.is_active == True).limit(1)
            )
            sqlite_db = result.scalar_one_or_none()
            if sqlite_db:
                database_id = sqlite_db.id
                db_path = sqlite_service.get_db_path(sqlite_db.id, sqlite_db.file_path)
                db_name = sqlite_db.name

                result = await db.execute(
                    select(Connector).where(
                        Connector.name == f"{db_name} (Semantic Catalog)",
                        Connector.status == "ready",
                    )
                )
                connector = result.scalar_one_or_none()
                if connector:
                    connector_id = connector.id

        # --- 2. Set ToolContext — propagates to worker tools via ContextVar ---
        context = ToolContext(
            db=db,
            database_id=database_id,
            database_path=db_path,
            database_name=db_name,
            connector_id=connector_id,
            collection_ids=collection_ids,
        )
        set_tool_context(context)
        import logging as _logging
        _logging.getLogger(__name__).info(
            "[framework] ToolContext: database_id=%s db_path=%s connector_id=%s",
            database_id, db_path, connector_id,
        )

        # --- 3. Get or create conversation ---
        if conversation_id:
            result = await db.execute(
                select(Conversation).where(Conversation.id == conversation_id)
            )
            conversation = result.scalar_one_or_none()
            if not conversation:
                conversation = Conversation(id=conversation_id)
                db.add(conversation)
                await db.commit()
        else:
            conversation = Conversation()
            db.add(conversation)
            await db.commit()
            await db.refresh(conversation)
            conversation_id = conversation.id

        yield {
            "type": "metadata",
            "conversation_id": str(conversation_id),
        }

        # --- 4. Load conversation history ---
        result = await db.execute(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at)
        )
        messages = result.scalars().all()
        is_initial = len(messages) == 0

        # Save user message to DB
        user_message = Message(
            conversation_id=conversation_id,
            role="user",
            content=message,
        )
        db.add(user_message)
        await db.commit()

        # --- 5. Build full prompt with history injected ---
        if is_initial:
            full_prompt = message
        else:
            history_parts = [
                f"{msg.role.capitalize()}: {msg.content}"
                for msg in messages
            ]
            history_text = "\n".join(history_parts)
            full_prompt = (
                f"[Previous conversation]\n{history_text}\n\n[User]: {message}"
            )

        # --- 6. Run orchestrator in thread pool (sync → async, non-blocking) ---
        try:
            orchestrator = self._build_orchestrator(settings.anthropic_api_key)

            # Capture context in closure so it's explicitly re-set inside the thread.
            # This is more reliable than relying solely on ContextVar copy_context()
            # propagation through run_in_executor inside an async generator.
            _ctx = context

            def _run_orchestrator() -> str:
                set_tool_context(_ctx)
                return orchestrator.run(full_prompt)

            loop = asyncio.get_running_loop()
            answer = await loop.run_in_executor(None, _run_orchestrator)

            yield {
                "type": "content",
                "content": answer,
            }

            # Save assistant message
            assistant_message = Message(
                conversation_id=conversation_id,
                role="assistant",
                content=answer,
                tool_calls=None,
            )
            db.add(assistant_message)
            await db.commit()

            # Set conversation title on first turn
            if is_initial:
                title = message[:50] + "..." if len(message) > 50 else message
                conversation.title = title
                await db.commit()

        except Exception as e:
            yield {
                "type": "error",
                "error": str(e),
            }

        yield {
            "type": "done",
            "conversation_id": str(conversation_id),
        }


# Singleton instance — matches existing import in chat.py
agent_framework = DatabaseAgentFramework()
