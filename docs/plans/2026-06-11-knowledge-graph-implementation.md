# Knowledge Graph Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the document→section mindmap with an LLM-extracted concept graph (topic clusters + concept nodes + typed edges), seeded from a curated dataset for existing materials and incrementally updated by a background pipeline for future uploads, rendered as a three-view interactive graph.

**Architecture:** New `app/graph/` domain package (extraction parsing, pipeline orchestration) + 5 Postgres tables + a worker task chained after index rebuild + `/graph` API replacing `/mindmap` + Cytoscape.js (vendored) three-view frontend in the existing vanilla-JS workbench. The initial 35-document graph is curated in-session (no API cost) and loaded by a seed script that records per-document extraction state so the pipeline only processes future changes.

**Tech Stack:** FastAPI, SQLAlchemy 2 + Alembic, Postgres, OpenAI chat (pipeline only), Cytoscape.js + dagre (vendored static), pytest. Spec: `docs/plans/2026-06-11-knowledge-graph-design.md`.

**Conventions (same as the RAG plan):**
- Python via `uv run --python 3.12 ...` (untracked `.python-version` pins 3.11.9; bare `uv run` fails)
- DB suites: `KB_DATABASE_URL_TEST=postgresql+psycopg://kb:kb@localhost:5432/kb_test` (Postgres up via docker compose; conftest migrates per session)
- Live `kb` DB from host: override `KB_DATABASE_URL=postgresql+psycopg://kb:kb@localhost:5432/kb` per command (`.env` points at the docker-internal hostname and Make re-includes `.env`)
- `make lint` = ruff + mypy strict, line length 100, full annotations everywhere
- Current suite counts before this plan: unit 349 / integration 83 / e2e 14(+4 skipped)

**Task order:** 1→2→3→4→5→6→7 are code (strict TDD). Task 8 is the controller-run dataset curation + seeding (needs Tasks 1, 5, 6 shipped). Task 9 is validation/acceptance/docs.

---

### Task 1: Concept tables — migration 0012 + models

**Files:**
- Create: `migrations/versions/0012_concept_graph.py`
- Modify: `app/models/tables.py` (append after `Chunk`)
- Test: `tests/integration/test_concept_tables.py`

- [ ] **Step 1: Write the failing integration test**

Create `tests/integration/test_concept_tables.py`:

```python
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.tables import (
    Concept,
    ConceptCluster,
    ConceptEdge,
    ConceptExtractionState,
    ConceptSource,
    Document,
    Section,
)


def _document(db_session: Session) -> Document:
    document = Document(
        filename="course.md",
        canonical_path="/docs/course.md",
        source_type="markdown",
        content_hash="doc-hash",
    )
    db_session.add(document)
    db_session.flush()
    return document


def _section(db_session: Session, document: Document, *, slug: str, position: int) -> Section:
    section = Section(
        document_id=document.id,
        source_id=f"course.md#{slug}",
        heading=slug,
        heading_slug=slug,
        level=2,
        body_md=f"關於 {slug} 的內容。",
        token_count=8,
        content_hash=f"hash-{slug}",
        position=position,
    )
    db_session.add(section)
    db_session.flush()
    return section


def test_concept_graph_round_trip(db_session: Session) -> None:
    document = _document(db_session)
    section = _section(db_session, document, slug="consistent-hashing", position=0)

    cluster = ConceptCluster(name="快取", position=0)
    db_session.add(cluster)
    db_session.flush()

    concept = Concept(
        name="Consistent Hashing",
        slug="consistent-hashing",
        summary="把節點與鍵映射到同一個雜湊環。",
        cluster_id=cluster.id,
        aliases=["一致性雜湊"],
    )
    other = Concept(name="Sharding", slug="sharding", summary="資料水平切分。")
    db_session.add_all([concept, other])
    db_session.flush()

    db_session.add(
        ConceptEdge(source_concept_id=concept.id, target_concept_id=other.id, kind="related")
    )
    db_session.add(ConceptSource(concept_id=concept.id, section_id=section.id))
    db_session.add(
        ConceptExtractionState(document_id=document.id, content_hash=document.content_hash)
    )
    db_session.flush()

    loaded = db_session.scalar(select(Concept).where(Concept.slug == "consistent-hashing"))
    assert loaded is not None
    assert loaded.cluster_id == cluster.id
    assert loaded.aliases == ["一致性雜湊"]


def test_deleting_section_cascades_concept_sources(db_session: Session) -> None:
    document = _document(db_session)
    section = _section(db_session, document, slug="quorum", position=0)
    concept = Concept(name="Quorum", slug="quorum", summary="多數決讀寫。")
    db_session.add(concept)
    db_session.flush()
    db_session.add(ConceptSource(concept_id=concept.id, section_id=section.id))
    db_session.flush()

    db_session.delete(section)
    db_session.flush()

    remaining = db_session.scalars(select(ConceptSource)).all()
    assert remaining == []


def test_deleting_concept_cascades_edges(db_session: Session) -> None:
    a = Concept(name="A", slug="a", summary="a")
    b = Concept(name="B", slug="b", summary="b")
    db_session.add_all([a, b])
    db_session.flush()
    db_session.add(ConceptEdge(source_concept_id=a.id, target_concept_id=b.id, kind="related"))
    db_session.flush()

    db_session.delete(a)
    db_session.flush()

    assert db_session.scalars(select(ConceptEdge)).all() == []
```

- [ ] **Step 2: Run to verify it fails**

```bash
KB_DATABASE_URL_TEST=postgresql+psycopg://kb:kb@localhost:5432/kb_test \
  uv run --python 3.12 pytest tests/integration/test_concept_tables.py -v
```
Expected: FAIL with `ImportError: cannot import name 'Concept'`

- [ ] **Step 3: Add models**

