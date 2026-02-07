from uuid import UUID
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_db
from src.schemas.database import (
    DatabaseCreate,
    DatabaseResponse,
    SchemaResponse,
    QueryRequest,
    QueryResponse,
)
from src.models.database import SQLiteDatabase
from src.services.sqlite_service import sqlite_service

router = APIRouter()


@router.post("", response_model=DatabaseResponse)
async def create_sample_database_endpoint(
    data: DatabaseCreate,
    db: AsyncSession = Depends(get_db),
):
    """Create a sample database."""
    if not data.create_sample:
        raise HTTPException(
            status_code=400,
            detail="Use /upload endpoint for file uploads, or set create_sample=true",
        )

    from src.scripts.create_sample_db import create_sample_database

    file_path = f"{data.name.lower().replace(' ', '_')}.db"
    full_path = sqlite_service.data_path / file_path

    # Ensure directory exists
    full_path.parent.mkdir(parents=True, exist_ok=True)

    create_sample_database(str(full_path))

    database = SQLiteDatabase(
        name=data.name,
        file_path=file_path,
        description=data.description or "Sample sales database",
    )

    db.add(database)
    await db.commit()
    await db.refresh(database)

    return database


@router.post("/upload", response_model=DatabaseResponse)
async def upload_database(
    file: UploadFile = File(...),
    name: str = None,
    description: str = None,
    db: AsyncSession = Depends(get_db),
):
    """Upload a SQLite database file."""
    if not file.filename.endswith(".db") and not file.filename.endswith(".sqlite"):
        raise HTTPException(status_code=400, detail="File must be a SQLite database (.db or .sqlite)")

    content = await file.read()

    # Save file
    file_path = f"{file.filename}"
    full_path = sqlite_service.data_path / file_path

    # Ensure directory exists
    full_path.parent.mkdir(parents=True, exist_ok=True)

    full_path.write_bytes(content)

    # Create database record
    database = SQLiteDatabase(
        name=name or file.filename.replace(".db", "").replace(".sqlite", ""),
        file_path=file_path,
        description=description,
    )

    db.add(database)
    await db.commit()
    await db.refresh(database)

    return database


@router.get("", response_model=list[DatabaseResponse])
async def list_databases(
    db: AsyncSession = Depends(get_db),
):
    """List all databases."""
    result = await db.execute(
        select(SQLiteDatabase)
        .where(SQLiteDatabase.is_active == True)
        .order_by(SQLiteDatabase.created_at.desc())
    )
    return result.scalars().all()


@router.get("/{database_id}", response_model=DatabaseResponse)
async def get_database(
    database_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Get a database by ID."""
    result = await db.execute(
        select(SQLiteDatabase).where(SQLiteDatabase.id == database_id)
    )
    database = result.scalar_one_or_none()

    if not database:
        raise HTTPException(status_code=404, detail="Database not found")

    return database


@router.get("/{database_id}/schema", response_model=SchemaResponse)
async def get_database_schema(
    database_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Get the complete schema of a database."""
    result = await db.execute(
        select(SQLiteDatabase).where(SQLiteDatabase.id == database_id)
    )
    database = result.scalar_one_or_none()

    if not database:
        raise HTTPException(status_code=404, detail="Database not found")

    db_path = sqlite_service.get_db_path(database.id, database.file_path)

    if not db_path.exists():
        raise HTTPException(status_code=404, detail="Database file not found")

    return sqlite_service.get_schema(db_path, database.id, database.name)


@router.post("/{database_id}/query", response_model=QueryResponse)
async def execute_query(
    database_id: UUID,
    request: QueryRequest,
    db: AsyncSession = Depends(get_db),
):
    """Execute a SQL query against a database."""
    result = await db.execute(
        select(SQLiteDatabase).where(SQLiteDatabase.id == database_id)
    )
    database = result.scalar_one_or_none()

    if not database:
        raise HTTPException(status_code=404, detail="Database not found")

    db_path = sqlite_service.get_db_path(database.id, database.file_path)

    if not db_path.exists():
        raise HTTPException(status_code=404, detail="Database file not found")

    return sqlite_service.execute_query(db_path, request.sql)


@router.delete("/{database_id}")
async def delete_database(
    database_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Delete a database."""
    result = await db.execute(
        select(SQLiteDatabase).where(SQLiteDatabase.id == database_id)
    )
    database = result.scalar_one_or_none()

    if not database:
        raise HTTPException(status_code=404, detail="Database not found")

    # Delete file
    db_path = sqlite_service.get_db_path(database.id, database.file_path)
    if db_path.exists():
        db_path.unlink()

    # Delete record
    await db.delete(database)
    await db.commit()

    return {"status": "deleted"}
