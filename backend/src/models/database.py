from datetime import datetime
from typing import Optional
from uuid import UUID, uuid4
from sqlalchemy import Column, String, Text, DateTime, Boolean
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from src.db.database import Base


class SQLiteDatabase(Base):
    __tablename__ = "sqlite_databases"

    id: UUID = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    name: str = Column(String(255), nullable=False)
    file_path: str = Column(String(1000), nullable=False)
    description: Optional[str] = Column(Text, nullable=True)
    is_active: bool = Column(Boolean, default=True)
    created_at: datetime = Column(DateTime, default=datetime.utcnow)
