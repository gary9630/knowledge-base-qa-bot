# Learner Chat UX Polish Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Polish the learner-facing chat tab so it feels like a production course assistant with guidance, streaming status, citation chips, and clear trust copy.

**Architecture:** Keep the existing FastAPI-served HTML/CSS/vanilla JS UI. Add presentational markup and client-side state in `app/ui/templates/index.html`, `app/ui/static/app.js`, and `app/ui/static/app.css`; no API or schema changes are required.

**Tech Stack:** FastAPI Jinja templates, vanilla JavaScript, CSS, pytest/TestClient e2e wiring tests, Browser or Playwright smoke validation.

---

### Task 1: Static Learner Chat Structure

**Files:**
- Modify: `tests/e2e/test_ui.py`
- Modify: `app/ui/templates/index.html`

**Step 1: Write the failing test**

Add `test_ui_exposes_learner_chat_polish_wiring` asserting the HTML includes:

- `id="learner-chat-status"`
- `id="chat-empty-state"`
- `data-sample-prompt`
- `id="chat-composer-status"`
- `id="chat-submit"`
- `id="chat-answer-template"` or equivalent answer footer/source-chip hook

**Step 2: Run test to verify it fails**

Run:

```bash
uv run --python 3.12 pytest tests/e2e/test_ui.py::test_ui_exposes_learner_chat_polish_wiring -q
```

Expected: FAIL because the new learner chat structure is not present.

**Step 3: Write minimal template implementation**

Update the chat panel in `app/ui/templates/index.html`:

- rename the visible chat heading to "Course Assistant"
- add `#learner-chat-status` in the header
- add `#chat-empty-state` inside `#chat-log`
- add three or four sample prompt buttons with `data-sample-prompt`
- add `#chat-composer-status`
- add `id="chat-submit"` to the submit button
- add stable hooks for answer footer/source chips

**Step 4: Run test to verify it passes**

Run the same focused test. Expected: PASS.

### Task 2: Chat Interaction State

**Files:**
- Modify: `tests/e2e/test_ui.py`
- Modify: `app/ui/static/app.js`

**Step 1: Extend the failing test**

In `test_ui_exposes_learner_chat_polish_wiring`, assert JS includes:

- `bindSamplePrompts`
- `setChatBusy`
- `renderStreamingStatus`
- `renderAnswerFooter`
- `renderSourceChips`
- `handleChatKeydown`
- `event.key === "Enter"`

**Step 2: Run test to verify it fails**

Run:

```bash
uv run --python 3.12 pytest tests/e2e/test_ui.py::test_ui_exposes_learner_chat_polish_wiring -q
```

Expected: FAIL because the JavaScript helpers are missing.

**Step 3: Implement minimal client-side behavior**

Update `app/ui/static/app.js`:

- add elements for sample prompts, submit button, composer status, learner chat status
- bind sample prompt buttons to fill and focus the textarea
- add Enter-to-submit and Shift+Enter newline behavior
- add `setChatBusy(isBusy, statusText)` to disable textarea, select, limit, and send button
- clear the empty state after the first user message
- add streaming status text before sources arrive
- update status when sources arrive
- re-enable composer after success or error

**Step 4: Run test to verify it passes**

Run the same focused test. Expected: PASS.

### Task 3: Answer Footer And Source Chips

**Files:**
- Modify: `tests/e2e/test_ui.py`
- Modify: `app/ui/static/app.js`
- Modify: `app/ui/static/app.css`

**Step 1: Extend the failing test**

Assert JS and CSS include:

- `answer-footer`
- `source-chip`
- `answer-trust`
- `previewCandidate(source)`
- `Answered from`
- `could not confirm`

**Step 2: Run test to verify it fails**

Run:

```bash
uv run --python 3.12 pytest tests/e2e/test_ui.py::test_ui_exposes_learner_chat_polish_wiring -q
```

Expected: FAIL because footer/chip code and styles are missing.

**Step 3: Implement footer and chip rendering**

Update `addMessage` so assistant messages can receive a stable wrapper. Add:

- `renderAnswerFooter(wrapper, payload)`
- `renderSourceChips(wrapper, sources)`
- `answerTrustText(payload, sources)`

For source chips, clicking a chip calls `previewCandidate(source)`.

**Step 4: Add CSS**

Style:

- empty state
- prompt grid
- busy composer
- answer footer
- source chip row
- trust badge states

Keep the visual language restrained and consistent with the current workbench.

**Step 5: Run test to verify it passes**

Run the same focused test. Expected: PASS.

### Task 4: Regression Verification

**Files:**
- Verify only unless test failures require scoped fixes.

**Step 1: Run focused UI tests**

```bash
uv run --python 3.12 pytest tests/e2e/test_ui.py -q
```

Expected: PASS.

**Step 2: Run chat-related unit/integration tests**

```bash
uv run --python 3.12 pytest tests/unit/test_chat_stream_events.py tests/unit/test_answer_service.py tests/integration/test_chat_stream.py -q
```

Expected: PASS, with DB-backed integration skipped if `KB_DATABASE_URL_TEST` is not configured.

**Step 3: Run lint**

```bash
make lint
```

Expected: PASS.

### Task 5: Browser QA

**Files:**
- Verify rendered behavior only.

**Step 1: Start the app**

Use the repo's existing local or Docker workflow. Prefer the already configured app if running.

**Step 2: Validate desktop**

Flow under test:

```text
/ -> learner login if required -> Chat tab -> sample prompt -> streaming answer -> source chip previews source
```

Check:

- page is not blank
- no framework/runtime overlay
- console has no relevant errors
- empty state and prompt buttons render
- composer disabled while request is active
- answer footer renders trust copy
- source chip previews markdown in the right inspector

**Step 3: Validate mobile**

Use a mobile viewport and check:

- no overlapping text
- prompt buttons wrap cleanly
- composer remains usable
- answer footer/chips do not overflow

### Task 6: Commit

**Files:**
- Stage only files changed by this task.

**Step 1: Inspect status**

```bash
git status --short
```

**Step 2: Commit**

```bash
git add docs/plans/2026-05-29-learner-chat-ux-polish-design.md docs/plans/2026-05-29-learner-chat-ux-polish-implementation.md tests/e2e/test_ui.py app/ui/templates/index.html app/ui/static/app.js app/ui/static/app.css
git commit -m "feat: polish learner chat ux"
```

Expected: commit succeeds. Leave unrelated untracked files untouched.
