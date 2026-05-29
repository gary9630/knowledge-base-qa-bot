# Real Content Acceptance Design

## Goal

Create a repeatable launch rehearsal for real course materials in `course-materials-md/`, including indexing into Postgres + pgvector, validating retrieval quality, and producing deployable DB/runtime backup artifacts.

## Approved Approach

Use an app-native CLI and Makefile workflow.

The real course files remain outside git. The repository stores only scripts, acceptance case definitions, and runbooks. Operators can run the same flow locally, in staging, or in a production-prep environment.

## Workflow

1. Prepare runtime docs by copying Markdown from `course-materials-md/` into the configured runtime docs volume.
2. Rebuild the Postgres + pgvector index from those runtime docs.
3. Run acceptance cases against the indexed DB and fail if expected course source files are not retrieved.
4. Package the indexed DB and runtime files with the existing backup mechanism.
5. Restore those artifacts into the deployment target with the existing restore runbook.

## Safety Rules

- The workflow must not delete files.
- If the target docs directory contains stale Markdown files not present in the real-content source directory, the prepare step fails and asks the operator to clean the directory manually.
- Source directories and destination paths are checked for symlinks before copying.
- The package step reuses backup artifacts instead of committing real course content.

## Acceptance Cases

The default acceptance set focuses on stable, file-level retrieval expectations:

- CAP theorem
- Overload protection
- RAG
- Message queue
- Database indexing

Each case checks that the selected retrieval result includes an expected source filename. This is deliberately narrower than full answer quality because the deploy artifact being validated is the real content index.

## Deployment Artifact

The deployable artifact is a backup directory containing:

- `postgres.dump`: DB dump with documents, sections, chunks, embeddings, index jobs, and metadata.
- `runtime-files.tar.gz`: docs/raw/.kb runtime files.
- acceptance report JSON, either stored separately or copied into `.kb`.

Deployment restores the DB and runtime files with:

```bash
make restore-db RESTORE_DB_FILE=<artifact>/postgres.dump CONFIRM_RESTORE=yes
make restore-files RESTORE_FILES_FILE=<artifact>/runtime-files.tar.gz CONFIRM_RESTORE=yes
```

## Deferred

- Full LLM answer acceptance against OpenAI chat responses.
- Per-cohort acceptance cases.
- Automated upload of artifacts to managed backup storage.
