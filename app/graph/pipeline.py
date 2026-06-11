from __future__ import annotations

from collections.abc import Iterable
from time import perf_counter
from typing import Any
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.document_lifecycle import active_document_filter
from app.graph import SEED_ORIGIN
from app.graph.extraction import (
    CLUSTER_EDGES_SYSTEM_PROMPT,
    CLUSTER_SYSTEM_PROMPT,
    DOCUMENT_SYSTEM_PROMPT,
    MERGE_SYSTEM_PROMPT,
    ChatCaller,
    DocumentExtraction,
    ExtractedConcept,
    build_cluster_edges_prompt,
    build_cluster_prompt,
    build_document_prompt,
    build_merge_prompt,
    parse_cluster_response,
    parse_document_response,
    parse_edges_response,
    parse_merge_response,
)
from app.indexing.tokenization import DEFAULT_TOKEN_ENCODING, count_tokens
from app.models.tables import (
    Concept,
    ConceptCluster,
    ConceptEdge,
    ConceptExtractionState,
    ConceptSource,
    Document,
    Section,
)
from app.provider_telemetry import (
    ProviderCallContext,
    ProviderCallRecord,
    ProviderCallStatus,
    ProviderUsage,
    completion_usage,
    response_request_id,
)

GRAPH_EXTRACTION_OPERATION = "graph_extraction"

_STATS_KEYS = (
    "documents_considered",
    "documents_extracted",
    "documents_failed",
    "concepts_created",
    "concepts_merged",
    "concepts_pruned",
    "edges_created",
    "clusters_total",
)


