# Admin Audit Trail / Security Event Log Implementation

## Goal

Add a production-ready, app-native audit trail for security-sensitive behavior without
introducing a separate observability stack.

## Scope

- Persist audit events in Postgres via `audit_events`.
- Record platform login success, login failure, and logout.
- Record admin access grants and denials for admin-protected routes.
- Record rate-limit and upload-concurrency blocks.
- Expose protected admin filtering through `GET /admin/audit-events`.
- Avoid storing raw admin keys or platform passwords.

## Design Notes

- Audit writes are best-effort and must not block the main request path if storage fails.
- Admin key actor IDs are SHA-256 fingerprints truncated to 16 hex characters.
- Request context includes request ID, method, path, client host, and user agent.
- Query filters are exact-match filters for `event_type`, `outcome`, and `actor_type`.

## Verification

- Unit tests cover audit defaults, secret fingerprinting, injected audit recorder behavior,
  and security events from rate-limit middleware.
- DB-backed integration tests cover auth audit writes and the admin audit API.
- Docker-backed tests should be used to verify Alembic migration and integration coverage.
