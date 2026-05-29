# Retrieval / Answer Quality Hardening Design

## Context

The product now has a production-ready operational base: platform login, admin audit logs,
source access labels, async ingestion, worker supervision, ingestion diagnostics, CI, Docker
smoke tests, and real OpenAI embedding configuration. The next launch risk is answer quality:
students must get grounded answers with inspectable citations, and admins need enough
diagnostics to understand retrieval misses or citation failures.

## Scope

This pass keeps the single-app, Postgres + pgvector architecture and adds an app-native
quality contract:

- Retrieval results expose diagnostics: strategy, limit, score threshold, raw/merged counts,
  accepted/rejected counts, top score, selected source ids, rejected source ids, strategy
  counts, and score debug data already produced by retrievers.
- Chat responses expose `answer_quality`: whether the provider answer passed citation
  validation, citation errors, selected source ids, cited source ids, and a cannot-confirm
  reason.
- Streaming chat sends retrieval diagnostics with the sources event and answer quality with
  the done event.
- Retrieval events persist diagnostics in existing `scores_json`; no DB migration is needed.
- Eval metrics distinguish retrieval misses from citation problems using top-1 hit,
  retrieval recall, citation recall, citation precision, and answer-validity metrics.
- The right-side UI inspector shows answer quality and score breakdowns without cluttering
  the main student chat.
- `AGENTS.md` records the current quality contract and implementation rules.

Out of scope: LLM rerankers, LLM judge scoring, schema migrations, multi-tenant user
registration, and Prometheus/OpenTelemetry.

## Data Flow

1. `/search` calls `HybridRetriever.search()`.
2. `HybridRetriever` merges raw lexical/vector results, applies the score threshold, and
   returns both selected candidates and a diagnostics payload.
3. `/chat` and `/chat/stream` pass selected candidates to `AnswerService`.
4. `AnswerService` validates citations, retries once in strict mode, and returns
   cannot-confirm with a machine-readable reason when it cannot produce a grounded answer.
5. Chat persistence stores selected sources, cited sources, score-by-source id, retrieval
   diagnostics, and answer quality in `retrieval_events`.
6. The UI renders selected sources and answer quality in the right inspector.

## Error Handling

No-source, low-score, invalid-citation, provider-cannot-confirm, and not-indexed outcomes all
remain successful HTTP responses when the request itself is valid. Provider exceptions still
surface as `502` for non-streaming chat and as streaming error events for SSE. Citation
failures never expose unselected source ids as cited sources.

## Testing

Use TDD with focused tests:

- Unit tests for retrieval diagnostics and answer cannot-confirm reasons.
- Unit tests for chat stream event payloads.
- Unit tests for eval quality metrics.
- Integration tests for `/search`, `/chat`, `RetrievalEvent.scores_json`, and streaming event
  diagnostics.
- UI wiring tests for answer quality inspector and selected-source score details.
- Final verification with unit tests, relevant integration/e2e tests, lint, and Docker smoke
  when feasible.