class GraphExtractionPipeline:
    """Incremental concept-graph extraction over the active document set.

    The pipeline never commits; the caller owns the transaction (matching
    ``IndexingService`` conventions). Internal flushes keep ids available.
    """

    def __init__(
        self,
        *,
        session: Session,
        caller: ChatCaller,
        max_concepts_per_doc: int,
        token_budget: int,
        encoding_name: str = DEFAULT_TOKEN_ENCODING,
    ) -> None:
        self._session = session
        self._caller = caller
        self._max_concepts_per_doc = max_concepts_per_doc
        self._token_budget = token_budget
        self._encoding_name = encoding_name

    def run(self) -> dict[str, Any]:
        """1) find active documents whose content_hash != extraction state (or no
        state); 2) per document: load sections ordered by position, batch them under
        token_budget (count_tokens over body_md), one LLM call per batch with
        DOCUMENT_SYSTEM_PROMPT + build_document_prompt, parse_document_response with
        allowed_source_ids = that document's section source_ids; failures (raised by
        caller) are caught per-document and recorded in stats["documents_failed"],
        leaving that document's previous state untouched; 3) global merge:
        deterministic match against existing concepts first — exact slug, then
        casefolded name, then casefolded alias — then ONE LLM call
        (MERGE_SYSTEM_PROMPT + build_merge_prompt) for remaining new names vs all
        existing canonical names + aliases; apply mapping (merged names become
        aliases on the canonical concept); upsert concepts (slug-keyed), replace
        each re-extracted document's concept_sources, insert edges (slug pairs ->
        concept ids, ON CONFLICT ignore via unique constraint + pre-check); 4) prune
        concepts whose concept_sources count is now zero, EXCEPT seed-origin
        (curated) concepts, which survive orphaning; 5) clustering is
        incremental-only: if any concept lacks a cluster, ONE LLM call
        (CLUSTER_SYSTEM_PROMPT + build_cluster_prompt) receives ONLY the
        unclustered concepts (name+summary) plus the existing cluster names and
        assigns each to an existing cluster or a newly named one; already-clustered
        concepts are never reassigned and clusters are never deleted; 6) for
        each cluster containing newly added concepts, ONE LLM call proposing edges
        (CLUSTER_EDGES_SYSTEM_PROMPT + build_cluster_edges_prompt, parsed via
        parse_edges_response over that cluster's slugs); 7) write/refresh
        ConceptExtractionState per successfully extracted
        document; return stats dict: documents_considered, documents_extracted,
        documents_failed, concepts_created, concepts_merged, concepts_pruned,
        edges_created, clusters_total, plus failures — a list of
        {"filename", "error_type"} dicts, one per failed document."""
        stats: dict[str, Any] = dict.fromkeys(_STATS_KEYS, 0)
        failures: list[dict[str, str]] = []
        stats["failures"] = failures

        considered, pending = self._pending_documents()
        stats["documents_considered"] = considered

        extractions: dict[UUID, DocumentExtraction] = {}
        document_sections: dict[UUID, list[Section]] = {}
        document_hashes: dict[UUID, str] = {}
        for document in pending:
            sections = self._document_sections(document.id)
            try:
                extraction = self._extract_document(document, sections)
            except Exception as error:
                failures.append(
                    {"filename": document.filename, "error_type": type(error).__name__}
                )
                continue
            extractions[document.id] = extraction
            document_sections[document.id] = sections
            document_hashes[document.id] = document.content_hash
            stats["documents_extracted"] += 1
        stats["documents_failed"] = len(failures)

        extracted_by_slug: dict[str, ExtractedConcept] = {}
        for extraction in extractions.values():
            for concept in extraction.concepts:
                extracted_by_slug.setdefault(concept.slug, concept)

        slug_to_concept = self._upsert_concepts(extracted_by_slug, stats)

        for document_id, extraction in extractions.items():
            self._replace_document_sources(
                sections=document_sections[document_id],
                extraction=extraction,
                slug_to_concept=slug_to_concept,
            )

        # Existing edge identity keys are loaded once per run and updated in
        # memory as edges are inserted, so later phases keep deduping without
        # re-scanning the table.
        edge_keys = self._load_edge_keys()
        stats["edges_created"] += self._insert_edges(
            _document_edge_triples(extractions.values(), slug_to_concept),
            existing=edge_keys,
        )
        stats["concepts_pruned"] = self._prune_orphan_concepts()
        receiving_cluster_ids = self._assign_clusters()
        stats["edges_created"] += self._propose_cluster_edges(
            receiving_cluster_ids, edge_keys
        )

        self._refresh_states(document_hashes)
        self._session.flush()

        stats["clusters_total"] = int(
            self._session.scalar(select(func.count(ConceptCluster.id))) or 0
        )
        return stats

    # -- document extraction ---------------------------------------------------

    def _pending_documents(self) -> tuple[int, list[Document]]:
        rows = self._session.execute(
            select(Document, ConceptExtractionState)
            .outerjoin(
                ConceptExtractionState,
                ConceptExtractionState.document_id == Document.id,
            )
            .where(active_document_filter())
            .order_by(Document.filename, Document.id)
        ).all()
        pending = [
            document
            for document, state in rows
            if state is None or state.content_hash != document.content_hash
        ]
        return len(rows), pending

    def _document_sections(self, document_id: UUID) -> list[Section]:
        return list(
            self._session.scalars(
                select(Section)
                .where(Section.document_id == document_id)
                .order_by(Section.position, Section.source_id)
            )
        )

    def _extract_document(
        self, document: Document, sections: list[Section]
    ) -> DocumentExtraction:
        allowed_source_ids = {section.source_id for section in sections}
        concepts: dict[str, ExtractedConcept] = {}
        edge_keys: set[tuple[str, str, str]] = set()
        edges = []
        for batch in self._batch_sections(sections):
            raw = self._caller.complete(
                system=DOCUMENT_SYSTEM_PROMPT,
                user=build_document_prompt(
                    filename=document.filename,
                    sections=[
                        (section.source_id, section.heading, section.body_md)
                        for section in batch
                    ],
                    max_concepts=self._max_concepts_per_doc,
                ),
            )
            extraction = parse_document_response(
                raw,
                allowed_source_ids=allowed_source_ids,
                max_concepts=self._max_concepts_per_doc,
            )
            for concept in extraction.concepts:
                existing = concepts.get(concept.slug)
                if existing is None:
                    concepts[concept.slug] = concept
                elif set(concept.source_ids) - set(existing.source_ids):
                    merged_ids = dict.fromkeys((*existing.source_ids, *concept.source_ids))
                    concepts[concept.slug] = ExtractedConcept(
                        name=existing.name,
                        slug=existing.slug,
                        summary=existing.summary,
                        source_ids=tuple(merged_ids),
                    )
            for edge in extraction.edges:
                key = (edge.source_slug, edge.target_slug, edge.kind)
                if key not in edge_keys:
                    edge_keys.add(key)
                    edges.append(edge)

        kept = list(concepts.values())[: self._max_concepts_per_doc]
        kept_slugs = {concept.slug for concept in kept}
        return DocumentExtraction(
            concepts=kept,
            edges=[
                edge
                for edge in edges
                if edge.source_slug in kept_slugs and edge.target_slug in kept_slugs
            ],
        )

    def _batch_sections(self, sections: list[Section]) -> list[list[Section]]:
        batches: list[list[Section]] = []
        current: list[Section] = []
        current_tokens = 0
        for section in sections:
            tokens = count_tokens(section.body_md, encoding_name=self._encoding_name)
            if current and current_tokens + tokens > self._token_budget:
                batches.append(current)
                current = []
                current_tokens = 0
            current.append(section)
            current_tokens += tokens
        if current:
            batches.append(current)
        return batches

    # -- concept upsert / merge --------------------------------------------------

    def _upsert_concepts(
        self,
        extracted_by_slug: dict[str, ExtractedConcept],
        stats: dict[str, Any],
    ) -> dict[str, Concept]:
        slug_to_concept: dict[str, Concept] = {}
        if not extracted_by_slug:
            return slug_to_concept

        existing_concepts = list(self._session.scalars(select(Concept)))
        existing_by_slug = {concept.slug: concept for concept in existing_concepts}
        concept_by_name: dict[str, Concept] = {}
        for concept in existing_concepts:
            concept_by_name.setdefault(concept.name, concept)
            for alias in concept.aliases:
                concept_by_name.setdefault(alias, concept)
        # Deterministic pre-match index: casefolded canonical names first, then
        # casefolded aliases, so a name match always wins over an alias match.
        concept_by_casefolded_name: dict[str, Concept] = {}
        for concept in existing_concepts:
            concept_by_casefolded_name.setdefault(concept.name.casefold(), concept)
        for concept in existing_concepts:
            for alias in concept.aliases:
                concept_by_casefolded_name.setdefault(alias.casefold(), concept)

        remaining: dict[str, ExtractedConcept] = {}
        for slug, extracted in extracted_by_slug.items():
            matched = existing_by_slug.get(slug)
            if matched is None:
                # Curated concepts may have a slug that differs from
                # slugify_concept(name); match by casefolded name/alias before
                # falling through to the LLM merge so exact duplicates like
                # "TTL" never reach it.
                matched = concept_by_casefolded_name.get(extracted.name.casefold())
                if matched is None:
                    remaining[slug] = extracted
                    continue
                stats["concepts_merged"] += 1
            elif matched.origin != SEED_ORIGIN:
                # Seed-origin concepts keep their curated summary wording;
                # extracted concepts refresh from the latest extraction.
                matched.summary = extracted.summary
            _add_alias(matched, extracted.name)
            slug_to_concept[slug] = matched

        if remaining and concept_by_name:
            new_names = sorted({extracted.name for extracted in remaining.values()})
            existing_names = sorted(concept_by_name)
            raw = self._caller.complete(
                system=MERGE_SYSTEM_PROMPT,
                user=build_merge_prompt(new_names=new_names, existing_names=existing_names),
            )
            mapping = parse_merge_response(
                raw,
                new_names=set(new_names),
                existing_names=set(existing_names),
            )
            self._apply_merge_mapping(
                mapping=mapping,
                remaining=remaining,
                concept_by_name=concept_by_name,
                slug_to_concept=slug_to_concept,
                stats=stats,
            )

        for slug, extracted in remaining.items():
            concept = Concept(name=extracted.name, slug=slug, summary=extracted.summary)
            self._session.add(concept)
            slug_to_concept[slug] = concept
            stats["concepts_created"] += 1
        self._session.flush()
        return slug_to_concept

    def _apply_merge_mapping(
        self,
        *,
        mapping: dict[str, str],
        remaining: dict[str, ExtractedConcept],
        concept_by_name: dict[str, Concept],
        slug_to_concept: dict[str, Concept],
        stats: dict[str, Any],
    ) -> None:
        resolved = _resolve_merge_mapping(mapping)
        for slug, extracted in list(remaining.items()):
            target_name = resolved.get(extracted.name)
            if target_name is None:
                continue
            concept = concept_by_name.get(target_name)
            if concept is None:
                continue
            _add_alias(concept, extracted.name)
            slug_to_concept[slug] = concept
            stats["concepts_merged"] += 1
            del remaining[slug]

    # -- sources / edges / pruning -------------------------------------------------

    def _replace_document_sources(
        self,
        *,
        sections: list[Section],
        extraction: DocumentExtraction,
        slug_to_concept: dict[str, Concept],
    ) -> None:
        section_id_by_source = {section.source_id: section.id for section in sections}
        if section_id_by_source:
            self._session.execute(
                delete(ConceptSource).where(
                    ConceptSource.section_id.in_(list(section_id_by_source.values()))
                )
            )
        pairs: set[tuple[UUID, UUID]] = set()
        for extracted in extraction.concepts:
            concept = slug_to_concept.get(extracted.slug)
            if concept is None:
                continue
            for source_id in extracted.source_ids:
                section_id = section_id_by_source.get(source_id)
                if section_id is not None:
                    pairs.add((concept.id, section_id))
        for concept_id, section_id in sorted(pairs):
            self._session.add(ConceptSource(concept_id=concept_id, section_id=section_id))
        self._session.flush()

    def _load_edge_keys(self) -> set[tuple[UUID, UUID, str]]:
        """Load all existing edge identity keys; call once per run."""
        return {
            (row.source_concept_id, row.target_concept_id, row.kind)
            for row in self._session.execute(
                select(
                    ConceptEdge.source_concept_id,
                    ConceptEdge.target_concept_id,
                    ConceptEdge.kind,
                )
            )
        }

    def _insert_edges(
        self,
        triples: list[tuple[Concept, Concept, str]],
        *,
        existing: set[tuple[UUID, UUID, str]],
    ) -> int:
        """Insert edges whose keys are absent from ``existing``, updating it in place.

        Dedupe is a pre-check against keys loaded once per run (single-writer
        assumption): a concurrent run inserting the same edge would raise
        IntegrityError on the unique constraint rather than being ignored.
        """
        if not triples:
            return 0
        self._session.flush()
        created = 0
        for source, target, kind in triples:
            key = (source.id, target.id, kind)
            if key in existing:
                continue
            existing.add(key)
            self._session.add(
                ConceptEdge(
                    source_concept_id=source.id,
                    target_concept_id=target.id,
                    kind=kind,
                )
            )
            created += 1
        self._session.flush()
        return created

    def _prune_orphan_concepts(self) -> int:
        self._session.flush()
        orphan_ids = list(
            self._session.scalars(
                select(Concept.id).where(
                    Concept.origin != SEED_ORIGIN,
                    ~select(ConceptSource.id)
                    .where(ConceptSource.concept_id == Concept.id)
                    .exists(),
                )
            )
        )
        if not orphan_ids:
            return 0
        # edges and sources cascade via FK ondelete
        self._session.execute(delete(Concept).where(Concept.id.in_(orphan_ids)))
        self._session.flush()
        return len(orphan_ids)

    # -- clustering ----------------------------------------------------------------

    def _assign_clusters(self) -> set[UUID]:
        """Assign clusters to concepts that lack one; return ids of clusters that
        gained members.

        Incremental-only by design: the LLM sees ONLY the unclustered concepts
        (name+summary) plus the existing cluster names, and either reuses an
        existing cluster or names a new one. Existing assignments are never
        rewritten and clusters are never deleted (assignments never move, so no
        cluster can empty out), keeping curated taxonomy intact.
        """
        self._session.flush()
        unclustered = list(
            self._session.scalars(
                select(Concept).where(Concept.cluster_id.is_(None)).order_by(Concept.slug)
            )
        )
        receiving: set[UUID] = set()
        if not unclustered:
            return receiving

        clusters = list(
            self._session.scalars(
                select(ConceptCluster).order_by(ConceptCluster.position, ConceptCluster.name)
            )
        )
        raw = self._caller.complete(
            system=CLUSTER_SYSTEM_PROMPT,
            user=build_cluster_prompt(
                concepts=[
                    {"name": concept.name, "summary": concept.summary}
                    for concept in unclustered
                ],
                existing_cluster_names=[cluster.name for cluster in clusters],
            ),
        )
        assignments = parse_cluster_response(
            raw, concept_names={concept.name for concept in unclustered}
        )

        cluster_by_name = {cluster.name: cluster for cluster in clusters}
        next_position = max((cluster.position for cluster in clusters), default=-1) + 1
        for concept in unclustered:
            cluster_name = assignments.get(concept.name)
            if cluster_name is None:
                continue  # left unclustered; retried on the next run
            cluster = cluster_by_name.get(cluster_name)
            if cluster is None:
                cluster = ConceptCluster(name=cluster_name, position=next_position)
                next_position += 1
                self._session.add(cluster)
                self._session.flush()
                cluster_by_name[cluster_name] = cluster
            concept.cluster_id = cluster.id
            receiving.add(cluster.id)
        self._session.flush()
        return receiving

    def _propose_cluster_edges(
        self,
        cluster_ids: set[UUID],
        edge_keys: set[tuple[UUID, UUID, str]],
    ) -> int:
        created = 0
        for cluster_id in sorted(cluster_ids):
            cluster = self._session.get(ConceptCluster, cluster_id)
            if cluster is None:
                continue
            members = list(
                self._session.scalars(
                    select(Concept)
                    .where(Concept.cluster_id == cluster_id)
                    .order_by(Concept.slug)
                )
            )
            if not members:
                continue
            raw = self._caller.complete(
                system=CLUSTER_EDGES_SYSTEM_PROMPT,
                user=build_cluster_edges_prompt(
                    cluster_name=cluster.name,
                    concepts=[
                        {"name": member.name, "summary": member.summary} for member in members
                    ],
                ),
            )
            member_by_slug = {member.slug: member for member in members}
            edges = parse_edges_response(
                raw,
                known_slugs=set(member_by_slug),
                max_edges=max(2 * len(members), 1),
            )
            triples: list[tuple[Concept, Concept, str]] = []
            for edge in edges:
                source = member_by_slug.get(edge.source_slug)
                target = member_by_slug.get(edge.target_slug)
                if source is None or target is None:
                    continue
                triples.append((source, target, edge.kind))
            created += self._insert_edges(triples, existing=edge_keys)
        return created

    # -- extraction state ------------------------------------------------------------

    def _refresh_states(self, document_hashes: dict[UUID, str]) -> None:
        if not document_hashes:
            return
        states = self._session.scalars(
            select(ConceptExtractionState).where(
                ConceptExtractionState.document_id.in_(list(document_hashes))
            )
        )
        missing = dict(document_hashes)
        for state in states:
            state.content_hash = missing.pop(state.document_id)
        for document_id, content_hash in missing.items():
            self._session.add(
                ConceptExtractionState(document_id=document_id, content_hash=content_hash)
            )


