# Ingestion Quality Hardening Design

## Context

The ingestion pipeline already stores raw uploads, queues async conversion, writes canonical
Markdown, deduplicates identical content, and retries failed jobs. The remaining production
risk is low-quality or ambiguous uploads entering durable storage without enough validation
or diagnostics.

## Scope

This pass hardens ingestion at the application boundary while keeping `POST /imports`
lightweight:

- Reject empty uploads, unsupported extensions, obvious content-type mismatches, PDF files
  without a PDF signature, HTML files without recognizable markup, and binary-looking text.
- Preserve the current async retry behavior for text decoding and parser errors.
- Keep deduplication by content hash for identical uploads.
- Allow same filename with different content by writing collision-safe artifact names using
  a content-hash suffix.
- Add import diagnostics to job metadata so admin status views can explain what happened.

## Data Flow

1. `POST /imports` reads the upload within `KB_MAX_UPLOAD_BYTES`.
2. `IngestionPipeline.queue_upload()` inspects filename, content type, and lightweight body
   signals before creating a job.
3. The pipeline computes the content hash and resolves artifact paths:
   - original filename if raw and canonical paths are unused
   - `<stem>-<hash12><ext>` and `<stem>-<hash12>.md` when the original destination is already
     occupied
4. The raw file is saved, a queued ingestion job is created, and `ingest.upload` is enqueued.
5. The worker converts raw bytes to Markdown, writes canonical Markdown, records
   `markdown_bytes`, and enqueues index rebuild when requested.

## Error Handling

Validation errors fail before a DB job or raw artifact is created. Worker-time conversion
errors still mark the ingestion job as `failed` with the raw artifact retained for retry.
Existing duplicate uploads are marked `duplicate` and point at the original raw and canonical
paths.

## Testing

The implementation uses unit tests for validation, collision-safe pathing, metadata, route
responses, and importer dispatch. Broader verification covers unit tests, integration tests,
and lint/typecheck.
