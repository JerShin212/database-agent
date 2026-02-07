import dspy
from uuid import UUID
from typing import AsyncGenerator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.models.conversation import Conversation, Message
from src.models.database import SQLiteDatabase
from src.services.sqlite_service import sqlite_service
from src.agent.signatures import InitialQuerySignature, FollowUpQuerySignature
from src.agent.tools import (
    execute_sql_query,
    get_database_schema,
    list_tables,
    get_table_info,
    search_collections,
    list_collections,
    ToolContext,
    set_tool_context,
)


class DatabaseAgentFramework:
    """DSPy-based database agent framework."""

    def __init__(self):
        self.tools = [
            execute_sql_query,
            get_database_schema,
            list_tables,
            get_table_info,
            search_collections,
            list_collections,
        ]

        # Configure DSPy with Claude
        self.lm = dspy.LM(
            model="anthropic/claude-sonnet-4-20250514",
            api_key=settings.anthropic_api_key,
            max_tokens=4096,
        )

        # Create agents
        self.initial_agent = dspy.ReAct(
            InitialQuerySignature,
            tools=self.tools,
            max_iters=10,
        )

        self.followup_agent = dspy.ReAct(
            FollowUpQuerySignature,
            tools=self.tools,
            max_iters=10,
        )

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

        Args:
            db: Database session
            message: User message
            conversation_id: Optional conversation ID for context
            database_id: Optional database to query
            collection_ids: Optional collections to search

        Yields:
            Response components (metadata, content, tool_calls, done)
        """
        # Pre-fetch database path for tools (avoids async issues in sync tools)
        db_path = None
        db_name = None
        if database_id:
            result = await db.execute(
                select(SQLiteDatabase).where(SQLiteDatabase.id == database_id)
            )
            sqlite_db = result.scalar_one_or_none()
            if sqlite_db:
                db_path = sqlite_service.get_db_path(sqlite_db.id, sqlite_db.file_path)
                db_name = sqlite_db.name
        else:
            # Get first active database
            result = await db.execute(
                select(SQLiteDatabase).where(SQLiteDatabase.is_active == True).limit(1)
            )
            sqlite_db = result.scalar_one_or_none()
            if sqlite_db:
                database_id = sqlite_db.id
                db_path = sqlite_service.get_db_path(sqlite_db.id, sqlite_db.file_path)
                db_name = sqlite_db.name

        # Set tool context for this request
        context = ToolContext(
            db=db,
            database_id=database_id,
            database_path=db_path,
            database_name=db_name,
            collection_ids=collection_ids,
        )
        set_tool_context(context)

        # Get or create conversation
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

        # Yield metadata
        yield {
            "type": "metadata",
            "conversation_id": str(conversation_id),
        }

        # Get conversation history
        result = await db.execute(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at)
        )
        messages = result.scalars().all()

        # Save user message
        user_message = Message(
            conversation_id=conversation_id,
            role="user",
            content=message,
        )
        db.add(user_message)
        await db.commit()

        # Determine if initial or followup
        is_initial = len(messages) == 0

        # Build history for followup
        history_text = ""
        if not is_initial:
            history_parts = []
            for msg in messages:
                history_parts.append(f"{msg.role.capitalize()}: {msg.content}")
            history_text = "\n".join(history_parts)

        # Execute agent
        try:
            with dspy.context(lm=self.lm):
                if is_initial:
                    result = self.initial_agent(question=message)
                else:
                    result = self.followup_agent(
                        conversation_history=history_text,
                        question=message,
                    )

            answer = result.answer

            # Extract tool calls from trajectory if available
            tool_calls = []
            if hasattr(result, "trajectory"):
                tool_calls = self._parse_trajectory(result.trajectory)

            # Yield tool calls if any
            for tool_call in tool_calls:
                yield {
                    "type": "tool_call",
                    "tool": tool_call["tool"],
                    "args": tool_call["args"],
                    "result": tool_call["result"],
                }

            # Yield content
            yield {
                "type": "content",
                "content": answer,
            }

            # Save assistant message
            assistant_message = Message(
                conversation_id=conversation_id,
                role="assistant",
                content=answer,
                tool_calls=tool_calls if tool_calls else None,
            )
            db.add(assistant_message)
            await db.commit()

            # Update conversation title if first message
            if is_initial:
                # Use first 50 chars of message as title
                title = message[:50] + "..." if len(message) > 50 else message
                conversation.title = title
                await db.commit()

        except Exception as e:
            yield {
                "type": "error",
                "error": str(e),
            }

        # Yield done
        yield {
            "type": "done",
            "conversation_id": str(conversation_id),
        }

    def _parse_trajectory(self, trajectory: dict) -> list[dict]:
        """Parse DSPy trajectory to extract tool calls."""
        tool_calls = []

        if not trajectory:
            return tool_calls

        i = 0
        while True:
            tool_name_key = f"tool_name_{i}"
            tool_args_key = f"tool_args_{i}"
            observation_key = f"observation_{i}"

            if tool_name_key not in trajectory:
                break

            tool_calls.append({
                "tool": trajectory.get(tool_name_key, ""),
                "args": trajectory.get(tool_args_key, {}),
                "result": trajectory.get(observation_key, ""),
            })

            i += 1

        return tool_calls


# Singleton instance
agent_framework = DatabaseAgentFramework()
