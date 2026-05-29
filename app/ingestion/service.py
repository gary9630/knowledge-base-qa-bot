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
    content_hash: str | None = None,
    canonical_path: str | None = None,
) -> str:
    suffix = Path(filename).suffix.lower()

    if suffix in {".md", ".markdown"}:
        return import_markdown_to_markdown(
            filename,
            _decode_text_body(body),
            imported_at=imported_at,
            content_hash=content_hash,
            canonical_path=canonical_path,
        )
    if suffix == ".txt":
        return import_text_to_markdown(
            filename,
            _decode_text_body(body),
            imported_at=imported_at,
            content_hash=content_hash,
            canonical_path=canonical_path,
        )
    if suffix in {".html", ".htm"}:
        return import_html_to_markdown(
            filename,
            _decode_text_body(body),
            imported_at=imported_at,
            content_hash=content_hash,
            canonical_path=canonical_path,
        )
    if suffix == ".pdf":
        return import_pdf_to_markdown(
            filename,
            body,
            imported_at=imported_at,
            content_hash=content_hash,
            canonical_path=canonical_path,
        )

    raise ValueError(f"Unsupported import file type: {suffix or '<none>'}")


def _decode_text_body(body: bytes) -> str:
    return body.decode("utf-8-sig")
