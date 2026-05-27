# Knowledge Base Q&A Bot

FastAPI knowledge-base product for ingesting local knowledge files, converting them into
canonical Markdown, indexing them in Postgres + pgvector, and answering questions with
grounded source citations. The MVP data flow uses Postgres for documents, sections,
chunks, conversations, feedback, and vector search. FAISS is not part of the MVP path.

## Local Setup

Prerequisites: Python 3.12, `uv`, Docker if you want local Postgres, and `curl`.

```bash
uv sync --python 3.12 --group dev
docker compose up -d postgres
make migrate
uv run --python 3.12 python -m scripts.seed_sample_docs
make dev
```

Open `http://localhost:8000` for the three-pane workbench:
left navigation, center chat/streaming answer, and right source/markdown/index inspector.
In another terminal, build the index after the app is running:

```bash
make index
```

The seed command copies Markdown files from `sample-docs/` into `docs/`, preserves nested
paths, skips existing files, and never deletes source or destination files.

## Docker Compose

Compose defines `postgres`, a one-shot `migrate` service, `app`, optional `worker`, and
optional `test` profiles. It uses the `pgvector/pgvector:pg16` Postgres image.

```bash
docker compose up --build app
docker compose --profile worker run --rm worker
docker compose --profile test run --rm test
```

`docs`, `raw`, `.kb`, and Postgres data are stored in named Docker volumes. For local
sample data, seed `docs/` before local indexing, or upload files through the UI/API when
running the Compose app. The Compose default platform login is `student` /
`student-password`, and the default admin key is `local-admin-key`; override
`KB_AUTH_SECRET_KEY`, `KB_PLATFORM_USERNAME`, `KB_PLATFORM_PASSWORD`, and
`KB_ADMIN_API_KEY` before using anything beyond local development. Docker Compose
configuration, image build, app health, upload, worker indexing, and retrieval can be
verified locally with the commands below.

## Environment

Settings use the `KB_` prefix unless noted.

| Variable | Default | Purpose |
| --- | --- | --- |
| `KB_DATABASE_URL` | `postgresql+psycopg://kb:kb@localhost:5432/kb` | Main Postgres database URL. |
| `KB_DATABASE_URL_TEST` | unset | Enables DB integration tests when set. |
| `KB_DOCS_DIR` | `docs` | Canonical Markdown source directory. |
| `KB_RAW_DIR` | `raw` | Uploaded original-file directory. |
| `KB_KB_DIR` | `.kb` | Local index/export artifacts. |
| `KB_AUTH_SECRET_KEY` | unset | HMAC secret for platform login sessions; production/staging require it. |
| `KB_PLATFORM_USERNAME` | unset | Single platform username for course-facing login. |
| `KB_PLATFORM_PASSWORD` | unset | Single platform password for course-facing login. |
| `KB_PLATFORM_COHORTS` | unset | Comma/space-separated cohort names granted to the platform learner, exposed as `cohort:<name>` source labels. |
| `KB_PLATFORM_EXTRA_VISIBILITY_LABELS` | unset | Extra source visibility labels granted to the platform learner, for example `staff`. |
| `KB_PLATFORM_SESSION_TTL_SECONDS` | `86400` | Platform session lifetime in seconds. |
| `KB_ADMIN_API_KEY` | unset | Optional admin key required for upload/index endpoints; production requires it. |
| `KB_MAX_UPLOAD_BYTES` | `10000000` | Maximum upload size accepted by `/imports`. |
| `KB_RATE_LIMIT_ENABLED` | `true` | Enables app-native rate limiting and upload concurrency guards. |
| `KB_RATE_LIMIT_WINDOW_SECONDS` | `60` | Fixed rate-limit window size in seconds. |
| `KB_RATE_LIMIT_LOGIN_REQUESTS` | `10` | Login attempts allowed per client identity per window. |
| `KB_RATE_LIMIT_CHAT_REQUESTS` | `60` | Chat and streaming chat requests allowed per client/session per window. |
| `KB_RATE_LIMIT_ADMIN_REQUESTS` | `60` | Admin write requests allowed per client/admin key per window. |
| `KB_RATE_LIMIT_UPLOAD_REQUESTS` | `10` | Upload requests allowed per client/admin key per window. |
| `KB_MAX_CONCURRENT_UPLOADS` | `2` | Concurrent upload requests allowed per app process. |
| `KB_EMBEDDING_PROVIDER` | `fake` | Use `fake` for deterministic dev/test or `openai` for real embeddings. |
| `KB_ANSWER_PROVIDER` | `fake` | Use `fake` for deterministic dev/test or `openai` for generated answers. |
| `OPENAI_API_KEY` | unset | Required by OpenAI providers. |
| `KB_OPENAI_EMBEDDING_MODEL` | unset | Optional OpenAI embedding model override. |
| `KB_OPENAI_CHAT_MODEL` | unset | Optional OpenAI chat model override. |
| `KB_EMBEDDING_DIMENSION` | `1536` | Embedding vector dimension used by the database schema/provider. |
| `KB_DEFAULT_RETRIEVAL_STRATEGY` | `hybrid` | Default retrieval mode. |
| `KB_POSTGRES_PORT` | `5432` | Host port for Compose Postgres. |

## Import, Index, Chat

Seed Markdown locally:

```bash
uv run --python 3.12 python -m scripts.seed_sample_docs
```

Upload PDF, Markdown, text, or HTML and convert it to canonical Markdown:

