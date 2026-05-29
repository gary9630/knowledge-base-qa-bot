from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

SUPPORTED_IMPORT_EXTENSIONS: dict[str, str] = {
    ".md": "markdown",
    ".markdown": "markdown",
    ".txt": "text",
    ".html": "html",
    ".htm": "html",
    ".pdf": "pdf",
}

_GENERIC_CONTENT_TYPES = {"application/octet-stream", "binary/octet-stream"}
_ALLOWED_CONTENT_TYPES = {
    "markdown": {"text/markdown", "text/x-markdown", "text/plain"},
    "text": {"text/plain"},
    "html": {"text/html", "application/xhtml+xml"},
    "pdf": {"application/pdf"},
}
_HTML_TAG_RE = re.compile(
    rb"<\s*(?:!doctype\s+html|html|head|body|article|section|div|p|h[1-6])\b",
    re.I,
)


class IngestionValidationError(ValueError):
    pass


@dataclass(frozen=True)
class UploadInspection:
    original_filename: str
    extension: str
    detected_file_type: str
    content_type: str | None
    warnings: tuple[str, ...] = ()


def inspect_upload(
    *,
    filename: str,
    content_type: str | None,
    body: bytes,
) -> UploadInspection:
    normalized_content_type = _normalize_content_type(content_type)
    suffix = Path(filename).suffix.lower()
    detected_file_type = SUPPORTED_IMPORT_EXTENSIONS.get(suffix)
    warnings: list[str] = []

    if not body or not body.strip():
        raise IngestionValidationError("Upload file is empty.")
    if detected_file_type is None:
        supported = ", ".join(sorted(SUPPORTED_IMPORT_EXTENSIONS))
        raise IngestionValidationError(
            f"Unsupported import file type: {suffix or '<none>'}. Supported: {supported}."
        )

    if normalized_content_type is None:
        warnings.append("content_type_missing")
    elif normalized_content_type not in _GENERIC_CONTENT_TYPES and (
        normalized_content_type not in _ALLOWED_CONTENT_TYPES[detected_file_type]
    ):
        raise IngestionValidationError(
            f"Upload content type {normalized_content_type} is not compatible with "
            f"{suffix} files."
        )

    if detected_file_type == "pdf" and not body.lstrip().startswith(b"%PDF-"):
        raise IngestionValidationError("PDF upload does not start with a PDF signature.")

    if detected_file_type == "html" and not _looks_like_html(body):
        raise IngestionValidationError("HTML upload does not contain recognizable HTML markup.")

    if detected_file_type in {"markdown", "text"} and b"\x00" in body[:4096]:
        raise IngestionValidationError("Text upload appears to be binary data.")

    return UploadInspection(
        original_filename=filename,
        extension=suffix,
        detected_file_type=detected_file_type,
        content_type=normalized_content_type,
        warnings=tuple(warnings),
    )


def _normalize_content_type(content_type: str | None) -> str | None:
    if not content_type:
        return None
    normalized = content_type.split(";", maxsplit=1)[0].strip().lower()
    return normalized or None


def _looks_like_html(body: bytes) -> bool:
    return _HTML_TAG_RE.search(body[:4096]) is not None
