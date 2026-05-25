from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path

from bs4 import BeautifulSoup
from markdownify import markdownify as html_to_markdown
from pypdf import PdfReader

_PRODUCT_FRONTMATTER_KEYS = frozenset(
    {
        "canonical_path",
        "content_hash",
        "imported_at",
        "imported_from",
        "source_original",
        "source_type",
        "title",
        "visibility",
    }
)
_PRODUCT_IMPORT_KEYS = frozenset({"imported_at", "source_original", "source_type"})


def import_markdown_to_markdown(
    filename: str,
    body: str,
    *,
    imported_at: str | datetime | None = None,
) -> str:
    body_without_product_frontmatter = _strip_existing_product_frontmatter(body)
    markdown_body = _ensure_trailing_newline(body_without_product_frontmatter)
    return _with_product_frontmatter(filename, markdown_body, imported_at)


def import_text_to_markdown(
    filename: str,
    body: str,
    *,
    imported_at: str | datetime | None = None,
) -> str:
    title = _filename_stem(filename)
    markdown_body = f"# {title}\n\n{_ensure_trailing_newline(body)}"
    return _with_product_frontmatter(filename, markdown_body, imported_at)


def import_html_to_markdown(
    filename: str,
    body: str,
    *,
    imported_at: str | datetime | None = None,
) -> str:
    soup = BeautifulSoup(body, "html.parser")
    for element in soup(["script", "style"]):
        element.decompose()

    readable_root = soup.body or soup
    markdown_body = html_to_markdown(
        str(readable_root),
        heading_style="ATX",
        bullets="-",
    ).strip()

    if not markdown_body:
        markdown_body = f"# {_filename_stem(filename)}"

    return _with_product_frontmatter(filename, f"{markdown_body}\n", imported_at)


def import_pdf_to_markdown(
    filename: str,
    body: bytes,
    *,
    imported_at: str | datetime | None = None,
    extractor: Callable[[bytes], str] | None = None,
) -> str:
    pdf_text = (extractor or extract_pdf_text)(body)
    return import_text_to_markdown(filename, pdf_text, imported_at=imported_at)


def extract_pdf_text(body: bytes) -> str:
    reader = PdfReader(BytesIO(body))
    page_text = (page.extract_text() or "" for page in reader.pages)
    return "\n\n".join(text.strip() for text in page_text if text.strip())


def _with_product_frontmatter(
    filename: str,
    body: str,
    imported_at: str | datetime | None,
) -> str:
    return (
        "---\n"
        f"source_original: raw/{Path(filename).name}\n"
        "source_type: imported\n"
        f"imported_at: {_format_imported_at(imported_at)}\n"
        "---\n\n"
        f"{body}"
    )


def _format_imported_at(imported_at: str | datetime | None) -> str:
    if imported_at is None:
        return datetime.now(UTC).isoformat()
    if isinstance(imported_at, datetime):
        return imported_at.isoformat()
    return imported_at


def _strip_existing_product_frontmatter(body: str) -> str:
    lines = body.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return body

    for index, line in enumerate(lines[1:], start=1):
        if line.strip() != "---":
            continue

        frontmatter_lines = lines[1:index]
        keys = tuple(_frontmatter_key(line) for line in frontmatter_lines if line.strip())
        if (
            keys
            and all(key in _PRODUCT_FRONTMATTER_KEYS for key in keys)
            and any(key in _PRODUCT_IMPORT_KEYS for key in keys)
        ):
            return "".join(lines[index + 1 :]).lstrip("\n\r")
        return body

    return body


def _frontmatter_key(line: str) -> str:
    key, separator, _ = line.strip().partition(":")
    if not separator:
        return ""
    return key.strip().lower()


def _filename_stem(filename: str) -> str:
    stem = Path(filename).stem
    return stem or Path(filename).name


def _ensure_trailing_newline(body: str) -> str:
    return body if body.endswith("\n") else f"{body}\n"
