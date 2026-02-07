from io import BytesIO
import pdfplumber
from src.processing.extractors.base import BaseExtractor, ExtractedDocument


class PDFExtractor(BaseExtractor):
    def extract(self, file_content: bytes) -> ExtractedDocument:
        """Extract text from a PDF file using pdfplumber."""
        text_parts = []
        page_count = 0

        with pdfplumber.open(BytesIO(file_content)) as pdf:
            page_count = len(pdf.pages)
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text_parts.append(page_text)

        content = "\n\n".join(text_parts)

        return ExtractedDocument(
            content=content,
            page_count=page_count,
            metadata={"extractor": "pdfplumber"},
            method="native_pdf",
        )
