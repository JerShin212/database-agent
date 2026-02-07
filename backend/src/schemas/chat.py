from datetime import datetime
from typing import Optional
from uuid import UUID
from pydantic import BaseModel


class ChatRequest(BaseModel):
    message: str
    conversation_id: Optional[UUID] = None
    collection_ids: Optional[list[UUID]] = None
    database_id: Optional[UUID] = None


class ChatResponse(BaseModel):
    conversation_id: UUID
    message: str
    tool_calls: Optional[list[dict]] = None


class MessageResponse(BaseModel):
    id: UUID
    role: str
    content: str
    tool_calls: Optional[list[dict]] = None
    created_at: datetime

    class Config:
        from_attributes = True


class ConversationResponse(BaseModel):
    id: UUID
    title: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    messages: Optional[list[MessageResponse]] = None

    class Config:
        from_attributes = True
