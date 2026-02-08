from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass
class ToolContext:
    """Context for tool execution."""

    db: AsyncSession
    database_id: Optional[UUID] = None
    database_path: Optional[Path] = None  # Pre-fetched path to SQLite file
    database_name: Optional[str] = None
    connector_id: Optional[UUID] = None  # For external database connectors
    collection_ids: Optional[list[UUID]] = None


# Context variable for async-safe context propagation
_tool_context: ContextVar[Optional[ToolContext]] = ContextVar("tool_context", default=None)


def set_tool_context(context: ToolContext) -> None:
    """Set the current tool context."""
    _tool_context.set(context)


def get_tool_context() -> Optional[ToolContext]:
    """Get the current tool context."""
    return _tool_context.get()
