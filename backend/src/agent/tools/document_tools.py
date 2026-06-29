"""
read_document tool — fetch the full extracted text of a document (paginated)
so the text_search_agent can deep-read after retrieval, e.g. to compare
sections across documents instead of reasoning from 1-2 retrieved chunks.
"""

import logging

from src.agent.tools.context import get_tool_context

logger = logging.getLogger(__name__)

# Cap per call to protect the worker's context window (~5K tokens of text)
_MAX_LENGTH = 20_000
_DEFAULT_LENGTH = 15_000


def read_document(filename: str, start_char: int = 0, length: int = _DEFAULT_LENGTH) -> str:
    """
    Read the extracted text of a document by filename.

    Use after search_collections has identified the right document, when you
    need more context than the retrieved chunks — e.g. reading a full section,
    or comparing content across multiple documents (call once per document).
    Long documents are paginated: the header tells you the next start_char.

    Args:
        filename: Document filename (partial match allowed, e.g. "manual")
        start_char: Character offset to start reading from (default 0)
        length: Number of characters to return (default 15000, max 20000)

    Returns:
        A slice of the document text with a pagination header
    """
    from sqlalchemy import select

    from src.db.database import SyncSessionLocal
    from src.models.collection import Document

    context = get_tool_context()

    try:
        start_char = max(0, int(start_char))
        length = min(max(1, int(length)), _MAX_LENGTH)
    except (TypeError, ValueError):
        return "Error: start_char and length must be integers."

    try:
        with SyncSessionLocal() as db:
            stmt = select(Document).where(
                Document.filename.ilike(f"%{filename}%"),
                Document.status == "completed",
            )
            if context and context.collection_ids:
                stmt = stmt.where(
                    Document.collection_id.in_(context.collection_ids)
                )
            documents = list(db.execute(stmt).scalars().all())

        if not documents:
            return (
                f"NO_RESULTS: No completed document matching '{filename}' found. "
                "Use search_collections or list_collections to find the right filename."
            )

        if len(documents) > 1:
            exact = [d for d in documents if d.filename.lower() == filename.lower()]
            if len(exact) == 1:
                documents = exact
            else:
                names = "\n".join(f"- {d.filename}" for d in documents[:10])
                return (
                    f"Multiple documents match '{filename}' — call read_document "
                    f"again with one exact filename:\n{names}"
                )

        document = documents[0]
        text = document.extracted_text or ""
        if not text:
            return f"Error: Document '{document.filename}' has no extracted text."

        total = len(text)
        if start_char >= total:
            return (
                f"Error: start_char {start_char} is beyond the end of "
                f"'{document.filename}' ({total} chars total)."
            )

        end = min(start_char + length, total)
        slice_text = text[start_char:end]

        header = (
            f"[{document.filename} — {total} chars total, showing {start_char}..{end}]"
        )
        if end < total:
            header += f"\n[More content follows — call read_document with start_char={end}]"

        return f"{header}\n\n{slice_text}"

    except Exception as e:
        logger.error("[read_document] %s", e, exc_info=True)
        return f"Error reading document: {str(e)}"
