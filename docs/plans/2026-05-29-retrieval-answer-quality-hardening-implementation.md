# Retrieval / Answer Quality Hardening Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make retrieval misses, citation failures, cannot-confirm behavior, and answer grounding visible and testable across API, streaming chat, evals, UI, and agent instructions.

**Architecture:** Extend existing dataclasses and Pydantic responses without a DB migration. Store richer diagnostics in the existing `retrieval_events.scores_json` JSONB field and render quality data in the existing right-side inspector.

**Tech Stack:** FastAPI, Pydantic, SQLAlchemy, Postgres/pgvector, server-rendered HTML, vanilla JS, pytest, ruff, mypy.

---

### Task 1: Retrieval Diagnostics Contract

**Files:**
- Modify: `app/retrieval/models.py`
- Modify: `app/retrieval/hybrid.py`
- Test: `tests/unit/test_hybrid_retrieval.py`

**Steps:**
1. Write a failing unit test proving `HybridRetriever.search(..., debug=True)` returns diagnostics with threshold, selected ids, rejected ids, strategy counts, and top score.
2. Add a `RetrievalDiagnostics` dataclass and a `diagnostics` field to `RetrievalResult`.
3. Populate diagnostics in `HybridRetriever.search()` for empty, accepted, and rejected-result paths.
4. Run `uv run --python 3.12 pytest tests/unit/test_hybrid_retrieval.py -q`.

### Task 2: Answer Quality Contract

**Files:**
- Modify: `app/answer/service.py`
- Test: `tests/unit/test_answer_service.py`

**Steps:**
1. Write failing tests for `cannot_confirm_reason` on no-source, provider-cannot-confirm, and invalid-citation fallback.
2. Add `cannot_confirm_reason` to `AnswerResult`.
3. Preserve existing citation validation and retry behavior.
4. Run `uv run --python 3.12 pytest tests/unit/test_answer_service.py -q`.

### Task 3: API and Persistence Exposure

**Files:**
- Modify: `app/api/search.py`
- Modify: `app/api/chat.py`
- Test: `tests/unit/test_chat_stream_events.py`
- Test: `tests/integration/test_api_workflow.py`
- Test: `tests/integration/test_chat_stream.py`

**Steps:**
1. Write failing tests asserting `/search` includes `diagnostics`, `/chat` includes `retrieval_diagnostics` and `answer_quality`, stream `sources` includes diagnostics, stream `done` includes answer quality, and `RetrievalEvent.scores_json` stores both.
2. Add Pydantic response models for retrieval diagnostics and answer quality.
3. Thread diagnostics/quality through chat response construction, streaming events, and persistence.
4. Run focused API and stream tests.

### Task 4: Eval Quality Metrics

**Files:**
- Modify: `app/evals/service.py`
- Test: `tests/unit/test_evaluation_service.py`

**Steps:**
1. Write a failing test for top-1 hit, citation precision, and answer-validity metrics.
2. Add metrics without changing eval DB schema.
3. Keep pass/fail rules compatible with existing expected-source behavior.
4. Run `uv run --python 3.12 pytest tests/unit/test_evaluation_service.py -q`.

### Task 5: UI Quality Inspector

**Files:**
- Modify: `app/ui/templates/index.html`
- Modify: `app/ui/static/app.js`
- Modify: `app/ui/static/app.css`
- Test: `tests/e2e/test_ui.py`

**Steps:**
1. Write a failing UI wiring test for `answer-quality`, `renderAnswerQuality`, `retrieval_diagnostics`, `answer_quality`, and selected-source score details.
2. Add a compact right-side answer quality panel.
3. Render retrieval/answer quality from streaming sources and done events.
4. Include score breakdowns in selected source rows and source preview.
5. Run `uv run --python 3.12 pytest tests/e2e/test_ui.py -q`.

### Task 6: Agent Instructions and Verification

**Files:**
- Modify: `AGENTS.md`

**Steps:**
1. Update project instructions with quality contract, diagnostics persistence, eval metrics, and citation grounding rules.
2. Run focused tests, `make lint`, and broad feasible verification.
3. Commit and push the branch.