```bash
curl -H "X-KB-Admin-Key: $KB_ADMIN_API_KEY" \
  -F "file=@notes.pdf" http://localhost:8000/imports
curl -H "X-KB-Admin-Key: $KB_ADMIN_API_KEY" \
  http://localhost:8000/imports/status
curl -H "X-KB-Admin-Key: $KB_ADMIN_API_KEY" \
  -X POST http://localhost:8000/imports/<job-id>/retry
```

Rebuild the DB index from `docs/`:

```bash
curl -H "X-KB-Admin-Key: $KB_ADMIN_API_KEY" \
  -X POST http://localhost:8000/index
curl http://localhost:8000/index/status
```

Ask grounded questions:

```bash
curl -X POST http://localhost:8000/chat \
  -H "content-type: application/json" \
  -d '{"query":"What does the knowledge base say?","strategy":"hybrid","limit":5}'
```

When platform auth is configured, use the browser login flow for chat/search/source
inspection. The platform login is intentionally a single configured user, not registration
or RBAC. Admin operations remain separate and require `X-KB-Admin-Key`.

Source access is enforced before search, chat, source preview, and mindmap responses are
returned. Canonical Markdown frontmatter can set `visibility`; omitted visibility defaults
to `public`. A platform learner can see `public`, `role:<role>`, `user:<username>`,
`cohort:<name>` labels from `KB_PLATFORM_COHORTS`, and any labels configured in
`KB_PLATFORM_EXTRA_VISIBILITY_LABELS`. Examples:

```markdown
---
visibility: public
---

---
visibility: cohort:spring-2026
---

---
visibility: staff
---
```

Useful read endpoints:

- `GET /imports/status`, `GET /imports/{job_id}`, and `POST /imports/{job_id}/retry`
- `GET /sources` and `GET /sources/{document_id}`
- `GET /sources/{document_id}/sections/{section_id}`
- `GET /mindmap`
- `POST /search`
- `POST /chat/stream` for server-sent token events

## Tests

```bash
make test-unit
make test-integration
make test-e2e
make test
make lint
```

DB-backed tests are skipped unless `KB_DATABASE_URL_TEST` points to a reachable test
database. Docker packaging checks can be run with:

```bash
docker compose --profile worker --profile test config
docker compose up --build -d app
KB_DOCKER_E2E=1 make test-e2e
docker compose --profile worker run --rm worker
```

Continuous integration is defined in `.github/workflows/ci.yml`. It runs lint/typecheck,
local tests, Docker Compose config validation, and Docker-backed tests.

## Operations

App-native operations endpoints are built into the FastAPI service:

- `GET /health` is a lightweight liveness check.
- `GET /ready` verifies database connectivity, pgvector availability, Alembic migration
  state, indexed document counts, production platform-auth configuration, and storage
  path writability/creatability. It returns HTTP 503 when any readiness check fails.
- `GET /metrics` returns in-process JSON counters and recent request samples for quick
  triage without a Prometheus/OpenTelemetry stack. It is protected by the admin API key
  when `KB_ADMIN_API_KEY` is configured.

Every response includes an `X-Request-ID` header. Clients can send their own request ID
with that header, or the app will generate one. Completed and failed requests emit
structured JSON log lines with the request ID, method, path, status code, duration, and
client host so support can correlate browser/API reports to server logs.

App-native abuse controls are enabled by default. `POST /auth/login`, `POST /chat`,
`POST /chat/stream`, upload, and admin write routes return HTTP 429 with `Retry-After`
and `X-RateLimit-*` headers when their configured per-window limit is exceeded. Uploads
also have a per-process concurrency guard controlled by `KB_MAX_CONCURRENT_UPLOADS`.
These limits are intentionally in-memory for the first single-process deploy model; use a
gateway, Redis-backed limiter, or reverse proxy policy before running multiple app
replicas.

Run the deployment smoke check against a local or deployed API with:

```bash
make ops-check API_URL=http://localhost:8000 KB_ADMIN_API_KEY=local-admin-key
```

If readiness fails, check the named item in the `checks` object first. `database` means the
app cannot query Postgres, `pgvector` means the vector extension is missing, `migrations`
means the database revision is not at the Alembic head, `index` reports whether any
documents/chunks have been indexed, `platform_auth` reports missing production login
configuration, and `storage` reports unusable `docs`, `raw`, or `.kb` paths.

Create local Compose backups with:

```bash
make backup BACKUP_DIR=backups/$(date -u +%Y%m%dT%H%M%SZ)
```

This captures a `pg_dump --format=custom` database dump plus a tar archive for the
`docs_data`, `raw_data`, and `kb_data` volumes. Restore operations require
`CONFIRM_RESTORE=yes`; see `ops/backup-restore.md` before restoring.

For production rollout steps, required secrets, smoke checks, and rollback procedure, see
`ops/deploy.md`.

## Production Notes

Use managed Postgres with pgvector enabled, real credentials, backups, and a migration step
that runs once per deploy. Keep raw uploads, canonical Markdown, and `.kb` artifacts on
durable mounted storage or managed object storage, and verify those paths through `/ready`.
Set `KB_AUTH_SECRET_KEY`, `KB_PLATFORM_USERNAME`,
`KB_PLATFORM_PASSWORD`, and `KB_ADMIN_API_KEY`; production/staging fail closed when platform
auth is incomplete. Keep the platform login separate from admin access, and do not expose
admin endpoints publicly without the admin key or an authenticated gateway. Use OpenAI or
another production embedding provider with a stable vector dimension before indexing production data.
Wire application logs to the hosting provider's log sink and run `make ops-check` after each
deploy. Tune the built-in rate limits and source-level access labels before exposing the
app publicly.
