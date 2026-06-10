# RAG Context Expansion Design

Date: 2026-06-11
Status: Approved
Scope: Sub-project 1 of 4 (RAG context expansion → knowledge graph redesign → UI
redesign → production readiness). This document covers only sub-project 1.

## Problem

Answer accuracy is limited by what the LLM receives, not by what retrieval finds:

- Vector hits feed only the matched 420-token chunk into the answer prompt
  (`app/retrieval/vector.py:74`), not the full section, and never neighboring
  sections. Cross-paragraph questions lack context.
- Token counting uses whitespace `split()` (`app/indexing/service.py`). Chinese
  course text barely splits, so long Chinese sections are embedded as one oversized
  chunk and context budgets are meaningless.
- Hybrid merge takes the max score per section plus small boosts
  (`app/retrieval/hybrid.py:106`), not a rank-aware fusion.
- Only 5 retrieval + 3 live-answer eval cases exist; changes to retrieval cannot be
  measured.

## Decisions (user-confirmed)

1. Scope: context expansion + tiktoken token counting + RRF fusion + automated eval
   set expansion, in this one sub-project.
2. Architecture: keep chunk-level retrieval unchanged; add a context assembly layer
   between retrieval and answer generation (option A; options B "fat chunks at index
   time" and C "section-level retrieval" rejected for embedding-quality and
   incremental-update costs).
3. Eval set: fully automated LLM generation with an automated self-verification
   pass; no manual review gate.

## Design

### 1. Data model: `Section.position`

- Add nullable `position` (Integer) to `sections`: 0-based document order. Add index
  on `(document_id, position)`.
- One Alembic migration. `IndexingService.rebuild_index()` and
  `reindex_document()` write `position` from parser output order (the parser already
  yields sections in document order).
- Backfill path for existing databases: run `make index` after migrating.
- Graceful degradation: when `position` is NULL (not yet reindexed), the context
  assembler expands hits to full section bodies but skips neighbor expansion.

### 2. Tokenizer: tiktoken

- New dependency `tiktoken`; new module owning encoding access (used by chunking and
  context budgeting). Encoding configurable via `KB_TOKEN_ENCODING`, default
  `o200k_base`.
- `split_section_chunks()` keeps `DEFAULT_CHUNK_TOKEN_LIMIT=420` /
  `DEFAULT_CHUNK_OVERLAP=64` but windows over real token ids, decoding back to text
  with safe UTF-8 boundary handling (never emit replacement characters; adjust
  window edges to valid byte boundaries).
- Side effect: fixes the existing bug where Chinese sections are never split. After
  this change a full reindex re-chunks and re-embeds all content (one-time,
  ~819 sections, negligible embedding cost).
- Startup behavior: if the configured encoding cannot be loaded, fail fast at app
  startup with a clear error.

### 3. Context assembly layer (core)

New module `app/answer/context_assembly.py`, called by `/chat` and `/chat/stream`
between `HybridRetriever.search()` and `AnswerService`. `/search` responses are
unchanged.

- Expansion: each accepted candidate (section-level) loads its full
  `Section.body_md` plus neighbors at `position ± 1..K` within the same document.
  `K = KB_CONTEXT_NEIGHBOR_SECTIONS`, default 1.
- Dedup/merge: when a neighbor is itself a hit, or two hit windows overlap or
  touch, merge into one entry (highest score wins for prioritization).
- Ordering: group by document; order groups by best hit score descending; order
  sections within a group by `position` ascending (reading order).
- Token budget: `KB_CONTEXT_TOKEN_BUDGET`, default 8000 tokens, measured with
  tiktoken over source bodies. Inclusion priority: hit sections by score, then
  neighbors by distance (1 before 2 ... before K) breaking ties by their hit's
  score. Entries that do not fit are dropped. The top-scoring hit is always
  included; if its body alone exceeds the budget, truncate its body at a token
  boundary to fit.
- Output: a list of answer sources where every included section (hit or neighbor)
  carries its own `source_id` (`filename.md#heading-slug`) and is citable —
  compatible with existing citation validation. Plus assembly diagnostics: which
  sources are hits vs expansions, neighbor distance, token usage, drops/truncations.
  Diagnostics ride along in chat response metadata / answer traces.
