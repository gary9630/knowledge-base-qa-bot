# Knowledge Base Q&A Bot

FastAPI course-assistant product for ingesting knowledge files, indexing them in
Postgres + pgvector, and answering learner questions with grounded citations. The app is
built for a single-course trial deployment today, with a path to harden into a larger
multi-course product later.

## Current Scope

- Ingest `.pdf`, `.md`, `.markdown`, `.txt`, `.html`, and `.htm` files.
- Convert uploads into canonical Markdown sources.
- Store documents, sections, chunks, conversations, jobs, evals, feedback, audit events,
  and embeddings in Postgres.
- Use pgvector for retrieval. FAISS is intentionally not part of the current path.
- Answer with selected source snippets through an answer provider and validate citations.
- Stream `/chat/stream` responses from the provider when OpenAI answering is enabled.
- Provide a three-pane workbench: left functional tabs (including a Graph tab that renders
  the knowledge graph), center chat, right source preview and diagnostics.
- Run app, worker, tests, backups, and deploy checks through Docker Compose and Make.

## Launch Configuration

The accepted launch configuration is:

- Embeddings: `text-embedding-3-small`
- Embedding dimension: `KB_EMBEDDING_DIMENSION=768`
- Answer model: `gpt-5.4-mini`
- Retrieval strategy: `hybrid`
- Learner auth: one configured platform login, no registration
- Admin auth: `X-KB-Admin-Key`

Latest local real-content acceptance:

- Artifact: `backups/real-content-20260529T171708Z/` (ignored by git)
- Indexed content: 35 course files, 819 sections/chunks
- Retrieval acceptance: 5/5 passed
- Live answer acceptance: 3/3 passed

See [ops/live-answer-acceptance.md](ops/live-answer-acceptance.md) for the required
learner-facing RAG checks.

## Quick Start

Prerequisites: Python 3.12, `uv`, Docker, and `curl`.

```bash
uv sync --python 3.12 --group dev
docker compose up -d postgres
make migrate
uv run --python 3.12 python -m scripts.seed_sample_docs
make dev
```

Open `http://localhost:8000`, log in with the local Compose learner account if platform
auth is enabled, then index the seeded docs from another terminal:

```bash
make index
```

Local Compose defaults are development-only:

- Learner login: `student` / `student-password`
- Admin key: `local-admin-key`

## Common Commands

| Task | Command |
| --- | --- |
| Install dependencies | `uv sync --python 3.12 --group dev` |
| Start local Postgres | `docker compose up -d postgres` |
| Run migrations | `make migrate` |
| Start app | `make dev` |
| Rebuild index | `make index` |
| Process one worker job | `make worker-once` |
| Run worker loop | `make worker` |
| Check worker runtime | `make worker-status` |
| Seed concept graph | `make graph-seed` |
| Seed eval cases | `make eval-seed` |
| Run scheduled evals | `make eval-run` |
| Unit tests | `make test-unit` |
| Integration tests | `make test-integration` |
| E2E tests | `make test-e2e` |
| Full test suite | `make test` |
| Lint/typecheck | `make lint` |
| Docker tests | `make docker-test` |
| Docker app/worker smoke | `make docker-smoke` |
| Deploy env validation | `make deploy-check` |
| Runtime ops smoke | `make ops-check API_URL=http://localhost:8000 KB_ADMIN_API_KEY=local-admin-key` |
| Real course package | `make real-content-package` |

## Configuration

Settings use the `KB_` prefix unless noted. The Makefile loads `.env` when present and
exports only `OPENAI_API_KEY` and `KB_POSTGRES_PORT` for Make-driven workflows.

Required for staging or production:

- `KB_AUTH_SECRET_KEY`
- `KB_PLATFORM_USERNAME`
- `KB_PLATFORM_PASSWORD`
- `KB_ADMIN_API_KEY`
- `KB_DATABASE_URL`
- `KB_DOCS_DIR`
- `KB_RAW_DIR`
- `KB_KB_DIR`
- `OPENAI_API_KEY` when using OpenAI providers

Important provider settings:

- `KB_EMBEDDING_PROVIDER=fake|openai`
- `KB_ANSWER_PROVIDER=fake|openai`
- `KB_OPENAI_EMBEDDING_MODEL=text-embedding-3-small`
- `KB_OPENAI_CHAT_MODEL=gpt-5.4-mini`
- `KB_OPENAI_REQUEST_TIMEOUT_SECONDS`
- `KB_OPENAI_MAX_RETRIES`
- `KB_OPENAI_CHAT_MAX_COMPLETION_TOKENS`
- `KB_PROVIDER_BUDGET_*`

