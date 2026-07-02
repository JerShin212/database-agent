"""
DatabaseAgentFramework — the chat entrypoint, on the Claude Agent SDK.

A fresh orchestrator + 3 narrow worker MCP servers are built per chat() call (the
isolation boundary). The orchestrator runs as a query() loop whose only tools are
delegate / create_chart / suggest_form; each worker runs as its own query() loop
behind `delegate`, with the bespoke NO_RESULTS fallback and Haiku->Sonnet
escalation preserved (see src/agent/sdk/orchestrator.py).

The public interface — chat() async generator and its chunk types (metadata /
content / tool_call / chart / action / error / done) — is unchanged, so chat.py
and the frontend require no modification.
"""

from __future__ import annotations

import logging
from typing import AsyncGenerator
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.connector import Connector
from src.models.conversation import Conversation, Message
from src.models.database import SQLiteDatabase
from src.services.sqlite_service import sqlite_service
from src.agent.sdk.descriptor import Descriptor
from src.agent.sdk.orchestrator import run_orchestrator_events

logger = logging.getLogger(__name__)

# Caps for the legacy text-replay fallback (conversations without a stored SDK
# session id, or whose session transcript is gone after a container restart).
_HISTORY_MAX_MESSAGES = 20
_HISTORY_MSG_CHAR_CAP = 4000


async def _stream_input(content):
    """Streaming-input form for query() — required to pass image content blocks."""
    yield {"type": "user", "message": {"role": "user", "content": content}}


