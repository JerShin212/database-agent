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
    anthropic_api_key: str = ""

    # Encryption
    encryption_key: str = ""  # Fernet key for encrypting connection strings

    # Shared secret for module-to-module integration endpoints (X-API-Key).
    # Empty string disables the integration endpoints (403).
    integration_api_key: str = ""

    # Form-filling module integration. When form_catalog_url is set, the form
    # catalog is fetched from that module's REST API (GET {url}/forms);
    # otherwise the local mock JSON file is used.
    form_catalog_url: str = ""
    form_catalog_path: str = "./data/forms.json"

    # Embedding dimensions (ColQwen2 text embeddings)
    embedding_dimensions: int = 128

    # ColQwen2 visual search (Modal endpoints)
    colqwen2_pdf_endpoint: str = "https://jershin212--daikin-test-colqwen2-embedder-model-embed-pdf.modal.run"
    colqwen2_text_endpoint: str = "https://jershin212--daikin-test-colqwen2-embedder-model-embed-text.modal.run"
    colqwen2_image_endpoint: str = "https://jershin212--daikin-test-colqwen2-embedder-model-embed-image.modal.run"
    visual_embedding_dimensions: int = 128

    # Chunking config — ~1500 chars keeps paragraphs intact (the chunker
    # splits on \n\n first and only recurses finer when a split exceeds
    # chunk_size). Documents uploaded before this change should be
    # re-uploaded to benefit.
    chunk_size: int = 1500
    chunk_overlap: int = 200

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
