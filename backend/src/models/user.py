"""
SQLAlchemy model for users.

Simple user model for connector ownership and multi-tenancy.
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import Column, String, TIMESTAMP
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import relationship

from src.db.database import Base


class User(Base):
    """User account for connector ownership."""

    __tablename__ = "users"

    id = Column(PGUUID(as_uuid=True), primary_key=True, server_default="gen_random_uuid()")
    username = Column(String(255), unique=True, nullable=False)
    email = Column(String(255), unique=True)
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default="CURRENT_TIMESTAMP")
    updated_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default="CURRENT_TIMESTAMP")

    # Relationships
    connectors = relationship("Connector", back_populates="user")

    def __repr__(self) -> str:
        return f"<User(id={self.id}, username={self.username})>"
