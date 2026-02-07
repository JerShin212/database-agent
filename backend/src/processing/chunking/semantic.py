from src.processing.chunking.base import BaseChunker, Chunk
from src.config import settings


class SemanticChunker(BaseChunker):
    """Semantic chunker that splits text at natural boundaries."""

    def __init__(
        self,
        chunk_size: int = None,
        chunk_overlap: int = None,
        separators: list[str] = None,
    ):
        self.chunk_size = chunk_size or settings.chunk_size
        self.chunk_overlap = chunk_overlap or settings.chunk_overlap
        self.separators = separators or ["\n\n", "\n", ". ", " ", ""]

    def chunk(self, text: str) -> list[Chunk]:
        """Split text into semantic chunks."""
        if not text or not text.strip():
            return []

        # Split text recursively
        splits = self._split_text(text, self.separators)

        # Merge splits into chunks of appropriate size
        chunks = self._merge_splits(splits)

        return chunks

    def _split_text(self, text: str, separators: list[str]) -> list[str]:
        """Recursively split text using separators."""
        if not separators:
            return [text]

        separator = separators[0]
        remaining_separators = separators[1:]

        if separator == "":
            # Character-level split
            return list(text)

        splits = text.split(separator)

        # Filter empty splits and add separator back
        final_splits = []
        for i, split in enumerate(splits):
            if split:
                # Check if split is small enough
                if len(split) <= self.chunk_size:
                    final_splits.append(split)
                else:
                    # Recursively split with finer separators
                    sub_splits = self._split_text(split, remaining_separators)
                    final_splits.extend(sub_splits)

        return final_splits

    def _merge_splits(self, splits: list[str]) -> list[Chunk]:
        """Merge splits into chunks of target size with overlap."""
        if not splits:
            return []

        chunks = []
        current_chunk = []
        current_length = 0
        current_start = 0
        position = 0

        for split in splits:
            split_length = len(split)

            # If adding this split exceeds chunk size, finalize current chunk
            if current_length + split_length > self.chunk_size and current_chunk:
                chunk_content = " ".join(current_chunk)
                chunks.append(
                    Chunk(
                        content=chunk_content,
                        index=len(chunks),
                        start_char=current_start,
                        end_char=current_start + len(chunk_content),
                    )
                )

                # Handle overlap - keep some splits for next chunk
                overlap_splits = []
                overlap_length = 0
                for s in reversed(current_chunk):
                    if overlap_length + len(s) <= self.chunk_overlap:
                        overlap_splits.insert(0, s)
                        overlap_length += len(s) + 1
                    else:
                        break

                current_chunk = overlap_splits
                current_length = overlap_length
                current_start = position - overlap_length

            current_chunk.append(split)
            current_length += split_length + 1  # +1 for space
            position += split_length + 1

        # Add final chunk
        if current_chunk:
            chunk_content = " ".join(current_chunk)
            chunks.append(
                Chunk(
                    content=chunk_content,
                    index=len(chunks),
                    start_char=current_start,
                    end_char=current_start + len(chunk_content),
                )
            )

        return chunks
