from app.indexing.citations import citation_for


def test_citation_for_uses_filename_and_heading_slug() -> None:
    assert citation_for("refund_policy.md", "Refund Timeline") == "refund_policy.md#refund-timeline"


def test_citation_for_preserves_cjk_heading_slug() -> None:
    assert citation_for("常見問題FAQ.md", "課程網站") == "常見問題FAQ.md#課程網站"
