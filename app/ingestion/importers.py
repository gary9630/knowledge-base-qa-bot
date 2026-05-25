from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
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
_REQUIRED_IMPORT_FRONTMATTER_KEYS = frozenset({"imported_at", "source_original", "source_type"})
_AUTHORED_FRONTMATTER_KEYS = _PRODUCT_FRONTMATTER_KEYS | frozenset(
    {
        "aliases",
        "author",
        "authors",
        "categories",
        "category",
        "date",
        "description",
        "draft",
        "lang",
        "language",
        "summary",
        "tag",
        "tags",
    }
)
_CONTROL_WHITESPACE_RE = re.compile(r"[\r\n\t\f\v]+")
_YAML_KEY_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_-]*)\s*:(.*)$")
_YAML_PLAIN_SAFE_RE = re.compile(r"^[A-Za-z0-9_./:+-]+$")
_BACKTICK_SEQUENCE_RE = re.compile(r"`+")


@dataclass(frozen=True)
class _FrontmatterMetadata:
    values: dict[str, str]
    has_nested_values: bool


def import_markdown_to_markdown(
    filename: str,
    body: str,
    *,
    imported_at: str | datetime | None = None,
) -> str:
    markdown_body = _ensure_trailing_newline(_normalize_markdown_body(body))
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
    rendered_pages: list[str] = []

    for page_number, page in enumerate(reader.pages, start=1):
        text = page.extract_text()
        if text is None or not text.strip():
            rendered_pages.append(f"[Page {page_number}: no extractable text]")
            continue

        rendered_pages.append(f"[Page {page_number}]\n{text.strip()}")

    return "\n\n".join(rendered_pages) or "[PDF: no extractable text]"


def _with_product_frontmatter(
    filename: str,
    body: str,
    imported_at: str | datetime | None,
) -> str:
    return (
        "---\n"
        f"source_original: {_yaml_scalar(f'raw/{Path(filename).name}')}\n"
        "source_type: imported\n"
        f"imported_at: {_yaml_scalar(_format_imported_at(imported_at))}\n"
        "---\n\n"
        f"{body}"
    )


def _format_imported_at(imported_at: str | datetime | None) -> str:
    if imported_at is None:
        return datetime.now(UTC).isoformat()
    if isinstance(imported_at, datetime):
        return imported_at.isoformat()
    return imported_at


def _normalize_markdown_body(body: str) -> str:
    lines = body.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return body

    for index, line in enumerate(lines[1:], start=1):
        if line.strip() != "---":
            continue

        frontmatter_lines = lines[1:index]
        metadata = _parse_frontmatter_metadata(frontmatter_lines)
        if metadata is None:
            return body
        if _is_importer_generated_frontmatter(metadata):
            return "".join(lines[index + 1 :]).lstrip("\n\r")
        if _is_plausible_yaml_frontmatter(metadata):
            frontmatter = "".join(frontmatter_lines)
            body_without_frontmatter = "".join(lines[index + 1 :]).lstrip("\n\r")
            return _authored_frontmatter_section(frontmatter, body_without_frontmatter)
        return body

    return body


def _parse_frontmatter_metadata(lines: list[str]) -> _FrontmatterMetadata | None:
    metadata: dict[str, str] = {}
    has_nested_values = False

    for line in lines:
        raw_line = line.rstrip("\n\r")
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue

        if raw_line[0].isspace():
            if not metadata:
                return None
            has_nested_values = True
            continue

        key_match = _YAML_KEY_RE.match(raw_line)
        if key_match is None:
            return None

        key, value = key_match.groups()
        metadata[key.lower()] = _unquote_yaml_scalar(value.strip())

    if not metadata:
        return None

    return _FrontmatterMetadata(values=metadata, has_nested_values=has_nested_values)


def _is_importer_generated_frontmatter(metadata: _FrontmatterMetadata) -> bool:
    return (
        _REQUIRED_IMPORT_FRONTMATTER_KEYS.issubset(metadata.values)
        and all(key in _PRODUCT_FRONTMATTER_KEYS for key in metadata.values)
        and metadata.values["source_type"] == "imported"
    )


def _is_plausible_yaml_frontmatter(metadata: _FrontmatterMetadata) -> bool:
    return (
        metadata.has_nested_values
        or len(metadata.values) > 1
        or any(key in _AUTHORED_FRONTMATTER_KEYS for key in metadata.values)
    )


def _authored_frontmatter_section(frontmatter: str, body: str) -> str:
    fence = _metadata_fence(frontmatter)
    return (
        "## Original Metadata\n\n"
        f"{fence}yaml\n"
        f"{_ensure_trailing_newline(frontmatter)}"
        f"{fence}\n\n"
        f"{body}"
    )


def _metadata_fence(content: str) -> str:
    max_backtick_run = max(
        (len(match.group(0)) for match in _BACKTICK_SEQUENCE_RE.finditer(content)),
        default=0,
    )
    return "`" * max(3, max_backtick_run + 1)


def _yaml_scalar(value: str) -> str:
    if _YAML_PLAIN_SAFE_RE.fullmatch(value):
        return value

    escaped = "".join(_escape_yaml_double_quoted_char(char) for char in value)
    return f'"{escaped}"'


def _escape_yaml_double_quoted_char(char: str) -> str:
    if char == "\\":
        return "\\\\"
    if char == '"':
        return '\\"'
    if char == "\n":
        return "\\n"
    if char == "\r":
        return "\\r"
    if char == "\t":
        return "\\t"
    if ord(char) < 0x20 or ord(char) == 0x7F:
        return f"\\x{ord(char):02x}"
    return char


def _unquote_yaml_scalar(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _filename_stem(filename: str) -> str:
    stem = Path(filename).stem
    return _sanitize_heading(stem or Path(filename).name)


def _sanitize_heading(value: str) -> str:
    return _CONTROL_WHITESPACE_RE.sub(" ", value).strip() or "untitled"


def _ensure_trailing_newline(body: str) -> str:
    return body if body.endswith("\n") else f"{body}\n"
