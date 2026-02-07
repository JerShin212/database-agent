from io import BytesIO
from datetime import timedelta
from minio import Minio
from minio.error import S3Error
from src.config import settings


class MinioService:
    def __init__(self):
        self.client = Minio(
            settings.minio_endpoint,
            access_key=settings.minio_access_key,
            secret_key=settings.minio_secret_key,
            secure=settings.minio_secure,
        )
        self.bucket_name = settings.minio_bucket_name
        self._ensure_bucket()

    def _ensure_bucket(self):
        """Create bucket if it doesn't exist."""
        try:
            if not self.client.bucket_exists(self.bucket_name):
                self.client.make_bucket(self.bucket_name)
        except S3Error as e:
            print(f"Error creating bucket: {e}")

    def upload_file(self, object_key: str, data: bytes, content_type: str) -> str:
        """Upload a file to MinIO."""
        self.client.put_object(
            self.bucket_name,
            object_key,
            BytesIO(data),
            length=len(data),
            content_type=content_type,
        )
        return object_key

    def download_file(self, object_key: str) -> bytes:
        """Download a file from MinIO."""
        response = self.client.get_object(self.bucket_name, object_key)
        data = response.read()
        response.close()
        response.release_conn()
        return data

    def delete_file(self, object_key: str) -> None:
        """Delete a file from MinIO."""
        self.client.remove_object(self.bucket_name, object_key)

    def get_presigned_url(self, object_key: str, expires: timedelta = timedelta(hours=1)) -> str:
        """Get a presigned URL for downloading a file."""
        return self.client.presigned_get_object(
            self.bucket_name,
            object_key,
            expires=expires,
        )


# Singleton instance
minio_service = MinioService()
