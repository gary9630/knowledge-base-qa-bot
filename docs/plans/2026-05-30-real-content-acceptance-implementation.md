# Real Content Acceptance Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a repeatable CLI/Makefile flow for indexing `course-materials-md/`, validating retrieval, and packaging DB/runtime artifacts for deployment.

**Architecture:** Add small scripts under `scripts/` for safe Markdown preparation, direct index rebuild, and retrieval acceptance reporting. Add Makefile targets that run those scripts in the existing Docker Compose app environment so the DB and runtime volumes match deployment.

**Tech Stack:** Python 3.12, FastAPI project settings, SQLAlchemy sessions, Postgres + pgvector, Docker Compose, pytest, ruff, mypy.

---

### Task 1: Safe Real Content Prepare Script

**Files:**
- Create: `scripts/prepare_real_content.py`
- Create: `tests/unit/test_prepare_real_content.py`

**Steps:**
1. Write tests for copying Markdown, preserving nested paths, rejecting stale target Markdown, and rejecting symlink paths.
2. Run `uv run --python 3.12 pytest tests/unit/test_prepare_real_content.py -q`; expect import failure.
3. Implement `prepare_real_content(source_dir, docs_dir)` with no deletes and stale-file detection.
4. Re-run tests; expect pass.

### Task 2: Acceptance Case Runner

**Files:**
- Create: `scripts/real_content_acceptance.py`
- Create: `tests/unit/test_real_content_acceptance.py`
- Create: `ops/real-content-acceptance-cases.json`

**Steps:**
1. Write tests for case evaluation and JSON report status.
2. Run the new tests; expect import failure.
3. Implement case loading, retrieval-result evaluation, report serialization, and CLI.
4. Re-run tests; expect pass.

### Task 3: Direct Index Rebuild CLI

**Files:**
- Create: `scripts/rebuild_index.py`
- Create: `tests/unit/test_rebuild_index_cli.py`

**Steps:**
1. Write tests that CLI returns non-zero when docs dir is missing and calls `IndexingService` in the success path via monkeypatch.
2. Run the new tests; expect import failure.
3. Implement a thin CLI around `Settings`, `SessionLocal`, `create_embedding_provider`, and `IndexingService.rebuild_index()`.
4. Re-run tests; expect pass.

### Task 4: Makefile Targets And Runbook

**Files:**
- Modify: `Makefile`
- Modify: `README.md`
- Modify: `ops/deploy.md`
- Modify: `ops/backup-restore.md`
- Modify: `AGENTS.md`
- Modify: `tests/unit/test_packaging_files.py`

**Steps:**
1. Add tests that Makefile exposes `real-content-prepare`, `real-content-index`, `real-content-acceptance`, and `real-content-package`.
2. Add targets that run scripts through Docker Compose with `course-materials-md/` mounted read-only.
3. Document the launch sequence and restore steps.
4. Re-run packaging tests.

### Task 5: Verification And Real Run

**Commands:**

```bash
make lint
make test-unit
node --check app/ui/static/app.js
make real-content-prepare
make real-content-index
make real-content-acceptance
make real-content-package
```

Expected:
- Static verification passes.
- Acceptance report passes all default cases.
- Backup directory contains `postgres.dump` and `runtime-files.tar.gz`.
