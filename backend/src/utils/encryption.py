"""
Encryption utilities for sensitive data.

Uses Fernet symmetric encryption for connection strings and credentials.
"""

from cryptography.fernet import Fernet

from src.config import settings


class EncryptionService:
    """Singleton service for encrypting/decrypting sensitive data."""

    _instance = None
    _fernet = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialize()
        return cls._instance

    def _initialize(self):
        """Initialize Fernet cipher with encryption key from settings."""
        # Allow initialization without key for backwards compatibility
        # The key will be required when encrypt/decrypt are actually called
        if settings.encryption_key:
            # Ensure the key is bytes
            key = settings.encryption_key
            if isinstance(key, str):
                key = key.encode('utf-8')

            self._fernet = Fernet(key)
        else:
            self._fernet = None

    def encrypt(self, plaintext: str) -> str:
        """
        Encrypt a plaintext string.

        Args:
            plaintext: String to encrypt

        Returns:
            Encrypted string (base64-encoded)
        """
        if not self._fernet:
            raise ValueError(
                "ENCRYPTION_KEY not set in environment. "
                "Generate one with: python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'"
            )

        if not plaintext:
            raise ValueError("Cannot encrypt empty string")

        encrypted_bytes = self._fernet.encrypt(plaintext.encode('utf-8'))
        return encrypted_bytes.decode('utf-8')

    def decrypt(self, encrypted: str) -> str:
        """
        Decrypt an encrypted string.

        Args:
            encrypted: Encrypted string (base64-encoded)

        Returns:
            Decrypted plaintext string
        """
        if not self._fernet:
            raise ValueError(
                "ENCRYPTION_KEY not set in environment. "
                "Generate one with: python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'"
            )

        if not encrypted:
            raise ValueError("Cannot decrypt empty string")

        decrypted_bytes = self._fernet.decrypt(encrypted.encode('utf-8'))
        return decrypted_bytes.decode('utf-8')


# Singleton instance
encryption_service = EncryptionService()
