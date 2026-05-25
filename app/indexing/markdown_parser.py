from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from app.indexing.citations import citation_for, slugify_heading

_HEADING_RE = re.compile(r"^(#{1,6})[ \t]+(.+?)[ \t]*#*[ \t]*$")


@dataclass(frozen=True)
class ParsedSection:
    filename: str
    source_id: str
    heading: str
    heading_slug: str
    level: int
    body_md: str


def parse_markdown_sections(filename: str, body: str) -> list[ParsedSection]:
    sections: list[ParsedSection] = []
    preamble_lines: list[str] = []
    current_heading: str | None = None
    current_level = 1
    current_lines: list[str] = []

    for line in body.splitlines(keepends=True):
        heading_match = _HEADING_RE.match(line.rstrip("\n\r"))
        if heading_match is not None:
            if current_heading is None:
                if preamble_lines:
                    sections.append(_synthetic_section(filename, "".join(preamble_lines)))
                    preamble_lines = []
            else:
                sections.append(
                    _section_from_parts(filename, current_heading, current_level, current_lines)
                )

            current_heading = _clean_heading(heading_match.group(2))
            current_level = len(heading_match.group(1))
            current_lines = [line]
            continue

        if current_heading is None:
            preamble_lines.append(line)
        else:
            current_lines.append(line)

    if current_heading is not None:
        sections.append(
            _section_from_parts(filename, current_heading, current_level, current_lines)
        )
    elif preamble_lines or body == "":
        sections.append(_synthetic_section(filename, "".join(preamble_lines)))

    return sections


def _clean_heading(heading: str) -> str:
    return heading.strip()


def _synthetic_heading(filename: str) -> str:
    stem = Path(filename).stem
    return stem or filename


def _synthetic_section(filename: str, body: str) -> ParsedSection:
    heading = _synthetic_heading(filename)
    return _section_from_parts(filename, heading, 1, [f"# {heading}\n", "\n", body])


def _section_from_parts(
    filename: str,
    heading: str,
    level: int,
    lines: list[str],
) -> ParsedSection:
    return ParsedSection(
        filename=filename,
        source_id=citation_for(filename, heading),
        heading=heading,
        heading_slug=slugify_heading(heading),
        level=level,
        body_md="".join(lines),
    )
