# Source / Document Lifecycle Management Implementation

## Goal

Give admins operational control over indexed source documents after ingestion: inspect
index health, disable or restore sources, remove stale index rows, and reindex one
document without rebuilding the whole knowledge base.

## Scope

- Add `documents.lifecycle_status` with `active`, `disabled`, and `deleted` states.
- Hide non-active documents from learner-visible sources, search, chat retrieval, and
  mindmap responses.
- Add protected admin document APIs:
  - `GET /admin/documents`
  - `PATCH /admin/documents/{document_id}/lifecycle`
  - `DELETE /admin/documents/{document_id}`
  - `POST /admin/documents/{document_id}/reindex`
- Keep source files on disk when deleting from the index.
- Record lifecycle mutations in the audit trail.
- Add source-panel UI controls for document lifecycle operations.

## Design Notes

- `DELETE /admin/documents/{document_id}` means "delete from DB index"; it does not remove
  canonical Markdown or raw upload files.
- Reindexing a document sets it back to `active` and rebuilds its sections/chunks from the
  canonical Markdown path.
- Admin document responses include section/chunk counts, source-file existence, lifecycle
  status, and a computed index status for triage.
- Full rebuilds keep non-active documents out of the exported index payload.

## Verification

- Unit tests cover model defaults.
- UI wiring tests cover the new lifecycle controls.
- Docker-backed integration tests cover disable, enable, delete-from-index, reindex, audit
  events, and migration columns/indexes.
