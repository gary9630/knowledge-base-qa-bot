# Provider Budget Guardrails Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add app-native provider budget alerts and optional hard blocking before OpenAI answer-provider calls.

**Architecture:** Extend the existing `Settings`, `InMemoryMetrics`, provider observability API, and chat execution path. Budget evaluation remains in-memory and derives from `InMemoryMetrics.snapshot()` so it fits the current app-native observability foundation.

**Tech Stack:** FastAPI, Pydantic settings, SQLAlchemy-backed chat persistence, vanilla JS/CSS UI, pytest, ruff, mypy.

---

### Task 1: Budget Settings

**Files:**
- Modify: `app/core/config.py`
- Modify: `tests/unit/test_config.py`

**Step 1: Write failing tests**

Add tests that assert default provider budget settings are non-disruptive and env overrides work:

- enabled defaults to true
- token and call limits default to 0
- error-rate limit defaults to 0
- warning ratio defaults to 0.8
- block mode defaults to false

**Step 2: Run tests**

Run:

```bash
uv run --python 3.12 pytest tests/unit/test_config.py -q
```

Expected: fail because settings do not exist.

**Step 3: Implement settings**

Add fields to `Settings` with validation:

- `provider_budget_enabled: bool = True`
- `provider_budget_daily_token_limit: int = Field(default=0, ge=0)`
- `provider_budget_daily_call_limit: int = Field(default=0, ge=0)`
- `provider_budget_error_rate_limit: float = Field(default=0.0, ge=0.0, le=1.0)`
- `provider_budget_warning_ratio: float = Field(default=0.8, ge=0.0, le=1.0)`
- `provider_budget_block_on_exceeded: bool = False`

**Step 4: Verify**

Run the same config tests and confirm they pass.

### Task 2: Budget Evaluator

**Files:**
- Create: `app/provider_budget.py`
- Create: `tests/unit/test_provider_budget.py`

**Step 1: Write failing tests**

Cover:

- disabled budget returns `ok` and no blocking
- token usage at warning ratio returns `warning`
- token usage at or above limit returns `exceeded`
- call usage at or above limit returns `exceeded`
- error rate above limit returns `exceeded`
- exceeded plus block mode returns `should_block=True`

**Step 2: Run tests**

Run:

```bash
uv run --python 3.12 pytest tests/unit/test_provider_budget.py -q
```

Expected: fail because module does not exist.

**Step 3: Implement evaluator**

Create Pydantic models or dataclasses:

- `ProviderBudgetPolicyStatus`
- `ProviderBudgetStatus`

Implement:

```python
def provider_budget_status(settings: Settings, metrics_snapshot: dict[str, Any]) -> ProviderBudgetStatus:
    ...
```

Use `provider_usage_by_key` totals for tokens, `provider_calls_total` for calls, and provider error rate for errors.

**Step 4: Verify**

Run unit budget tests and config tests.

### Task 3: Provider Observability API

**Files:**
- Modify: `app/api/provider_observability.py`
- Modify: `tests/unit/test_provider_observability.py`
- Modify: `tests/integration/test_provider_observability_api.py`

**Step 1: Write failing tests**

Assert `ProviderObservabilityResponse` includes `budget` with overall status, block flag, and policy details.

**Step 2: Run focused tests**

Run:

```bash
uv run --python 3.12 pytest tests/unit/test_provider_observability.py -q
```

Expected: fail because budget is missing.

**Step 3: Implement API response**

Inject settings through `get_app_settings`, evaluate budget from metrics snapshot, and include the serialized budget in the response.

**Step 4: Verify**

Run provider observability unit and integration tests.

### Task 4: Chat Enforcement

**Files:**
- Modify: `app/api/chat.py`
- Create or modify: `tests/unit/test_provider_budget.py`
- Modify: `tests/integration/test_api_workflow.py` or `tests/integration/test_chat_stream.py`

**Step 1: Write failing tests**

Add tests proving:

- `/chat` returns 429 when budget is exceeded and block mode is true.
- answer provider is not called when blocked.
- `/chat/stream` yields an SSE `error` event when blocked.

**Step 2: Run focused tests**

Run the new focused tests and confirm they fail.

**Step 3: Implement gate**

Add a small helper in `chat.py` that:

- reads settings and metrics
- evaluates budget
- raises HTTP 429 before answer provider execution when blocked

Use the same helper in streaming flow before `_stream_answer_response_events`.

**Step 4: Verify**

Run focused chat and stream tests.

### Task 5: Provider Ops UI

**Files:**
- Modify: `app/ui/templates/index.html`
- Modify: `app/ui/static/app.js`
- Modify: `app/ui/static/app.css`
- Modify: `tests/e2e/test_ui.py`

**Step 1: Write failing UI wiring test**

Assert the page includes budget section IDs and JS rendering functions.

**Step 2: Run test**

Run:

```bash
uv run --python 3.12 pytest tests/e2e/test_ui.py::test_ui_exposes_provider_observability_wiring -q
```

Expected: fail because budget UI is missing.

**Step 3: Implement UI**

Add `provider-budget` section and render budget status from `/admin/provider-observability`.

**Step 4: Verify**

Run UI tests and `node --check app/ui/static/app.js`.

### Task 6: Docs and Final Verification

**Files:**
- Modify: `AGENTS.md`

**Step 1: Update docs**

Document the `KB_PROVIDER_BUDGET_*` settings and the enforcement behavior.

**Step 2: Verify**

Run:

```bash
make lint
make test-unit
uv run --python 3.12 pytest tests/e2e/test_ui.py tests/integration/test_provider_observability_api.py -q
node --check app/ui/static/app.js
```

Expected: lint/typecheck pass, unit tests pass, UI tests pass, DB integration tests skip locally unless `KB_DATABASE_URL_TEST` is configured.
