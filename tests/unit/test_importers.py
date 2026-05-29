from __future__ import annotations

import pytest

from app.indexing.markdown_parser import parse_markdown_sections
from app.ingestion import importers
from app.ingestion.importers import (
    extract_pdf_text,
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
        (
            "---\n"
            "source_original: raw/old.md\n"
            "source_type: imported\n"
            "imported_at: 2026-05-20T00:00:00+00:00\n"
            "---\n\n"
            "# FAQ\n\n"
            "Answer"
        ),
        imported_at=IMPORTED_AT,
    )

    assert markdown.count("source_original:") == 1
    assert "source_original: raw/faq.md" in markdown
    assert "raw/old.md" not in markdown
    assert markdown.endswith("# FAQ\n\nAnswer\n")


def test_markdown_import_converts_authored_frontmatter_to_metadata_section() -> None:
    authored_body = (
        "---\n"
        "title: Vendor Doc\n"
        "source_type: vendor\n"
        "---\n\n"
        "# Vendor\n\n"
        "Body\n"
    )

    markdown = import_markdown_to_markdown("vendor.md", authored_body, imported_at=IMPORTED_AT)

    imported_body = _import_body(markdown)
    assert not imported_body.startswith("---\n")
    expected_metadata_section = (
        "## Original Metadata\n\n"
        "```yaml\n"
        "title: Vendor Doc\n"
        "source_type: vendor\n"
        "```\n"
    )
    assert expected_metadata_section in markdown
    assert "# Vendor\n\nBody\n" in markdown

    sections = parse_markdown_sections(filename="vendor.md", body=markdown)
    assert [section.heading for section in sections] == ["Original Metadata", "Vendor"]


def test_markdown_import_converts_nested_authored_frontmatter_to_metadata_section() -> None:
    authored_body = (
        "---\n"
        "title: Vendor Doc\n"
        "tags:\n"
        "  - policy\n"
        "---\n\n"
        "# Policy\n"
        "Body\n"
    )

    markdown = import_markdown_to_markdown("policy.md", authored_body, imported_at=IMPORTED_AT)

    imported_body = _import_body(markdown)
    assert not imported_body.startswith("---\n")
    assert "## Original Metadata\n\n```yaml\n" in imported_body
    assert "title: Vendor Doc\n" in imported_body
    assert "tags:\n  - policy\n" in imported_body
    assert "# Policy\nBody\n" in imported_body

    sections = parse_markdown_sections(filename="policy.md", body=markdown)
    assert [section.heading for section in sections] == ["Original Metadata", "Policy"]


def test_markdown_import_uses_collision_safe_metadata_fence() -> None:
    authored_body = (
        "---\n"
        "title: Vendor Doc\n"
        "description: |\n"
        "  sample fence:\n"
        "  ```\n"
        "---\n\n"
        "# Policy\n"
        "Body\n"
    )

    markdown = import_markdown_to_markdown("policy.md", authored_body, imported_at=IMPORTED_AT)

    assert "````yaml\n" in markdown
    sections = parse_markdown_sections(filename="policy.md", body=markdown)
    assert [section.heading for section in sections] == ["Original Metadata", "Policy"]
    assert "  ```\n" in sections[0].body_md


def test_markdown_import_keeps_indented_yaml_delimiter_inside_metadata() -> None:
    authored_body = (
        "---\n"
        "title: Vendor Doc\n"
        "notes: |\n"
        "  before\n"
        "  ---\n"
        "  after\n"
        "---\n\n"
        "# Policy\n"
        "Body\n"
    )

    markdown = import_markdown_to_markdown("policy.md", authored_body, imported_at=IMPORTED_AT)

    imported_body = _import_body(markdown)
    assert "## Original Metadata\n\n```yaml\n" in imported_body
    assert "notes: |\n  before\n  ---\n  after\n" in imported_body
    assert "# Policy\nBody\n" in imported_body

    sections = parse_markdown_sections(filename="policy.md", body=markdown)
    assert [section.heading for section in sections] == ["Original Metadata", "Policy"]


def test_markdown_import_keeps_prose_thematic_break_content() -> None:
    authored_body = "---\nNote: this is real content.\n---\n\n# Policy\nBody\n"

    markdown = import_markdown_to_markdown("policy.md", authored_body, imported_at=IMPORTED_AT)

    imported_body = _import_body(markdown)
    assert imported_body.startswith(authored_body)
    assert "## Original Metadata" not in imported_body

    sections = parse_markdown_sections(filename="policy.md", body=markdown)
    assert [section.heading for section in sections] == ["policy", "Policy"]


