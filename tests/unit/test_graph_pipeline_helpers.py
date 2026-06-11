from __future__ import annotations

from typing import cast

from sqlalchemy.orm import Session

from app.graph.extraction import ChatCaller
from app.graph.pipeline import GraphExtractionPipeline, _resolve_merge_mapping
from app.indexing.tokenization import count_tokens
from app.models.tables import Section

# -- _resolve_merge_mapping ----------------------------------------------------


def test_resolve_merge_mapping_resolves_simple_chain_to_terminal() -> None:
    assert _resolve_merge_mapping({"A": "B", "B": "C"}) == {"A": "C", "B": "C"}


def test_resolve_merge_mapping_drops_two_name_cycle() -> None:
    assert _resolve_merge_mapping({"A": "B", "B": "A"}) == {}


def test_resolve_merge_mapping_drops_self_mapping() -> None:
    assert _resolve_merge_mapping({"A": "A"}) == {}


def test_resolve_merge_mapping_resolves_long_chain() -> None:
    mapping = {"A": "B", "B": "C", "C": "D", "D": "E", "E": "F"}
    assert _resolve_merge_mapping(mapping) == {name: "F" for name in mapping}


def test_resolve_merge_mapping_hop_cap_terminates_on_larger_cycle() -> None:
    # Every hop stays inside the mapping, so without the len(mapping) hop cap the
    # walk would never leave the cycle; capped entries are dropped, not merged.
    assert _resolve_merge_mapping({"A": "B", "B": "C", "C": "A"}) == {}


# -- _batch_sections -----------------------------------------------------------


def _pipeline(token_budget: int) -> GraphExtractionPipeline:
    # _batch_sections only reads section bodies and the token budget; the session
    # and caller are never touched, so inert stand-ins are sufficient.
    return GraphExtractionPipeline(
        session=cast(Session, object()),
        caller=cast(ChatCaller, object()),
        max_concepts_per_doc=10,
        token_budget=token_budget,
    )


def _section(body_md: str) -> Section:
    return Section(body_md=body_md)


def test_batch_sections_keeps_sections_within_budget_in_one_batch() -> None:
    sections = [_section("alpha beta"), _section("gamma delta")]
    budget = sum(count_tokens(section.body_md) for section in sections)

    assert _pipeline(budget)._batch_sections(sections) == [sections]


def test_batch_sections_isolates_oversized_section_in_its_own_batch() -> None:
    small = _section("tiny")
    big = _section("word " * 50)
    trailing = _section("tail")
    budget = count_tokens(small.body_md) + 1
    assert count_tokens(big.body_md) > budget  # guard: big really exceeds the budget

    batches = _pipeline(budget)._batch_sections([small, big, trailing])

    assert batches == [[small], [big], [trailing]]


def test_batch_sections_returns_single_oversized_section_alone() -> None:
    big = _section("word " * 50)

    assert _pipeline(1)._batch_sections([big]) == [[big]]
