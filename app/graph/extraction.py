from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Protocol

EDGE_KINDS = ("prerequisite", "part_of", "related")

DOCUMENT_SYSTEM_PROMPT = (
    "You extract a concept graph from course material for a learner-facing knowledge "
    "map. Concepts are course-level ideas (e.g. 'Consistent Hashing', 'Quorum'), named "
    "in the language the material uses (Traditional Chinese or English technical "
    "terms). Each concept needs a 1-2 sentence Traditional Chinese summary and the "
    "source_ids of the sections that teach it. Edges connect concepts in THIS "
    'document: kind is one of "prerequisite" (source should be learned before '
    'target), "part_of" (source is a component of target), "related". '
    'Return JSON: {"concepts": [{"name": str, "summary": str, "source_ids": [str]}], '
    '"edges": [{"source": str, "target": str, "kind": str}]}'
)

MERGE_SYSTEM_PROMPT = (
    "You deduplicate concept names for a knowledge graph. Given NEW concept names and "
    "EXISTING canonical names, identify new names that mean the same concept as an "
    'existing one. Return JSON: {"merges": [{"from": str, "into": str}]} where "from" '
    'is a NEW name and "into" is an EXISTING name. Only merge true synonyms/aliases.'
)

CLUSTER_SYSTEM_PROMPT = (
    "You group course concepts into 10-20 named topic clusters for a learner-facing "
    "knowledge map. Cluster names are short Traditional Chinese topic labels. Reuse "
    "the provided existing cluster names wherever they still fit. Every concept must "
    'appear in exactly one cluster. Return JSON: {"clusters": [{"name": str, '
    '"concepts": [str]}]}'
)

CLUSTER_EDGES_SYSTEM_PROMPT = (
    "You connect concepts within one topic cluster of a course knowledge map. "
    "Propose edges among ONLY the provided concepts: kind is one of "
    '"prerequisite", "part_of", "related". Return JSON: {"edges": '
    '[{"source": str, "target": str, "kind": str}]}'
)


class ChatCaller(Protocol):
    def complete(self, *, system: str, user: str) -> str: ...


@dataclass(frozen=True)
class ExtractedConcept:
    name: str
    slug: str
    summary: str
    source_ids: tuple[str, ...]


@dataclass(frozen=True)
class ExtractedEdge:
    source_slug: str
    target_slug: str
    kind: str


@dataclass(frozen=True)
class DocumentExtraction:
    concepts: list[ExtractedConcept] = field(default_factory=list)
    edges: list[ExtractedEdge] = field(default_factory=list)


_SLUG_STRIP_RE = re.compile(r"[^\w㐀-鿿]+", re.UNICODE)


def slugify_concept(name: str) -> str:
    normalized = unicodedata.normalize("NFKC", name).strip().casefold()
    slug = _SLUG_STRIP_RE.sub("-", normalized).strip("-")
    return slug or "concept"


def build_document_prompt(
    *,
    filename: str,
    sections: list[tuple[str, str, str]],
    max_concepts: int,
) -> str:
    payload = json.dumps(
        [
            {"source_id": source_id, "heading": heading, "content": body}
            for source_id, heading, body in sections
        ],
        ensure_ascii=False,
    )
    return (
        f"Extract at most {max_concepts} concepts from these sections of {filename}:\n"
        f"{payload}"
    )


def build_merge_prompt(*, new_names: list[str], existing_names: list[str]) -> str:
    return json.dumps(
        {"new": sorted(new_names), "existing": sorted(existing_names)},
        ensure_ascii=False,
    )


def build_cluster_prompt(
    *,
    concept_names: list[str],
    existing_cluster_names: list[str],
) -> str:
    return json.dumps(
        {"concepts": sorted(concept_names), "existing_clusters": sorted(existing_cluster_names)},
        ensure_ascii=False,
    )


def build_cluster_edges_prompt(*, cluster_name: str, concepts: list[dict[str, str]]) -> str:
    return (
        f"Concepts in topic cluster {cluster_name} (name + summary):\n"
        + json.dumps(concepts, ensure_ascii=False)
    )