class DatabaseAgentFramework:
    """SDK-backed framework. State never leaks across requests: every chat() call
    builds a fresh descriptor and fresh per-request MCP servers."""

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
        """Process a chat message and yield response components.

        Yields chunks:
          {"type": "metadata",  "conversation_id": str}
          {"type": "content",   "content": str}
          {"type": "tool_call", "tool","args","result","agent"}
          {"type": "chart",     "spec": {...}}
          {"type": "action",    "action": "form_suggestion", ...}
          {"type": "error",     "error": str}
          {"type": "done",      "conversation_id": str}
        """
        # --- 1. Pre-fetch database info (db path + semantic catalog connector) ---
        db_path = None
        db_name = None
        connector_id = None

        if not database_id:
            result = await db.execute(
                select(SQLiteDatabase).where(SQLiteDatabase.is_active == True).limit(1)
            )
            sqlite_db = result.scalar_one_or_none()
            if sqlite_db:
                database_id = sqlite_db.id
        else:
            result = await db.execute(
                select(SQLiteDatabase).where(SQLiteDatabase.id == database_id)
            )
            sqlite_db = result.scalar_one_or_none()

        if database_id and sqlite_db:
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

        # --- 2. Build the descriptor (bound into every tool factory closure) ---
        image_bytes = None
        if image_data:
            import base64
            try:
                image_bytes = base64.b64decode(image_data)
            except Exception:
                yield {"type": "error", "error": "Invalid base64 image data"}
                return

        descriptor = Descriptor(
            database_id=database_id,
            database_path=db_path,
            database_name=db_name,
            connector_id=connector_id,
            collection_ids=collection_ids,
            image_bytes=image_bytes,
            image_media_type=image_media_type or "image/png",
        )
        logger.info(
            "[framework] descriptor: database_id=%s db_path=%s connector_id=%s",
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

        yield {"type": "metadata", "conversation_id": str(conversation_id)}

        # --- 4. Load conversation history ---
        result = await db.execute(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at)
        )
        messages = result.scalars().all()
        is_initial = len(messages) == 0

        user_message = Message(
            conversation_id=conversation_id,
            role="user",
            content=f"[Image attached]\n{message}" if image_bytes else message,
        )
        db.add(user_message)
        await db.commit()

        # --- 5. Build the prompt ---
        # With a stored SDK session id we resume the CLI session — the model
        # keeps its full prior context (including tool results) with prompt
        # caching, and we send only the new message. Conversations without a
        # session id (or whose session transcript is gone, e.g. after a
        # container restart) fall back to replaying recent history as text.
        resume_id = None if is_initial else conversation.sdk_session_id

        def build_prompt_input(use_resume: bool):
            if is_initial or use_resume:
                text = message
            else:
                recent = messages[-_HISTORY_MAX_MESSAGES:]
                history_text = "\n".join(
                    f"{msg.role.capitalize()}: {msg.content[:_HISTORY_MSG_CHAR_CAP]}"
                    for msg in recent
                )
                dropped = len(messages) - len(recent)
                omitted = f", {dropped} older messages omitted" if dropped else ""
                text = (f"[Previous conversation — last {len(recent)} messages{omitted}]\n"
                        f"{history_text}\n\n[User]: {message}")

            # An attached image is passed to the vision-capable orchestrator via
            # the streaming-input form; the visual worker re-embeds image_bytes
            # from the descriptor (it does not need the image in the prompt).
            if image_bytes:
                return _stream_input([
                    {"type": "image", "source": {
                        "type": "base64",
                        "media_type": image_media_type or "image/png",
                        "data": image_data,
                    }},
                    {"type": "text", "text": f"[The user attached the image above]\n\n{text}"},
                ])
            return text

        # --- 6. Drive the orchestrator query() and forward its event stream ---
        # First attempt resumes the stored session; if that fails before any
        # output was produced, retry once from scratch with text-replay history.
        attempts = [True, False] if resume_id else [False]
        answer_parts: list[str] = []
        tool_calls: list[dict] = []
        session_id: str | None = None
        try:
            for attempt_idx, use_resume in enumerate(attempts):
                produced_output = False
                retry_without_resume = False
                events = run_orchestrator_events(
                    descriptor,
                    build_prompt_input(use_resume),
                    resume=resume_id if use_resume else None,
                )
                async for event in events:
                    etype = event.get("type")
                    if (etype == "error" and not produced_output
                            and attempt_idx + 1 < len(attempts)):
                        logger.warning(
                            "[framework] resume of session %s failed (%s) — "
                            "retrying with history replay", resume_id, event.get("error"),
                        )
                        retry_without_resume = True
                        break
                    if etype == "session":
                        session_id = event.get("session_id")
                    elif etype == "content":
                        produced_output = True
                        answer_parts.append(event["content"])
                        yield {"type": "content", "content": event["content"]}
                    elif etype == "tool_call":
                        produced_output = True
                        call = {
                            "tool": event["tool"],
                            "args": event.get("args", {}),
                            "result": event.get("result", ""),
                            "agent": event.get("agent"),
                        }
                        tool_calls.append(call)
                        yield {"type": "tool_call", **call}
                    elif etype == "chart":
                        produced_output = True
                        yield {"type": "chart", "spec": event["spec"]}
                    elif etype == "action":
                        produced_output = True
                        yield {k: v for k, v in event.items()}
                    elif etype == "notice":
                        answer_parts.append(event["text"])
                        yield {"type": "content", "content": event["text"]}
                    elif etype == "error":
                        yield {"type": "error", "error": event["error"]}
                if not retry_without_resume:
                    break
                # Deterministically shut the abandoned event stream down
                # (its finally block awaits the orchestrator task).
                await events.aclose()

            answer = "".join(answer_parts)

            assistant_message = Message(
                conversation_id=conversation_id,
                role="assistant",
                content=answer,
                tool_calls=tool_calls or None,
            )
            db.add(assistant_message)
            if session_id:
                conversation.sdk_session_id = session_id
            if is_initial:
                conversation.title = message[:50] + "..." if len(message) > 50 else message
            await db.commit()

        except Exception as e:
            logger.error("[framework] %s", e, exc_info=True)
            yield {"type": "error", "error": str(e)}

        yield {"type": "done", "conversation_id": str(conversation_id)}


# Singleton instance — matches the existing import in chat.py
agent_framework = DatabaseAgentFramework()
