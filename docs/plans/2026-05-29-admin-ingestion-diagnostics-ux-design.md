# Admin Ingestion Diagnostics UX Design

## Context

The ingestion pipeline now records useful diagnostics in import job metadata: detected file
type, extension, normalized content type, raw and canonical artifact names, path strategy,
warnings, async processing state, Markdown byte size, and background job id. The current
Admin Uploads UI only shows filename, status, and updated time, so operators still need to
inspect raw JSON or logs to understand why an import chose a path, whether validation emitted
warnings, or which background job handled the upload.

## Scope

This pass keeps the existing API surface and makes `/imports/status` operationally useful in
the workbench:

- Add an import diagnostics summary above the import job list with counts for loaded jobs,
  active jobs, failed jobs, warning-bearing jobs, and duplicate jobs.
- Expand each import job row with status badges, artifact details, ingestion metadata,
  warnings, error text, content hash, and linked background job id when present.
- Preserve existing Retry behavior for failed import jobs.
- Keep the layout compact inside the Admin Uploads tab so it remains usable in the
  three-column workbench.

Out of scope: new ingestion states, raw file deletion, canonical preview, and backend schema
changes.

## Data Flow

1. Admin clicks Refresh or uploads a file.
2. The UI fetches `GET /imports/status` using the existing admin key header.
3. `renderImportJobs()` stores the jobs in UI state, renders the diagnostics summary, and
   renders each job row.
4. Job rows use the existing `metadata` object defensively. Missing fields fall back to
   readable placeholders instead of breaking rendering.

## Error Handling

Failed import jobs show both `job.error` and retry actions. Warning-bearing jobs surface the
warning codes from `metadata.import_warnings`. If the import status endpoint is unavailable,
the existing unavailable-state message remains and the diagnostics summary resets to zero.

## Testing

The API metadata is already covered by ingestion route and workflow tests. This UX pass adds
UI wiring coverage that asserts the diagnostics summary container, rendering functions, and
metadata fields are present in the served HTML/JS. Manual browser smoke should verify the
Admin Uploads tab remains readable after upload and refresh.
