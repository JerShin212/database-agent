from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_db
from src.schemas.chat import ChatRequest, ConversationResponse, MessageResponse
from src.models.conversation import Conversation, Message
from src.agent.framework import agent_framework

router = APIRouter()


@router.post("/")
async def chat(
    request: ChatRequest,
    db: AsyncSession = Depends(get_db),
):
    """Process a chat message and return the full response."""
    conversation_id = None
    content = ""
    tool_calls = []
    error = None

    async for chunk in agent_framework.chat(
        db=db,
        message=request.message,
        conversation_id=request.conversation_id,
        database_id=request.database_id,
        collection_ids=request.collection_ids,
    ):
        chunk_type = chunk.get("type")
        if chunk_type == "metadata":
            conversation_id = chunk.get("conversation_id")
        elif chunk_type == "content":
            content += chunk.get("content", "")
        elif chunk_type == "tool_call":
            tool_calls.append({
                "tool": chunk.get("tool", ""),
                "args": chunk.get("args", {}),
                "result": chunk.get("result", ""),
            })
        elif chunk_type == "error":
            error = chunk.get("error")

    return {
        "conversation_id": conversation_id,
        "content": content,
        "tool_calls": tool_calls,
        "error": error,
    }


@router.get("/conversations", response_model=list[ConversationResponse])
async def list_conversations(
    skip: int = 0,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
):
    """List all conversations."""
    result = await db.execute(
        select(Conversation)
        .order_by(Conversation.updated_at.desc())
        .offset(skip)
        .limit(limit)
    )
    conversations = result.scalars().all()
    return conversations


@router.get("/conversations/{conversation_id}", response_model=ConversationResponse)
async def get_conversation(
    conversation_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Get a conversation with all messages."""
    result = await db.execute(
        select(Conversation).where(Conversation.id == conversation_id)
    )
    conversation = result.scalar_one_or_none()

    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")

    # Get messages
    result = await db.execute(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at)
    )
    messages = result.scalars().all()

    return ConversationResponse(
        id=conversation.id,
        title=conversation.title,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
        messages=[
            MessageResponse(
                id=msg.id,
                role=msg.role,
                content=msg.content,
                tool_calls=msg.tool_calls,
                created_at=msg.created_at,
            )
            for msg in messages
        ],
    )


@router.delete("/conversations/{conversation_id}")
async def delete_conversation(
    conversation_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Delete a conversation."""
    result = await db.execute(
        select(Conversation).where(Conversation.id == conversation_id)
    )
    conversation = result.scalar_one_or_none()

    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")

    # Delete messages first (cascade should handle this, but being explicit)
    await db.execute(
        delete(Message).where(Message.conversation_id == conversation_id)
    )

    # Delete conversation
    await db.delete(conversation)
    await db.commit()

    return {"status": "deleted"}
