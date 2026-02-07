from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass
class Chunk:
    content: str
    index: int
    start_char: Optional[int] = None
    end_char: Optional[int] = None


class BaseChunker(ABC):
    @abstractmethod
    def chunk(self, text: str) -> list[Chunk]:
        """Split text into chunks.

        Args:
            text: The text to chunk

        Returns:
            List of Chunk objects with content and position info
        """
        pass
