from __future__ import annotations

import pytest

from scripts.seed_concept_graph import SeedGraph, parse_seed_graph


def _valid_payload() -> dict:  # type: ignore[type-arg]
    return {
        "version": 1,
        "clusters": [
            {"name": "快取", "position": 0},
            {"name": "一致性", "position": 1},
        ],
        "concepts": [
            {
                "name": "Consistent Hashing",
                "slug": "consistent-hashing",
                "summary": "把節點與鍵映射到同一個雜湊環，重新配置時只搬動少量資料。",
                "aliases": ["一致性雜湊"],
                "cluster": "快取",
                "source_ids": ["doc.md#section-a"],
            },
            {
                "name": "Sharding",
                "slug": "sharding",
                "summary": "資料水平切分。",
                "aliases": [],
                "cluster": "一致性",
                "source_ids": ["doc.md#section-b"],
            },
        ],
        "edges": [
            {"source": "consistent-hashing", "target": "sharding", "kind": "related"},
        ],
    }


def test_parse_seed_graph_valid_payload() -> None:
    payload = _valid_payload()
    seed = parse_seed_graph(payload)
    assert isinstance(seed, SeedGraph)
    assert len(seed.clusters) == 2
    assert len(seed.concepts) == 2
    assert len(seed.edges) == 1
    assert seed.clusters[0].name == "快取"
    assert seed.clusters[0].position == 0
    assert seed.concepts[0].slug == "consistent-hashing"
    assert seed.concepts[0].aliases == ["一致性雜湊"]
    assert seed.edges[0].source == "consistent-hashing"
    assert seed.edges[0].target == "sharding"
    assert seed.edges[0].kind == "related"


def test_parse_seed_graph_wrong_version_rejected() -> None:
    payload = _valid_payload()
    payload["version"] = 2
    with pytest.raises(ValueError, match="version"):
        parse_seed_graph(payload)


def test_parse_seed_graph_duplicate_slug_rejected() -> None:
    payload = _valid_payload()
    payload["concepts"].append(
        {
            "name": "Consistent Hashing Dupe",
            "slug": "consistent-hashing",  # duplicate slug
            "summary": "重複。",
            "aliases": [],
            "cluster": "快取",
            "source_ids": ["doc.md#section-a"],
        }
    )
    with pytest.raises(ValueError, match="[Dd]uplicate concept"):
        parse_seed_graph(payload)


def test_parse_seed_graph_unknown_edge_kind_rejected() -> None:
    payload = _valid_payload()
    payload["edges"] = [
        {"source": "consistent-hashing", "target": "sharding", "kind": "banana"}
    ]
    with pytest.raises(ValueError, match="edge kind|kind.*banana|banana"):
        parse_seed_graph(payload)


def test_parse_seed_graph_edge_unknown_slug_rejected() -> None:
    payload = _valid_payload()
    payload["edges"] = [
        {"source": "consistent-hashing", "target": "nonexistent-slug", "kind": "related"}
    ]
    with pytest.raises(ValueError, match="nonexistent-slug"):
        parse_seed_graph(payload)


def test_parse_seed_graph_self_loop_rejected() -> None:
    payload = _valid_payload()
    payload["edges"] = [
        {"source": "consistent-hashing", "target": "consistent-hashing", "kind": "related"}
    ]
    with pytest.raises(ValueError, match="self.loop|self-loop"):
        parse_seed_graph(payload)


def test_parse_seed_graph_empty_source_ids_rejected() -> None:
    payload = _valid_payload()
    payload["concepts"][0]["source_ids"] = []
    with pytest.raises(ValueError, match="source_ids"):
        parse_seed_graph(payload)


def test_parse_seed_graph_unknown_cluster_name_rejected() -> None:
    payload = _valid_payload()
    payload["concepts"][0]["cluster"] = "NonexistentCluster"
    with pytest.raises(ValueError, match="NonexistentCluster"):
        parse_seed_graph(payload)


def test_parse_seed_graph_undirected_duplicate_after_canonicalization_rejected() -> None:
    payload = _valid_payload()
    # "related" is undirected: (a, b) and (b, a) should canonicalize to same key
    payload["edges"] = [
        {"source": "consistent-hashing", "target": "sharding", "kind": "related"},
        {"source": "sharding", "target": "consistent-hashing", "kind": "related"},
    ]
    with pytest.raises(ValueError, match="[Dd]uplicate edge.*canonicalization"):
        parse_seed_graph(payload)
