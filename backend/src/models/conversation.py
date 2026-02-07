from datetime import datetime
from typing import Optional
from uuid import UUID, uuid4
from sqlalchemy import Column, String, Text, DateTime, ForeignKey, JSON
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from src.db.database import Base


class Conversation(Base):
    __tablename__ = "conversations"

    id: UUID = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    title: Optional[str] = Column(String(500), nullable=True)
    created_at: datetime = Column(DateTime, default=datetime.utcnow)
    updated_at: datetime = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Message(Base):
    __tablename__ = "messages"

    id: UUID = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    conversation_id: UUID = Column(
        PGUUID(as_uuid=True), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    role: str = Column(String(20), nullable=False)  # 'user' or 'assistant'
    content: str = Column(Text, nullable=False)
    tool_calls: Optional[dict] = Column(JSON, nullable=True)
    created_at: datetime = Column(DateTime, default=datetime.utcnow)