Append to `app/models/tables.py` (after `Chunk`, following the file's existing style — `JsonDefaultsMixin`, `TimestampMixin`, `Base`, UUID pks with `default=uuid4`):

```python
class ConceptCluster(TimestampMixin, Base):
    __tablename__ = "concept_clusters"
    __table_args__ = (Index("ux_concept_clusters_name", "name", unique=True),)

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    concepts: Mapped[list[Concept]] = relationship(back_populates="cluster")


class Concept(JsonDefaultsMixin, TimestampMixin, Base):
    __tablename__ = "concepts"
    __table_args__ = (Index("ux_concepts_slug", "slug", unique=True),)
    __json_defaults__ = {"aliases": list}

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    slug: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    cluster_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("concept_clusters.id", ondelete="SET NULL"),
    )
    aliases: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default=text("'[]'::jsonb"),
    )

    cluster: Mapped[ConceptCluster | None] = relationship(back_populates="concepts")
    sources: Mapped[list[ConceptSource]] = relationship(
        back_populates="concept",
        cascade="all, delete-orphan",
    )


class ConceptEdge(TimestampMixin, Base):
    __tablename__ = "concept_edges"
    __table_args__ = (
        Index(
            "ux_concept_edges_source_target_kind",
            "source_concept_id",
            "target_concept_id",
            "kind",
            unique=True,
        ),
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    source_concept_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("concepts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    target_concept_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("concepts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    kind: Mapped[str] = mapped_column(Text, nullable=False)


class ConceptSource(TimestampMixin, Base):
    __tablename__ = "concept_sources"
    __table_args__ = (
        Index("ux_concept_sources_concept_section", "concept_id", "section_id", unique=True),
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    concept_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("concepts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    section_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("sections.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    concept: Mapped[Concept] = relationship(back_populates="sources")
    section: Mapped[Section] = relationship()


class ConceptExtractionState(TimestampMixin, Base):
    __tablename__ = "concept_extraction_state"
    __table_args__ = (Index("ux_concept_extraction_state_document", "document_id", unique=True),)

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    document_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
    )
    content_hash: Mapped[str] = mapped_column(Text, nullable=False)
```

Note: `Concept`/`ConceptSource` forward references require the classes in this order or `from __future__ import annotations` (already present at the top of tables.py).

- [ ] **Step 4: Write migration**

Create `migrations/versions/0012_concept_graph.py`:

```python
"""add concept graph tables

Revision ID: 0012_concept_graph
Revises: 0011_section_position
Create Date: 2026-06-11 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "0012_concept_graph"
down_revision: str | None = "0011_section_position"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _uuid_pk() -> sa.Column:
    return sa.Column("id", UUID(as_uuid=True), primary_key=True)


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    ]


def upgrade() -> None:
    op.create_table(
        "concept_clusters",
        _uuid_pk(),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False, server_default=sa.text("0")),
        *_timestamps(),
    )
    op.create_index("ux_concept_clusters_name", "concept_clusters", ["name"], unique=True)

    op.create_table(
        "concepts",
        _uuid_pk(),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("slug", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column(
            "cluster_id",
            UUID(as_uuid=True),
            sa.ForeignKey("concept_clusters.id", ondelete="SET NULL"),
        ),
        sa.Column("aliases", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        *_timestamps(),
    )
    op.create_index("ux_concepts_slug", "concepts", ["slug"], unique=True)

    op.create_table(
        "concept_edges",
        _uuid_pk(),
        sa.Column(
            "source_concept_id",
            UUID(as_uuid=True),
            sa.ForeignKey("concepts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "target_concept_id",
            UUID(as_uuid=True),
            sa.ForeignKey("concepts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.Text(), nullable=False),
        *_timestamps(),
    )
    op.create_index(
        "ux_concept_edges_source_target_kind",
        "concept_edges",
        ["source_concept_id", "target_concept_id", "kind"],
        unique=True,
    )
    op.create_index("ix_concept_edges_source_concept_id", "concept_edges", ["source_concept_id"])
    op.create_index("ix_concept_edges_target_concept_id", "concept_edges", ["target_concept_id"])

    op.create_table(
        "concept_sources",
        _uuid_pk(),
        sa.Column(
            "concept_id",
            UUID(as_uuid=True),
            sa.ForeignKey("concepts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "section_id",
            UUID(as_uuid=True),
            sa.ForeignKey("sections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        *_timestamps(),
    )
    op.create_index(
        "ux_concept_sources_concept_section",
        "concept_sources",
        ["concept_id", "section_id"],
        unique=True,
    )
    op.create_index("ix_concept_sources_concept_id", "concept_sources", ["concept_id"])
    op.create_index("ix_concept_sources_section_id", "concept_sources", ["section_id"])

    op.create_table(
        "concept_extraction_state",
        _uuid_pk(),
        sa.Column(
            "document_id",
            UUID(as_uuid=True),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("content_hash", sa.Text(), nullable=False),
        *_timestamps(),
    )
    op.create_index(
        "ux_concept_extraction_state_document",
        "concept_extraction_state",
        ["document_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_table("concept_extraction_state")
    op.drop_table("concept_sources")
    op.drop_table("concept_edges")
    op.drop_table("concepts")
    op.drop_table("concept_clusters")
```

Check existing migrations (e.g. `0004_eval_tables.py`) for the exact column-helper style used in this repo and match it; the structure above (tables, FKs, unique indexes, cascade behavior) is the contract.

- [ ] **Step 5: Run the test to verify it passes**

Same command as Step 2. Expected: 3 passed (conftest runs downgrade base → upgrade head, exercising 0012 both ways).

- [ ] **Step 6: Full suites, lint, commit**

```bash
uv run --python 3.12 pytest tests/unit -q
KB_DATABASE_URL_TEST=... uv run --python 3.12 pytest tests/integration -q
make lint
git add migrations/versions/0012_concept_graph.py app/models/tables.py \
  tests/integration/test_concept_tables.py
git commit -m "feat: add concept graph tables"
```

---

### Task 2: Extraction parsing & validation (`app/graph/extraction.py`)

Pure module: prompts, ChatCaller protocol, strict JSON parsing with caps. No DB.

**Files:**
- Create: `app/graph/__init__.py` (empty), `app/graph/extraction.py`
- Test: `tests/unit/test_graph_extraction.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_graph_extraction.py`:

```python
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
```

- [ ] **Step 2: Run to verify failure** — `uv run --python 3.12 pytest tests/unit/test_graph_extraction.py -v` → ModuleNotFoundError.

- [ ] **Step 3: Implement**

Create `app/graph/__init__.py` (empty) and `app/graph/extraction.py`:

```python
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
```

- [ ] **Step 4: Run tests** → PASS. **Step 5:** `make lint` clean. **Step 6: Commit**

```bash
git add app/graph tests/unit/test_graph_extraction.py
git commit -m "feat: add concept extraction parsing and prompts"
```

---

### Task 3: Pipeline orchestration (`app/graph/pipeline.py`) + settings

**Files:**
- Create: `app/graph/pipeline.py`
- Modify: `app/core/config.py` (3 settings)
- Test: `tests/unit/test_config.py` (append), `tests/integration/test_graph_pipeline.py`

- [ ] **Step 1: Settings (TDD)** — append to `tests/unit/test_config.py`:

```python
def test_graph_extraction_defaults() -> None:
    settings = Settings()
    assert settings.graph_extraction_enabled is True
    assert settings.graph_max_concepts_per_doc == 30
    assert settings.graph_extraction_token_budget == 12000


def test_graph_settings_validation() -> None:
    with pytest.raises(ValidationError, match="graph_max_concepts_per_doc"):
        Settings(graph_max_concepts_per_doc=0)
    with pytest.raises(ValidationError, match="graph_extraction_token_budget"):
        Settings(graph_extraction_token_budget=500)
```

Run → FAIL. Then add to `Settings` in `app/core/config.py` (after the context expansion block) and to `_SETTINGS_ENV_KEYS` in the test file (`KB_GRAPH_EXTRACTION_ENABLED`, `KB_GRAPH_MAX_CONCEPTS_PER_DOC`, `KB_GRAPH_EXTRACTION_TOKEN_BUDGET`):

```python
    graph_extraction_enabled: bool = True
    graph_max_concepts_per_doc: int = Field(default=30, ge=1)
    graph_extraction_token_budget: int = Field(default=12000, ge=1000)
```

Run → PASS.

- [ ] **Step 2: Write the failing pipeline integration test**

Create `tests/integration/test_graph_pipeline.py`:

```python
from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.graph.pipeline import GraphExtractionPipeline
from app.models.tables import (
    Concept,
    ConceptEdge,
    ConceptExtractionState,
    ConceptSource,
    Document,
    Section,
)


class ScriptedCaller:
    """Returns responses keyed by system-prompt kind, in order per kind."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self.responses: dict[str, list[str]] = {}

    def queue(self, system_contains: str, response: str) -> None:
        self.responses.setdefault(system_contains, []).append(response)

    def complete(self, *, system: str, user: str) -> str:
        self.calls.append((system, user))
        for key, queued in self.responses.items():
            if key in system and queued:
                return queued.pop(0)
        return "{}"


def _seed_document(
    db_session: Session, *, filename: str, slugs: list[str], content_hash: str
) -> Document:
    document = Document(
        filename=filename,
        canonical_path=f"/docs/{filename}",
        source_type="markdown",
        content_hash=content_hash,
    )
    db_session.add(document)
    db_session.flush()
    for position, slug in enumerate(slugs):
        db_session.add(
            Section(
                document_id=document.id,
                source_id=f"{filename}#{slug}",
                heading=slug,
                heading_slug=slug,
                level=2,
                body_md=f"{slug} 的內容。",
                token_count=8,
                content_hash=f"{filename}-{slug}",
                position=position,
            )
        )
    db_session.flush()
    return document


def _document_response(filename: str, names: list[str], slugs: list[str]) -> str:
    return json.dumps(
        {
            "concepts": [
                {"name": name, "summary": f"{name} 摘要。", "source_ids": [f"{filename}#{slug}"]}
                for name, slug in zip(names, slugs, strict=True)
            ],
            "edges": (
                [{"source": names[0], "target": names[1], "kind": "prerequisite"}]
                if len(names) > 1
                else []
            ),
        }
    )


def test_pipeline_extracts_merges_and_clusters(db_session: Session) -> None:
    _seed_document(db_session, filename="a.md", slugs=["s1", "s2"], content_hash="ha")
    caller = ScriptedCaller()
    caller.queue("extract a concept graph", _document_response("a.md", ["Caching", "TTL"], ["s1", "s2"]))
    caller.queue("deduplicate concept names", json.dumps({"merges": []}))
    caller.queue(
        "group course concepts",
        json.dumps({"clusters": [{"name": "快取", "concepts": ["Caching", "TTL"]}]}),
    )
    caller.queue("Propose edges", json.dumps({"edges": []}))

    pipeline = GraphExtractionPipeline(
        session=db_session, caller=caller, max_concepts_per_doc=30, token_budget=12000
    )
    stats = pipeline.run()

    concepts = db_session.scalars(select(Concept)).all()
    assert {concept.name for concept in concepts} == {"Caching", "TTL"}
    assert all(concept.cluster is not None and concept.cluster.name == "快取" for concept in concepts)
    edges = db_session.scalars(select(ConceptEdge)).all()
    assert len(edges) == 1 and edges[0].kind == "prerequisite"
    assert db_session.scalars(select(ConceptSource)).all()
    assert stats["documents_extracted"] == 1


def test_pipeline_is_incremental(db_session: Session) -> None:
    document = _seed_document(db_session, filename="a.md", slugs=["s1"], content_hash="ha")
    db_session.add(ConceptExtractionState(document_id=document.id, content_hash="ha"))
    db_session.flush()

    caller = ScriptedCaller()  # no responses queued: any LLM call would return "{}"
    pipeline = GraphExtractionPipeline(
        session=db_session, caller=caller, max_concepts_per_doc=30, token_budget=12000
    )
    stats = pipeline.run()

    assert stats["documents_extracted"] == 0
    assert caller.calls == []  # nothing to do, no LLM calls at all


def test_pipeline_reextracts_changed_document_and_prunes_orphans(db_session: Session) -> None:
    document = _seed_document(db_session, filename="a.md", slugs=["s1"], content_hash="ha-v2")
    db_session.add(ConceptExtractionState(document_id=document.id, content_hash="ha-v1"))
    # pre-existing concept that the new extraction no longer mentions, sourced only
    # from this document
    stale = Concept(name="Old Idea", slug="old-idea", summary="舊概念。")
    db_session.add(stale)
    db_session.flush()
    section = db_session.scalars(select(Section)).one()
    db_session.add(ConceptSource(concept_id=stale.id, section_id=section.id))
    db_session.flush()

    caller = ScriptedCaller()
    caller.queue("extract a concept graph", _document_response("a.md", ["Fresh"], ["s1"]))
    caller.queue("deduplicate concept names", json.dumps({"merges": []}))
    caller.queue(
        "group course concepts",
        json.dumps({"clusters": [{"name": "主題", "concepts": ["Fresh"]}]}),
    )
    caller.queue("Propose edges", json.dumps({"edges": []}))

    GraphExtractionPipeline(
        session=db_session, caller=caller, max_concepts_per_doc=30, token_budget=12000
    ).run()

    names = {concept.name for concept in db_session.scalars(select(Concept)).all()}
    assert names == {"Fresh"}  # stale concept lost its only source and was pruned
    state = db_session.scalar(select(ConceptExtractionState))
    assert state is not None and state.content_hash == "ha-v2"


def test_pipeline_merges_into_existing_concepts(db_session: Session) -> None:
    _seed_document(db_session, filename="a.md", slugs=["s1"], content_hash="ha")
    existing = Concept(name="Consistent Hashing", slug="consistent-hashing", summary="既有。")
    db_session.add(existing)
    db_session.flush()

    caller = ScriptedCaller()
    caller.queue(
        "extract a concept graph",
        _document_response("a.md", ["一致性雜湊"], ["s1"]),
    )
    caller.queue(
        "deduplicate concept names",
        json.dumps({"merges": [{"from": "一致性雜湊", "into": "Consistent Hashing"}]}),
    )
    caller.queue(
        "group course concepts",
        json.dumps({"clusters": [{"name": "主題", "concepts": ["Consistent Hashing"]}]}),
    )
    caller.queue("Propose edges", json.dumps({"edges": []}))

    GraphExtractionPipeline(
        session=db_session, caller=caller, max_concepts_per_doc=30, token_budget=12000
    ).run()

    concepts = db_session.scalars(select(Concept)).all()
    assert len(concepts) == 1
    assert concepts[0].slug == "consistent-hashing"
    assert "一致性雜湊" in concepts[0].aliases
    assert db_session.scalars(select(ConceptSource)).all()  # sources remapped
```

- [ ] **Step 3: Run to verify failure**, then implement `app/graph/pipeline.py`

Implementation contract (write it to satisfy the tests; key structure):

```python
from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.document_lifecycle import active_document_filter
from app.graph.extraction import (
    CLUSTER_EDGES_SYSTEM_PROMPT,
    CLUSTER_SYSTEM_PROMPT,
    DOCUMENT_SYSTEM_PROMPT,
    MERGE_SYSTEM_PROMPT,
    ChatCaller,
    DocumentExtraction,
    build_cluster_edges_prompt,
    build_cluster_prompt,
    build_document_prompt,
    build_merge_prompt,
    parse_cluster_response,
    parse_document_response,
    parse_edges_response,
    parse_merge_response,
    slugify_concept,
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


class GraphExtractionPipeline:
    def __init__(
        self,
        *,
        session: Session,
        caller: ChatCaller,
        max_concepts_per_doc: int,
        token_budget: int,
        encoding_name: str = DEFAULT_TOKEN_ENCODING,
    ) -> None: ...

    def run(self) -> dict[str, Any]:
        """1) find active documents whose content_hash != extraction state (or no
        state); 2) per document: load sections ordered by position, batch them under
        token_budget (count_tokens over body_md), one LLM call per batch with
        DOCUMENT_SYSTEM_PROMPT + build_document_prompt, parse_document_response with
        allowed_source_ids = that document's section source_ids; failures (raised by
        caller) are caught per-document and recorded in stats["documents_failed"],
        leaving that document's previous state untouched; 3) global merge:
        exact slug match against existing concepts first, then ONE LLM call
        (MERGE_SYSTEM_PROMPT + build_merge_prompt) for remaining new names vs all
        existing canonical names + aliases; apply mapping (merged names become
        aliases on the canonical concept); upsert concepts (slug-keyed), replace
        each re-extracted document's concept_sources, insert edges (slug pairs ->
        concept ids, ON CONFLICT ignore via unique constraint + pre-check); 4) prune
        concepts whose concept_sources count is now zero; 5) clustering: if any
        concept lacks a cluster OR >30% of concepts are new/changed, ONE LLM call
        (CLUSTER_SYSTEM_PROMPT + build_cluster_prompt with existing cluster names);
        create/reuse clusters by name, assign concepts, drop empty clusters; 6) for
        each cluster containing newly added concepts, ONE LLM call proposing edges
        (CLUSTER_EDGES_SYSTEM_PROMPT + build_cluster_edges_prompt, parsed via
        parse_edges_response over that cluster's slugs); 7) write/refresh
        ConceptExtractionState per successfully extracted
        document; return stats dict: documents_considered, documents_extracted,
        documents_failed, concepts_created, concepts_merged, concepts_pruned,
        edges_created, clusters_total."""
```

Write the real implementation (~250 lines) following this contract exactly — every behavior above is pinned by the Step 2 tests. Keep DB writes in small helper methods (`_upsert_concepts`, `_apply_merge_mapping`, `_replace_document_sources`, `_prune_orphan_concepts`, `_assign_clusters`, `_insert_edges`). The pipeline does NOT commit — the caller (worker task / script) owns the transaction, matching `IndexingService` conventions.

Also add the OpenAI caller with telemetry at the bottom of `app/graph/pipeline.py` (reuse the provider-telemetry pattern; read `app/answer/providers.py` for `ProviderCallContext` usage and `app/provider_telemetry.py`):

```python
class OpenAIGraphCaller:
    """ChatCaller backed by the configured OpenAI chat model, recording provider
    telemetry so budget guardrails see extraction usage (operation label
    "graph_extraction")."""
```

Implement it mirroring `OpenAIChatCaller` in `scripts/generate_eval_cases.py` (json_object response format) plus telemetry recording; if wiring telemetry requires the provider context plumbing, follow how `OpenAIAnswerProvider` records calls — keep it to ~40 lines.

- [ ] **Step 4: Run the integration tests** → all 4 pass. **Step 5:** unit + integration suites + lint. **Step 6: Commit**

```bash
git add app/graph/pipeline.py app/core/config.py tests/
git commit -m "feat: add concept graph extraction pipeline"
```

---

### Task 4: Worker task + chaining + admin trigger

**Files:**
- Modify: `app/background_jobs/worker.py` (new task type + chain after rebuild), the task-constants module where `TASK_INDEX_REBUILD` lives (check `app/background_jobs/` imports — constants are imported in worker.py:28-31), `app/api/graph.py` does NOT exist yet — admin trigger endpoint comes with Task 6
- Test: `tests/unit/test_background_jobs.py` or `tests/integration/test_background_job_workflow.py` (follow where TASK_INDEX_REBUILD chaining from ingest is tested — grep `index_after_import`)

- [ ] **Step 1: Find the existing chaining test** — `grep -rn "index_after_import\|TASK_INDEX_REBUILD" tests/` and read the test that asserts ingest chains a rebuild job. Write the analogous failing test: after `_run_index_rebuild` succeeds AND `settings.graph_extraction_enabled` is true, a `TASK_CONCEPT_EXTRACTION` job is enqueued; when the setting is false, it is not. Follow the existing test file's fixture style exactly.

- [ ] **Step 2: Implement**

In the task-constants location (same module as `TASK_INDEX_REBUILD`): add `TASK_CONCEPT_EXTRACTION = "concept_extraction"`.

In `app/background_jobs/worker.py`:
- `_execute_task` gains: `if task_type == TASK_CONCEPT_EXTRACTION: return self._run_concept_extraction()`
- `_run_index_rebuild` enqueues the follow-up after success (mirror the ingest→index chaining at worker.py:177-181):

```python
    def _run_index_rebuild(self) -> dict[str, object]:
        with self.session_factory() as session:
            result = IndexingService(
                session=session,
                docs_dir=Path(self.settings.docs_dir),
                kb_dir=Path(self.settings.kb_dir),
                embedding_provider=self._embedding_provider(),
                token_encoding=self.settings.token_encoding,
            ).rebuild_index()
            if self.settings.graph_extraction_enabled:
                BackgroundJobService(session).enqueue(
                    task_type=TASK_CONCEPT_EXTRACTION,
                    payload={"reason": TASK_INDEX_REBUILD},
                )
                session.commit()
        return _indexing_result_payload(result)
```

(Adapt to the actual session/commit pattern in that method — read it first; `rebuild_index` manages its own transactions, so the enqueue needs its own commit or a fresh session block.)

- `_run_concept_extraction`:

```python
    def _run_concept_extraction(self) -> dict[str, object]:
        with self.session_factory() as session:
            pipeline = GraphExtractionPipeline(
                session=session,
                caller=self._graph_caller(),
                max_concepts_per_doc=self.settings.graph_max_concepts_per_doc,
                token_budget=self.settings.graph_extraction_token_budget,
                encoding_name=self.settings.token_encoding,
            )
            stats = pipeline.run()
            session.commit()
        return stats
```

- `_graph_caller()`: returns `OpenAIGraphCaller` when `settings.answer_provider == "openai"` (api key required), else a fail-fast error — BUT tests need injection. Follow how `_embedding_provider()` resolves fake vs openai in this file and mirror it; for the fake path return a caller that returns `"{}"` (no-op extraction) so docker smoke environments don't explode.

- [ ] **Step 3: Run the new test** → PASS. Full unit + integration suites. **Step 4:** lint + commit `feat: chain concept extraction after index rebuild`.

---

### Task 5: Seed script (`scripts/seed_concept_graph.py`)

**Files:**
- Create: `scripts/seed_concept_graph.py`
- Modify: `Makefile` (`graph-seed` target + .PHONY)
- Test: `tests/unit/test_seed_concept_graph.py`, `tests/integration/test_seed_concept_graph_db.py`

**Dataset JSON schema** (shared contract with Task 8 — keep field names exactly):

```json
{
  "version": 1,
  "clusters": [{"name": "快取", "position": 0}],
  "concepts": [
    {
      "name": "Consistent Hashing",
      "slug": "consistent-hashing",
      "summary": "把節點與鍵映射到同一個雜湊環，重新配置時只搬動少量資料。",
      "aliases": ["一致性雜湊"],
      "cluster": "快取",
      "source_ids": ["1-基本觀念-06-Consistent Hashing.md#什麼是-consistent-hashing"]
    }
  ],
  "edges": [{"source": "consistent-hashing", "target": "sharding", "kind": "related"}]
}
```

- [ ] **Step 1: Failing unit tests** — `tests/unit/test_seed_concept_graph.py` covering `parse_seed_graph(raw_dict)`: valid payload parses; duplicate slugs rejected (ValueError); unknown edge kind rejected; edge referencing unknown slug rejected; concept with empty source_ids rejected; concept referencing unknown cluster name rejected. Write ~6 small tests against a `parse_seed_graph` function returning a `SeedGraph` dataclass (clusters/concepts/edges).

- [ ] **Step 2: Failing integration test** — `tests/integration/test_seed_concept_graph_db.py`: seed two sections (reuse the `_document`/`_section` helpers pattern from `tests/integration/test_concept_tables.py`), build a seed dict citing one real source_id and one bogus, call `apply_seed_graph(session, seed, strict=True)` → raises on the bogus reference; with only valid references it: creates clusters/concepts/edges/sources, writes `ConceptExtractionState` for every document that has at least one cited section (content_hash = the document's CURRENT hash), and a second `apply_seed_graph` call is idempotent (same counts, no duplicates).

- [ ] **Step 3: Implement** `scripts/seed_concept_graph.py`:
- `parse_seed_graph(payload: dict) -> SeedGraph` — pure validation per Step 1.
- `apply_seed_graph(session, seed: SeedGraph, *, strict: bool = True) -> dict[str, int]` — resolves source_ids → Section rows (`select(Section).where(Section.source_id.in_(...))`); strict mode raises listing every unknown source_id; upserts clusters by name, concepts by slug (update name/summary/aliases/cluster on conflict), replaces each concept's sources, inserts edges (skip existing via the unique constraint pre-check), writes/updates `ConceptExtractionState` rows with each affected document's current `content_hash`; returns counts.
- `main(argv)` — argparse: `--file` (required, Path), `--dry-run` (parse + validate against DB without writing). Uses `SessionLocal`, commits on success. Same CLI conventions as `scripts/seed_eval_cases.py`.
- Makefile:

```makefile
graph-seed:
	$(UV) python -m scripts.seed_concept_graph --file docs/plans/2026-06-11-concept-graph-seed.json
```

(+ `.PHONY` entry.)

- [ ] **Step 4:** All tests pass; lint; commit `feat: add concept graph seed script`.

---

### Task 6: `/graph` API, admin trigger, remove `/mindmap`

**Files:**
- Create: `app/api/graph.py`
- Modify: `app/main.py` (router swap)
- Delete: `app/api/mindmap.py`, `tests/unit/test_mindmap_response.py`, `tests/integration/test_mindmap.py`
- Test: `tests/integration/test_graph_api.py`

- [ ] **Step 1: Failing integration test** — `tests/integration/test_graph_api.py` using the app test-client fixture pattern from `tests/integration/test_api_workflow.py`:
  - seed a small graph directly via models (1 cluster, 2 concepts with sources to 2 sections of an active public document, 1 prerequisite edge)
  - `GET /graph` → 200 with clusters[]/nodes[]/edges[]/stats matching the spec shape; node has `source_count`
  - visibility: a concept whose ONLY sources belong to a non-public document does not appear for an anonymous/public principal (set the document's visibility to `["cohort-x"]`)
  - `GET /graph/concepts/{id}` → 200 with sources list (source_id/filename/heading); 404 for unknown id
  - `POST /graph/extract` without admin key → 401/403; with `X-KB-Admin-Key` → 202 and a `TASK_CONCEPT_EXTRACTION` background job row exists

- [ ] **Step 2: Implement `app/api/graph.py`**

Response models per spec §3 (`GraphCluster`, `GraphNode {id,name,slug,summary,cluster_id,source_count}`, `GraphEdge {source,target,kind}`, `GraphStats {concept_count,cluster_count,edge_count,extracted_at}`, `GraphResponse`; `ConceptDetailResponse {id,name,summary,aliases,cluster,sources:[{section_id,document_id,source_id,filename,heading}]}`).

Query shape for `/graph`: load concepts joined to their sources' sections' documents, filtered by `active_document_filter()` AND `source_visibility_filter(Document.visibility, principal)`; a concept is visible iff it has ≥1 visible source; `source_count` counts visible sources only; edges included only when both endpoints are visible; `extracted_at` = max(ConceptExtractionState.updated_at) or None. Reuse dependency wiring (`get_request_db_session`, `get_source_principal`) exactly as the old `app/api/mindmap.py` did; for `POST /graph/extract` use the `require_admin_access` dependency (see `app/api/indexing.py:89`) and `BackgroundJobService.enqueue(task_type=TASK_CONCEPT_EXTRACTION, payload={"reason": "manual"})`, returning 202 with the job id.

In `app/main.py`: replace the mindmap import/include with `from app.api.graph import router as graph_router` + `app.include_router(graph_router)`. Delete `app/api/mindmap.py` and both mindmap test files (`git rm`).

- [ ] **Step 3:** New tests pass; full suites pass (e2e will FAIL on mindmap UI assertions — that fallout is fixed in Task 7; if running e2e here, note it and proceed); lint; commit `feat: add concept graph API, remove mindmap endpoint`.

NOTE: Tasks 6 and 7 must merge together conceptually — the suite is only fully green after Task 7. Run `tests/e2e` at the END of Task 7, not as a gate here.

---### Task 7: Frontend — Graph tab with three views

**Files:**
- Create: `app/ui/static/vendor/cytoscape.min.js`, `app/ui/static/vendor/dagre.min.js`, `app/ui/static/vendor/cytoscape-dagre.js`
- Modify: `app/ui/templates/index.html` (tab + panel markup, script tags), `app/ui/static/app.js` (replace mindmap module), `app/ui/static/app.css` (graph styles)
- Test: `tests/e2e/test_ui.py` (replace mindmap assertions)

- [ ] **Step 1: Vendor the libraries**

```bash
mkdir -p app/ui/static/vendor
curl -fsSL https://unpkg.com/cytoscape@3.30.2/dist/cytoscape.min.js -o app/ui/static/vendor/cytoscape.min.js
curl -fsSL https://unpkg.com/dagre@0.8.5/dist/dagre.min.js -o app/ui/static/vendor/dagre.min.js
curl -fsSL https://unpkg.com/cytoscape-dagre@2.5.0/cytoscape-dagre.js -o app/ui/static/vendor/cytoscape-dagre.js
head -c 200 app/ui/static/vendor/cytoscape.min.js   # sanity: real JS, not an error page
```

- [ ] **Step 2: Update e2e tests first (failing)**

In `tests/e2e/test_ui.py`: remove/replace every `mindmap` assertion (grep the file). New assertions following its string-assert style:

```python
def test_ui_exposes_graph_tab_wiring(client) -> None:  # adapt fixture name to file
    page = client.get("/")
    assert 'id="tab-graph"' in page.text
    assert 'id="panel-graph"' in page.text
    assert 'vendor/cytoscape.min.js' in page.text

    js_response = client.get("/static/app.js")
    assert 'getJson("/graph")' in js_response.text
    assert "renderGraphView" in js_response.text
    assert "graph-view-cluster" in js_response.text
    assert "graph-view-radial" in js_response.text
    assert "graph-view-order" in js_response.text
    assert "askAboutConcept" in js_response.text

    vendor = client.get("/static/vendor/cytoscape.min.js")
    assert vendor.status_code == 200
```

Run → FAIL.

- [ ] **Step 3: Replace the tab markup**

In `app/ui/templates/index.html`: rename the mindmap tab/panel (lines ~79 and ~171-180) to:

```html
<button class="tab" id="tab-graph" type="button" role="tab" aria-selected="false"
        aria-controls="panel-graph" tabindex="-1" data-tab="graph">知識圖譜</button>
```

```html
<section class="workspace-panel" id="panel-graph" role="tabpanel" tabindex="0"
         data-panel="graph" aria-labelledby="tab-graph" hidden>
  <div class="panel-header">
    <h2>知識圖譜</h2>
    <div class="graph-toolbar">
      <input class="graph-search" id="graph-search" type="search" placeholder="搜尋概念…" />
      <div class="graph-view-toggle" role="group" aria-label="圖譜視角">
        <button class="graph-view-button is-active" type="button" id="graph-view-cluster">叢集</button>
        <button class="graph-view-button" type="button" id="graph-view-radial">放射</button>
        <button class="graph-view-button" type="button" id="graph-view-order">學習順序</button>
      </div>
      <button class="secondary-button" type="button" id="load-graph">載入圖譜</button>
    </div>
  </div>
  <div class="graph-canvas" id="graph-canvas"></div>
  <p class="graph-empty" id="graph-empty">尚未建立知識圖譜。請先建立索引並執行概念抽取。</p>
</section>
```

Add before the existing `app.js` script tag:

```html
<script src="/static/vendor/cytoscape.min.js"></script>
<script src="/static/vendor/dagre.min.js"></script>
<script src="/static/vendor/cytoscape-dagre.js"></script>
```

- [ ] **Step 4: Replace the mindmap JS module**

In `app/ui/static/app.js`: delete the mindmap state fields, element refs, and functions (`bindMindmap`, `loadMindmap`, `renderMindmap`, `refreshMindmapAfterContentChange` — grep `mindmap` and remove all hits), then add the graph module. Core code (follow the file's existing idioms — `$`, `getJson`, `state`, `elements`, `emptyText`, the tab registry where `mindmap` is listed as a tab name must become `graph`):

```javascript
  // --- knowledge graph ---
  const CLUSTER_COLORS = ["#4285f4", "#34a853", "#f9ab00", "#ea4335", "#9334e6",
    "#12a4af", "#e8710a", "#7b1fa2", "#1565c0", "#2e7d32", "#c2185b", "#5d4037"];

  function bindGraph() {
    elements.loadGraph.addEventListener("click", loadGraph);
    elements.graphViewCluster.addEventListener("click", () => setGraphView("cluster"));
    elements.graphViewRadial.addEventListener("click", () => setGraphView("radial"));
    elements.graphViewOrder.addEventListener("click", () => setGraphView("order"));
    elements.graphSearch.addEventListener("input", filterGraphNodes);
  }

  async function loadGraph() {
    try {
      state.graph = await getJson("/graph");
      state.graphLoaded = true;
      renderGraphView(state.graphView || "cluster");
    } catch (error) {
      state.graphLoaded = false;
      elements.graphEmpty.hidden = false;
      elements.graphEmpty.textContent = "圖譜載入失敗，請稍後再試。";
    }
  }

  function graphElements() {
    const clusterColor = new Map();
    (state.graph.clusters || []).forEach((cluster, index) => {
      clusterColor.set(cluster.id, CLUSTER_COLORS[index % CLUSTER_COLORS.length]);
    });
    const parents = (state.graph.clusters || []).map((cluster) => ({
      data: { id: `cluster:${cluster.id}`, label: cluster.name, isCluster: true },
    }));
    const nodes = (state.graph.nodes || []).map((node) => ({
      data: {
        id: node.id,
        label: node.name,
        summary: node.summary,
        parent: node.cluster_id ? `cluster:${node.cluster_id}` : undefined,
        color: clusterColor.get(node.cluster_id) || "#62717f",
        size: 18 + Math.min(22, node.source_count * 4),
      },
    }));
    const edges = (state.graph.edges || []).map((edge, index) => ({
      data: { id: `e${index}`, source: edge.source, target: edge.target, kind: edge.kind },
    }));
    return { parents, nodes, edges };
  }

  const GRAPH_LAYOUTS = {
    cluster: { name: "cose", animate: false, padding: 24, nodeRepulsion: 9000 },
    radial: { name: "concentric", animate: false, padding: 24, minNodeSpacing: 28,
      concentric: (node) => (node.data("isCluster") ? 2 : 1), levelWidth: () => 1 },
    order: { name: "dagre", rankDir: "LR", animate: false, padding: 24 },
  };

  function renderGraphView(view) {
    state.graphView = view;
    document.querySelectorAll(".graph-view-button").forEach((button) => {
      button.classList.toggle("is-active", button.id === `graph-view-${view}`);
    });
    if (!state.graphLoaded) return;
    const hasNodes = (state.graph.nodes || []).length > 0;
    elements.graphEmpty.hidden = hasNodes;
    if (!hasNodes) return;

    const { parents, nodes, edges } = graphElements();
    const useCompound = view === "cluster";
    const orderView = view === "order";
    if (state.cy) state.cy.destroy();
    state.cy = cytoscape({
      container: elements.graphCanvas,
      elements: [...(useCompound ? parents : []), ...nodes, ...edges],
      layout: GRAPH_LAYOUTS[view],
      style: [
        { selector: "node", style: {
          label: "data(label)", "font-size": 11, width: "data(size)", height: "data(size)",
          "background-color": "data(color)", "text-valign": "bottom", "text-margin-y": 4 } },
        { selector: "node[?isCluster]", style: {
          "background-opacity": 0.08, "border-width": 1.5, "border-color": "#aaa",
          label: "data(label)", "font-size": 14, "font-weight": 700,
          "text-valign": "top", shape: "round-rectangle" } },
        { selector: "edge", style: {
          width: 1.4, "line-color": "#c4ccd4", "curve-style": "bezier" } },
        { selector: 'edge[kind = "prerequisite"]', style: {
          "target-arrow-shape": "triangle", "target-arrow-color": "#8a96a3",
          "line-color": "#8a96a3" } },
        { selector: 'edge[kind = "part_of"]', style: { "line-style": "dashed" } },
        ...(orderView
          ? [{ selector: 'edge[kind != "prerequisite"]', style: { opacity: 0.25 } }]
          : []),
        { selector: "node.dimmed", style: { opacity: 0.15 } },
        { selector: "node.highlighted", style: { "border-width": 3, "border-color": "#162029" } },
      ],
    });
    state.cy.on("tap", "node[^isCluster]", (event) => previewConcept(event.target.id()));
  }

  function setGraphView(view) { renderGraphView(view); }

  function filterGraphNodes() {
    if (!state.cy) return;
    const query = elements.graphSearch.value.trim().toLowerCase();
    state.cy.nodes("[^isCluster]").forEach((node) => {
      const match = !query || node.data("label").toLowerCase().includes(query);
      node.toggleClass("dimmed", !match);
      node.toggleClass("highlighted", Boolean(query) && match);
    });
  }

  async function previewConcept(conceptId) {
    const detail = await getJson(`/graph/concepts/${conceptId}`);
    // Render into the right inspector using the existing preview pane helpers:
    // title = detail.name, body = detail.summary, then a list of detail.sources
    // where each row is a button reusing the existing section-preview click path
    // (same behaviour the old mindmap section buttons used), plus:
    //   <button id="ask-about-concept">去問問題</button>
    // wired to askAboutConcept(detail.name).
  }

  function askAboutConcept(name) {
    elements.chatInput.value = `請解釋「${name}」，以及它和課程裡其他概念的關係。`;
    activateTab("chat");
    elements.chatInput.focus();
  }
```

The implementer must: register `graph` in the tab-switching registry (where `mindmap` appears), add the new element refs (`graphCanvas`, `graphEmpty`, `graphSearch`, `loadGraph`, `graphViewCluster`, `graphViewRadial`, `graphViewOrder`) to the `elements` map, call `bindGraph()` where `bindMindmap()` was called, implement `previewConcept`'s inspector rendering with the file's real helper names (read the old `renderMindmap` section-preview code BEFORE deleting it and reuse its preview call), and replace `refreshMindmapAfterContentChange` with `refreshGraphAfterContentChange` (re-fetch when `state.graphLoaded`). `activateTab("chat")` in `askAboutConcept` is a stand-in — use the file's real tab-switching helper (find how clicking a `.tab` button switches panels and call that). Where this plan's snippet conflicts with an existing idiom, the file's idiom wins — keep names from the e2e assertions stable.

Cluster expand/collapse (cluster view, spec §4): lightweight custom implementation, no extra plugin — on `tap` of a cluster compound node, toggle `display: none` on its child nodes and their connected edges, and show a `(+N)` suffix in the collapsed cluster's label; track collapsed cluster ids in `state.collapsedClusters` (a Set) and reapply after `renderGraphView` re-creates the instance. ~20 lines next to `renderGraphView`.

- [ ] **Step 5: CSS** — append to `app/ui/static/app.css`:

```css
.graph-canvas { height: 560px; border: 1px solid var(--border); border-radius: 8px; background: var(--surface); }
.graph-toolbar { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.graph-search { min-width: 180px; }
.graph-view-toggle { display: inline-flex; border: 1px solid var(--border); border-radius: 6px; overflow: hidden; }
.graph-view-button { border: 0; background: var(--surface); padding: 6px 12px; cursor: pointer; }
.graph-view-button.is-active { background: var(--accent); color: #fff; }
.graph-empty { color: var(--muted); }
```

- [ ] **Step 6:** e2e tests pass (`uv run --python 3.12 pytest tests/e2e -q`); full unit + integration suites pass; lint clean. Manual smoke (optional but recommended): start the app, seed a tiny graph via Task 5's script with a 2-concept fixture, click through the three views.

- [ ] **Step 7: Commit** — `git add app/ui tests/e2e && git commit -m "feat: replace mindmap with three-view knowledge graph tab"`

---

### Task 8: Curated dataset + initial seeding (CONTROLLER-RUN — not a code subagent)

This task is executed by the plan controller in-session (per spec §2b the initial
graph is curated by the assistant, not the API pipeline). Requires Tasks 1, 5, 6
shipped and migration applied to the live `kb` DB.

- [ ] **Step 1: Apply migration + dump the section inventory**

```bash
KB_DATABASE_URL=postgresql+psycopg://kb:kb@localhost:5432/kb uv run --python 3.12 alembic upgrade head
docker compose exec -T postgres psql -U kb -d kb -At -F $'\t' -c \
  "SELECT d.filename, s.source_id, s.heading FROM sections s JOIN documents d ON d.id = s.document_id WHERE d.lifecycle_status = 'active' ORDER BY d.filename, s.position;" \
  > tmp/section-inventory.tsv
wc -l tmp/section-inventory.tsv   # expect ~819
```

- [ ] **Step 2: Fan out extraction subagents** — dispatch parallel read-only subagents, each assigned 5-7 course files from `course-materials-md/` plus their slice of the inventory (exact source_ids). Each returns JSON: concepts (name, summary in Traditional Chinese, source_ids strictly from its slice, aliases where the material uses synonyms) and intra-document edges (kinds: prerequisite/part_of/related), honoring the ≤30-concepts-per-doc cap and the dataset schema from Task 5.

- [ ] **Step 3: Controller merge + clustering** — merge subagent outputs: unify duplicate concepts across documents (same idea, different files — union their source_ids, keep one canonical name + aliases), assign every concept to one of 10-20 named clusters, add cross-document edges where clearly justified by the material, normalize slugs via the same rules as `slugify_concept`. Target ~100-200 concepts total. Write to `docs/plans/2026-06-11-concept-graph-seed.json`.

- [ ] **Step 4: Validate + seed + verify**

```bash
KB_DATABASE_URL=postgresql+psycopg://kb:kb@localhost:5432/kb \
  uv run --python 3.12 python -m scripts.seed_concept_graph \
  --file docs/plans/2026-06-11-concept-graph-seed.json --dry-run   # validation only
KB_DATABASE_URL=postgresql+psycopg://kb:kb@localhost:5432/kb \
  uv run --python 3.12 python -m scripts.seed_concept_graph \
  --file docs/plans/2026-06-11-concept-graph-seed.json
docker compose exec -T postgres psql -U kb -d kb -c \
  "SELECT (SELECT count(*) FROM concepts), (SELECT count(*) FROM concept_edges), (SELECT count(*) FROM concept_clusters), (SELECT count(*) FROM concept_extraction_state);"
```

Expect: concepts 100-200, clusters 10-20, extraction_state rows = 35 (so the pipeline treats all current documents as done).

- [ ] **Step 5: Commit the dataset** — `git add docs/plans/2026-06-11-concept-graph-seed.json && git commit -m "feat: seed curated concept graph for current course materials"`

---

### Task 9: Real-API pipeline validation, acceptance, docs

- [ ] **Step 1: Small-sample real-API validation** — force re-extraction of 2 documents and verify the pipeline + merge behave against the seeded graph:

```bash
docker compose exec -T postgres psql -U kb -d kb -c \
  "DELETE FROM concept_extraction_state WHERE document_id IN (SELECT id FROM documents WHERE filename IN ('1-基本觀念-03-CAP Theorem.md', '1-基本觀念-09-Caching.md'));"
KB_DATABASE_URL=postgresql+psycopg://kb:kb@localhost:5432/kb KB_ANSWER_PROVIDER=openai KB_EMBEDDING_PROVIDER=openai \
  uv run --python 3.12 python -m scripts.run_background_worker --once   # check the script's actual once-flag (make worker-once)
```

(Enqueue first via the admin endpoint or `BackgroundJobService` — check how `make worker-once` drives a single job; simplest: `curl -X POST localhost:8000/graph/extract -H "X-KB-Admin-Key: ..."` with the app running, then `make worker-once` semantics.) Verify: extraction_state restored for both documents; concept count did NOT balloon (merge mapped re-extracted concepts onto existing ones — tolerate a small drift, investigate if >15 net new concepts); spot-read 5 re-extracted concepts for quality.

- [ ] **Step 2: Full verification sweep** — unit + integration + e2e suites, `make lint`, `docker build -t kb-check .`.

- [ ] **Step 3: UI acceptance** — app running with seeded graph: the Graph tab renders all three views, search filters, concept click shows sources in the right pane, 去問問題 prefills chat. Use the browser preview/screenshot tooling if available; otherwise document manual verification.

- [ ] **Step 4: Docs + commit** — README (Graph tab + 3 new `KB_GRAPH_*` settings + seed/extract Make targets), `AGENTS.md` (concept graph snapshot bullet: tables, pipeline chaining, seeded-state behavior), `ops/deploy.md` (deploy step: run `make graph-seed` once after migration; future uploads auto-extract). Commit `docs: document knowledge graph`.

---

## Completion checklist (gates from the spec)

- [ ] All suites green (unit/integration/e2e) + lint + docker build
- [ ] `/graph` serves the seeded graph with visibility filtering; `/mindmap` is gone
- [ ] Seeded: 100-200 concepts, 10-20 clusters, extraction_state rows for all 35 documents
- [ ] Real-API sample run: 2 documents re-extracted without ballooning the concept count
- [ ] Three views render and interact correctly in the learner UI
- [ ] Docs updated (README, AGENTS.md, ops/deploy.md)
