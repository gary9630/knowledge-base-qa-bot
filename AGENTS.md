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
- Concept graph: 5 tables (`concepts`, `concept_clusters`, `concept_edges`, `concept_sources`, `concept_extraction_state`). Concepts with `origin='seed'` are protected from orphan pruning; cluster assignments are immutable once made (new concepts get assigned, existing ones never move). Extraction runs as a background job chained after index rebuild; it is incremental (only new or content-changed documents are processed) and skips without error when `KB_ANSWER_PROVIDER` is not `openai`. The curated seed dataset lives at `docs/plans/2026-06-11-concept-graph-seed.json` and is loaded via `make graph-seed`, which marks all currently active documents as extracted to prevent duplicates.
- Query guardrail: before retrieval, `app/answer/query_router.py` classifies each chat query with an LLM (`gpt-5.4-mini`, JSON mode): off-topic / harmful / prompt-injection queries are blocked with the fixed reply 「這個問題和學習無關，Let's learn together!」; allowed course questions are tagged easy/hard in the same call, and hard questions answer with `KB_OPENAI_CHAT_MODEL_HARD` (default `gpt-5.4`). The router fails open (easy course question) on provider errors.
- Every LLM call (router + answer, streaming included) is persisted to `provider_call_logs` with full request messages, response content, usage, latency, and provider request id, keyed by `conversation_id`/`retrieval_event_id` for tracing.
- Admin runtime settings (`runtime_settings` table, `GET/PUT /admin/settings`) override chat model, hard model, router model, max output tokens, temperature, and provider budgets without a restart; `get_effective_settings` merges them over env settings per request.
- UI: a pre-login landing page (topbar 登入) gates a three-pane learner workbench (left tabs: chat / 知識圖譜 / Sources; center content; right citation sources + 來源內容 reader). Learner chat has a toolbar: 🧹 清除對話, ⬇ 匯出 JSON, 🚩 回報問題 (copies the conversation id and writes a `chat.session_reported` audit event). Mermaid code fences in course materials render as diagrams (vendored `mermaid.min.js`, code-block fallback). Dual theme (light/dark/auto) on scholarly design tokens in `app/ui/static/app.css`.
- Learner UI principle: keep diagnostics (scores, index status, answer-quality internals) out of learner-facing surfaces; the admin console owns them.
- Admin console panels: overview, uploads/indexing, 教材編輯 (markdown CRUD + reindex), document lifecycle, graph extraction, evals, 服務狀態 (system health), 系統設定 (runtime settings), background jobs, provider usage (incl. LLM call logs with request/response), audit log (sortable table).
- Auth: two configured logins — learner (`KB_PLATFORM_USERNAME/PASSWORD`, role `student`) and admin (`KB_ADMIN_USERNAME/PASSWORD`, role `admin`). Only the admin role sees the 管理主控台 entry; an admin session or `X-KB-Admin-Key` authorizes `/admin/*` routes. No registration or full RBAC.

## Local Commands

- Install: `uv sync --python 3.12 --group dev`
- Start DB: `docker compose up -d postgres`
- Run migrations: `make migrate`
- Seed sample docs: `uv run --python 3.12 python -m scripts.seed_sample_docs`
- Seed concept graph: `make graph-seed`
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
- Required for production/staging: `KB_AUTH_SECRET_KEY`, `KB_PLATFORM_USERNAME`, `KB_PLATFORM_PASSWORD`, `KB_ADMIN_USERNAME`, `KB_ADMIN_PASSWORD`, `KB_ADMIN_API_KEY`.
- Query router / difficulty routing: `KB_QUERY_ROUTER_ENABLED` (default true), `KB_OPENAI_ROUTER_MODEL` (default `gpt-5.4-mini`), `KB_OPENAI_CHAT_MODEL_HARD` (default `gpt-5.4`). `KB_OPENAI_CHAT_MAX_COMPLETION_TOKENS` defaults to 4096.
- OpenAI providers require unprefixed `OPENAI_API_KEY`.
- Keep `KB_EMBEDDING_DIMENSION` aligned with the schema dimension, currently `768`.
- Real course content lives in local `course-materials-md/` and must remain out of git.
- Makefile includes `.env` when present, but only exports `OPENAI_API_KEY` and `KB_POSTGRES_PORT` intentionally. Do not use `.EXPORT_ALL_VARIABLES`; it pollutes local tests with deploy-only settings such as Docker-only database hosts.
- Local Compose defaults are only for development: platform login `student` / `student-password`, admin key `local-admin-key`.
- App-native abuse controls are enabled by default: tune `KB_RATE_LIMIT_*` values and `KB_MAX_CONCURRENT_UPLOADS` for the deploy target.
- Background worker reliability controls are `KB_BACKGROUND_JOB_STALE_AFTER_SECONDS`, `KB_BACKGROUND_JOB_RETRY_BASE_DELAY_SECONDS`, and `KB_BACKGROUND_JOB_RETRY_MAX_DELAY_SECONDS`.
- Worker runtime supervision controls are `KB_WORKER_ID`, `KB_WORKER_HEARTBEAT_INTERVAL_SECONDS`, and `KB_WORKER_HEARTBEAT_STALE_AFTER_SECONDS`; protected `GET /admin/jobs/runtime` exposes queue depth and worker heartbeat status.
- Source access labels are enforced across search, chat, sources, and the knowledge graph. Learners see `public`, `role:<role>`, `user:<username>`, `cohort:<name>` from `KB_PLATFORM_COHORTS`, plus `KB_PLATFORM_EXTRA_VISIBILITY_LABELS`.
- `/ready` includes a storage check for `docs`, `raw`, and `.kb` path usability.
- Admin/security audit events are DB-backed in `audit_events` and exposed through protected `GET /admin/audit-events`.
- Document lifecycle is managed through protected `/admin/documents` routes. Non-active documents must stay hidden from sources, search/chat retrieval, and the knowledge graph.
- Async orchestration is DB-backed in `background_jobs`; `POST /imports` enqueues `ingest.upload`, `POST /admin/jobs` can enqueue `index.rebuild`, `document.reindex`, and `eval.run`, and `python -m scripts.run_background_worker` processes them.
- Retrieval / answer quality is app-native: `/search`, `/chat`, and `/chat/stream` expose retrieval diagnostics and answer quality metadata without adding a reranker or LLM judge.

