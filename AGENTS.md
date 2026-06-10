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
- Between retrieval and answering sits a context assembly layer: each retrieved chunk expands to its full section plus `KB_CONTEXT_NEIGHBOR_SECTIONS` neighbors within `KB_CONTEXT_TOKEN_BUDGET` tokens, used by chat, streaming chat, and the eval answer path.
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
- Process one background job: `make worker-once`
- Unit tests: `make test-unit`
- Integration tests: `make test-integration`
- E2E tests: `make test-e2e`
- Full local tests: `make test`
- Lint/typecheck: `make lint`
- Docker tests: `make docker-test`
- Ops smoke check: `make ops-check API_URL=http://localhost:8000 KB_ADMIN_API_KEY=local-admin-key`
- Deploy env validation: `make deploy-check`
- Compose app/worker smoke: `make docker-smoke`
- Compose backup: `make backup BACKUP_DIR=backups/$(date -u +%Y%m%dT%H%M%SZ)`
- Real content launch package: `OPENAI_API_KEY=... make real-content-package`
- Real content launch package with local Postgres port conflict: `KB_POSTGRES_PORT=55432 make real-content-package`
- CI workflow: `.github/workflows/ci.yml`

## Environment Notes

- Settings use the `KB_` prefix unless noted.
- Required for production/staging: `KB_AUTH_SECRET_KEY`, `KB_PLATFORM_USERNAME`, `KB_PLATFORM_PASSWORD`, `KB_ADMIN_API_KEY`.
- OpenAI providers require unprefixed `OPENAI_API_KEY`.
- Keep `KB_EMBEDDING_DIMENSION` aligned with the schema dimension, currently `768`.
- Real course content lives in local `course-materials-md/` and must remain out of git.
- Makefile includes `.env` when present, but only exports `OPENAI_API_KEY` and `KB_POSTGRES_PORT` intentionally. Do not use `.EXPORT_ALL_VARIABLES`; it pollutes local tests with deploy-only settings such as Docker-only database hosts.
- Local Compose defaults are only for development: platform login `student` / `student-password`, admin key `local-admin-key`.
- App-native abuse controls are enabled by default: tune `KB_RATE_LIMIT_*` values and `KB_MAX_CONCURRENT_UPLOADS` for the deploy target.
- Background worker reliability controls are `KB_BACKGROUND_JOB_STALE_AFTER_SECONDS`, `KB_BACKGROUND_JOB_RETRY_BASE_DELAY_SECONDS`, and `KB_BACKGROUND_JOB_RETRY_MAX_DELAY_SECONDS`.
- Worker runtime supervision controls are `KB_WORKER_ID`, `KB_WORKER_HEARTBEAT_INTERVAL_SECONDS`, and `KB_WORKER_HEARTBEAT_STALE_AFTER_SECONDS`; protected `GET /admin/jobs/runtime` exposes queue depth and worker heartbeat status.
- Source access labels are enforced across search, chat, sources, and mindmap. Learners see `public`, `role:<role>`, `user:<username>`, `cohort:<name>` from `KB_PLATFORM_COHORTS`, plus `KB_PLATFORM_EXTRA_VISIBILITY_LABELS`.
- `/ready` includes a storage check for `docs`, `raw`, and `.kb` path usability.
- Admin/security audit events are DB-backed in `audit_events` and exposed through protected `GET /admin/audit-events`.
- Document lifecycle is managed through protected `/admin/documents` routes. Non-active documents must stay hidden from sources, search/chat retrieval, and mindmap.
- Async orchestration is DB-backed in `background_jobs`; `POST /imports` enqueues `ingest.upload`, `POST /admin/jobs` can enqueue `index.rebuild`, `document.reindex`, and `eval.run`, and `python -m scripts.run_background_worker` processes them.
- Retrieval / answer quality is app-native: `/search`, `/chat`, and `/chat/stream` expose retrieval diagnostics and answer quality metadata without adding a reranker or LLM judge.

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
- Preserve the retrieval quality contract: every search/chat result should keep selected source IDs, rejected source IDs, score threshold, raw/merged/accepted/rejected counts, strategy counts, top score, and score debug data available through response diagnostics.
- Preserve the answer quality contract: every chat result should expose `answer_valid`, `citation_errors`, `selected_source_ids`, `cited_source_ids`, and `cannot_confirm_reason`.
- Streaming chat must send retrieval diagnostics in the `sources` event and answer quality in the `done` event.
- Persist retrieval diagnostics and answer quality in `RetrievalEvent.scores_json`; keep cited sources separate from selected sources.
- Never expose unselected source IDs as cited sources. Invalid provider citations should downgrade to the exact cannot-confirm answer with `cannot_confirm_reason="invalid_citations"`.
- Eval metrics should distinguish retrieval failure from citation failure. Keep `top1_hit`, `retrieval_recall`, `citation_recall`, `citation_precision`, `answer_valid`, and `citation_error_count` useful for dashboard/reporting.
- The right-side UI inspector owns answer quality and retrieval score breakdowns; avoid cluttering the main learner chat transcript with admin diagnostics.
- Store raw uploads and canonical Markdown on durable production storage before public launch.
- `POST /imports` must stay lightweight: save the raw artifact, create a queued ingestion job, enqueue `ingest.upload`, and let the worker convert Markdown and enqueue index rebuilds.
- Ingestion supports `.pdf`, `.md`, `.markdown`, `.txt`, `.html`, and `.htm`; reject empty uploads, obvious content-type mismatches, invalid PDF signatures, HTML without recognizable markup, and binary-looking text before writing raw artifacts.
- Same filename with different content should be kept as a new artifact using the content-hash suffix path strategy; identical content should remain deduplicated by hash.
- Keep ingestion job metadata useful for operations: original filename, detected file type, raw/canonical artifact filenames, path strategy, warnings, and Markdown byte size.
- Backup/restore runbook lives at `ops/backup-restore.md`; restore targets require `CONFIRM_RESTORE=yes` and do not remove stale files.
- Production deploy runbook lives at `ops/deploy.md`.
- Live answer acceptance runbook lives at `ops/live-answer-acceptance.md`.
- Production env template lives at `ops/env.production.example`; validate real deploy environments with `make deploy-check` before migration/restart.
- Do not expose admin endpoints publicly without the admin key or an authenticated gateway.
- Never store raw admin keys or platform passwords in audit metadata; use `fingerprint_secret()` for admin-key actor IDs.
- `DELETE /admin/documents/{document_id}` deletes DB index rows only; it must not remove canonical Markdown or raw upload files.
- Keep the background worker running in production. `IndexingJob` and `EvalRun` remain domain history; `BackgroundJob` is orchestration state.
- Production Compose should run the `worker` profile so `python -m scripts.run_background_worker` keeps processing jobs and writing DB-backed heartbeats.
- Workers recover stale `running` jobs before claiming new work. Use protected `POST /admin/jobs/recover-stale` for manual recovery and `POST /admin/jobs/{job_id}/requeue` for failed/canceled jobs.
- Run Alembic migrations once per deploy, then run `make ops-check`.
- Current real embedding contract is `text-embedding-3-small` with `KB_EMBEDDING_DIMENSION=768`.
- First production data loads should use `make real-content-package` to prepare `course-materials-md/`, rebuild the Compose DB index, run `ops/real-content-acceptance-cases.json`, and package `postgres.dump`, `runtime-files.tar.gz`, and `real-content-acceptance-report.json`.
- Real content packaging defaults to isolated Docker Compose project `kb-real-content`; change `REAL_CONTENT_COMPOSE_PROJECT` for another fresh artifact workspace instead of deleting volumes in bulk.
- Real content preparation refuses source/destination symlinks and fails on stale runtime Markdown instead of deleting files; stale files must be handled manually one explicit path at a time.
- Current verified local launch artifact is `backups/real-content-20260529T171708Z/`: 35 course files, 819 sections/chunks, retrieval acceptance 5/5 passed. It is intentionally ignored by git.
- Current OpenAI answer model default is `gpt-5.4-mini`; `/chat/stream` should forward provider streaming deltas and use the final `done.answer` as the validated persisted answer.
- Live answer acceptance against the real-content index passed 3/3 with `gpt-5.4-mini`: CAP theorem via `/chat`, RAG flow via `/chat`, and Message Queue via `/chat/stream`. This sends selected snippets to OpenAI Chat API and requires explicit operator approval.
- OpenAI provider controls are `KB_OPENAI_REQUEST_TIMEOUT_SECONDS`, `KB_OPENAI_MAX_RETRIES`, and `KB_OPENAI_CHAT_MAX_COMPLETION_TOKENS`; provider usage and error metadata should stay user-safe and be recorded through `/metrics` plus `RetrievalEvent.scores_json`.
- Protected `GET /admin/provider-observability` backs the Provider Ops UI tab with provider call summaries, token usage by operation, latest in-memory calls, and DB-backed answer traces; keep it admin-only and free of raw provider prompts, credentials, or source payload dumps.
- App-native provider budget guardrails are controlled by `KB_PROVIDER_BUDGET_*`; when `KB_PROVIDER_BUDGET_BLOCK_ON_EXCEEDED=true`, `/chat` returns 429 and `/chat/stream` emits a stable SSE error before calling the answer provider.
- If changing embedding model or dimension later, add a migration and rebuild the index.
- Sample content lives in `sample-docs/`; do not treat it as production data.
