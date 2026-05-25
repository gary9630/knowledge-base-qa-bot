from __future__ import annotations

import unicodedata


def slugify_heading(heading: str) -> str:
    """Create a stable source-id slug while preserving non-ASCII headings."""
    normalized = unicodedata.normalize("NFKD", heading).strip().lower()
    parts: list[str] = []
    pending_separator = False

    for char in normalized:
        if unicodedata.combining(char):
            continue

        if char.isascii() and char.isalnum():
            if pending_separator and parts:
                parts.append("-")
            parts.append(char)
            pending_separator = False
            continue

        if not char.isascii() and char.isalnum():
            if pending_separator and parts:
                parts.append("-")
            parts.append(char)
            pending_separator = False
            continue

        if char.isspace() or char in "-_":
            pending_separator = True

    slug = "".join(parts).strip("-")
    return slug or "section"


def citation_for(filename: str, heading: str) -> str:
    return f"{filename}#{slugify_heading(heading)}"
