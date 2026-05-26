# Platform Auth Hardening Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a single-user platform login with signed cookie sessions, CSRF protection, and protected product APIs while keeping admin API-key workflows intact.

**Architecture:** Add a small auth module that signs/verifies platform session cookies using HMAC-SHA256. FastAPI dependencies enforce platform sessions on product APIs and preserve the existing admin-key dependency for admin APIs. The vanilla JS workbench handles login/logout, stores the CSRF token in memory, and attaches it to state-changing requests.

**Tech Stack:** Python 3.12, FastAPI, Pydantic settings, stdlib `hmac`/`hashlib`/`secrets`, pytest, TestClient, vanilla HTML/CSS/JS.

---

## Task 1: Auth Settings and Session Tokens

**Files:**
- Modify: `app/core/config.py`
- Create: `app/auth/__init__.py`
- Create: `app/auth/sessions.py`
- Test: `tests/unit/test_platform_auth.py`

**Step 1: Write failing tests**

Cover token creation, successful verification, tamper rejection, expiry rejection, and safe development defaults.

**Step 2: Run red test**

Run:

```bash
uv run --python 3.12 pytest tests/unit/test_platform_auth.py -q
```

Expected: FAIL because `app.auth.sessions` does not exist.

**Step 3: Implement minimal auth core**

Add settings:

```text
auth_secret_key
platform_username
platform_password
platform_session_ttl_seconds
```

Implement:

```text
PlatformSession
create_platform_session_token()
verify_platform_session_token()
verify_platform_credentials()
platform_auth_is_configured()
platform_auth_requires_configuration()
```

Use signed JSON payloads with base64url encoding and HMAC-SHA256.

**Step 4: Verify**

Run the targeted unit test.

## Task 2: Auth API and Platform Dependency

**Files:**
- Create: `app/api/auth.py`
- Modify: `app/api/dependencies.py`
- Modify: `app/main.py`
- Modify: product API route files:
  - `app/api/search.py`
  - `app/api/chat.py`
  - `app/api/sources.py`
  - `app/api/mindmap.py`
  - `app/api/feedback.py`
- Test: `tests/unit/test_api_dependencies.py`
- Test: `tests/integration/test_auth_workflow.py`

**Step 1: Write failing tests**

Cover:

```text
POST /auth/login sets cookie and returns csrf token
GET /auth/session reports authenticated session
POST /auth/logout clears cookie
configured platform auth blocks protected product APIs without login
unsafe cookie-authenticated requests require X-KB-CSRF-Token
development remains open when credentials are absent
production/staging fail closed when credentials are absent
admin API-key workflows still pass without platform session
```

**Step 2: Run red tests**

Run:

```bash
uv run --python 3.12 pytest tests/unit/test_api_dependencies.py tests/integration/test_auth_workflow.py -q
```

Expected: FAIL because auth routes/dependencies are missing.

**Step 3: Implement API layer**

Add:

```text
POST /auth/login
POST /auth/logout
GET /auth/session
require_platform_access()
```

Attach `require_platform_access` to product APIs only. Keep admin-key auth unchanged for admin APIs.

**Step 4: Verify**

Run targeted tests.

## Task 3: Workbench Login UI and CSRF Headers

**Files:**
- Modify: `app/ui/templates/index.html`
- Modify: `app/ui/static/app.js`
- Modify: `app/ui/static/app.css`
- Test: `tests/e2e/test_ui.py`

**Step 1: Write failing tests**

Assert:

```text
login form exists
logout button exists
JS calls /auth/session, /auth/login, /auth/logout
state-changing fetches include X-KB-CSRF-Token
admin key inputs remain present for admin-only operations
```

**Step 2: Run red test**

Run:

```bash
uv run --python 3.12 pytest tests/e2e/test_ui.py::test_ui_exposes_platform_login_wiring -q
```

Expected: FAIL because UI login wiring does not exist.

**Step 3: Implement UI**

Add login shell, login form, logout button, auth status, and in-memory CSRF token. Disable workbench interaction until authenticated when auth is configured.

**Step 4: Verify**

Run the targeted UI test.

## Task 4: Docs, Full Verification, and Commit

**Files:**
- Modify: `README.md`
- Modify: `.env.example`
- Test: full suite

**Step 1: Update docs**

Document:

```text
KB_AUTH_SECRET_KEY
KB_PLATFORM_USERNAME
KB_PLATFORM_PASSWORD
KB_PLATFORM_SESSION_TTL_SECONDS
platform login behavior
admin key remains separate
```

**Step 2: Verify**

Run:

```bash
uv run --python 3.12 pytest -q
make lint
make docker-test
KB_DOCKER_E2E=1 make test-e2e
```

**Step 3: Commit and push**

Stage only auth hardening files and docs, leaving `.python-version`, `project-ideas.md`, and `sample-docs/` untracked.
