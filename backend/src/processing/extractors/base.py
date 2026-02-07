from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass
class ExtractedDocument:
    content: str
    page_count: Optional[int] = None
    metadata: Optional[dict] = None
    method: str = "unknown"


class BaseExtractor(ABC):
    @abstractmethod
    def extract(self, file_content: bytes) -> ExtractedDocument:
        """Extract text content from a file.

        Args:
            file_content: Raw file bytes

        Returns:
            ExtractedDocument with text content and metadata
        """
        pass
