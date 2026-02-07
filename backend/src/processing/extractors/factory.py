from src.processing.extractors.base import BaseExtractor
from src.processing.extractors.pdf import PDFExtractor
from src.processing.extractors.docx import DOCXExtractor
from src.processing.extractors.excel import ExcelExtractor
from src.processing.extractors.csv_extractor import CSVExtractor
from src.processing.extractors.text import TextExtractor


class ExtractorFactory:
    _EXTRACTORS: dict[str, type[BaseExtractor]] = {
        "application/pdf": PDFExtractor,
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": DOCXExtractor,
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ExcelExtractor,
        "application/vnd.ms-excel": ExcelExtractor,
        "text/csv": CSVExtractor,
        "text/plain": TextExtractor,
        "text/markdown": TextExtractor,
        "application/octet-stream": TextExtractor,
    }

    @classmethod
    def get_extractor(cls, mime_type: str) -> BaseExtractor:
        """Get the appropriate extractor for a MIME type.

        Args:
            mime_type: The MIME type of the file

        Returns:
            An extractor instance

        Raises:
            ValueError: If the MIME type is not supported
        """
        extractor_class = cls._EXTRACTORS.get(mime_type)
        if extractor_class is None:
            raise ValueError(f"Unsupported file type: {mime_type}")
        return extractor_class()

    @classmethod
    def is_supported(cls, mime_type: str) -> bool:
        """Check if a MIME type is supported."""
        return mime_type in cls._EXTRACTORS

    @classmethod
    def supported_types(cls) -> list[str]:
        """Get list of supported MIME types."""
        return list(cls._EXTRACTORS.keys())