def test_markdown_import_separates_headingless_body_from_original_metadata() -> None:
    authored_body = "---\ntitle: Vendor Doc\n---\n\nIntro body with no heading."

    markdown = import_markdown_to_markdown("vendor.md", authored_body, imported_at=IMPORTED_AT)

    sections = parse_markdown_sections(filename="vendor.md", body=markdown)
    assert [section.heading for section in sections] == ["Original Metadata", "vendor"]
    assert "Intro body with no heading." not in sections[0].body_md
    assert "Intro body with no heading." in sections[1].body_md


def test_markdown_import_separates_intro_prose_before_first_heading() -> None:
    authored_body = "---\ntitle: Vendor Doc\n---\n\nIntro prose\n\n# Policy\nBody\n"

    markdown = import_markdown_to_markdown("source.md", authored_body, imported_at=IMPORTED_AT)

    sections = parse_markdown_sections(filename="source.md", body=markdown)
    assert [section.heading for section in sections] == ["Original Metadata", "source", "Policy"]
    assert "Intro prose" not in sections[0].body_md
    assert "Intro prose" in sections[1].body_md
    assert "Body" in sections[2].body_md


def test_text_import_uses_filename_stem_heading_and_raw_source_path() -> None:
    markdown = import_text_to_markdown(
        "faq.txt",
        "Question\n\nAnswer",
        imported_at=IMPORTED_AT,
    )

    assert "source_original: raw/faq.txt" in markdown
    assert markdown.split("---", maxsplit=2)[-1].lstrip().startswith("# faq\n\n")
    assert "Question\n\nAnswer" in markdown


def test_text_import_can_include_canonical_metadata_for_ingestion_jobs() -> None:
    markdown = import_text_to_markdown(
        "faq.txt",
        "Question\n\nAnswer",
        imported_at=IMPORTED_AT,
        content_hash="abc123",
        canonical_path="docs/faq.md",
    )
    frontmatter = _import_frontmatter(markdown)

    assert "content_hash: abc123" in frontmatter
    assert "canonical_path: docs/faq.md" in frontmatter


def test_text_import_preserves_original_text_whitespace_after_heading() -> None:
    body = "\n\n    indented first line\nbody line\n  trailing spaces  \n\n"

    markdown = import_text_to_markdown("notes.txt", body, imported_at=IMPORTED_AT)

    assert markdown.endswith(f"# notes\n\n{body}")


def test_text_import_sanitizes_filename_stem_to_single_line_heading() -> None:
    markdown = import_text_to_markdown("bad\n# injected.txt", "Body", imported_at=IMPORTED_AT)

    imported_body = _import_body(markdown)
    assert imported_body.startswith("# bad # injected\n\nBody\n")

    sections = parse_markdown_sections(filename="bad.md", body=markdown)
    assert [section.heading for section in sections] == ["bad # injected"]


def test_text_import_sanitizes_ascii_file_separator_in_filename_heading() -> None:
    markdown = import_text_to_markdown("bad\x1c# injected.txt", "Body", imported_at=IMPORTED_AT)

    imported_body = _import_body(markdown)
    assert imported_body.startswith("# bad # injected\n\nBody\n")

    sections = parse_markdown_sections(filename="bad.md", body=markdown)
    assert [section.heading for section in sections] == ["bad # injected"]


def test_source_original_quotes_yaml_sensitive_filename() -> None:
    markdown = import_text_to_markdown("bad: name\nextra.txt", "Body", imported_at=IMPORTED_AT)
    frontmatter = _import_frontmatter(markdown)

    assert frontmatter.splitlines()[0] == 'source_original: "raw/bad: name\\nextra.txt"'
    assert frontmatter.count("source_original:") == 1

    hash_markdown = import_text_to_markdown("policy #1.txt", "Body", imported_at=IMPORTED_AT)
    hash_frontmatter = _import_frontmatter(hash_markdown)
    assert hash_frontmatter.splitlines()[0] == 'source_original: "raw/policy #1.txt"'


