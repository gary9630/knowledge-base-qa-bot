# Knowledge Graph Design

Date: 2026-06-11
Status: Approved
Scope: Sub-project 2 of 4 (RAG context expansion → **knowledge graph** → UI redesign →
production readiness). This document covers only the knowledge graph.

## Problem

The current "mindmap" (`app/api/mindmap.py` + DOM tree rendering in `app.js`) is a
two-level document→section indented list derived from Markdown headings. It shows the
file structure, not the knowledge structure: no concepts, no cross-document
relationships, no way for a learner to grasp how the course's ideas connect. Course
materials are uploaded continuously, so whatever replaces it must update incrementally.

## Decisions (user-confirmed)

1. Primary purpose: whole-course overview + navigation ("what's in this course, how do
   the pieces relate, click to read"). Prerequisite ordering is an edge type, not a
   full learning-path planner.
2. Granularity: two layers — topic clusters (~10–20, LLM-named) containing concept
   nodes (~100–200 total, e.g. "Consistent Hashing", "Quorum"), each concept linked to
   its source sections.
3. Backend: incremental LLM extraction as a background job + Postgres storage
   (option A; embedding-clustering-only and full-corpus-per-rebuild rejected for
   quality and incremental-cost reasons respectively).
4. Frontend: clustered force-directed graph as the default view (Cytoscape.js), with
   two alternative view modes the learner can toggle: radial (cluster-membership
   emphasis) and layered tech-tree (prerequisite emphasis). All three views render
   the same `/graph` data with different layouts — no backend difference.

## Design

### 1. Data model (one Alembic migration, four tables + one state table)

- `concept_clusters`: id (UUID), name (Text, zh-TW), position (Integer, stable
  ordering), timestamps.
- `concepts`: id (UUID), name (Text, canonical zh-TW), slug (Text, unique),
  summary (Text, 1–2 sentences), cluster_id (FK → concept_clusters, SET NULL),
  aliases (JSONB list of strings), timestamps.
- `concept_edges`: id, source_concept_id (FK CASCADE), target_concept_id
  (FK CASCADE), kind (Text: `prerequisite` directed | `part_of` | `related`
  undirected), unique (source, target, kind). Undirected kinds store one row with
  (source, target) ordered by id to avoid mirror duplicates.
- `concept_sources`: concept_id (FK CASCADE), section_id (FK → sections CASCADE),
  unique pair. Powers click-through to materials and automatic cleanup when sections
  are deleted.
- `concept_extraction_state`: document_id (FK CASCADE, unique), content_hash,
  extracted_at. Drives incremental extraction (re-extract only changed documents).

Concepts whose `concept_sources` count drops to zero are deleted during the merge
step (their edges cascade).

### 2. Extraction pipeline (background job, four steps)

New background task `TASK_CONCEPT_EXTRACTION`, enqueued automatically by the worker
after a successful `TASK_INDEX_REBUILD` (same chaining pattern as ingest→index).
Manual trigger: admin `POST /graph/extract` (admin-key gated) and a Make target.

1. **Per-document extraction.** For each active document whose `content_hash`
   differs from `concept_extraction_state` (or has no state row): one LLM call with
   the document's sections (split into multiple calls only when over a token budget,
   measured with the existing tokenization module). Output JSON: concepts
   `{name, summary, source_section_slugs}` and intra-document edges
   `{source_name, target_name, kind}`. Strict validation: malformed entries are
   dropped; per-document caps prevent runaway output (concepts capped by
   `KB_GRAPH_MAX_CONCEPTS_PER_DOC`, edges by a code constant of 2× that cap);
   section slugs that don't exist in the document are discarded.
2. **Global merge.** Exact-name match first, then one LLM call given (new concept
   names + existing concept names/aliases) returning a merge mapping; merged names
   become aliases. `concept_sources` and edges are remapped to canonical concepts.
3. **Cluster assignment.** One LLM call grouping the full concept list into 10–20
   named clusters. Existing cluster names are passed in and reused where they still
   fit, so cluster identity is stable across incremental runs; only new/orphaned
   concepts get (re)assigned unless the concept set changed by more than 30%.
4. **Cross-document edges.** Per cluster, one LLM call proposing edges among the
   cluster's concepts (the merge step already connects same-concept-multi-document
   cases). Validated and capped like step 1.