def _document_edge_triples(
    extractions: Iterable[DocumentExtraction],
    slug_to_concept: dict[str, Concept],
) -> list[tuple[Concept, Concept, str]]:
    triples: list[tuple[Concept, Concept, str]] = []
    for extraction in extractions:
        for edge in extraction.edges:
            source = slug_to_concept.get(edge.source_slug)
            target = slug_to_concept.get(edge.target_slug)
            # merges can collapse both endpoints onto one concept — skip self-edges
            if source is None or target is None or source is target:
                continue
            # undirected kinds were slug-order normalized pre-merge; re-normalize
            # against the canonical concepts so duplicates collapse after remapping
            if edge.kind != "prerequisite" and source.slug > target.slug:
                source, target = target, source
            triples.append((source, target, edge.kind))
    return triples


def _resolve_merge_mapping(mapping: dict[str, str]) -> dict[str, str]:
    """Resolve chained merges ({A→B, B→C} → {A→C, B→C}) to terminal names.

    parse_merge_response can emit chains when a name appears in both the new and
    existing sets. Hops are capped at the mapping size, which any acyclic chain
    satisfies; entries still pointing into the mapping after the cap (cycles) are
    dropped rather than merged.
    """
    resolved: dict[str, str] = {}
    max_hops = len(mapping)
    for source, target in mapping.items():
        hops = 0
        while target in mapping and hops < max_hops:
            target = mapping[target]
            hops += 1
        if target in mapping or target == source:
            continue
        resolved[source] = target
    return resolved


