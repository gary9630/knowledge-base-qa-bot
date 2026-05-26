from __future__ import annotations

import re

PRODUCT_FRONTMATTER_KEYS = frozenset(
    {
        "canonical_path",
        "content_hash",
        "imported_at",
        "imported_from",
        "published_at",
        "source_original",
        "source_priority",
        "source_type",
        "title",
        "visibility",
    }
)
_REQUIRED_IMPORTED_KEYS = frozenset({"imported_at", "source_original", "source_type"})
_YAML_KEY_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_-]*)\s*:(.*)$")


def parse_product_frontmatter(body: str) -> dict[str, str]:
    lines = body.splitlines(keepends=True)
    if not lines or not _is_frontmatter_delimiter(lines[0]):
        return {}

    for index, line in enumerate(lines[1:], start=1):
        if not _is_frontmatter_delimiter(line):
            continue

        metadata = _parse_flat_metadata(lines[1:index])
        if not metadata or any(key not in PRODUCT_FRONTMATTER_KEYS for key in metadata):
            return {}

        if metadata.get("source_type") == "imported" and not _REQUIRED_IMPORTED_KEYS.issubset(
            metadata
        ):
            return {}

        return metadata

    return {}


def _parse_flat_metadata(lines: list[str]) -> dict[str, str]:
    metadata: dict[str, str] = {}
    for line in lines:
        raw_line = line.rstrip("\n\r")
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        if raw_line[0].isspace():
            return {}

        key_match = _YAML_KEY_RE.match(raw_line)
        if key_match is None:
            return {}

        key, value = key_match.groups()
        metadata[key.lower()] = _unquote_yaml_scalar(value.strip())

    return metadata


def _is_frontmatter_delimiter(line: str) -> bool:
    return line.rstrip("\n\r") == "---"


def _unquote_yaml_scalar(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value
