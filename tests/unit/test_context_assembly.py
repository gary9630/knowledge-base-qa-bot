from __future__ import annotations

from uuid import uuid4

from app.answer.context_assembly import (
    CandidateEntry,
    order_for_output,
    select_within_budget,
)


def _entry(
    *,
    source_id: str,
    filename: str = "doc.md",
    is_hit: bool = True,
    score: float | None = 0.9,
    neighbor_distance: int = 0,
    anchor_score: float = 0.9,
    token_count: int = 100,
    position: int | None = 0,
) -> CandidateEntry:
    return CandidateEntry(
        section_id=uuid4(),
        source_id=source_id,
        filename=filename,
        heading=source_id,
        body_md="x " * token_count,
        score=score,
        is_hit=is_hit,
        neighbor_distance=neighbor_distance,
        anchor_score=anchor_score,
        token_count=token_count,
        position=position,
    )


def test_select_within_budget_prioritizes_hits_then_close_neighbors() -> None:
    hit = _entry(source_id="doc.md#hit", token_count=100)
    near = _entry(
        source_id="doc.md#near",
        is_hit=False,
        score=None,
        neighbor_distance=1,
        token_count=100,
        position=1,
    )
    far = _entry(
        source_id="doc.md#far",
        is_hit=False,
        score=None,
        neighbor_distance=2,
        token_count=100,
        position=2,
    )

    selection = select_within_budget([hit, far, near], token_budget=210)

    selected_ids = [entry.source_id for entry in selection.selected]
    assert selected_ids == ["doc.md#hit", "doc.md#near"]
    assert selection.dropped_count == 1
    assert selection.tokens_used == 200


def test_select_within_budget_always_keeps_top_hit_with_truncation() -> None:
    huge_hit = _entry(source_id="doc.md#huge", token_count=20_000)

    selection = select_within_budget([huge_hit], token_budget=1000)

    assert len(selection.selected) == 1
    assert selection.truncated_count == 1
    assert selection.selected[0].token_count <= 1000


def test_select_within_budget_orders_hits_by_score() -> None:
    low = _entry(source_id="doc.md#low", score=0.2, anchor_score=0.2, token_count=600)
    high = _entry(source_id="doc.md#high", score=0.9, anchor_score=0.9, token_count=600)

    selection = select_within_budget([low, high], token_budget=700)

    assert [entry.source_id for entry in selection.selected] == ["doc.md#high"]


def test_order_for_output_groups_by_document_in_reading_order() -> None:
    a_hit = _entry(source_id="a.md#2", filename="a.md", score=0.5, anchor_score=0.5,
                   position=2)
    a_neighbor = _entry(
        source_id="a.md#1",
        filename="a.md",
        is_hit=False,
        score=None,
        neighbor_distance=1,
        anchor_score=0.5,
        position=1,
    )
    b_hit = _entry(source_id="b.md#0", filename="b.md", score=0.9, anchor_score=0.9,
                   position=0)

    ordered = order_for_output([a_hit, a_neighbor, b_hit])

    # b.md group first (higher best hit score), then a.md in position order
    assert [entry.source_id for entry in ordered] == ["b.md#0", "a.md#1", "a.md#2"]


def test_order_for_output_handles_null_positions() -> None:
    with_position = _entry(source_id="a.md#0", position=0)
    without_position = _entry(source_id="a.md#x", position=None, score=0.99,
                              anchor_score=0.99)

    ordered = order_for_output([without_position, with_position])

    assert {entry.source_id for entry in ordered} == {"a.md#0", "a.md#x"}
    assert ordered[-1].source_id == "a.md#x"  # null position sorts after positioned ones