Important knowledge graph settings:

- `KB_GRAPH_EXTRACTION_ENABLED=true`: auto-chains concept extraction after every index
  rebuild. Requires `KB_ANSWER_PROVIDER=openai`; the step is skipped (not failed) when
  the answer provider is `fake`.
- `KB_GRAPH_MAX_CONCEPTS_PER_DOC=30`: maximum concepts extracted per document.
- `KB_GRAPH_EXTRACTION_TOKEN_BUDGET=12000`: token budget for the extraction prompt sent
  to the answer provider.

Important retrieval and context settings:

- `KB_TOKEN_ENCODING=o200k_base`: tiktoken encoding used for token-aware chunking and
  context budgeting.
- `KB_CONTEXT_NEIGHBOR_SECTIONS=1`: neighboring sections included on each side of a
  retrieved section when assembling answer context.
- `KB_CONTEXT_TOKEN_BUDGET=8000`: token budget for the assembled answer context.

Important runtime settings:

- `KB_RATE_LIMIT_*`
- `KB_MAX_CONCURRENT_UPLOADS`
- `KB_BACKGROUND_JOB_STALE_AFTER_SECONDS`
- `KB_BACKGROUND_JOB_RETRY_BASE_DELAY_SECONDS`
- `KB_BACKGROUND_JOB_RETRY_MAX_DELAY_SECONDS`
- `KB_WORKER_ID`
- `KB_WORKER_HEARTBEAT_INTERVAL_SECONDS`
- `KB_WORKER_HEARTBEAT_STALE_AFTER_SECONDS`
- `KB_PLATFORM_COHORTS`
- `KB_PLATFORM_EXTRA_VISIBILITY_LABELS`
- `KB_POSTGRES_PORT`

Use [ops/env.production.example](ops/env.production.example) as the production template,
then validate the target environment with:

```bash
make deploy-check
```

## Data Flow

```text
upload/import
  -> raw artifact in raw/
  -> background_jobs.ingest.upload
  -> canonical Markdown in docs/
  -> background_jobs.index.rebuild
  -> documents/sections/chunks + pgvector embeddings
  -> search/chat retrieval
  -> answer provider
  -> citation validation + response diagnostics
```

`POST /imports` stays lightweight: it stores the raw artifact, creates import metadata,
and queues background work. `python -m scripts.run_background_worker` handles conversion,
index rebuilds, eval runs, retries, stale-job recovery, and worker heartbeats.

Identical uploads deduplicate by content hash. Same filename with different content is
kept as a new artifact with a content-hash suffix. The app rejects empty uploads,
unsupported extensions, invalid PDF signatures, obvious content-type mismatches, HTML
without recognizable markup, and binary-looking text before writing raw artifacts.

## API Surface

Learner-facing:

- `POST /auth/login`
- `POST /auth/logout`
- `POST /search`
- `POST /chat`
- `POST /chat/stream`
- `GET /sources`
- `GET /sources/{document_id}`
- `GET /sources/{document_id}/sections/{section_id}`
- `GET /graph`
- `GET /graph/concepts/{concept_id}`

Admin-only:

- `POST /imports`
- `GET /imports/status`
- `POST /index`
- `GET /index/status`
- `GET /admin/jobs`
- `POST /admin/jobs`
- `POST /admin/jobs/recover-stale`
- `POST /admin/jobs/{job_id}/requeue`
- `GET /admin/jobs/runtime`
- `GET /admin/documents`
- `PATCH /admin/documents/{document_id}/lifecycle`
- `DELETE /admin/documents/{document_id}`
- `POST /admin/documents/{document_id}/reindex`
- `GET /admin/audit-events`
- `GET /admin/provider-observability`
- `POST /graph/extract`
- `GET /metrics`

`GET /health` is liveness. `GET /ready` checks database, pgvector, Alembic migration
state, storage paths, platform auth, and index readiness.

## Retrieval And Answer Quality

Hybrid retrieval now fuses lexical, vector, and markdown candidates with Reciprocal Rank
Fusion (RRF), applying the score threshold to per-strategy scores before fusion. Chat
answers no longer see only the matched chunk: a context assembly step expands each hit to
its full section plus `KB_CONTEXT_NEIGHBOR_SECTIONS` neighbors on each side, within the
`KB_CONTEXT_TOKEN_BUDGET` token budget, and chat responses report this in a
`context_assembly` block.

