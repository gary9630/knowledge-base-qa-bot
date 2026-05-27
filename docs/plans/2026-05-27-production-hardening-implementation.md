# Production Hardening Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Harden the app for public course usage by adding rate limits, source access control, durable storage/backup workflows, and deploy/CI guardrails.

**Architecture:** Use small app-native increments that match the current FastAPI, Postgres/pgvector, Docker Compose, and Makefile architecture. Start with in-process guards and explicit tests, then keep later interfaces replaceable for managed production infrastructure.

**Tech Stack:** FastAPI/Starlette ASGI middleware, Pydantic settings, SQLAlchemy/Postgres/pgvector, Alembic, Docker Compose, Makefile, pytest.

---

## Task 1: App-Native Rate Limiting And Upload Concurrency

**Files:**

- Create: `app/observability/rate_limit.py`
- Modify: `app/core/config.py`
- Modify: `app/main.py`
- Modify: `app/observability/metrics.py`
- Modify: `README.md`
- Test: `tests/unit/test_rate_limit.py`
- Test: `tests/unit/test_config.py`
- Test: `tests/unit/test_observability_middleware.py`

**Steps:**

1. Write failing tests for limiter config defaults and env overrides.
2. Write failing unit tests for fixed-window request limiting and window reset.
3. Write failing API tests proving `POST /auth/login` returns HTTP 429 after the configured login limit.
4. Write failing API tests proving `POST /imports` rejects excess concurrent uploads without reading the full body.
5. Implement `Settings` fields for enabling/disabling limits, per-bucket limits, and upload concurrency.
6. Implement an ASGI middleware that applies route policies, emits 429 JSON responses, and adds `Retry-After` / `X-RateLimit-*` headers.
7. Record rate-limit and concurrency rejections in the in-memory metrics snapshot.
8. Add README environment and operations notes.
9. Run focused tests, then `make test` and `make lint`.

## Task 2: Source-Level Access Control

**Files:**

- Create: migration for source access metadata if needed.
- Modify: `app/models/tables.py`
- Modify: `app/api/dependencies.py`
- Modify: retrieval, source, chat, mindmap, and eval services.
- Test: unit and integration tests for allowed/denied documents.

**Steps:**

1. Define a `Principal` model with roles and cohort labels.
2. Persist or derive document access grants from frontmatter.
3. Enforce grant filtering before candidates reach answer generation.
4. Apply the same access rules to source preview, mindmap, and eval cases.
5. Document the frontmatter contract.

## Task 3: Durable Storage And Backup-Restore

**Files:**

- Create: storage abstraction if object storage is introduced.
- Create: backup/restore runbook under `ops/` so Docker runtime `docs` volumes do not hide it.
- Modify: Docker Compose volume documentation.
- Test: packaging and smoke tests where practical.

**Steps:**

1. Document the supported production storage mode.
2. Add validation that production paths are configured and writable.
3. Add backup and restore commands/runbook.
4. Add post-restore smoke check instructions.

## Task 4: Production Deploy And CI/CD

**Files:**

- Create or modify CI workflow files if the repo adopts GitHub Actions.
- Modify: `Makefile`
- Modify: `README.md`
- Test: Docker config, image build, and ops smoke checks.

**Steps:**

1. Add CI targets for lint, unit, integration, Docker config, and e2e smoke.
2. Add deployment environment documentation.
3. Add migration and health-check deploy sequence.
4. Ensure secrets are documented as environment variables only.
