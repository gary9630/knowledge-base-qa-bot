# Production Deploy Runbook

This runbook describes the current single-host or simple VM deployment model. The app
runs as one FastAPI container, one queue worker container, and Postgres with pgvector. The
same image can run the app, migration, worker, and scheduled eval commands.

## Required Secrets And Settings

Set production values outside git:

- `KB_AUTH_SECRET_KEY`
- `KB_PLATFORM_USERNAME`
- `KB_PLATFORM_PASSWORD`
- `KB_ADMIN_API_KEY`
- `KB_DATABASE_URL`
- `KB_DOCS_DIR`
- `KB_RAW_DIR`
- `KB_KB_DIR`
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
- `OPENAI_API_KEY`
- `KB_OPENAI_EMBEDDING_MODEL`
- `KB_OPENAI_CHAT_MODEL`
- `KB_PROVIDER_BUDGET_*`

Use durable storage for `docs`, `raw`, and `.kb`. Use managed Postgres backups when
available, plus the application backup path below.

Start from `ops/env.production.example`, copy it outside git, and replace every
placeholder. Validate the target environment before building or restarting services:

```bash
set -a
. /path/to/production.env
set +a
make deploy-check
```

## Pre-Deploy Checks

1. Confirm CI passed on the commit to deploy.
2. Confirm `make deploy-check` passes on the deploy target.
3. Confirm `docker compose --profile worker --profile test config` is valid.
4. For a release candidate, run the local Compose smoke check:

```bash
make docker-smoke
```

5. Create a backup:

```bash
make backup BACKUP_DIR=backups/$(date -u +%Y%m%dT%H%M%SZ)
```

## Deploy Sequence

For the Compose deployment model:

```bash
docker compose build app migrate worker eval-runner
docker compose up -d postgres
docker compose run --rm migrate
docker compose up -d app
docker compose --profile worker up -d worker
make ops-check API_URL=https://your-app.example.com KB_ADMIN_API_KEY=$KB_ADMIN_API_KEY
```

If running directly against a local database instead of Compose, run `make migrate` before
starting the app process.

## Post-Deploy Smoke

1. `GET /health` returns 200.
2. `GET /ready` returns ready with database, pgvector, migrations, storage, platform auth,
   and index checks.
3. Protected `GET /metrics` works with `X-KB-Admin-Key`.
4. Protected `GET /admin/jobs/runtime` shows queue depth and at least one fresh worker
   heartbeat after the worker container starts.
5. Login works with the configured platform user.
6. A known chat/search query returns expected source IDs.
7. Upload returns `202 Accepted`, creates `ingest.upload`, and the worker converts it to
   canonical Markdown plus a queued `index.rebuild`.
8. A protected `POST /admin/jobs` can enqueue `index.rebuild`, and the worker marks it
   succeeded.
9. Protected `POST /admin/jobs/recover-stale` returns successfully; if any stale jobs are
   returned, confirm they are queued or failed according to their attempt budget.
10. Scheduled eval runner can run `python -m scripts.run_evals --trigger scheduled`.

## Rollback

Rollback the app image or git ref first. If the previous image can read the current schema,
avoid restoring data. If schema or data rollback is required:

```bash
make restore-db RESTORE_DB_FILE=backups/<backup-id>/postgres.dump CONFIRM_RESTORE=yes
make restore-files RESTORE_FILES_FILE=backups/<backup-id>/runtime-files.tar.gz CONFIRM_RESTORE=yes
make migrate
make ops-check API_URL=https://your-app.example.com KB_ADMIN_API_KEY=$KB_ADMIN_API_KEY
```

The file restore overlays archived files and does not delete stale files. Handle stale files
manually one explicit path at a time.

## CI/CD Gates

The GitHub Actions workflow runs `make lint`, `make test`, `make deploy-check-ci`,
`docker compose --profile worker --profile test config`, `make docker-test`, and
`make docker-smoke`. Keep these gates green before promoting an image or git ref.