Search and chat return retrieval diagnostics such as selected source IDs, rejected source
IDs, threshold, strategy counts, top score, raw/merged/accepted/rejected counts, and score
debug data. Chat responses also expose answer-quality metadata:

- `answer_valid`
- `citation_errors`
- `selected_source_ids`
- `cited_source_ids`
- `cannot_confirm_reason`

Provider citations must reference selected sources. Invalid citations downgrade the answer
to the exact cannot-confirm response with `cannot_confirm_reason="invalid_citations"`.
Streaming chat sends retrieval diagnostics in the `sources` event and final answer quality
in the `done` event.

## Access Control

Learner platform auth is intentionally simple: one configured username and password for
the trial course. Admin operations are separate and require `X-KB-Admin-Key`.

Source visibility is enforced across search, chat, streaming chat, source preview, and the
knowledge graph. Canonical Markdown frontmatter can set `visibility`; omitted visibility
defaults to `public`. Learners can see:

- `public`
- `role:<role>`
- `user:<username>`
- `cohort:<name>` from `KB_PLATFORM_COHORTS`
- labels from `KB_PLATFORM_EXTRA_VISIBILITY_LABELS`

## Real Course Content

Private course material lives in `course-materials-md/`, which is ignored by git. Build a
deployable artifact with the real embedding provider:

```bash
make real-content-package
```

If local port `5432` is already in use:

```bash
KB_POSTGRES_PORT=55432 make real-content-package
```

The workflow uses an isolated Compose project named `kb-real-content`, indexes
`course-materials-md/`, runs retrieval acceptance cases, and writes:

- `postgres.dump`
- `runtime-files.tar.gz`
- `real-content-acceptance-report.json`

Restore on the deploy target with:

```bash
make restore-db RESTORE_DB_FILE=<artifact>/postgres.dump CONFIRM_RESTORE=yes
make restore-files RESTORE_FILES_FILE=<artifact>/runtime-files.tar.gz CONFIRM_RESTORE=yes
make ops-check API_URL=https://your-app.example.com KB_ADMIN_API_KEY=$KB_ADMIN_API_KEY
```

Never commit `course-materials-md/`, `.env`, or generated `backups/` artifacts.

## Testing

Use focused tests while developing, then run the broadest feasible check before claiming
work is complete.

```bash
make test-unit
make test-integration
make test-e2e
make test
make lint
make docker-test
make docker-smoke
```

DB-backed tests need `KB_DATABASE_URL_TEST`; otherwise they are skipped. CI is defined in
[.github/workflows/ci.yml](.github/workflows/ci.yml) and runs lint/typecheck, local tests,
deploy env validation, Docker Compose validation, Docker tests, and Docker smoke checks.

## Operations

The app includes an app-native operations foundation:

- Structured logs with `X-Request-ID`
- `/health`, `/ready`, protected `/metrics`
- Rate limits and upload concurrency guards
- Provider timeout, retry, budget, usage, and error controls
- Admin audit/security event log
- Provider observability dashboard data
- Document lifecycle management
- Background worker runtime supervision
- Stuck job recovery and requeue endpoints

Create an application backup:

```bash
make backup BACKUP_DIR=backups/$(date -u +%Y%m%dT%H%M%SZ)
```

Restore operations require `CONFIRM_RESTORE=yes`. File restore overlays archived files and
does not delete stale files.

Runbooks:

- [ops/deploy.md](ops/deploy.md)
- [ops/backup-restore.md](ops/backup-restore.md)
- [ops/live-answer-acceptance.md](ops/live-answer-acceptance.md)

## Deployment Notes

For the first learner trial, use one app container, one worker container, and Postgres with
pgvector. Run Alembic migrations once per deploy, keep `docs`, `raw`, and `.kb` on durable
storage, and run:

```bash
make ops-check API_URL=https://your-app.example.com KB_ADMIN_API_KEY=$KB_ADMIN_API_KEY
```

Before inviting learners, confirm:

- CI is green for the deployed commit.
- `make deploy-check` passes on the target environment.
- `/ready` is ready.
- Worker heartbeat is fresh.
- Login works with the configured platform user.
- Known search/chat cases return expected citations.
- Live answer acceptance passes with OpenAI answering enabled.
