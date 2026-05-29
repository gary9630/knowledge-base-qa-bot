from app.indexing.frontmatter import parse_product_frontmatter


def test_parse_product_frontmatter_extracts_importer_metadata() -> None:
    metadata = parse_product_frontmatter(
        "---\n"
        'source_original: "raw/course guide.md"\n'
        "source_type: imported\n"
        "imported_at: 2026-05-26T12:00:00+00:00\n"
        "---\n\n"
        "# Course Guide\n"
    )

    assert metadata == {
        "source_original": "raw/course guide.md",
        "source_type": "imported",
        "imported_at": "2026-05-26T12:00:00+00:00",
    }


def test_parse_product_frontmatter_extracts_canonical_source_metadata() -> None:
    metadata = parse_product_frontmatter(
        "---\n"
        "source_type: announcement\n"
        "source_priority: 40\n"
        "visibility: staff\n"
        "published_at: 2026-05-26\n"
        "---\n\n"
        "# Course Notice\n"
    )

    assert metadata == {
        "source_type": "announcement",
        "source_priority": "40",
        "visibility": "staff",
        "published_at": "2026-05-26",
    }


def test_parse_product_frontmatter_ignores_thematic_break_prose() -> None:
    metadata = parse_product_frontmatter(
        "---\n"
        "Note: this is prose, not importer metadata.\n"
        "---\n\n"
        "# Policy\n"
    )

    assert metadata == {}
