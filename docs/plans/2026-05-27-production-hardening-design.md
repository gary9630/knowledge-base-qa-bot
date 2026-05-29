# Production Hardening Design

## Goal

Move the current knowledge-base Q&A MVP toward a launchable course product by
hardening abuse controls, source access boundaries, storage durability, and deployment
operations.

## Scope Order

1. Rate limiting / abuse control.
2. Source-level access control.
3. Durable storage / backup and restore.
4. Production deploy / CI/CD.

This order keeps public exposure risk low before adding broader deploy automation.

## Design

### Rate Limiting / Abuse Control

Use an app-native in-memory limiter first. The app currently has app-native operations
metrics and request middleware, and the first production slice intentionally avoids
Prometheus, OpenTelemetry, or extra infrastructure. The limiter should be simple to run in
Docker Compose and easy to replace with Redis or a gateway limiter later.

Requests are grouped into policy buckets:

- `login`: `POST /auth/login`
- `chat`: `POST /chat`, `POST /chat/stream`
- `upload`: `POST /imports`
- `admin`: admin write operations such as `/index`, import retry, and eval mutations

Each bucket is keyed by client host plus a stable session/admin identity where available.
For the first slice, client-host limiting is enough to reduce accidental abuse, repeated
login attempts, runaway chat loops, and repeated upload/eval actions. The middleware
returns HTTP 429 with `Retry-After` and rate-limit headers. Uploads also get a separate
concurrency guard so large file parsing cannot starve normal chat traffic.

Trade-off: this is per-process and resets on deploy. That is acceptable for the current
single-instance Docker/CLI runner model. A future multi-replica deploy should move this
policy to Redis, a reverse proxy, or the managed gateway.

### Source-Level Access Control

The app already filters simple document visibility labels such as `public` and `staff`.
The production model should promote this to first-class source grants:

- Store source visibility metadata in the document/source layer.
- Resolve the current platform principal into `user_id`, roles, and `cohort_id` values.
- Enforce grants before vector/lexical results are returned.
- Apply the same filtering in chat, search, mindmap, source preview, and eval runs.

The current single-user platform login can map to a default learner principal. Admin API
key access remains separate from learner access.

### Durable Storage / Backup-Restore

Postgres remains the source of truth for index metadata, chunks, feedback, evals, and
operational records. Raw uploads and canonical Markdown need durable storage before
public launch. The first production-ready option is configurable filesystem storage backed
by a managed persistent volume. The next option is object storage with the same logical
paths used today.

Backup/restore needs to cover:

- Postgres backup and restore.
- Raw upload files.
- Canonical Markdown sources.
- Alembic migration state.
- A post-restore `make ops-check` smoke test.

### Production Deploy / CI/CD

Keep Docker Compose for local and single-host deployment, then add deploy-specific
profiles and CI checks:

- Build and test the app image.
- Run unit, integration, Docker, and e2e smoke checks.
- Run Alembic migrations once per deploy.
- Verify `/health`, `/ready`, and protected `/metrics`.
- Keep secrets out of committed files.

## Testing Strategy

- Unit tests for limiter policy matching, key generation, window reset, and metrics.
- API tests for 429 responses and headers.
- Integration/e2e tests for Docker configuration and ops checks.
- Later source-access tests must cover search, chat, stream, source preview, mindmap, and
  eval paths with allowed and denied documents.