Failure handling: a document failing extraction is recorded in job stats and does not
abort the run (its previous concepts stay); the job uses existing background-job
retry. LLM calls go through an injectable ChatCaller protocol (same pattern as
`scripts/generate_eval_cases.py`) so tests use a fake; the OpenAI implementation uses
the configured chat model and records provider telemetry so budget guardrails see
extraction usage.

Cost envelope: initial run over 35 documents ≈ 40–50 gpt-5.4-mini calls; each
subsequent upload pays 1 call per changed document + merge + (sometimes) cluster and
cluster-edge calls.

### 3. API

- `GET /graph` (learner, session-gated like `/mindmap` today, same visibility
  filtering): `{clusters: [{id, name, position}], nodes: [{id, name, slug, summary,
  cluster_id, source_count}], edges: [{source, target, kind}], stats: {concept_count,
  cluster_count, edge_count, extracted_at}}`. Node size in the UI derives from
  `source_count`.
- `GET /graph/concepts/{id}`: `{id, name, summary, aliases, cluster, sources:
  [{section_id, document_id, source_id, filename, heading}]}` — feeds the right-pane
  preview; sections are visibility-filtered.
- `POST /graph/extract` (admin): enqueue extraction job; returns job id.
- The legacy `GET /mindmap` endpoint, its response builder, and its tests are
  REMOVED in the same change that ships the new tab (no transition period; single
  deploy).

### 4. Frontend (Mindmap tab becomes Graph tab)

- **Library:** Cytoscape.js + fcose layout + cytoscape-dagre, vendored as static
  files under `app/ui/static/vendor/` (repo has no build tooling; keep it that way).
- **Three view modes**, one data payload, toggle buttons top-right; selected node and
  right-pane preview persist across view switches:
  - **Cluster view (default):** fcose force layout; clusters as compound nodes with
    tinted hulls; concepts colored by cluster; node diameter ∝ source_count; edge
    styles: prerequisite = directed arrow, part_of = dashed, related = thin line.
  - **Radial view:** concentric layout — course at center, clusters as ring sectors,
    concepts on the outer ring grouped by cluster.
  - **Learning-order view:** dagre left→right layered by `prerequisite` edges;
    `related`/`part_of` edges dimmed; concepts with no prerequisite relations are
    placed in their cluster's column block.
- **Interactions:** pan/zoom; cluster expand/collapse (cluster view); a search box
  filtering/highlighting nodes by name or alias; click concept → right inspector
  shows summary + source sections (reuses the existing section preview
  infrastructure) + a "去問問題" button that switches to the chat tab with the input
  prefilled ("請解釋「{concept}」…" style prompt) — it does not auto-send.
- **Refresh:** the existing after-content-change hook reloads `/graph`. Empty state
  (no extraction yet) shows guidance text; extraction-in-progress shows the job
  status line for admins.

### 5. Testing

- Unit: LLM output parsing/validation (caps, malformed entries, unknown slugs),
  merge mapping application, cluster reuse logic, undirected-edge normalization,
  `/graph` response shape + visibility filtering.
- Integration (Postgres): fake-caller end-to-end — extraction job → tables →
  `/graph` and `/graph/concepts/{id}`; incremental run re-extracts only the changed
  document; deleting a document removes its orphaned concepts; worker chains
  extraction after index rebuild.
- E2E: Graph tab markup, vendored script presence, JS wiring assertions in the
  repo's existing string-assert style; `/mindmap` assertions removed.
- Acceptance (operator step): run real extraction on the 35-file corpus; sanity
  check ~10 concepts/edges for quality and the cluster count is 10–20; existing
  retrieval/live-answer acceptance unaffected (graph work touches no retrieval
  code).

## New configuration

| Setting | Default | Meaning |
| --- | --- | --- |
| `KB_GRAPH_EXTRACTION_ENABLED` | `true` | Auto-chain extraction after index rebuild |
| `KB_GRAPH_MAX_CONCEPTS_PER_DOC` | `30` | Validation cap per document |
| `KB_GRAPH_EXTRACTION_TOKEN_BUDGET` | `12000` | Max tokens of section text per extraction call |

## Out of scope

Learning-path planner (progress tracking, "what should I study next" recommendations),
graph editing by admins, concept-level embeddings for retrieval, UI visual redesign
(sub-project 3 — the graph tab ships functional with current styling and gets
restyled there), multi-course graphs.
