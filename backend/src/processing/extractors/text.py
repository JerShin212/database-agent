from src.processing.extractors.base import BaseExtractor, ExtractedDocument


class TextExtractor(BaseExtractor):
    MAX_CHARS = 100000  # Limit characters to prevent memory issues

    def extract(self, file_content: bytes) -> ExtractedDocument:
        """Extract text from a plain text file."""
        # Try to decode content
        try:
            content = file_content.decode("utf-8")
        except UnicodeDecodeError:
            try:
                content = file_content.decode("latin-1")
            except UnicodeDecodeError:
                content = file_content.decode("utf-8", errors="replace")

        # Truncate if too long
        if len(content) > self.MAX_CHARS:
            content = content[: self.MAX_CHARS] + "\n\n... (truncated)"

        return ExtractedDocument(
            content=content,
            page_count=1,
            metadata={"extractor": "text"},
            method="native_text",
        )
