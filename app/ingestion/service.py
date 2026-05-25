from __future__ import annotations

from datetime import datetime
from pathlib import Path

from app.ingestion.importers import (
    import_html_to_markdown,
    import_markdown_to_markdown,
    import_pdf_to_markdown,
    import_text_to_markdown,
)


def import_file_to_markdown(
    filename: str,
    body: bytes,
    *,
    imported_at: str | datetime | None = None,
) -> str:
    suffix = Path(filename).suffix.lower()

    if suffix == ".md":
        return import_markdown_to_markdown(filename, body.decode("utf-8"), imported_at=imported_at)
    if suffix == ".txt":
        return import_text_to_markdown(filename, body.decode("utf-8"), imported_at=imported_at)
    if suffix == ".html":
        return import_html_to_markdown(filename, body.decode("utf-8"), imported_at=imported_at)
    if suffix == ".pdf":
        return import_pdf_to_markdown(filename, body, imported_at=imported_at)

    raise ValueError(f"Unsupported import file type: {suffix or '<none>'}")