def parse_document_response(
    raw: str,
    *,
    allowed_source_ids: set[str],
    max_concepts: int,
) -> DocumentExtraction:
    payload = _json_object(raw)
    raw_concepts = payload.get("concepts")
    raw_edges = payload.get("edges")

    concepts: list[ExtractedConcept] = []
    seen_slugs: set[str] = set()
    for item in raw_concepts if isinstance(raw_concepts, list) else []:
        if len(concepts) >= max_concepts:
            break
        concept = _parse_concept(item, allowed_source_ids)
        if concept is None or concept.slug in seen_slugs:
            continue
        seen_slugs.add(concept.slug)
        concepts.append(concept)

    edges = _parse_edges(raw_edges, known_slugs=seen_slugs, max_edges=max_concepts * 2)
    return DocumentExtraction(concepts=concepts, edges=edges)


def parse_edges_response(raw: str, *, known_slugs: set[str], max_edges: int) -> list[ExtractedEdge]:
    payload = _json_object(raw)
    return _parse_edges(payload.get("edges"), known_slugs=known_slugs, max_edges=max_edges)


def parse_merge_response(
    raw: str,
    *,
    new_names: set[str],
    existing_names: set[str],
) -> dict[str, str]:
    payload = _json_object(raw)
    raw_merges = payload.get("merges")
    mapping: dict[str, str] = {}
    for item in raw_merges if isinstance(raw_merges, list) else []:
        if not isinstance(item, dict):
            continue
        source = item.get("from")
        target = item.get("into")
        if (
            isinstance(source, str)
            and isinstance(target, str)
            and source in new_names
            and target in existing_names
            and source != target
        ):
            mapping[source] = target
    return mapping


def parse_cluster_response(raw: str, *, concept_names: set[str]) -> dict[str, str]:
    payload = _json_object(raw)
    raw_clusters = payload.get("clusters")
    assignments: dict[str, str] = {}
    for item in raw_clusters if isinstance(raw_clusters, list) else []:
        if not isinstance(item, dict):
            continue
        cluster_name = item.get("name")
        members = item.get("concepts")
        if not isinstance(cluster_name, str) or not cluster_name.strip():
            continue
        for member in members if isinstance(members, list) else []:
            if isinstance(member, str) and member in concept_names and member not in assignments:
                assignments[member] = cluster_name.strip()
    return assignments


def _parse_concept(item: object, allowed_source_ids: set[str]) -> ExtractedConcept | None:
    if not isinstance(item, dict):
        return None
    name = item.get("name")
    summary = item.get("summary")
    source_ids = item.get("source_ids")
    if not isinstance(name, str) or not name.strip():
        return None
    if not isinstance(summary, str) or not summary.strip():
        return None
    if not isinstance(source_ids, list):
        return None
    valid_ids = tuple(
        source_id
        for source_id in source_ids
        if isinstance(source_id, str) and source_id in allowed_source_ids
    )
    if not valid_ids:
        return None
    return ExtractedConcept(
        name=name.strip(),
        slug=slugify_concept(name),
        summary=summary.strip(),
        source_ids=valid_ids,
    )


def _parse_edges(
    raw_edges: object,
    *,
    known_slugs: set[str],
    max_edges: int,
) -> list[ExtractedEdge]:
    edges: list[ExtractedEdge] = []
    seen: set[tuple[str, str, str]] = set()
    for item in raw_edges if isinstance(raw_edges, list) else []:
        if len(edges) >= max_edges:
            break
        if not isinstance(item, dict):
            continue
        source = item.get("source")
        target = item.get("target")
        kind = item.get("kind")
        if not (isinstance(source, str) and isinstance(target, str) and isinstance(kind, str)):
            continue
        source_slug = slugify_concept(source)
        target_slug = slugify_concept(target)
        if kind not in EDGE_KINDS or source_slug == target_slug:
            continue
        if source_slug not in known_slugs or target_slug not in known_slugs:
            continue
        if kind != "prerequisite" and source_slug > target_slug:
            source_slug, target_slug = target_slug, source_slug  # normalize undirected
        key = (source_slug, target_slug, kind)
        if key in seen:
            continue
        seen.add(key)
        edges.append(ExtractedEdge(source_slug=source_slug, target_slug=target_slug, kind=kind))
    return edges


def _json_object(raw: str) -> dict[str, Any]:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}
