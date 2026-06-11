from __future__ import annotations

import json

from app.graph.extraction import (
    EDGE_KINDS,
    build_cluster_prompt,
    build_document_prompt,
    build_merge_prompt,
    parse_cluster_response,
    parse_document_response,
    parse_merge_response,
    slugify_concept,
)


def test_slugify_concept_handles_english_and_chinese() -> None:
    assert slugify_concept("Consistent Hashing") == "consistent-hashing"
    assert slugify_concept("一致性雜湊") == "一致性雜湊"
    assert slugify_concept("Read/Write Quorum!") == "read-write-quorum"


def test_parse_document_response_validates_and_caps() -> None:
    allowed = {"doc.md#sec-a", "doc.md#sec-b"}
    raw = json.dumps(
        {
            "concepts": [
                {
                    "name": "Quorum",
                    "summary": "多數決讀寫。",
                    "source_ids": ["doc.md#sec-a"],
                },
                {
                    "name": "Ghost",
                    "summary": "引用不存在的 section。",
                    "source_ids": ["doc.md#nope"],
                },
                {"name": "No summary", "source_ids": ["doc.md#sec-a"]},
            ],
            "edges": [
                {"source": "Quorum", "target": "Ghost", "kind": "related"},
                {"source": "Quorum", "target": "Quorum", "kind": "related"},
                {"source": "Quorum", "target": "Unknown", "kind": "banana"},
            ],
        }
    )

    extraction = parse_document_response(raw, allowed_source_ids=allowed, max_concepts=30)

    assert [concept.name for concept in extraction.concepts] == ["Quorum"]
    assert extraction.concepts[0].slug == "quorum"
    # edges referencing dropped/unknown concepts or invalid kinds are discarded;
    # self-edges are discarded
    assert extraction.edges == []


def test_parse_document_response_caps_concepts() -> None:
    allowed = {"doc.md#s"}
    raw = json.dumps(
        {
            "concepts": [
                {"name": f"C{index}", "summary": "x", "source_ids": ["doc.md#s"]}
                for index in range(40)
            ],
            "edges": [],
        }
    )

    extraction = parse_document_response(raw, allowed_source_ids=allowed, max_concepts=30)

    assert len(extraction.concepts) == 30


def test_parse_document_response_rejects_garbage() -> None:
    extraction = parse_document_response("not json", allowed_source_ids=set(), max_concepts=30)
    assert extraction.concepts == [] and extraction.edges == []


def test_parse_merge_response_maps_only_known_names() -> None:
    raw = json.dumps({"merges": [{"from": "一致性雜湊", "into": "Consistent Hashing"}]})

    mapping = parse_merge_response(
        raw,
        new_names={"一致性雜湊"},
        existing_names={"Consistent Hashing"},
    )

    assert mapping == {"一致性雜湊": "Consistent Hashing"}
    assert (
        parse_merge_response(raw, new_names={"其他"}, existing_names={"Consistent Hashing"}) == {}
    )


def test_parse_cluster_response_assigns_known_concepts_only() -> None:
    raw = json.dumps(
        {
            "clusters": [
                {"name": "快取", "concepts": ["Caching", "TTL", "Nope"]},
                {"name": "一致性", "concepts": ["Quorum"]},
            ]
        }
    )

    assignments = parse_cluster_response(raw, concept_names={"Caching", "TTL", "Quorum"})

    assert assignments == {"Caching": "快取", "TTL": "快取", "Quorum": "一致性"}


def test_prompts_contain_payloads() -> None:
    doc_prompt = build_document_prompt(
        filename="doc.md",
        sections=[("doc.md#sec-a", "標題A", "內容A")],
        max_concepts=30,
    )
    assert "doc.md#sec-a" in doc_prompt and "內容A" in doc_prompt

    merge_prompt = build_merge_prompt(new_names=["一致性雜湊"], existing_names=["Quorum"])
    assert "一致性雜湊" in merge_prompt and "Quorum" in merge_prompt

    cluster_prompt = build_cluster_prompt(
        concept_names=["Quorum"], existing_cluster_names=["一致性"]
    )
    assert "Quorum" in cluster_prompt and "一致性" in cluster_prompt


def test_edge_kinds_constant() -> None:
    assert EDGE_KINDS == ("prerequisite", "part_of", "related")
