# Learner Feedback and Citation Drilldown Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add learner-facing numeric citations, citation drilldown, and answer feedback controls.

**Architecture:** Preserve exact source IDs in backend validation and storage. Render display-only numeric citation buttons in the browser and submit learner feedback through the existing `/feedback` API.

**Tech Stack:** FastAPI, SQLAlchemy, vanilla JavaScript, CSS, pytest, TestClient, Playwright/browser verification.

---

### Task 1: Static UI Contract Tests

**Files:**
- Modify: `tests/e2e/test_ui.py`

**Step 1: Write failing tests**

Add assertions that `/static/app.js` includes `renderAnswerCitations`, `citationLabelForSource`, `submitAnswerFeedback`, `feedbackExpectedSource`, and `fetch("/feedback"`.

**Step 2: Run test to verify it fails**

Run: `uv run --python 3.12 pytest tests/e2e/test_ui.py::test_ui_exposes_learner_chat_polish_wiring -q`

Expected: FAIL because the new helpers do not exist yet.

### Task 2: Citation Rendering

**Files:**
- Modify: `app/ui/static/app.js`
- Modify: `app/ui/static/app.css`

**Step 1: Implement minimal UI logic**

Add helpers to map source IDs to numbers, replace bracketed source-id citations with inline buttons, and preview the cited source on click.

**Step 2: Verify static tests**

Run: `uv run --python 3.12 pytest tests/e2e/test_ui.py::test_ui_exposes_learner_chat_polish_wiring -q`

Expected: PASS.

### Task 3: Learner Feedback Controls

**Files:**
- Modify: `app/ui/static/app.js`
- Modify: `app/ui/static/app.css`

**Step 1: Implement controls**

Render Helpful, Not helpful, and Answer missing controls in each assistant answer footer. Submit to `/feedback` with the assistant message ID from the stream `done` payload.

**Step 2: Verify focused UI tests**

Run: `uv run --python 3.12 pytest tests/e2e/test_ui.py -q`

Expected: PASS.

### Task 4: Runtime Browser Check

**Files:**
- No source edits unless the browser check exposes a bug.

**Step 1: Run the app with sample docs**

Run migrations, start the app on a non-conflicting port, index `sample-docs/`, and submit `課程網站在哪裡？`.

**Step 2: Verify behavior**

Confirm the visible answer contains `[1]`, clicking `[1]` updates `Previewed Source`, and feedback posts successfully.

### Task 5: Final Verification and Commit

**Files:**
- Stage only touched docs, UI, and tests.

**Step 1: Run verification**

Run focused UI tests, unit tests if affected, `make lint`, and `git diff --check`.

**Step 2: Commit**

Commit message: `feat: add learner feedback citation drilldown`.