def _add_alias(concept: Concept, name: str) -> None:
    if name == concept.name or name in concept.aliases:
        return
    # plain JSONB column (no mutation tracking) — reassign instead of append
    concept.aliases = [*concept.aliases, name]


class OpenAIGraphCaller:
    """ChatCaller backed by the configured OpenAI chat model, recording provider
    telemetry so budget guardrails see extraction usage (operation label
    "graph_extraction")."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str,
        timeout_seconds: float = 30.0,
        max_retries: int = 2,
        context: ProviderCallContext | None = None,
        client: object | None = None,
    ) -> None:
        if client is None and not api_key:
            raise ValueError("OPENAI_API_KEY is required for OpenAI graph caller")

        if client is None:
            from openai import OpenAI

            client = OpenAI(
                api_key=api_key,
                timeout=timeout_seconds,
                max_retries=max_retries,
            )
        self._client: Any = client
        self._model = model
        self._context = context if context is not None else ProviderCallContext()

    @property
    def call_records(self) -> list[ProviderCallRecord]:
        return list(self._context.records)

    def complete(self, *, system: str, user: str) -> str:
        started_at = perf_counter()
        client_request_id = self._context.next_client_request_id()
        try:
            response = self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                response_format={"type": "json_object"},
            )
        except Exception as error:
            self._record(
                status="failed",
                started_at=started_at,
                client_request_id=client_request_id,
                error_type=error.__class__.__name__,
            )
            raise
        usage = completion_usage(response)
        provider_request_id = response_request_id(response)
        choices = response.choices
        content = choices[0].message.content if choices else None
        if not isinstance(content, str) or not content:
            # An empty extraction parses as {} and would silently wipe the
            # document's concept sources; fail the document instead.
            self._record(
                status="failed",
                started_at=started_at,
                client_request_id=client_request_id,
                provider_request_id=provider_request_id,
                usage=usage,
                error_type="RuntimeError",
            )
            raise RuntimeError("graph extraction returned empty content")
        self._record(
            status="succeeded",
            started_at=started_at,
            client_request_id=client_request_id,
            provider_request_id=provider_request_id,
            usage=usage,
        )
        return content

    def _record(
        self,
        *,
        status: ProviderCallStatus,
        started_at: float,
        client_request_id: str | None,
        provider_request_id: str | None = None,
        usage: ProviderUsage | None = None,
        error_type: str | None = None,
    ) -> None:
        self._context.record(
            ProviderCallRecord(
                provider="openai",
                operation=GRAPH_EXTRACTION_OPERATION,
                model=self._model,
                status=status,
                client_request_id=client_request_id,
                provider_request_id=provider_request_id,
                usage=usage,
                usage_complete=usage is not None,
                latency_ms=max(0, round((perf_counter() - started_at) * 1000)),
                error_type=error_type,
            )
        )
