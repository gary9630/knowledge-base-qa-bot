# Observability and Operations Design

Date: 2026-05-27

## Goal

Add an app-native operations foundation for the first production deploy without adding Prometheus, OpenTelemetry, or extra infrastructure services.

## Chosen Approach

Use in-process observability primitives inside the FastAPI app:

```text
request id middleware
structured JSON request logs
in-memory metrics snapshot
stronger readiness checks
ops runbook and Makefile checks
```

This gives operators enough signal to run and debug the MVP while keeping deployment as one app container plus Postgres.

## Request IDs

Every HTTP request gets a request id. If the client sends `X-Request-ID`, the app preserves it after validation; otherwise it generates a UUID4 hex value. The response always includes `X-Request-ID`.

The request id is available at:

```text
request.state.request_id
response header X-Request-ID
structured request log
unhandled exception log
```

## Structured Logs

The app logs one JSON object per request through the Python logging system. Fields:

```text
event=request_completed
request_id
method
path
status_code
duration_ms
client
```

Unhandled exceptions log:

```text
event=request_failed
request_id
method
path
error
```

The app still relies on the container platform to collect stdout/stderr. No file logging is added.

## Metrics

Expose a JSON metrics snapshot at `GET /metrics`. This is intentionally not Prometheus format yet.

Metrics include:

```text
requests_total
responses_by_status
responses_by_route
errors_total
average_latency_ms
latest_requests
```

The metrics store is in-memory and per-process. That is acceptable for MVP debugging and smoke checks. Multi-replica aggregation can come later through Prometheus/Otel.

## Readiness

Keep `GET /health` as a lightweight liveness endpoint:

```json
{"status":"ok"}
```

Strengthen `GET /ready` so it reports:

```text
database connection
pgvector extension availability
alembic migration revision matches code head
index readiness
platform auth configuration when production/staging
overall ready
```

`/ready` returns HTTP 200 with detailed status when dependencies are reachable, even if `ready=false`; it returns HTTP 503 only when readiness cannot be evaluated because a critical dependency query fails.

## Docker and Makefile

Docker app healthcheck remains liveness-oriented and calls `/health`. Operators use:

```text
make ops-check
```

to check `/health`, `/ready`, and `/metrics` against the configured app URL.

## Runbook

README gains an operations section covering:

```text
startup order
migration readiness
platform auth readiness
index readiness
request id tracing
basic troubleshooting
scheduled eval command
```

## Testing

Unit tests:

```text
request id middleware returns/preserves X-Request-ID
metrics records status/route/error/latency
structured logs include request id and request fields
```

Integration tests:

```text
/ready reports DB, pgvector, migration, auth, and index state
/metrics returns request counters after traffic
ops endpoints remain public
```

E2E tests:

```text
Docker app serves /health and /ready
```
