from app.indexing.markdown_parser import parse_markdown_sections


def test_parse_markdown_sections_uses_headings_as_units() -> None:
    markdown = "# FAQ\n\nIntro\n\n## 課程網站\n\n課程網站是 https://buildmoat.org/\n"

    sections = parse_markdown_sections(filename="常見問題FAQ.md", body=markdown)

    assert [section.heading for section in sections] == ["FAQ", "課程網站"]
    assert sections[1].source_id == "常見問題FAQ.md#課程網站"
    assert "課程網站是" in sections[1].body_md


def test_parse_markdown_sections_keeps_heading_line_in_body() -> None:
    markdown = "## Refund Timeline\n\nRefunds take 5 business days.\n"

    sections = parse_markdown_sections(filename="refund_policy.md", body=markdown)

    assert sections[0].body_md.startswith("## Refund Timeline\n")
    assert sections[0].source_id == "refund_policy.md#refund-timeline"


def test_parse_markdown_sections_creates_synthetic_section_without_heading() -> None:
    markdown = "Intro without an explicit heading.\n"

    sections = parse_markdown_sections(filename="about-us.md", body=markdown)

    assert [section.heading for section in sections] == ["about-us"]
    assert sections[0].source_id == "about-us.md#about-us"
    assert sections[0].body_md.startswith("# about-us\n\n")
    assert "Intro without" in sections[0].body_md


def test_parse_markdown_sections_returns_no_sections_for_empty_doc() -> None:
    assert parse_markdown_sections(filename="doc.md", body="") == []


def test_parse_markdown_sections_disambiguates_repeated_same_level_headings() -> None:
    markdown = "## FAQ\n\nFirst answer.\n\n## FAQ\n\nSecond answer.\n"

    sections = parse_markdown_sections(filename="doc.md", body=markdown)

    assert [section.source_id for section in sections] == ["doc.md#faq", "doc.md#faq-2"]


def test_parse_markdown_sections_uses_parent_slug_for_repeated_child_headings() -> None:
    markdown = "# Week 1\n\n## FAQ\n\nFirst.\n\n# Week 2\n\n## FAQ\n\nSecond.\n"

    sections = parse_markdown_sections(filename="doc.md", body=markdown)

    assert [section.source_id for section in sections] == [
        "doc.md#week-1",
        "doc.md#week-1-faq",
        "doc.md#week-2",
        "doc.md#week-2-faq",
    ]


def test_parse_markdown_sections_uses_disambiguated_parent_slug_for_children() -> None:
    markdown = "# Week\n\n## FAQ\n\nFirst.\n\n# Week\n\n## FAQ\n\nSecond.\n"

    sections = parse_markdown_sections(filename="course.md", body=markdown)

    assert [section.source_id for section in sections] == [
        "course.md#week",
        "course.md#week-faq",
        "course.md#week-2",
        "course.md#week-2-faq",
    ]


def test_parse_markdown_sections_ignores_yaml_frontmatter_before_heading() -> None:
    markdown = "---\nsource_original: raw/a.txt\n---\n\n# Title\n\nBody.\n"

    sections = parse_markdown_sections(filename="doc.md", body=markdown)

    assert [section.heading for section in sections] == ["Title"]
    assert sections[0].source_id == "doc.md#title"
    assert "source_original" not in sections[0].body_md


def test_parse_markdown_sections_ignores_import_metadata_frontmatter() -> None:
    markdown = (
        "---\n"
        "source_original: raw/a.txt\n"
        "source_type: imported\n"
        "imported_at: 2026-05-25T00:00:00Z\n"
        "---\n\n"
        "# Title\n\n"
        "Body.\n"
    )

    sections = parse_markdown_sections(filename="doc.md", body=markdown)

    assert [section.heading for section in sections] == ["Title"]
    assert sections[0].source_id == "doc.md#title"
    assert "source_original" not in sections[0].body_md


def test_parse_markdown_sections_returns_no_sections_for_frontmatter_only_doc() -> None:
    markdown = "---\nsource_original: raw/a.txt\n---\n"

    assert parse_markdown_sections(filename="doc.md", body=markdown) == []


def test_parse_markdown_sections_keeps_thematic_break_content_before_heading() -> None:
    markdown = "---\nIntro paragraph that is real content.\n---\n\n# Title\n\nBody.\n"

    sections = parse_markdown_sections(filename="doc.md", body=markdown)

    assert [section.heading for section in sections] == ["doc", "Title"]
    assert sections[0].source_id == "doc.md#doc"
    assert "Intro paragraph that is real content." in sections[0].body_md
    assert sections[1].source_id == "doc.md#title"


def test_parse_markdown_sections_keeps_note_label_thematic_break_content() -> None:
    markdown = "---\nNote: this is real content.\n---\n\n# Title\n\nBody.\n"

    sections = parse_markdown_sections(filename="doc.md", body=markdown)

    assert [section.heading for section in sections] == ["doc", "Title"]
    assert sections[0].source_id == "doc.md#doc"
    assert "Note: this is real content." in sections[0].body_md
    assert sections[1].source_id == "doc.md#title"


def test_parse_markdown_sections_ignores_leading_blank_lines_before_heading() -> None:
    markdown = "\n\n# Title\nBody.\n"

    sections = parse_markdown_sections(filename="doc.md", body=markdown)

    assert [section.heading for section in sections] == ["Title"]
    assert sections[0].source_id == "doc.md#title"


def test_parse_markdown_sections_ignores_headings_inside_backtick_fences() -> None:
    markdown = "# Title\n\n```python\n# Not a heading\n```\n\nAfter.\n"

    sections = parse_markdown_sections(filename="doc.md", body=markdown)

    assert [section.heading for section in sections] == ["Title"]
    assert "# Not a heading" in sections[0].body_md


def test_parse_markdown_sections_ignores_headings_inside_tilde_fences() -> None:
    markdown = "# Title\n\n~~~\n## Not a heading\n~~~\n"

    sections = parse_markdown_sections(filename="doc.md", body=markdown)

    assert [section.heading for section in sections] == ["Title"]
    assert "## Not a heading" in sections[0].body_md


def test_parse_markdown_sections_preserves_hash_without_closing_space() -> None:
    markdown = "# C#\n\nLanguage content.\n"

    sections = parse_markdown_sections(filename="doc.md", body=markdown)

    assert sections[0].heading == "C#"
    assert sections[0].source_id == "doc.md#c"


def test_parse_markdown_sections_strips_atx_closing_hashes_after_space() -> None:
    markdown = "# Title ###\n\nBody.\n"

    sections = parse_markdown_sections(filename="doc.md", body=markdown)

    assert sections[0].heading == "Title"
    assert sections[0].source_id == "doc.md#title"
