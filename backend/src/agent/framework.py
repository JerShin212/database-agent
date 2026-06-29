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
    search_by_image,
    create_chart,
    CHART_SUCCESS_PREFIX,
    read_document,
    ToolContext,
    set_tool_context,
)
from src.agent.tools.form_tools import (
    FORM_SUGGESTION_PREFIX,
    build_suggest_form_description,
    suggest_form,
)

_WORKER_MODEL = "claude-haiku-4-5-20251001"
_ORCHESTRATOR_MODEL = "claude-sonnet-4-6"
# Workers are rebuilt on this model when the Haiku attempt crashes or runs
# out of iterations (see OrchestratorAgent._should_escalate)
_ESCALATION_MODEL = "claude-sonnet-4-6"
_BUILTIN_TOOLS = ("read_file", "write_file", "bash", "list_directory")


class DatabaseAgentFramework:
    """
    OrchestratorAgent-based framework. A fresh orchestrator and worker pool is
    created per chat() call to avoid session state leaking across requests.
    """

    # ------------------------------------------------------------------
    # Worker builders
    # ------------------------------------------------------------------

    def _build_database_worker(self, api_key: str, on_event=None, model: str = _WORKER_MODEL) -> AgentRuntime:
        worker = AgentRuntime(
            api_key=api_key,
            model=model,
            system=DATABASE_AGENT_PROMPT,
            max_tokens=4096,
            max_iter=10,
            name="database_agent",
            on_event=on_event,
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

    def _build_text_worker(self, api_key: str, on_event=None, model: str = _WORKER_MODEL) -> AgentRuntime:
        worker = AgentRuntime(
            api_key=api_key,
            model=model,
            system=TEXT_SEARCH_AGENT_PROMPT,
            max_tokens=4096,
            max_iter=8,  # search -> read_document (xN) -> synthesize
            name="text_search_agent",
            on_event=on_event,
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
            "read_document",
            read_document.__doc__ or "Read a document's full extracted text (paginated)",
            read_document,
            params={
                "filename": {"type": "string", "description": "Document filename (partial match allowed)"},
                "start_char": {"type": "integer", "description": "Character offset to start from (default 0)"},
                "length": {"type": "integer", "description": "Characters to return (default 15000, max 20000)"},
            },
            required=["filename"],
        )
        worker.add_tool(
            "list_collections",
            list_collections.__doc__ or "List all document collections",
            list_collections,
            params={},
            required=[],
        )
        return worker

    def _build_visual_worker(self, api_key: str, on_event=None, model: str = _WORKER_MODEL) -> AgentRuntime:
        worker = AgentRuntime(
            api_key=api_key,
            model=model,
            system=VISUAL_SEARCH_AGENT_PROMPT,
            max_tokens=4096,
            max_iter=6,
            name="visual_search_agent",
            on_event=on_event,
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
            "search_by_image",
            search_by_image.__doc__ or "Search document pages using the user's attached image",
            search_by_image,
            params={
                "text_query": {"type": "string", "description": "Optional short description of the image content, used to fuse a text search with the image search"},
                "limit": {"type": "integer", "description": "Max results (default 5)"},
            },
            required=[],
        )
        worker.add_tool(
            "list_collections",
            list_collections.__doc__ or "List all document collections",
            list_collections,
            params={},
            required=[],
        )
        return worker

    def _build_orchestrator(self, api_key: str, on_event=None) -> OrchestratorAgent:
        pool = AgentPool()
        pool.register(
            "database_agent",
            self._build_database_worker(api_key, on_event),
            escalated_factory=lambda: self._build_database_worker(
                api_key, on_event, model=_ESCALATION_MODEL
            ),
        )
        pool.register(
            "text_search_agent",
            self._build_text_worker(api_key, on_event),
            escalated_factory=lambda: self._build_text_worker(
                api_key, on_event, model=_ESCALATION_MODEL
            ),
        )
        pool.register(
            "visual_search_agent",
            self._build_visual_worker(api_key, on_event),
            escalated_factory=lambda: self._build_visual_worker(
                api_key, on_event, model=_ESCALATION_MODEL
            ),
        )

        orchestrator = OrchestratorAgent(
            pool=pool,
            system=ORCHESTRATOR_SYSTEM_PROMPT,
            api_key=api_key,
            model=_ORCHESTRATOR_MODEL,
            max_tokens=8192,
            max_iter=20,
        )

        # The orchestrator (not a worker) renders charts: it holds the
        # synthesized data after delegation and Sonnet emits structured
        # specs more reliably than Haiku.
        orchestrator.add_tool(
            name="create_chart",
            description=create_chart.__doc__ or "Render a chart for the user",
            handler=create_chart,
            params={
                "chart_type": {
                    "type": "string",
                    "enum": ["bar", "line", "pie", "scatter"],
                    "description": "Chart type",
                },
                "title": {"type": "string", "description": "Short chart title"},
                "labels": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Category/x-axis labels, one per data point (omit for scatter)",
                },
                "datasets": {
                    "type": "array",
                    "description": (
                        '1-4 series: [{"label": str, "data": [numbers]}]; '
                        'for scatter, data is [{"x": number, "y": number}]'
                    ),
                    "items": {"type": "object"},
                },
            },
            required=["chart_type", "title", "datasets"],
        )

        # Form suggestions (form-filling module integration) — description is
        # built per request so newly added forms are visible immediately.
        orchestrator.add_tool(
            name="suggest_form",
            description=build_suggest_form_description(),
            handler=suggest_form,
            params={
                "form_id": {"type": "string", "description": "ID of the form to suggest"},
                "prefill": {
                    "type": "object",
                    "description": "Field values you already know, e.g. {\"order_id\": \"1023\"}",
                },
            },
            required=["form_id"],
        )

        return orchestrator

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
        image_data: str = None,
        image_media_type: str = None,
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
        image_bytes = None
        if image_data:
            import base64
            try:
                image_bytes = base64.b64decode(image_data)
            except Exception:
                yield {"type": "error", "error": "Invalid base64 image data"}
                return

        context = ToolContext(
            db=db,
            database_id=database_id,
            database_path=db_path,
            database_name=db_name,
            connector_id=connector_id,
            collection_ids=collection_ids,
            image_bytes=image_bytes,
            image_media_type=image_media_type or "image/png",
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

        # Save user message to DB (don't store base64 — just note the attachment
        # so the image is reflected in conversation history on later turns)
        user_message = Message(
            conversation_id=conversation_id,
            role="user",
            content=f"[Image attached]\n{message}" if image_bytes else message,
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

        # When an image is attached, the vision-capable orchestrator sees it
        # directly: it can describe the image for routing and pass that
        # description to search_by_image as a fusion text query.
        if image_bytes:
            orchestrator_input: str | list = [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": image_media_type or "image/png",
                        "data": image_data,
                    },
                },
                {"type": "text", "text": f"[The user attached the image above]\n\n{full_prompt}"},
            ]
        else:
            orchestrator_input = full_prompt

        # --- 6. Run orchestrator in thread pool, streaming events back ---
        # The orchestrator runs synchronously in an executor thread and pushes
        # events into an asyncio queue via call_soon_threadsafe; this async
        # generator drains the queue until a None sentinel arrives.
        try:
            loop = asyncio.get_running_loop()
            queue: asyncio.Queue = asyncio.Queue()

            def _emit(event: dict | None) -> None:
                loop.call_soon_threadsafe(queue.put_nowait, event)

            orchestrator = self._build_orchestrator(settings.anthropic_api_key, on_event=_emit)

            # Capture context in closure so it's explicitly re-set inside the thread.
            # This is more reliable than relying solely on ContextVar copy_context()
            # propagation through run_in_executor inside an async generator.
            _ctx = context

            def _run_orchestrator() -> None:
                set_tool_context(_ctx)
                try:
                    for event in orchestrator.run_events(orchestrator_input):
                        _emit(event)
                except Exception as exc:
                    _emit({"type": "error", "error": str(exc)})
                finally:
                    _emit(None)  # sentinel: orchestrator finished

            future = loop.run_in_executor(None, _run_orchestrator)

            answer_parts: list[str] = []
            tool_calls: list[dict] = []

            while (event := await queue.get()) is not None:
                event_type = event.get("type")
                if event_type == "text_delta":
                    answer_parts.append(event["text"])
                    yield {"type": "content", "content": event["text"]}
                elif event_type == "tool_call":
                    call = {
                        "tool": event["tool"],
                        "args": event["args"],
                        "result": event["result"],
                        "agent": event.get("agent"),
                    }
                    tool_calls.append(call)
                    yield {"type": "tool_call", **call}
                    # Successfully validated charts also go to the frontend
                    # as a dedicated event for rendering
                    if event["tool"] == "create_chart" and str(event["result"]).startswith(
                        CHART_SUCCESS_PREFIX
                    ):
                        yield {"type": "chart", "spec": event["args"]}
                    # Validated form suggestions become an action event; the
                    # form name/URL are resolved through the catalog (never
                    # trusted from model output).
                    elif event["tool"] == "suggest_form" and str(event["result"]).startswith(
                        FORM_SUGGESTION_PREFIX
                    ):
                        from src.services.form_catalog import form_catalog

                        form = form_catalog.get_form(event["args"].get("form_id", ""))
                        if form is not None:
                            yield {
                                "type": "action",
                                "action": "form_suggestion",
                                "form_id": form["id"],
                                "form_name": form["name"],
                                "redirect_url": form["url"],
                                "prefill": event["args"].get("prefill") or {},
                            }
                elif event_type == "max_iterations":
                    notice = (
                        "\n\nI couldn't fully complete this within my step limit — "
                        "here's what I found so far."
                    )
                    answer_parts.append(notice)
                    yield {"type": "content", "content": notice}
                elif event_type == "error":
                    yield {"type": "error", "error": event["error"]}
                # "final" carries the last message's full text, which has
                # already been streamed as text_delta chunks — skip it.

            await future
            answer = "".join(answer_parts)

            # Save assistant message
            assistant_message = Message(
                conversation_id=conversation_id,
                role="assistant",
                content=answer,
                tool_calls=tool_calls or None,
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
