from __future__ import annotations

import json

from app.graph.extraction import (
    CLUSTER_SYSTEM_PROMPT,
    DOCUMENT_SYSTEM_PROMPT,
    EDGE_KINDS,
    build_cluster_prompt,
    build_document_prompt,
    build_merge_prompt,
    parse_cluster_response,
    parse_document_response,
    parse_edges_response,
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
        concepts=[{"name": "Quorum", "summary": "多數決讀寫。"}],
        existing_cluster_names=["一致性"],
    )
    assert "Quorum" in cluster_prompt and "一致性" in cluster_prompt
    assert "多數決讀寫" in cluster_prompt  # summaries travel with the names


def test_document_prompt_excludes_entities_case_studies_and_toc() -> None:
    # Acceptance-run hardening: the prompt must steer the model away from
    # named entities, case-study scenarios, and table-of-contents sections.
    assert "transferable" in DOCUMENT_SYSTEM_PROMPT
    assert "companies" in DOCUMENT_SYSTEM_PROMPT
    assert "Airbnb" in DOCUMENT_SYSTEM_PROMPT and "Polymarket" in DOCUMENT_SYSTEM_PROMPT
    assert "案例" in DOCUMENT_SYSTEM_PROMPT
    assert "table-of-contents" in DOCUMENT_SYSTEM_PROMPT
    assert "extract nothing" in DOCUMENT_SYSTEM_PROMPT
    # the JSON contract is unchanged
    assert '"concepts"' in DOCUMENT_SYSTEM_PROMPT and '"edges"' in DOCUMENT_SYSTEM_PROMPT


def test_cluster_prompt_describes_incremental_assignment() -> None:
    # Clustering is incremental-only: the prompt assigns the GIVEN concepts to
    # existing-or-new clusters instead of regrouping the whole graph.
    assert "assign the given course concepts" in CLUSTER_SYSTEM_PROMPT.lower()
    assert "existing" in CLUSTER_SYSTEM_PROMPT
    assert "ONLY when no existing cluster fits" in CLUSTER_SYSTEM_PROMPT


def test_edge_kinds_constant() -> None:
    assert EDGE_KINDS == ("prerequisite", "part_of", "related")


def test_parse_document_response_keeps_and_canonicalizes_edges() -> None:
    allowed = {"doc.md#a", "doc.md#b"}
    raw = json.dumps(
        {
            "concepts": [
                {"name": "Beta", "summary": "b", "source_ids": ["doc.md#b"]},
                {"name": "Alpha", "summary": "a", "source_ids": ["doc.md#a"]},
            ],
            "edges": [
                {"source": "Beta", "target": "Alpha", "kind": "related"},
                {"source": "Alpha", "target": "Beta", "kind": "related"},
                {"source": "Beta", "target": "Alpha", "kind": "prerequisite"},
            ],
        }
    )

    extraction = parse_document_response(raw, allowed_source_ids=allowed, max_concepts=30)

    related = [edge for edge in extraction.edges if edge.kind == "related"]
    assert len(related) == 1  # swapped duplicate deduped after canonicalization
    assert (related[0].source_slug, related[0].target_slug) == ("alpha", "beta")
    prerequisite = [edge for edge in extraction.edges if edge.kind == "prerequisite"]
    assert len(prerequisite) == 1
    assert (prerequisite[0].source_slug, prerequisite[0].target_slug) == ("beta", "alpha")


def test_parse_edges_response_canonicalizes_consistently() -> None:
    raw = json.dumps({"edges": [{"source": "Beta", "target": "Alpha", "kind": "part_of"}]})

    edges = parse_edges_response(raw, known_slugs={"alpha", "beta"}, max_edges=10)

    assert len(edges) == 1
    assert edges[0].source_slug == "alpha"
    assert edges[0].target_slug == "beta"
    assert edges[0].kind == "part_of"


def test_parse_edges_response_caps_edges() -> None:
    raw = json.dumps(
        {
            "edges": [
                {"source": f"c{i}", "target": f"c{i+1}", "kind": "prerequisite"}
                for i in range(50)
            ]
        }
    )

    edges = parse_edges_response(
        raw, known_slugs={f"c{i}" for i in range(51)}, max_edges=10
    )

    assert len(edges) == 10


def test_parse_document_response_handles_fenced_json() -> None:
    allowed = {"doc.md#a"}
    inner = json.dumps(
        {
            "concepts": [{"name": "Alpha", "summary": "a", "source_ids": ["doc.md#a"]}],
            "edges": [],
        }
    )
    raw = f"```json\n{inner}\n```"

    extraction = parse_document_response(raw, allowed_source_ids=allowed, max_concepts=30)

    assert len(extraction.concepts) == 1
    assert extraction.concepts[0].slug == "alpha"
