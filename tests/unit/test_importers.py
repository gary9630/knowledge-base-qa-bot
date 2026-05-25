from __future__ import annotations

import pytest

from app.ingestion import importers
from app.ingestion.importers import (
    import_html_to_markdown,
    import_markdown_to_markdown,
    import_pdf_to_markdown,
    import_text_to_markdown,
)
from app.ingestion.service import import_file_to_markdown

IMPORTED_AT = "2026-05-25T10:30:00+00:00"


def test_markdown_import_prepends_product_frontmatter() -> None:
    markdown = import_markdown_to_markdown(
        "faq.md",
        "# FAQ\n\nQuestion\n\nAnswer",
        imported_at=IMPORTED_AT,
    )

    assert markdown.startswith(
        "---\n"
        "source_original: raw/faq.md\n"
        "source_type: imported\n"
        f"imported_at: {IMPORTED_AT}\n"
        "---\n\n"
    )
    assert "# FAQ\n\nQuestion\n\nAnswer" in markdown


def test_markdown_import_replaces_existing_product_frontmatter() -> None:
    markdown = import_markdown_to_markdown(
        "faq.md",
        "---\nsource_original: raw/old.md\nsource_type: imported\n---\n\n# FAQ\n\nAnswer",
        imported_at=IMPORTED_AT,
    )

    assert markdown.count("source_original:") == 1
    assert "source_original: raw/faq.md" in markdown
    assert "raw/old.md" not in markdown
    assert markdown.endswith("# FAQ\n\nAnswer\n")


def test_text_import_uses_filename_stem_heading_and_raw_source_path() -> None:
    markdown = import_text_to_markdown(
        "faq.txt",
        "Question\n\nAnswer",
        imported_at=IMPORTED_AT,
    )

    assert "source_original: raw/faq.txt" in markdown
    assert markdown.split("---", maxsplit=2)[-1].lstrip().startswith("# faq\n\n")
    assert "Question\n\nAnswer" in markdown


def test_text_import_preserves_original_text_whitespace_after_heading() -> None:
    body = "\n\n    indented first line\nbody line\n  trailing spaces  \n\n"

    markdown = import_text_to_markdown("notes.txt", body, imported_at=IMPORTED_AT)

    assert markdown.endswith(f"# notes\n\n{body}")


def test_html_import_converts_readable_headings_and_body_to_markdown() -> None:
    markdown = import_html_to_markdown(
        "policy.html",
        "<html><body><h1>Policy</h1><h2>Refunds</h2><p>Five days.</p></body></html>",
        imported_at=IMPORTED_AT,
    )

    assert "source_original: raw/policy.html" in markdown
    assert "# Policy" in markdown
    assert "## Refunds" in markdown
    assert "Five days." in markdown


def test_pdf_import_uses_extractor_and_stem_heading(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_extract_pdf_text(pdf_bytes: bytes) -> str:
        assert pdf_bytes == b"%PDF tiny fixture"
        return "PDF Question\n\nPDF Answer"

    monkeypatch.setattr(importers, "extract_pdf_text", fake_extract_pdf_text)

    markdown = import_pdf_to_markdown(
        "handbook.pdf",
        b"%PDF tiny fixture",
        imported_at=IMPORTED_AT,
    )

    assert "source_original: raw/handbook.pdf" in markdown
    assert "# handbook" in markdown
    assert "PDF Question\n\nPDF Answer" in markdown


def test_import_file_dispatches_by_extension() -> None:
    markdown = import_file_to_markdown(
        "notes.txt",
        b"Line one\n\nLine two",
        imported_at=IMPORTED_AT,
    )

    assert "source_original: raw/notes.txt" in markdown
    assert "# notes" in markdown
    assert "Line one\n\nLine two" in markdown


def test_import_file_rejects_unsupported_extension() -> None:
    with pytest.raises(ValueError, match="Unsupported import file type"):
        import_file_to_markdown("archive.zip", b"data", imported_at=IMPORTED_AT)
