"""
Descriptor — the resolved, per-request object bound into every tool factory
closure (replacing the old ToolContext ContextVar).

It carries only the scalars the tools need; tools open their own short-lived
sync DB sessions (SyncSessionLocal), so the request AsyncSession is deliberately
NOT included here.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from uuid import UUID


@dataclass
class Descriptor:
    database_id: UUID | None = None
    database_path: Path | None = None
    database_name: str | None = None
    connector_id: UUID | None = None
    collection_ids: list[UUID] | None = None
    image_bytes: bytes | None = None
    image_media_type: str | None = None
