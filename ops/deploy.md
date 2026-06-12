# Production Deploy Runbook

This runbook describes the current single-host or simple VM deployment model. The app
runs as one FastAPI container, one queue worker container, and Postgres with pgvector. The
same image can run the app, migration, worker, and scheduled eval commands.

## Required Secrets And Settings

Set production values outside git:

- `KB_AUTH_SECRET_KEY`
- `KB_PLATFORM_USERNAME`
- `KB_PLATFORM_PASSWORD`
- `KB_ADMIN_USERNAME`
- `KB_ADMIN_PASSWORD`
- `KB_ADMIN_API_KEY`
- `KB_IMAGE`
- `KB_POSTGRES_PASSWORD`
- `KB_DATABASE_URL`
- `KB_DOCS_DIR`
- `KB_RAW_DIR`
- `KB_KB_DIR`
- `KB_APP_PORT`
- `KB_POSTGRES_PORT`
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

## DigitalOcean Host Setup

The current production path targets one DigitalOcean Droplet running Docker Compose,
Nginx, and Certbot. Clone the repository on the server, keep `/etc/kb/production.env`
outside git, and use `docker-compose.prod.yml` with the base Compose file:

```bash
git clone https://github.com/gary9630/knowledge-base-qa-bot.git /opt/kb/knowledge-base-qa-bot
cd /opt/kb/knowledge-base-qa-bot
cp ops/env.production.example /etc/kb/production.env
chmod 600 /etc/kb/production.env
```

Set loopback ports in `/etc/kb/production.env` so only Nginx is public:

```bash
KB_APP_PORT=127.0.0.1:8000
KB_POSTGRES_PORT=127.0.0.1:5432
```

Use `ops/nginx/kb.conf.example` as the Nginx site template, replacing
`example.com` with the production domain. After DNS points at the Droplet, enable
HTTPS with Certbot's Nginx installer.

## Automated DigitalOcean Deployment

`.github/workflows/deploy.yml` promotes only commits that already passed the `CI`
workflow on `main`. It builds the app image on the GitHub runner, runs `docker save`,
compresses the archive with `gzip`, copies it to the Droplet with `scp`, SSHes to the
Droplet, checks out the exact commit, loads the archive with `docker load`, and runs
`scripts/deploy_production.sh`.

Configure these GitHub repository or environment secrets:

- `DEPLOY_SSH_HOST`
- `DEPLOY_SSH_USER`
- `DEPLOY_SSH_PRIVATE_KEY`
- `DEPLOY_SSH_KNOWN_HOSTS`
- `DEPLOY_PATH` - usually `/opt/kb/knowledge-base-qa-bot`

The server-side `/etc/kb/production.env` remains the source of runtime secrets. Do not
send OpenAI keys, platform passwords, or database passwords through workflow commands.

For a first deploy or manual retry on the server:

```bash
cd /opt/kb/knowledge-base-qa-bot
set -a
. /etc/kb/production.env
set +a
KB_IMAGE=knowledge-base-qa-bot:<commit-sha> \
KB_IMAGE_ARCHIVE=/tmp/knowledge-base-qa-bot-image-<commit-sha>.tar.gz \
  scripts/deploy_production.sh
```

The deploy script uses:

```bash
docker compose --env-file /etc/kb/production.env \
  -f docker-compose.yml -f docker-compose.prod.yml
```

It loads the copied image archive when `KB_IMAGE_ARCHIVE` is set, starts Postgres, runs
migrations, starts the app and worker with `--no-build`, then verifies `/health`,
`/ready`, and worker runtime.

## Upload Local Knowledge Files

Keep `course-materials-md/` out of git. To transfer a local course-material directory
to the Droplet through the same SSH target used by `connect-server.sh`, run:

```bash
scripts/scp_knowledge_files_to_server.sh
```

Useful overrides:

```bash
SOURCE_DIR=course-materials-md \
CONNECT_SCRIPT=connect-server.sh \
REMOTE_UPLOAD_ROOT=/opt/kb/knowledge-uploads \
scripts/scp_knowledge_files_to_server.sh
```

The script creates a versioned remote directory and prints a follow-up command using
`REAL_CONTENT_SOURCE_DIR=<remote-versioned-source> make real-content-package`. It does
not delete or merge old remote course files.

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

## Real Content Launch Artifact

For the first production data load, keep `course-materials-md/` private and build a
deployable DB/runtime artifact from the repository root:

```bash
OPENAI_API_KEY=... make real-content-package
```

This uses the real embedding contract, `text-embedding-3-small` with
`KB_EMBEDDING_DIMENSION=768`, prepares the Compose `docs_data` volume, rebuilds the
Postgres + pgvector index, runs retrieval acceptance cases, and packages:

- `postgres.dump`
- `runtime-files.tar.gz`
- `real-content-acceptance-report.json`

Move the backup directory to the deploy target through your normal encrypted artifact
path, then restore it before starting app traffic:

```bash
make restore-db RESTORE_DB_FILE=<artifact>/postgres.dump CONFIRM_RESTORE=yes
make restore-files RESTORE_FILES_FILE=<artifact>/runtime-files.tar.gz CONFIRM_RESTORE=yes
make ops-check API_URL=https://your-app.example.com KB_ADMIN_API_KEY=$KB_ADMIN_API_KEY
```

Do not commit `course-materials-md/` or generated backup artifacts.

The real-content workflow defaults to an isolated Compose project,
`REAL_CONTENT_COMPOSE_PROJECT=kb-real-content`, so stale local development docs do not
enter the launch artifact. Use a different project name for a fresh rehearsal rather
than deleting Docker volumes in bulk.

If another local service already binds Postgres port `5432`, run the package workflow
with an alternate host port:

```bash
KB_POSTGRES_PORT=55432 make real-content-package
```

The latest local launch artifact accepted for trial deploy is
`backups/real-content-20260529T171708Z/`. It contains 35 course files, 819 indexed
sections/chunks, and a retrieval acceptance report with 5/5 cases passed. Keep that
directory out of git and transfer it through an encrypted artifact path.

## Deploy Sequence

For the Compose deployment model:

```bash
set -a
. /etc/kb/production.env
set +a
docker compose --env-file /etc/kb/production.env \
  -f docker-compose.yml -f docker-compose.prod.yml up -d postgres
docker compose --env-file /etc/kb/production.env \
  -f docker-compose.yml -f docker-compose.prod.yml run --rm migrate
docker compose --env-file /etc/kb/production.env \
  -f docker-compose.yml -f docker-compose.prod.yml up -d --no-build app
docker compose --env-file /etc/kb/production.env \
  -f docker-compose.yml -f docker-compose.prod.yml --profile worker up -d --no-build worker
make ops-check API_URL=https://your-app.example.com KB_ADMIN_API_KEY=$KB_ADMIN_API_KEY
```

If running directly against a local database instead of Compose, run `make migrate` before
starting the app process.

### Knowledge Graph Release Note

Deploying the knowledge graph change requires:

1. `make migrate` (adds migrations 0012 and 0013 for the five concept-graph tables).
2. `make graph-seed` once per environment to load the curated seed dataset
   (`docs/plans/2026-06-11-concept-graph-seed.json`). This populates 115 concepts across
   16 clusters with `origin='seed'` protection and marks all currently active documents as
   extracted so future uploads do not re-extract seed concepts.

After seeding, future document uploads auto-extract concepts via the background worker when
`KB_ANSWER_PROVIDER=openai`. When the answer provider is `fake`, the extraction step is
skipped without error. Provider token usage for each extraction run is recorded in the job's
`result` field and is visible through the admin jobs API.

To restore the curated graph after accidental deletion or a full re-seed (the
`graph-seed` make target does not accept flags, so invoke the script directly with
`KB_DATABASE_URL` pointing at the target database, as for the other commands above):

```bash
uv run --python 3.12 python -m scripts.seed_concept_graph \
  --file docs/plans/2026-06-11-concept-graph-seed.json --replace
```

The `--replace` flag wipes ALL concept-graph rows (clusters, concepts, edges, sources,
and extraction state — including extracted, non-seed concepts) and then re-applies the
seed, re-marking all active documents as extracted.

### Context Expansion Release Note

Deploying the retrieval context expansion change (tiktoken chunking, section positions,
RRF fusion, full-section answer context) requires both:

1. `make migrate` (adds `sections.position`).
2. A full index rebuild (`python -m scripts.rebuild_index` against the production docs
   dir, or `make real-content-package` for a fresh launch artifact). The rebuild
   re-chunks every document with token-aware chunking and re-embeds all chunks, so expect
   a one-time OpenAI embedding cost proportional to the full corpus.

Answer calls now send full-section windows instead of single chunks, which grows answer
input tokens roughly 4-5x. Raise `KB_PROVIDER_BUDGET_*` daily token limits accordingly
before enabling traffic.

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
11. Run live answer acceptance from `ops/live-answer-acceptance.md`; the current required
    cases are CAP theorem through `/chat`, RAG flow through `/chat`, and Message Queue
    through `/chat/stream`.

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

The CI workflow runs `make lint`, `make test`, `make deploy-check-ci`,
`docker compose --profile worker --profile test config`, `make docker-test`, and
`make docker-smoke`. Keep these gates green before promoting an image or git ref. The
production deployment workflow in `.github/workflows/deploy.yml` runs only after CI
succeeds on `main` or through an explicit `workflow_dispatch`.