## Testing Expectations

- Use TDD for new behavior: write the failing test, run it, implement, rerun.
- Tests never read the local `.env` (`tests/conftest.py` sets `Settings.model_config["env_file"] = None`); tests that need specific settings pass them explicitly to `Settings(...)`.
- DB-backed tests need `KB_DATABASE_URL_TEST`; otherwise they are skipped. Local recipe: create a `kb_test` database with the `vector` extension on the compose Postgres, then run `KB_DATABASE_URL_TEST="postgresql+psycopg://kb:kb@localhost:5432/kb_test" make test-integration`.
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
- Apply source access filtering consistently across search, chat, streaming chat, source preview, and the knowledge graph. Admin eval routes are still admin-only and should be reviewed if learner-specific eval personas are added.
- Preserve the retrieval quality contract: every search/chat result should keep selected source IDs, rejected source IDs, score threshold, raw/merged/accepted/rejected counts, strategy counts, top score, and score debug data available through response diagnostics.
- Preserve the answer quality contract: every chat result should expose `answer_valid`, `citation_errors`, `selected_source_ids`, `cited_source_ids`, and `cannot_confirm_reason`.
- Streaming chat must send retrieval diagnostics in the `sources` event and answer quality in the `done` event.
- Persist retrieval diagnostics and answer quality in `RetrievalEvent.scores_json`; keep cited sources separate from selected sources.
- Cited source IDs must be sections the answer provider was actually given: selected sections or their context-assembly neighbors (never arbitrary IDs). Citation matching is normalized (anchors are slugified, surrounding punctuation tolerated) so heading punctuation variants still match. An answer with at least one valid citation stays valid — unmatched citation tokens become warnings, and the frontend maps them to a same-file pill or hides them gracefully. Only answers with zero valid citations downgrade to the exact cannot-confirm answer with `cannot_confirm_reason="invalid_citations"`.
- Guardrail-blocked queries persist as `cannot_confirm` with `cannot_confirm_reason="guardrail_blocked"` and the route decision in `scores_json.query_route`; the UI shows no citations and no source rail for them.
- Debug-trace chain for a reported session: audit `chat.session_reported` (conversation id) → `retrieval_events.conversation_id` → `provider_call_logs.conversation_id` (full LLM request/response). Keep all three keyed by conversation id.
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
- OpenAI provider controls are `KB_OPENAI_REQUEST_TIMEOUT_SECONDS`, `KB_OPENAI_MAX_RETRIES`, and `KB_OPENAI_CHAT_MAX_COMPLETION_TOKENS` (default 4096); learner-facing responses and `/metrics` stay free of raw prompts, while the admin-only `provider_call_logs` table deliberately stores full request/response payloads for debugging.
- Protected `GET /admin/provider-observability` backs the Provider Ops UI tab with provider call summaries, token usage by operation, latest in-memory calls, and DB-backed answer traces; protected `GET /admin/provider-logs` exposes the full request/response call log. Both stay admin-only and free of credentials.
- Protected `GET /admin/system-status` aggregates DB latency, readiness checks, index freshness, worker heartbeats, and provider budget for the 服務狀態 console panel.
- Admin markdown editing: `GET/PUT /admin/documents/{id}/content` reads/overwrites the canonical file and reindexes the document (docs root is derived from the document's canonical path, not `KB_DOCS_DIR`); creation goes through the normal `/imports` flow.
- App-native provider budget guardrails are controlled by `KB_PROVIDER_BUDGET_*`; when `KB_PROVIDER_BUDGET_BLOCK_ON_EXCEEDED=true`, `/chat` returns 429 and `/chat/stream` emits a stable SSE error before calling the answer provider.
- If changing embedding model or dimension later, add a migration and rebuild the index.
- Sample content lives in `sample-docs/`; do not treat it as production data.
