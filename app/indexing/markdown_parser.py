from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from app.indexing.citations import citation_for, slugify_heading

_HEADING_RE = re.compile(r"^(#{1,6})(?:[ \t]+|$)(.*)$")
_CLOSING_HASHES_RE = re.compile(r"[ \t]+#+[ \t]*$")
_FENCE_RE = re.compile(r"^[ \t]{0,3}(`{3,}|~{3,})")
_METADATA_KEY_RE = re.compile(r"^[A-Za-z_][\w.-]*\s*:")


@dataclass(frozen=True)
class ParsedSection:
    filename: str
    source_id: str
    heading: str
    heading_slug: str
    level: int
    body_md: str


@dataclass(frozen=True)
class _RawSection:
    filename: str
    heading: str
    heading_slug: str
    level: int
    body_md: str


def parse_markdown_sections(filename: str, body: str) -> list[ParsedSection]:
    body_without_frontmatter, had_frontmatter = _strip_yaml_frontmatter(body)
    if had_frontmatter and not body_without_frontmatter.strip():
        return []

    raw_sections: list[_RawSection] = []
    preamble_lines: list[str] = []
    current_heading: str | None = None
    current_level = 1
    current_lines: list[str] = []
    heading_stack: list[tuple[int, str]] = []
    fence: tuple[str, int] | None = None

    for line in body_without_frontmatter.splitlines(keepends=True):
        if fence is not None:
            if current_heading is None:
                preamble_lines.append(line)
            else:
                current_lines.append(line)

            if _is_closing_fence(line, fence):
                fence = None
            continue

        opening_fence = _opening_fence(line)
        if opening_fence is not None:
            if current_heading is None:
                preamble_lines.append(line)
            else:
                current_lines.append(line)
            fence = opening_fence
            continue

        heading_match = _match_heading(line)
        if heading_match is not None:
            if current_heading is None:
                if _has_nonblank_content(preamble_lines):
                    raw_sections.append(_synthetic_section(filename, "".join(preamble_lines)))
                    preamble_lines = []
            else:
                raw_sections.append(
                    _section_from_parts(
                        filename,
                        current_heading,
                        current_level,
                        current_lines,
                    )
                )

            current_level, current_heading = heading_match
            current_heading_slug = slugify_heading(current_heading)
            while heading_stack and heading_stack[-1][0] >= current_level:
                heading_stack.pop()

            heading_stack.append((current_level, current_heading_slug))
            current_lines = [line]
            continue

        if current_heading is None:
            preamble_lines.append(line)
        else:
            current_lines.append(line)

    if current_heading is not None:
        raw_sections.append(
            _section_from_parts(
                filename,
                current_heading,
                current_level,
                current_lines,
            )
        )
    elif _has_nonblank_content(preamble_lines) or body_without_frontmatter == "":
        raw_sections.append(_synthetic_section(filename, "".join(preamble_lines)))

    return _assign_unique_source_ids(raw_sections)


def _match_heading(line: str) -> tuple[int, str] | None:
    heading_match = _HEADING_RE.match(line.rstrip("\n\r"))
    if heading_match is None:
        return None

    level = len(heading_match.group(1))
    heading = _CLOSING_HASHES_RE.sub("", heading_match.group(2)).strip()
    return level, heading


def _opening_fence(line: str) -> tuple[str, int] | None:
    fence_match = _FENCE_RE.match(line.rstrip("\n\r"))
    if fence_match is None:
        return None

    marker = fence_match.group(1)
    return marker[0], len(marker)


def _is_closing_fence(line: str, fence: tuple[str, int]) -> bool:
    marker, length = fence
    stripped = line.strip()
    return stripped.startswith(marker * length) and set(stripped) == {marker}


def _strip_yaml_frontmatter(body: str) -> tuple[str, bool]:
    lines = body.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return body, False

    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            frontmatter_lines = lines[1:index]
            if _looks_like_yaml_metadata(frontmatter_lines):
                return "".join(lines[index + 1 :]).lstrip("\n\r"), True
            return body, False

    return body, False


def _looks_like_yaml_metadata(lines: list[str]) -> bool:
    return any(_METADATA_KEY_RE.match(line.strip()) for line in lines)


def _has_nonblank_content(lines: list[str]) -> bool:
    return any(line.strip() for line in lines)


def _synthetic_heading(filename: str) -> str:
    stem = Path(filename).stem
    return stem or filename


def _synthetic_section(filename: str, body: str) -> _RawSection:
    heading = _synthetic_heading(filename)
    return _section_from_parts(filename, heading, 1, [f"# {heading}\n", "\n", body])


def _section_from_parts(
    filename: str,
    heading: str,
    level: int,
    lines: list[str],
) -> _RawSection:
    return _RawSection(
        filename=filename,
        heading=heading,
        heading_slug=slugify_heading(heading),
        level=level,
        body_md="".join(lines),
    )


def _assign_unique_source_ids(raw_sections: list[_RawSection]) -> list[ParsedSection]:
    slug_counts = Counter(section.heading_slug for section in raw_sections)
    used_slugs: set[str] = set()
    parsed_sections: list[ParsedSection] = []
    unique_heading_stack: list[tuple[int, str]] = []

    for section in raw_sections:
        while unique_heading_stack and unique_heading_stack[-1][0] >= section.level:
            unique_heading_stack.pop()

        slug = section.heading_slug
        if slug_counts[slug] > 1 and unique_heading_stack:
            parent_slugs = tuple(parent_slug for _, parent_slug in unique_heading_stack)
            slug = "-".join((*parent_slugs, slug))

        unique_slug = _unique_slug(slug, used_slugs)
        parsed_sections.append(
            ParsedSection(
                filename=section.filename,
                source_id=citation_for(section.filename, section.heading, slug=unique_slug),
                heading=section.heading,
                heading_slug=unique_slug,
                level=section.level,
                body_md=section.body_md,
            )
        )
        unique_heading_stack.append((section.level, unique_slug))

    return parsed_sections


def _unique_slug(slug: str, used_slugs: set[str]) -> str:
    if slug not in used_slugs:
        used_slugs.add(slug)
        return slug

    suffix = 2
    while f"{slug}-{suffix}" in used_slugs:
        suffix += 1

    unique_slug = f"{slug}-{suffix}"
    used_slugs.add(unique_slug)
    return unique_slug