def test_frontmatter_escapes_raw_control_characters() -> None:
    markdown = import_text_to_markdown(
        "bad\fdoc.txt",
        "Body",
        imported_at="2026-05-25T10:30:00+00:00\fextra: injected",
    )
    frontmatter = _import_frontmatter(markdown)

    assert "\f" not in frontmatter
    assert 'source_original: "raw/bad\\x0cdoc.txt"' in frontmatter
    assert 'imported_at: "2026-05-25T10:30:00+00:00\\x0cextra: injected"' in frontmatter
    assert all(not line.startswith("extra:") for line in frontmatter.splitlines())


def test_frontmatter_and_title_escape_unicode_line_separators() -> None:
    markdown = import_text_to_markdown(
        "bad\u2028# injected.txt",
        "Body",
        imported_at="2026-05-25T10:30:00+00:00\u2029extra: injected",
    )
    frontmatter = _import_frontmatter(markdown)

    assert "\u2028" not in frontmatter
    assert "\u2029" not in frontmatter
    assert frontmatter.count("source_original:") == 1
    assert frontmatter.count("imported_at:") == 1
    assert 'source_original: "raw/bad\\u2028# injected.txt"' in frontmatter
    assert 'imported_at: "2026-05-25T10:30:00+00:00\\u2029extra: injected"' in frontmatter
    assert all(not line.startswith("extra:") for line in frontmatter.splitlines())

    imported_body = _import_body(markdown)
    assert imported_body.startswith("# bad # injected\n\nBody\n")

    sections = parse_markdown_sections(filename="bad.md", body=markdown)
    assert [section.heading for section in sections] == ["bad # injected"]


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


def test_extract_pdf_text_marks_unextractable_pages(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_pdf_reader(monkeypatch, ["First page", None, " Third page "])

    text = extract_pdf_text(b"%PDF tiny fixture")

    assert text == (
        "[Page 1]\n"
        "First page\n\n"
        "[Page 2: no extractable text]\n\n"
        "[Page 3]\n"
        "Third page"
    )


def test_extract_pdf_text_marks_pdf_with_no_extractable_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_pdf_reader(monkeypatch, [None, "   "])

    text = extract_pdf_text(b"%PDF tiny fixture")

    assert text == "[Page 1: no extractable text]\n\n[Page 2: no extractable text]"


def test_import_file_dispatches_by_extension() -> None:
    markdown = import_file_to_markdown(
        "notes.txt",
        b"Line one\n\nLine two",
        imported_at=IMPORTED_AT,
    )

    assert "source_original: raw/notes.txt" in markdown
    assert "# notes" in markdown
    assert "Line one\n\nLine two" in markdown


def test_import_file_dispatches_markdown_long_extension() -> None:
    markdown = import_file_to_markdown(
        "notes.markdown",
        b"# Notes\n\nBody",
        imported_at=IMPORTED_AT,
    )

    assert "source_original: raw/notes.markdown" in markdown
    assert "# Notes\n\nBody" in markdown


def test_import_file_decodes_utf8_sig_text_without_bom() -> None:
    markdown = import_file_to_markdown("bom.txt", b"\xef\xbb\xbfBody", imported_at=IMPORTED_AT)

    assert "\ufeff" not in markdown
    assert markdown.endswith("# bom\n\nBody\n")


def test_import_file_rejects_unsupported_extension() -> None:
    with pytest.raises(ValueError, match="Unsupported import file type"):
        import_file_to_markdown("archive.zip", b"data", imported_at=IMPORTED_AT)


def _import_frontmatter(markdown: str) -> str:
    assert markdown.startswith("---\n")
    frontmatter, separator, _ = markdown.removeprefix("---\n").partition("\n---\n\n")
    assert separator
    return frontmatter


def _import_body(markdown: str) -> str:
    assert markdown.startswith("---\n")
    _, separator, body = markdown.removeprefix("---\n").partition("\n---\n\n")
    assert separator
    return body


def _patch_pdf_reader(monkeypatch: pytest.MonkeyPatch, page_texts: list[str | None]) -> None:
    class FakePage:
        def __init__(self, text: str | None) -> None:
            self.text = text

        def extract_text(self) -> str | None:
            return self.text

    class FakeReader:
        def __init__(self, _source: object) -> None:
            self.pages = [FakePage(text) for text in page_texts]

    monkeypatch.setattr(importers, "PdfReader", FakeReader)
