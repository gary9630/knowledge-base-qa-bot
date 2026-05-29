# Observability and Operations Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add request IDs, structured request logs, in-memory JSON metrics, stronger readiness checks, and operator docs for the production MVP.

**Architecture:** Add a small `app/observability` package with middleware and an in-memory metrics store. Register middleware during app creation, expose `/metrics` from the health router, and expand `/ready` in the indexing router using DB, pgvector, Alembic, index, and auth checks. Keep Docker healthcheck on `/health`; add `make ops-check` for liveness/readiness/metrics.

**Tech Stack:** Python 3.12, FastAPI/Starlette middleware, SQLAlchemy, Alembic script metadata, pytest/TestClient, Docker Compose, Makefile.

---

## Task 1: Request ID, Structured Logs, and Metrics Store

**Files:**
- Create: `app/observability/__init__.py`
- Create: `app/observability/middleware.py`
- Create: `app/observability/metrics.py`
- Modify: `app/main.py`
- Test: `tests/unit/test_observability_middleware.py`

**Step 1: Write failing tests**

Cover:

```text
response includes generated X-Request-ID
incoming X-Request-ID is preserved when valid
metrics record request count, status family, route, and average latency
request completion log is JSON and contains request_id/method/path/status_code
unhandled exception increments errors_total
```

**Step 2: Run red tests**

Run:

```bash
uv run --python 3.12 pytest tests/unit/test_observability_middleware.py -q
```

Expected: FAIL because `app.observability` does not exist.

**Step 3: Implement**

Implement:

```text
InMemoryMetrics
RequestObservabilityMiddleware
create_request_id()
request_id_from_headers()
```

Register middleware in `create_app()` and store metrics on `app.state.metrics`.

**Step 4: Verify**

Run the targeted test.

## Task 2: `/metrics` Endpoint

**Files:**
- Modify: `app/api/health.py`
- Test: `tests/unit/test_health_routes.py`

**Step 1: Write failing tests**

Cover:

```text
GET /metrics returns requests_total and latest_requests
metrics endpoint is public
```

**Step 2: Run red tests**

Run:

```bash
uv run --python 3.12 pytest tests/unit/test_health_routes.py -q
```

Expected: FAIL because `/metrics` does not exist.

**Step 3: Implement**

Expose the app metrics snapshot through `GET /metrics`.

**Step 4: Verify**

Run the targeted test.

## Task 3: Strong Readiness Checks

**Files:**
- Modify: `app/api/indexing.py`
- Test: `tests/integration/test_api_workflow.py`
- Test: `tests/integration/test_migrations.py`

**Step 1: Write failing tests**

Cover:

```text
/ready response includes checks.database, checks.pgvector, checks.migrations, checks.index, checks.platform_auth
pgvector is checked through pg_extension
migration head is compared to alembic_version
production/staging platform auth missing makes ready=false
```

**Step 2: Run red tests**

Run in Docker:

```bash
docker compose run --rm -e KB_DATABASE_URL_TEST=postgresql+psycopg://kb:kb@postgres:5432/kb_test test pytest tests/integration/test_api_workflow.py::test_ready_reports_operational_checks -q
```

Expected: FAIL because `/ready` is still minimal.

**Step 3: Implement**

Add readiness helpers for:

```text
database
pgvector
migrations
index
platform_auth
```

Keep HTTP 200 when checks are evaluated but readiness is false. Return 503 only when DB check raises.

**Step 4: Verify**

Run targeted Docker-backed integration tests.

## Task 4: Makefile, Docker E2E, and Runbook

**Files:**
- Modify: `Makefile`
- Modify: `tests/e2e/test_docker_compose.py`
- Modify: `README.md`
- Test: `tests/unit/test_packaging_files.py`
- Test: `tests/e2e/test_docker_compose.py`

**Step 1: Write failing tests**

Cover:

```text
Makefile exposes ops-check
Docker E2E checks /ready
README documents request ids, /metrics, /ready, and ops-check
```

**Step 2: Run red tests**

Run:

```bash
uv run --python 3.12 pytest tests/unit/test_packaging_files.py tests/e2e/test_docker_compose.py -q
```

Expected: FAIL until Makefile/docs/E2E are updated.

**Step 3: Implement**

Add `make ops-check` using `curl` against `$(API_URL)/health`, `/ready`, and `/metrics`. Update README operations section.

**Step 4: Verify**

Run full verification:

```bash
uv run --python 3.12 pytest -q
make lint
make docker-test
docker compose up --build -d app
KB_DOCKER_E2E=1 make test-e2e
```

**Step 5: Commit and push**

Stage only observability/operations files and docs. Leave `.python-version`, `project-ideas.md`, and `sample-docs/` untracked.
