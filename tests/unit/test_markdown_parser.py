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
