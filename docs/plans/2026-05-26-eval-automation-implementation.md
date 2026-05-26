# Eval Automation and Reporting Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add seeded eval cases, feedback-to-eval promotion, a Docker/CLI scheduled eval runner, and an eval report dashboard.

**Architecture:** Extend the existing eval tables with provenance fields, then move shared run behavior into reusable eval services. FastAPI handles admin APIs and UI data, while Docker/CLI handles scheduled execution outside the web process.

**Tech Stack:** Python 3.12, FastAPI, Pydantic, SQLAlchemy 2, Alembic, pytest, Docker Compose, Makefile, vanilla HTML/CSS/JS.

---

## Ground Rules

- Use TDD: write a failing test, verify it fails, implement, verify it passes.
- Keep scheduling outside FastAPI. Use Docker/CLI runner only.
- Do not stage `.python-version`, `project-ideas.md`, or `sample-docs/`.
- Do not batch-delete files or directories.
- Reuse existing eval response models where practical; avoid a second eval execution path.

## Task 1: Eval Provenance Migration

**Files:**
- Modify: `app/models/tables.py`
- Modify: `app/models/__init__.py`
- Create: `migrations/versions/0005_eval_automation.py`
- Test: `tests/unit/test_model_defaults.py`
- Test: `tests/integration/test_migrations.py`

**Step 1: Write failing tests**

Add assertions that `EvalCase` has JSON defaults plus `source_kind`, `seed_key`, and `promoted_feedback_id`, and that `EvalRun` has `trigger`. Update migration tests to expect the new columns/indexes.

**Step 2: Run tests to verify failure**

Run:

```bash
uv run --python 3.12 pytest tests/unit/test_model_defaults.py -q
```

Expected: FAIL because the model fields do not exist.

**Step 3: Implement migration and models**

Add nullable provenance columns and indexes:

```text
eval_cases.source_kind text default 'manual'
eval_cases.seed_key text nullable unique
eval_cases.promoted_feedback_id uuid nullable unique references feedback(id) on delete set null
eval_runs.trigger text default 'manual'
```

**Step 4: Verify**

Run unit tests locally and migration tests in Docker.

## Task 2: Seed Eval Cases

**Files:**
- Create: `app/evals/cases.py`
- Create: `app/evals/default_seed_cases.json`
- Modify: `app/api/evals.py`
- Create: `scripts/seed_eval_cases.py`
- Test: `tests/unit/test_eval_case_seeding.py`
- Test: `tests/integration/test_evals.py`

**Step 1: Write failing tests**

Cover idempotent seed upsert:

```python
summary = seed_eval_cases(session, [seed])
summary.created == 1
summary.updated == 0
summary = seed_eval_cases(session, [updated_seed])
summary.created == 0
summary.updated == 1
```

Add integration coverage for `POST /evals/seed`.

**Step 2: Run tests to verify failure**

Run:

```bash
uv run --python 3.12 pytest tests/unit/test_eval_case_seeding.py -q
```

Expected: FAIL because `app.evals.cases` is missing.

**Step 3: Implement**

Implement:

```text
EvalSeedCase
EvalSeedSummary
load_default_seed_cases()
seed_eval_cases()
POST /evals/seed
scripts/seed_eval_cases.py
make eval-seed
```

**Step 4: Verify**

Run unit, integration, lint.

## Task 3: Feedback Promotion

**Files:**
- Modify: `app/api/feedback.py`
- Modify: `app/api/evals.py`
- Modify: `app/evals/cases.py`
- Test: `tests/integration/test_evals.py`
- Test: `tests/integration/test_api_workflow.py`

**Step 1: Write failing tests**

Create a conversation, assistant message, feedback row, then promote the feedback. Assert the eval case query comes from the preceding user message, expected sources come from feedback/request, and repeated promotion returns the same eval case.

**Step 2: Run tests to verify failure**

Run:

```bash
uv run --python 3.12 pytest tests/integration/test_evals.py -q
```

Expected: FAIL because promotion endpoints do not exist.

**Step 3: Implement**

Add:

```text
GET /feedback
POST /evals/cases/promote-feedback
```

Promotion stores provenance in `metadata` and uses `promoted_feedback_id` for idempotency.

**Step 4: Verify**

Run integration tests in Docker.

## Task 4: Shared Eval Runner and CLI

**Files:**
- Create: `app/evals/runner.py`
- Create: `scripts/run_evals.py`
- Modify: `app/api/evals.py`
- Modify: `Makefile`
- Modify: `docker-compose.yml`
- Test: `tests/unit/test_eval_runner_cli.py`
- Test: `tests/integration/test_evals.py`

**Step 1: Write failing tests**

Cover:

```text
CLI exits 0 for successful run
CLI exits 2 when --fail-on-regression and eval stats failed > 0
scheduled trigger is persisted to eval_runs
```

**Step 2: Run tests to verify failure**

Run:

```bash
uv run --python 3.12 pytest tests/unit/test_eval_runner_cli.py -q
```

Expected: FAIL because the CLI does not exist.

**Step 3: Implement**

Move common run logic out of `app/api/evals.py` into `app/evals/runner.py`. Add:

```text
python -m scripts.run_evals --trigger scheduled
make eval-run
docker compose --profile eval run --rm eval-runner
```

**Step 4: Verify**

Run unit, integration, Docker tests.

## Task 5: Eval Report Dashboard

**Files:**
- Create: `app/evals/reporting.py`
- Modify: `app/api/evals.py`
- Modify: `app/ui/templates/index.html`
- Modify: `app/ui/static/app.js`
- Modify: `app/ui/static/app.css`
- Test: `tests/unit/test_eval_reporting.py`
- Test: `tests/integration/test_evals.py`
- Test: `tests/e2e/test_ui.py`

**Step 1: Write failing tests**

Cover `GET /evals/report` with no runs, with recent runs, and with failures. Update UI test to assert dashboard wiring:

```text
id="eval-report"
fetch("/evals/report"
id="seed-evals"
id="feedback-promotions"
```

**Step 2: Run tests to verify failure**

Run:

```bash
uv run --python 3.12 pytest tests/unit/test_eval_reporting.py tests/e2e/test_ui.py -q
```

Expected: FAIL because report service and UI wiring do not exist.

**Step 3: Implement**

Add report aggregation and UI rendering for:

```text
case totals
latest run
recent run history
latest failures
worst cases
feedback promotion queue
```

**Step 4: Verify**

Run:

```bash
make lint
uv run --python 3.12 pytest -q
make docker-test
docker compose up --build -d app
KB_DOCKER_E2E=1 make test-e2e
```
