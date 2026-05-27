# Agent Instructions

## Repository Safety Rules

- Do not batch-delete files or directories.
- Never use `del /s`, `rd /s`, `rmdir /s`, `Remove-Item -Recurse`, or `rm -rf`.
- If a file must be deleted, delete exactly one explicit file path at a time.
- If bulk deletion is needed, stop and ask the user to handle it manually.
- Do not revert user changes unless the user explicitly asks for that exact operation.
- Use `apply_patch` for manual file edits.

## Project Snapshot

- Product: FastAPI knowledge-base Q&A bot for course materials.
- Core flow: ingest PDF/Markdown/TXT/HTML, convert to canonical Markdown, index into Postgres + pgvector, answer with grounded citations.
- MVP intentionally uses Postgres + pgvector; FAISS is not in the current path.
- UI is a three-column workbench: left functional tabs, center chat/streaming answer, right sources/Markdown/index status.
- Platform auth is a single configured login for learners. It is not registration or full RBAC.
- Admin operations are separate and require `X-KB-Admin-Key`.

## Local Commands

- Install: `uv sync --python 3.12 --group dev`
- Start DB: `docker compose up -d postgres`
- Run migrations: `make migrate`
- Seed sample docs: `uv run --python 3.12 python -m scripts.seed_sample_docs`
- Start app: `make dev`
- Rebuild index: `make index`
- Unit tests: `make test-unit`
- Integration tests: `make test-integration`
- E2E tests: `make test-e2e`
- Full local tests: `make test`
- Lint/typecheck: `make lint`
- Docker tests: `make docker-test`
- Ops smoke check: `make ops-check API_URL=http://localhost:8000 KB_ADMIN_API_KEY=local-admin-key`
- Compose backup: `make backup BACKUP_DIR=backups/$(date -u +%Y%m%dT%H%M%SZ)`
- CI workflow: `.github/workflows/ci.yml`

## Environment Notes

- Settings use the `KB_` prefix unless noted.
- Required for production/staging: `KB_AUTH_SECRET_KEY`, `KB_PLATFORM_USERNAME`, `KB_PLATFORM_PASSWORD`, `KB_ADMIN_API_KEY`.
- OpenAI providers require unprefixed `OPENAI_API_KEY`.
- Keep `KB_EMBEDDING_DIMENSION` aligned with the schema dimension, currently `1536`.
- Local Compose defaults are only for development: platform login `student` / `student-password`, admin key `local-admin-key`.
- App-native abuse controls are enabled by default: tune `KB_RATE_LIMIT_*` values and `KB_MAX_CONCURRENT_UPLOADS` for the deploy target.
- Source access labels are enforced across search, chat, sources, and mindmap. Learners see `public`, `role:<role>`, `user:<username>`, `cohort:<name>` from `KB_PLATFORM_COHORTS`, plus `KB_PLATFORM_EXTRA_VISIBILITY_LABELS`.
- `/ready` includes a storage check for `docs`, `raw`, and `.kb` path usability.

## Testing Expectations

- Use TDD for new behavior: write the failing test, run it, implement, rerun.
- DB-backed tests need `KB_DATABASE_URL_TEST`; otherwise they are skipped.
- Docker/e2e verification is expected before claiming deploy packaging works.
- Before a final completion claim, run focused tests plus the broadest feasible verification.

## Production Hardening Backlog

Current priority order:

1. Rate limiting / abuse control.
2. Source-level access control by principal, role, and cohort.
3. Durable storage plus backup/restore runbooks.
4. Production deploy and CI/CD.

The app currently has app-native observability, `/health`, `/ready`, protected `/metrics`,
request IDs, structured logs, streaming error tracking, rate limiting, and upload
concurrency guards, and source visibility label enforcement. Prometheus/OpenTelemetry is
intentionally deferred until traffic or multi-replica deployment requires it.

## Important Implementation Tips

- Keep learner platform access separate from admin API key access.
- Apply source access filtering consistently across search, chat, streaming chat, source preview, and mindmap. Admin eval routes are still admin-only and should be reviewed if learner-specific eval personas are added.
- Store raw uploads and canonical Markdown on durable production storage before public launch.
- Backup/restore runbook lives at `ops/backup-restore.md`; restore targets require `CONFIRM_RESTORE=yes` and do not remove stale files.
- Production deploy runbook lives at `ops/deploy.md`.
- Do not expose admin endpoints publicly without the admin key or an authenticated gateway.
- Run Alembic migrations once per deploy, then run `make ops-check`.
- If switching to real embeddings, lock the model and vector dimension before indexing production data.
- Sample content lives in `sample-docs/`; do not treat it as production data.
