# Streaming Observability Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Record accurate completion duration and late generator failures for streaming HTTP/SSE responses.

**Architecture:** Convert request observability from `BaseHTTPMiddleware` to raw ASGI middleware. Wrap `send` to inject `X-Request-ID`, capture response start status, and record completion only on the final body frame. Wrap the downstream app call to record/log failures before response start and late streaming failures after response start.

**Tech Stack:** Python 3.12, FastAPI, Starlette ASGI middleware, pytest/TestClient, in-memory metrics, Python logging.

---

## Task 1: Streaming Completion Timing

**Files:**
- Modify: `tests/unit/test_observability_middleware.py`
- Modify: `app/observability/middleware.py`

**Step 1: Write the failing test**

Add a streaming endpoint test that yields two chunks with a measurable pause. Assert:

```text
response status is 200
X-Request-ID exists
requests_total is 1
latest_requests[0].duration_ms includes the stream delay
request_completed is logged once
```

**Step 2: Run test to verify it fails**

Run:

```bash
uv run --python 3.12 pytest tests/unit/test_observability_middleware.py::test_request_observability_records_streaming_completion_after_body_finishes -q
```

Expected: FAIL because the current middleware records before the streaming body finishes.

**Step 3: Implement ASGI completion recording**

Convert `RequestObservabilityMiddleware` to ASGI middleware:

```text
__call__(scope, receive, send)
ignore non-http scopes
create Request(scope, receive)
set request.state.request_id
wrap send
inject X-Request-ID on http.response.start
capture status_code
record/log success on final http.response.body
```

**Step 4: Verify**

Run the targeted test and existing observability unit tests.

## Task 2: Late Streaming Error Tracking

**Files:**
- Modify: `tests/unit/test_observability_middleware.py`
- Modify: `app/observability/middleware.py`

**Step 1: Write the failing test**

Add a streaming endpoint that yields one chunk then raises. Use `TestClient(..., raise_server_exceptions=False)` or the client behavior needed by Starlette, then assert:

```text
errors_total is 1
requests_total is 1
latest_requests[0].status_code is 200
request_failed log includes stream_error=true
log has exc_info
```

**Step 2: Run test to verify it fails**

Run:

```bash
uv run --python 3.12 pytest tests/unit/test_observability_middleware.py::test_request_observability_records_late_streaming_errors -q
```

Expected: FAIL because the current middleware records success before the generator fails.

**Step 3: Implement late error recording**

Track whether response start has been sent and whether metrics have already been recorded. In `except Exception`, record failure exactly once:

```text
status_code=500 before response start
status_code=<started status> after response start
stream_error=true after response start
```

Always re-raise the exception.

**Step 4: Verify**

Run the targeted test and full observability unit tests.

## Task 3: Regression and Deploy Verification

**Files:**
- Modify only if tests require small expectation updates.

**Step 1: Run local verification**

Run:

```bash
uv run --python 3.12 pytest tests/unit/test_observability_middleware.py tests/unit/test_health_routes.py -q
uv run --python 3.12 pytest -q
make lint
```

**Step 2: Run Docker verification**

Run:

```bash
make docker-test
docker compose up --build -d app
KB_DOCKER_E2E=1 make test-e2e
make ops-check
```

**Step 3: Commit and push**

Stage only streaming observability docs/code/tests. Leave `.python-version`, `project-ideas.md`, and `sample-docs/` untracked.
