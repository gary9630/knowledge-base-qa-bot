# Learner Landing Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a polished student landing/login page and hide admin-side UI from platform learners after login.

**Architecture:** Keep `/` as the single entry point. The unauthenticated state renders a landing/login shell, and the authenticated state renders the existing workbench. Admin-side visibility is controlled by declarative `data-admin-only` markers plus a small JS access policy; backend admin API keys remain the security boundary.

**Tech Stack:** FastAPI + Jinja template, static JavaScript, static CSS, pytest/TestClient UI assertions, optional browser validation through the local FastAPI server.

---

### Task 1: Add failing UI tests for landing and learner-mode admin hiding

**Files:**
- Modify: `tests/e2e/test_ui.py`

**Step 1: Write the failing tests**

Add tests that assert:

- `/` contains `id="landing-preview"`, `id="landing-trust-strip"`, and student-facing login copy.
- Admin tab buttons and admin panels include `data-admin-only`.
- `app.js` includes `applyAccessPolicy`, `isRestrictedLearner`, `tabIsAvailable`, and an `activateTab` guard.
- Existing platform login wiring remains present.

**Step 2: Verify red**

Run:

```bash
uv run --python 3.12 pytest tests/e2e/test_ui.py -q
```

Expected: fails because the landing shell and admin visibility policy are not implemented.

### Task 2: Update the Jinja template

**Files:**
- Modify: `app/ui/templates/index.html`

**Step 1: Implement landing structure**

Replace the compact login shell with a full landing surface containing:

- `landing-copy`
- `landing-preview`
- `landing-trust-strip`
- Existing `platform-login-form`, `platform-username`, `platform-password`, and `platform-auth-status`.

**Step 2: Mark admin-only UI**

Add `data-admin-only` to:

- `tab-uploads`, `tab-ops`, `tab-audit`, `tab-evals`
- `panel-uploads`, `panel-ops`, `panel-audit`, `panel-evals`
- `document-lifecycle-form`
- the `admin-documents` tool section

Keep `tab-sources` visible for learners, but hide the document lifecycle controls.

### Task 3: Add the learner access policy in JavaScript

**Files:**
- Modify: `app/ui/static/app.js`

**Step 1: Cache admin-only elements**

Add `adminOnlySurfaces: $$("[data-admin-only]")`.

**Step 2: Apply policy after auth changes**

Implement:

```javascript
function isRestrictedLearner() {
  return state.auth.authRequired && state.auth.authenticated;
}

function applyAccessPolicy() {
  const restricted = isRestrictedLearner();
  elements.adminOnlySurfaces.forEach((surface) => {
    surface.hidden = restricted;
    surface.setAttribute("aria-hidden", String(restricted));
  });
  if (restricted && !tabIsAvailable(activeTabName())) {
    activateTab("chat");
  }
}
```

**Step 3: Guard tab activation**

Update `activateTab()` and `nextTabForKey()` so restricted learners cannot activate
admin-only tabs and keyboard navigation only rotates through available tabs.

### Task 4: Update CSS for the landing page

**Files:**
- Modify: `app/ui/static/app.css`

Add responsive landing styles with restrained product styling:

- Full-height login shell.
- Two-column desktop layout, single-column mobile layout.
- Product preview panel using real app concepts.
- Form controls sized for touch.
- No marketing-only decorative cards inside cards.

### Task 5: Verify focused tests and lint

Run:

```bash
uv run --python 3.12 pytest tests/e2e/test_ui.py -q
uv run --python 3.12 pytest tests/unit/test_platform_auth.py tests/integration/test_auth_workflow.py -q
make lint
```

Expected: all pass.

### Task 6: Rendered validation

Start the local app:

```bash
make dev
```

Then validate:

- `http://localhost:8000` shows the landing page before login.
- The login form is visible and usable.
- After platform login in a configured auth environment, admin tabs are hidden.
- Desktop and mobile viewports have no obvious overlap or clipping.
