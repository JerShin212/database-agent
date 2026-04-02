from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # Database
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5433/database_agent"

    # MinIO
    minio_endpoint: str = "localhost:9002"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_bucket_name: str = "documents"
    minio_secure: bool = False

    # SQLite storage path
    sqlite_data_path: str = "./data/sqlite"

    # LLM APIs
    openai_api_key: str = ""
    anthropic_api_key: str = ""

    # Encryption
    encryption_key: str = ""  # Fernet key for encrypting connection strings

    # Embedding model
    embedding_model: str = "text-embedding-3-small"
    embedding_dimensions: int = 1536

    # ColQwen2 visual search (Modal endpoints)
    colqwen2_pdf_endpoint: str = ""
    colqwen2_text_endpoint: str = ""
    visual_embedding_dimensions: int = 128

    # Chunking config
    chunk_size: int = 500
    chunk_overlap: int = 50

    # Backend
    backend_host: str = "0.0.0.0"
    backend_port: int = 8000
    debug: bool = True

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
