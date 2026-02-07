from io import BytesIO, StringIO
import pandas as pd
from src.processing.extractors.base import BaseExtractor, ExtractedDocument


class CSVExtractor(BaseExtractor):
    MAX_ROWS = 1000  # Limit rows to prevent memory issues

    def extract(self, file_content: bytes) -> ExtractedDocument:
        """Extract text from a CSV file using pandas."""
        # Try to decode content
        try:
            text_content = file_content.decode("utf-8")
        except UnicodeDecodeError:
            text_content = file_content.decode("latin-1")

        # Read CSV with pandas (auto-detects delimiter)
        try:
            df = pd.read_csv(
                StringIO(text_content),
                nrows=self.MAX_ROWS,
                on_bad_lines="skip",
            )
        except Exception:
            # Fallback: try with different separators
            for sep in [",", ";", "\t", "|"]:
                try:
                    df = pd.read_csv(
                        StringIO(text_content),
                        sep=sep,
                        nrows=self.MAX_ROWS,
                        on_bad_lines="skip",
                    )
                    break
                except Exception:
                    continue
            else:
                # If all fail, return raw content
                return ExtractedDocument(
                    content=text_content[:50000],  # Limit raw content
                    page_count=1,
                    metadata={"extractor": "raw"},
                    method="raw_csv",
                )

        # Convert to readable text
        lines = []

        # Add header
        header = " | ".join(str(col) for col in df.columns)
        lines.append(header)
        lines.append("-" * len(header))

        # Add rows
        for _, row in df.iterrows():
            row_text = " | ".join(str(val) if pd.notna(val) else "" for val in row)
            lines.append(row_text)

        content = "\n".join(lines)

        return ExtractedDocument(
            content=content,
            page_count=1,
            metadata={
                "extractor": "pandas",
                "row_count": len(df),
                "column_count": len(df.columns),
            },
            method="native_csv",
        )
