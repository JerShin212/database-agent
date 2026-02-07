from datetime import datetime
from typing import Optional, Any
from uuid import UUID
from pydantic import BaseModel


class DatabaseCreate(BaseModel):
    name: str
    description: Optional[str] = None
    create_sample: bool = False


class DatabaseResponse(BaseModel):
    id: UUID
    name: str
    file_path: str
    description: Optional[str] = None
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


class ColumnInfo(BaseModel):
    name: str
    type: str
    nullable: bool
    primary_key: bool
    foreign_key: Optional[str] = None


class TableInfo(BaseModel):
    name: str
    columns: list[ColumnInfo]
    row_count: int
    sample_data: Optional[list[dict]] = None


class SchemaResponse(BaseModel):
    database_id: UUID
    database_name: str
    tables: list[TableInfo]


class QueryRequest(BaseModel):
    sql: str


class QueryResponse(BaseModel):
    columns: list[str]
    rows: list[list[Any]]
    row_count: int
    error: Optional[str] = None
