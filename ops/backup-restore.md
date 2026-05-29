# Backup And Restore Runbook

This runbook covers the first production deployment model: Postgres with pgvector plus
durable filesystem volumes for canonical Markdown, raw uploads, and generated `.kb`
artifacts.

## What Must Be Backed Up

- Postgres database, including pgvector embeddings, conversations, feedback, evals, jobs,
  and Alembic migration state.
- `docs_data`, mounted at `/app/docs`, for canonical Markdown sources.
- `raw_data`, mounted at `/app/raw`, for original uploaded files.
- `kb_data`, mounted at `/app/.kb`, for generated index/export artifacts.

## Create A Backup

Run from the repository root while the Compose stack can reach Postgres:

```bash
make backup BACKUP_DIR=backups/$(date -u +%Y%m%dT%H%M%SZ)
```

This writes:

- `postgres.dump` from `pg_dump --format=custom`
- `runtime-files.tar.gz` containing `docs`, `raw`, and `.kb`

For managed Postgres, use the provider's scheduled backups as the primary recovery
mechanism and keep this `pg_dump` path as an application-level export.

## Package Real Course Content

Before the first learner-facing deploy, build a deployable artifact from the private
`course-materials-md/` directory instead of indexing repository docs:

```bash
OPENAI_API_KEY=... make real-content-package
```

The target prepares `/app/docs`, rebuilds the index with `text-embedding-3-small` at
768 dimensions, runs `ops/real-content-acceptance-cases.json`, and writes a backup
directory containing:

- `postgres.dump`
- `runtime-files.tar.gz`
- `real-content-acceptance-report.json`

The real course files stay outside git. If the runtime docs volume contains stale
Markdown not present in `course-materials-md/`, preparation fails and the stale files
must be handled manually one explicit path at a time.

The real-content targets default to an isolated Compose project named
`kb-real-content`, so local development `docs_data` volumes are not reused. Override
`REAL_CONTENT_COMPOSE_PROJECT` only when you intentionally want another isolated
artifact workspace.

## Restore Database

Restoring the database can replace existing tables and data. Require an explicit
confirmation variable:

```bash
make restore-db \
  RESTORE_DB_FILE=backups/20260527T120000Z/postgres.dump \
  CONFIRM_RESTORE=yes
```

The target uses `pg_restore --clean --if-exists` against the configured Compose Postgres
database.

## Restore Runtime Files

Restoring files overlays the archived `docs`, `raw`, and `.kb` paths into the app volume.
It does not delete stale files. If stale files must be removed, stop and handle those paths
manually one explicit file at a time.

```bash
make restore-files \
  RESTORE_FILES_FILE=backups/20260527T120000Z/runtime-files.tar.gz \
  CONFIRM_RESTORE=yes
```

## Post-Restore Checks

1. Run migrations once: `make migrate`.
2. Start the app.
3. Run `make ops-check API_URL=http://localhost:8000 KB_ADMIN_API_KEY=local-admin-key`.
4. Confirm `/ready` reports database, pgvector, migrations, storage, platform auth, and
   index checks.
5. Run a known search/chat smoke test against expected source IDs.

## Notes

- Keep backup files outside the runtime volumes being backed up.
- Store production backups in encrypted storage with retention policies.
- Do not commit backup artifacts to git.
