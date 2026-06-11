"""Seed script for the concept graph.

Reads a curated JSON dataset and loads it into the DB, writing
ConceptExtractionState for EVERY active document (cited or not) so the
incremental extraction pipeline skips them on the next run. Seeded concepts
carry origin="seed", which exempts them from the pipeline's orphan pruning.

Usage:
    uv run --python 3.12 python -m scripts.seed_concept_graph \\
        --file docs/plans/2026-06-11-concept-graph-seed.json

    # validation only, no writes:
    uv run --python 3.12 python -m scripts.seed_concept_graph \\
        --file docs/plans/2026-06-11-concept-graph-seed.json --dry-run

    # wipe-and-replace (removes zombie concepts/edges from previous runs):
    uv run --python 3.12 python -m scripts.seed_concept_graph \\
        --file docs/plans/2026-06-11-concept-graph-seed.json --replace
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.document_lifecycle import active_document_filter
from app.graph import SEED_ORIGIN
from app.graph.extraction import EDGE_KINDS
from app.models.tables import (
    Concept,
    ConceptCluster,
    ConceptEdge,
    ConceptExtractionState,
    ConceptSource,
    Document,
    Section,
)

# ---------------------------------------------------------------------------
# Pure data structures
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SeedCluster:
    name: str
    position: int


@dataclass(frozen=True)
class SeedConcept:
    name: str
    slug: str
    summary: str
    aliases: list[str]
    cluster: str  # cluster name (must exist in clusters list)
    source_ids: list[str]


@dataclass(frozen=True)
class SeedEdge:
    source: str  # concept slug
    target: str  # concept slug
    kind: str


@dataclass(frozen=True)
class SeedGraph:
    clusters: list[SeedCluster]
    concepts: list[SeedConcept]
    edges: list[SeedEdge]


# ---------------------------------------------------------------------------
# Pure validation/parsing
# ---------------------------------------------------------------------------


def parse_seed_graph(payload: dict[str, Any]) -> SeedGraph:  # noqa: C901
    """Validate *payload* and return a :class:`SeedGraph`.

    Raises :class:`ValueError` with a specific message on any violation.
    """
    version = payload.get("version")
    if version != 1:
        raise ValueError(f"Unsupported seed dataset version: {version!r}. Expected 1.")

    # --- clusters -----------------------------------------------------------
    raw_clusters = payload.get("clusters", [])
    if not isinstance(raw_clusters, list):
        raise ValueError("'clusters' must be a list.")
    clusters: list[SeedCluster] = []
    seen_cluster_names: set[str] = set()
    for idx, item in enumerate(raw_clusters):
        if not isinstance(item, dict):
            raise ValueError(f"clusters[{idx}] is not an object.")
        name = item.get("name")
        position = item.get("position", 0)
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"clusters[{idx}].name is missing or empty.")
        if not isinstance(position, int):
            raise ValueError(f"clusters[{idx}].position must be an integer.")
        if name in seen_cluster_names:
            raise ValueError(f"Duplicate cluster name: {name!r}.")
        seen_cluster_names.add(name)
        clusters.append(SeedCluster(name=name, position=position))

    # --- concepts -----------------------------------------------------------
    raw_concepts = payload.get("concepts", [])
    if not isinstance(raw_concepts, list):
        raise ValueError("'concepts' must be a list.")
    concepts: list[SeedConcept] = []
    seen_slugs: set[str] = set()
    for idx, item in enumerate(raw_concepts):
        if not isinstance(item, dict):
            raise ValueError(f"concepts[{idx}] is not an object.")
        name = item.get("name")
        slug = item.get("slug")
        summary = item.get("summary")
        aliases = item.get("aliases", [])
        cluster_name = item.get("cluster")
        source_ids = item.get("source_ids")

        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"concepts[{idx}].name is missing or empty.")
        if not isinstance(slug, str) or not slug.strip():
            raise ValueError(f"concepts[{idx}].slug is missing or empty.")
        if not isinstance(summary, str) or not summary.strip():
            raise ValueError(f"concepts[{idx}].summary is missing or empty.")
        if not isinstance(aliases, list):
            raise ValueError(f"concepts[{idx}].aliases must be a list.")
        for alias_idx, alias in enumerate(aliases):
            if not isinstance(alias, str):
                raise ValueError(
                    f"concepts[{idx}].aliases[{alias_idx}] must be a string, "
                    f"got {type(alias).__name__!r}."
                )
        if not isinstance(cluster_name, str) or not cluster_name.strip():
            raise ValueError(f"concepts[{idx}].cluster is missing or empty.")
        if cluster_name not in seen_cluster_names:
            raise ValueError(
                f"concepts[{idx}] references unknown cluster name: {cluster_name!r}."
            )
        if not isinstance(source_ids, list) or len(source_ids) == 0:
            raise ValueError(
                f"concepts[{idx}] ({slug!r}) must have at least one source_id in source_ids."
            )

        # Duplicate source_ids within a concept would silently collapse into one
        # ConceptSource row; reject them so the dataset stays canonical.
        seen_sids: set[str] = set()
        for sid in source_ids:
            if sid in seen_sids:
                raise ValueError(
                    f"Duplicate source_id {sid!r} in concept {slug!r} (concepts[{idx}])."
                )
            seen_sids.add(sid)

        if slug in seen_slugs:
            raise ValueError(
                f"Duplicate concept slug: {slug!r} (concepts[{idx}])."
            )
        seen_slugs.add(slug)
        concepts.append(
            SeedConcept(
                name=name.strip(),
                slug=slug.strip(),
                summary=summary.strip(),
                aliases=list(aliases),
                cluster=cluster_name.strip(),
                source_ids=list(source_ids),
            )
        )

    # --- edges --------------------------------------------------------------
    raw_edges = payload.get("edges", [])
    if not isinstance(raw_edges, list):
        raise ValueError("'edges' must be a list.")
    edges: list[SeedEdge] = []
    seen_edge_keys: set[tuple[str, str, str]] = set()
    for idx, item in enumerate(raw_edges):
        if not isinstance(item, dict):
            raise ValueError(f"edges[{idx}] is not an object.")
        source = item.get("source")
        target = item.get("target")
        kind = item.get("kind")
        if not isinstance(source, str) or not source.strip():
            raise ValueError(f"edges[{idx}].source is missing or empty.")
        if not isinstance(target, str) or not target.strip():
            raise ValueError(f"edges[{idx}].target is missing or empty.")
        if not isinstance(kind, str) or not kind.strip():
            raise ValueError(f"edges[{idx}].kind is missing or empty.")

        if kind not in EDGE_KINDS:
            raise ValueError(
                f"edges[{idx}] has unknown edge kind: {kind!r}. "
                f"Allowed: {EDGE_KINDS!r}."
            )
        if source == target:
            raise ValueError(
                f"edges[{idx}] is a self-loop: source and target are both {source!r}."
            )
        if source not in seen_slugs:
            raise ValueError(
                f"edges[{idx}].source references unknown concept slug: {source!r}."
            )
        if target not in seen_slugs:
            raise ValueError(
                f"edges[{idx}].target references unknown concept slug: {target!r}."
            )

        # Canonicalize undirected kinds by slug ordering
        canon_source, canon_target = source, target
        if kind != "prerequisite" and canon_source > canon_target:
            canon_source, canon_target = canon_target, canon_source

        key = (canon_source, canon_target, kind)
        if key in seen_edge_keys:
            raise ValueError(
                f"Duplicate edge after canonicalization: "
                f"({canon_source!r}, {canon_target!r}, {kind!r}) at edges[{idx}]."
            )
        seen_edge_keys.add(key)
        edges.append(SeedEdge(source=canon_source, target=canon_target, kind=kind))

    return SeedGraph(clusters=clusters, concepts=concepts, edges=edges)


# ---------------------------------------------------------------------------
# DB application
# ---------------------------------------------------------------------------


def apply_seed_graph(
    session: Session,
    seed: SeedGraph,
    *,
    strict: bool = True,
    replace: bool = False,
) -> dict[str, int]:
    """Apply *seed* to the database.

    - Resolves ``source_ids`` → :class:`Section` rows via a single IN query.
    - In strict mode, raises :class:`ValueError` listing every unknown source_id
      as ``concept-slug: unknown-source-id``, one per line.
    - When *replace* is True, all existing concept graph rows are deleted
      (concept_sources, concept_edges, concept_extraction_state, concepts,
      concept_clusters — in FK-safe order) before applying the seed.
    - Upserts clusters by name (update position on conflict).
    - Upserts concepts by slug (update name/summary/aliases/cluster on conflict);
      seeded concepts get ``origin="seed"`` on create AND update so the
      extraction pipeline never prunes them.
    - Replaces each seeded concept's :class:`ConceptSource` rows.
    - Inserts edges idempotently (pre-checks existing triplets).
    - Writes/updates :class:`ConceptExtractionState` for EVERY active document
      (cited or not) using the document's CURRENT ``content_hash`` — uncited
      documents (e.g. overviews) would otherwise stay "pending" and get
      junk-extracted by the first worker run.

    Returns a dict of counts:
    ``{"clusters_created": N, "clusters_updated": N,
       "concepts_created": N, "concepts_updated": N,
       "edges": N, "sources": N, "extraction_states": N}``

    Does **not** commit — the caller (main / test) owns the transaction.
    """
    # Collect all source_ids referenced by this seed
    all_source_ids: set[str] = {sid for concept in seed.concepts for sid in concept.source_ids}

    # One IN query to resolve them all
    section_rows: list[Section] = list(
        session.scalars(select(Section).where(Section.source_id.in_(all_source_ids)))
    )
    resolved_source_map: dict[str, Section] = {s.source_id: s for s in section_rows}

    # Check for unknown source_ids — grouped per concept for actionable errors
    unknown_by_concept: dict[str, list[str]] = {}
    for concept in seed.concepts:
        bad = [sid for sid in concept.source_ids if sid not in resolved_source_map]
        if bad:
            unknown_by_concept[concept.slug] = bad

    if unknown_by_concept:
        if strict:
            lines = "\n".join(
                f"  {slug}: {sid}"
                for slug, sids in sorted(unknown_by_concept.items())
                for sid in sids
            )
            raise ValueError(
                f"Unknown source_id(s) not found in sections table:\n{lines}"
            )
        # non-strict: silently skip unknown ids (they'll just not create sources)

    # --- Replace mode: wipe all existing concept graph data ------------------
    if replace:
        # Delete in FK-safe order:
        # 1. concept_extraction_state (FK → documents, independent of concepts)
        session.execute(delete(ConceptExtractionState))
        # 2. concept_sources (FK → concepts + sections, cascade="all, delete-orphan"
        #    on Concept.sources, but explicit delete is cleaner here)
        session.execute(delete(ConceptSource))
        # 3. concept_edges (FK → concepts with ondelete="CASCADE")
        session.execute(delete(ConceptEdge))
        # 4. concepts (FK → concept_clusters with ondelete="SET NULL")
        session.execute(delete(Concept))
        # 5. concept_clusters (now safe — all concepts referencing them are gone)
        session.execute(delete(ConceptCluster))
        session.flush()

    # Extraction state covers EVERY active document — not just cited ones —
    # so the incremental pipeline treats the whole current corpus as extracted.
    doc_id_to_hash: dict[UUID, str] = {
        document.id: document.content_hash
        for document in session.scalars(select(Document).where(active_document_filter()))
    }

    # --- Upsert clusters ------------------------------------------------------
    cluster_name_to_obj: dict[str, ConceptCluster] = {}
    clusters_created = 0
    clusters_updated = 0
    for seed_cluster in seed.clusters:
        existing_cluster = session.scalar(
            select(ConceptCluster).where(ConceptCluster.name == seed_cluster.name)
        )
        if existing_cluster is None:
            cluster_obj = ConceptCluster(name=seed_cluster.name, position=seed_cluster.position)
            session.add(cluster_obj)
            session.flush()
            clusters_created += 1
        else:
            existing_cluster.position = seed_cluster.position
            cluster_obj = existing_cluster
            session.flush()
            clusters_updated += 1
        cluster_name_to_obj[seed_cluster.name] = cluster_obj

    # --- Upsert concepts ------------------------------------------------------
    concept_slug_to_obj: dict[str, Concept] = {}
    concepts_created = 0
    concepts_updated = 0
    for seed_concept in seed.concepts:
        maybe_cluster = cluster_name_to_obj.get(seed_concept.cluster)
        cluster_id = maybe_cluster.id if maybe_cluster is not None else None

        existing_concept = session.scalar(
            select(Concept).where(Concept.slug == seed_concept.slug)
        )
        if existing_concept is None:
            concept_obj = Concept(
                name=seed_concept.name,
                slug=seed_concept.slug,
                summary=seed_concept.summary,
                aliases=seed_concept.aliases,
                cluster_id=cluster_id,
                origin=SEED_ORIGIN,
            )
            session.add(concept_obj)
            session.flush()
            concepts_created += 1
        else:
            existing_concept.name = seed_concept.name
            existing_concept.summary = seed_concept.summary
            existing_concept.aliases = seed_concept.aliases
            existing_concept.cluster_id = cluster_id
            existing_concept.origin = SEED_ORIGIN
            concept_obj = existing_concept
            session.flush()
            concepts_updated += 1
        concept_slug_to_obj[seed_concept.slug] = concept_obj

    # --- Replace concept sources --------------------------------------------
    sources_count = 0
    for seed_concept in seed.concepts:
        concept_obj = concept_slug_to_obj[seed_concept.slug]

        # Delete existing sources for this concept
        existing_sources = list(
            session.scalars(
                select(ConceptSource).where(ConceptSource.concept_id == concept_obj.id)
            )
        )
        for src in existing_sources:
            session.delete(src)
        session.flush()

        # Insert new sources
        for source_id in seed_concept.source_ids:
            maybe_section = resolved_source_map.get(source_id)
            if maybe_section is None:
                continue  # skip unknown (already handled above in strict mode)
            session.add(ConceptSource(concept_id=concept_obj.id, section_id=maybe_section.id))
            sources_count += 1
        session.flush()

    # --- Insert edges idempotently ------------------------------------------
    edges_count = 0
    for seed_edge in seed.edges:
        source_concept = concept_slug_to_obj.get(seed_edge.source)
        target_concept = concept_slug_to_obj.get(seed_edge.target)
        if source_concept is None or target_concept is None:
            continue

        existing_edge = session.scalar(
            select(ConceptEdge).where(
                ConceptEdge.source_concept_id == source_concept.id,
                ConceptEdge.target_concept_id == target_concept.id,
                ConceptEdge.kind == seed_edge.kind,
            )
        )
        if existing_edge is None:
            session.add(
                ConceptEdge(
                    source_concept_id=source_concept.id,
                    target_concept_id=target_concept.id,
                    kind=seed_edge.kind,
                )
            )
        # always count: represents edges processed (created-or-already-existing)
        edges_count += 1
        session.flush()

    # --- Write/update ConceptExtractionState --------------------------------
    extraction_states_count = 0
    for doc_id, content_hash in doc_id_to_hash.items():
        existing_state = session.scalar(
            select(ConceptExtractionState).where(
                ConceptExtractionState.document_id == doc_id
            )
        )
        if existing_state is None:
            session.add(
                ConceptExtractionState(document_id=doc_id, content_hash=content_hash)
            )
        else:
            existing_state.content_hash = content_hash
        extraction_states_count += 1
    session.flush()

    return {
        "clusters_created": clusters_created,
        "clusters_updated": clusters_updated,
        "concepts_created": concepts_created,
        "concepts_updated": concepts_updated,
        "edges": edges_count,
        "sources": sources_count,
        "extraction_states": extraction_states_count,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    """Entry point for the seed CLI.

    --file     Required path to the JSON seed dataset.
    --dry-run  Parse + validate against the DB without writing.
    --replace  Delete all existing concept graph data before applying.
    """
    # Import here to avoid circular imports at test-collection time
    import json

    from app.core.database import SessionLocal

    parser = argparse.ArgumentParser(
        description="Seed the concept graph from a curated JSON dataset."
    )
    parser.add_argument(
        "--file",
        type=Path,
        required=True,
        help="Path to the JSON seed dataset.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Parse and validate without writing to the database.",
    )
    parser.add_argument(
        "--replace",
        action="store_true",
        default=False,
        help="Delete all existing concept graph data before applying the seed.",
    )
    namespace = parser.parse_args(argv)

    # 1. Read + parse
    try:
        raw_text = namespace.file.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"Error reading file {namespace.file}: {exc}", file=sys.stderr)
        return 1

    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        print(f"Error parsing JSON: {exc}", file=sys.stderr)
        return 1

    try:
        seed = parse_seed_graph(payload)
    except ValueError as exc:
        print(f"Invalid seed dataset: {exc}", file=sys.stderr)
        return 1

    print(
        f"Parsed: {len(seed.clusters)} clusters, "
        f"{len(seed.concepts)} concepts, "
        f"{len(seed.edges)} edges."
    )

    if namespace.dry_run:
        # Run apply_seed_graph inside a transaction and roll back — this
        # exercises the real validation path while guaranteeing zero writes.
        try:
            with SessionLocal() as session:
                try:
                    apply_seed_graph(session, seed, strict=True)
                except ValueError as exc:
                    print(
                        f"Dry-run: validation failed:\n{exc}",
                        file=sys.stderr,
                    )
                    return 1
                finally:
                    # Always roll back — never commit in dry-run mode
                    session.rollback()
        except Exception as exc:
            print(f"Dry-run: unexpected error: {exc}", file=sys.stderr)
            return 1

        print(
            "Dry-run: all source_ids resolved and seed validated. No issues found."
        )
        return 0

    # 2. Apply
    try:
        with SessionLocal() as session:
            counts = apply_seed_graph(session, seed, strict=True, replace=namespace.replace)
            session.commit()
    except ValueError as exc:
        print(f"Error applying seed graph: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"Unexpected error: {exc}", file=sys.stderr)
        return 1

    print(
        f"Seeded concept graph: "
        f"{counts['clusters_created']} clusters created, "
        f"{counts['clusters_updated']} updated; "
        f"{counts['concepts_created']} concepts created, "
        f"{counts['concepts_updated']} updated; "
        f"{counts['edges']} edges, "
        f"{counts['sources']} sources, "
        f"{counts['extraction_states']} extraction state(s)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