- Config validation: `KB_CONTEXT_NEIGHBOR_SECTIONS >= 0`,
  `KB_CONTEXT_TOKEN_BUDGET >= 1000`; reject invalid values at settings load.
- Visibility/lifecycle: neighbors come from the same document as the hit, so
  document-level visibility and lifecycle filters already applied during retrieval
  hold for neighbors. Sections are loaded only from active, already-visible
  documents.

### 4. RRF fusion

In `app/retrieval/hybrid.py`:

- Replace per-section max-score merge with Reciprocal Rank Fusion across the
  lexical and vector ranked lists: `rrf = Σ_strategies 1 / (60 + rank)` (rank is
  1-based within each strategy's result list).
- Normalize to [0,1] by dividing by the maximum possible value `2 / 61` (both
  strategies rank 1). A single-strategy rank-1 hit scores 0.5.
- Apply existing source-priority and query-relevance boosts after normalization,
  unchanged.
- Keep per-strategy raw scores and ranks in `debug_scores`; diagnostics shape is
  preserved.
- The score threshold (currently 0.10) changes meaning under normalized RRF. It
  stays configurable; the default is recalibrated during eval comparison and fixed
  before merge (acceptance gate below).

### 5. Automated eval set generation

New `scripts/generate_eval_cases.py` + Make target `eval-generate`, using the
existing OpenAI provider plumbing (works with the configured answer model; no new
provider code).

- Samples sections from active documents and generates ~25 Traditional Chinese
  cases: single-section factual questions, cross-section synthesis questions
  (adjacent sections of one document — these exercise the window expansion), and
  3–5 negative cases with `expected_decision = cannot_confirm`.
- Self-verification pass (because there is no manual review): a second LLM call
  checks that the expected sections actually suffice to answer the question;
  failing candidates are discarded. Generation continues until the target count or
  a bounded number of attempts is reached, and reports how many were discarded.
- Cases are stored through the existing eval-case seeding mechanism with seed keys
  namespaced `auto.*`, so they run under the existing eval runner and metrics
  (top1_hit, retrieval_recall, citation_recall, citation_precision, answer_valid).

### 6. Acceptance workflow

1. Generate the eval set and run a baseline against the current code, before any of
   the changes in this design, recording per-case results.
2. Implement changes; rerun the same eval set.
3. Gates to merge:
   - Existing acceptance stays green: retrieval 5/5, live answers 3/3
     (`ops/live-answer-acceptance.md`).
   - New eval set: retrieval recall and citation recall not below baseline;
     report the full before/after comparison in the PR/plan notes.
   - Full test suite (`make test`) and lint/typecheck (`make lint`) pass.

### 7. Testing & error handling

TDD throughout (superpowers test-driven-development skill).

- Unit: context assembler (neighbor selection, dedup/merge, ordering, budget drops
  and truncation, position-NULL fallback, K=0); tokenization (Chinese/English/mixed
  text, UTF-8 boundary safety, chunk reconstruction); RRF scoring (single/double
  strategy, normalization, boost interaction); config validation bounds.
- Integration: reindex writes `position`; chat flow returns expanded sources and
  assembly diagnostics; citations against expanded neighbors validate.
- Existing 57 test files must stay green.
- Error handling: tiktoken load failure → fail fast at startup; invalid
  expansion/budget config → settings validation error; single-section documents and
  document-edge sections (first/last) expand to whatever neighbors exist.

## New configuration

| Setting | Default | Meaning |
| --- | --- | --- |
| `KB_CONTEXT_NEIGHBOR_SECTIONS` | `1` | Neighbor window K on each side |
| `KB_CONTEXT_TOKEN_BUDGET` | `8000` | Max tokens of source bodies fed to the LLM |
| `KB_TOKEN_ENCODING` | `o200k_base` | tiktoken encoding for chunking and budgeting |

RRF constant `k=60` is a code constant, not configuration.

## Cost note

Per-query input context grows from ~1–2k to up to 8k tokens (~4–5× input cost on
`gpt-5.4-mini`). Provider budget guardrails already exist; raise `KB_PROVIDER_*`
daily token limits accordingly at deploy time.

## Out of scope (later sub-projects)

Knowledge graph redesign (concept extraction + graph UI), UI redesign, production
readiness items (multi-learner auth, HTTPS/reverse proxy, alerting), learned
reranker models.
