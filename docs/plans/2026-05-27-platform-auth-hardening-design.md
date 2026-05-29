# Platform Auth Hardening Design

Date: 2026-05-27

## Goal

Add a production-oriented platform login for one course-facing user, without registration or multi-user account management. The platform user is distinct from admin access.

## Chosen Approach

Use signed cookie sessions for the platform user and keep the existing `X-KB-Admin-Key` path for admin and automation. This gives students a normal login flow while preserving the current deploy, CLI, Docker eval runner, and curl workflows.

This is intentionally not a full user system. There is no signup, reset flow, invitation system, profile page, or database user table in this version.

## Roles

```text
platform user
  - one configured username/password
  - can access the workbench
  - can chat, search, view sources, view mindmap, and submit feedback

admin
  - existing admin API key
  - can upload, retry imports, rebuild index, seed/run evals, promote feedback
  - remains separate from platform user
```

## Configuration

Add settings:

```text
KB_AUTH_SECRET_KEY
KB_PLATFORM_USERNAME
KB_PLATFORM_PASSWORD
KB_PLATFORM_SESSION_TTL_SECONDS
```

Development remains open when platform credentials are not configured. Production and staging fail closed: platform-protected routes return `503` until the platform login settings and auth secret are configured.

## Session Model

The login route verifies the configured platform username/password and writes a signed HttpOnly cookie. The cookie payload stores:

```text
sub       platform username
role      platform
csrf      random CSRF token
exp       unix expiry timestamp
```

The signature uses HMAC-SHA256 with `KB_AUTH_SECRET_KEY`. Cookies use SameSite=Lax. Secure cookies are enabled in production/staging.

## API Surface

New routes:

```text
POST /auth/login
POST /auth/logout
GET  /auth/session
```

Platform-protected routes:

```text
POST /search
POST /chat
POST /chat/stream
GET  /sources
GET  /sources/{document_id}
GET  /sources/{document_id}/sections/{section_id}
GET  /mindmap
POST /feedback
```

Public routes:

```text
GET /health
GET /ready
GET /
GET /static/*
POST /auth/login
POST /auth/logout
GET /auth/session
```

Admin routes keep their existing admin-key requirement. The platform user does not become admin.

## CSRF

Cookie-authenticated unsafe requests must include `X-KB-CSRF-Token`. The UI receives the token from `GET /auth/session` and attaches it to POST requests. Admin-key requests are not CSRF checked because they do not use cookie authentication.

## UI

The workbench loads publicly but starts in a login state when platform auth is configured. The login view asks for platform username/password. After login, the normal three-column workbench becomes usable. Admin operations continue to ask for the admin key in this version.

## Error Handling

```text
401 invalid or missing platform session
403 missing or invalid CSRF token
503 platform auth required but not configured in production/staging
```

Login failures return a generic `401` so the API does not reveal which credential was wrong.

## Testing

Unit tests:

```text
session tokens round-trip and reject tampering/expiry
platform dependency allows development when unconfigured
platform dependency fails closed in production when unconfigured
CSRF is required for unsafe cookie-authenticated requests
```

Integration tests:

```text
login/session/logout workflow
configured platform auth protects chat/search/sources/mindmap/feedback
API key admin workflows remain compatible
```

E2E/UI tests:

```text
login panel exists
frontend calls /auth/session and /auth/login
state-changing fetches include X-KB-CSRF-Token
```
