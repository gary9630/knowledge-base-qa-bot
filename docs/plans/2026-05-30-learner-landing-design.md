# Learner Landing And Admin Tab Visibility Design

## Goal

Create a student-facing landing page for the course assistant and make sure a platform
learner who signs in with the single configured account cannot see or use admin-side UI
tabs.

## Current State

The app already serves a three-column workbench from `/`. Platform auth is enforced by
`/auth/session`, `/auth/login`, the `kb_platform_session` cookie, and CSRF headers for
protected learner writes. Admin endpoints are separately protected by `X-KB-Admin-Key`.

The current unauthenticated UI is only a compact login form overlay. After platform login,
the DOM still exposes Admin Uploads, Provider Ops, Audit Log, and Feedback / Evals tabs.
Those routes are backend-protected, but the student experience still looks like an admin
tool.

## Product Design

Use `/` as both the public landing page and the authenticated app entry. Before login, show
a first-screen course assistant landing page with:

- Clear course-assistant positioning.
- A student login form using the existing platform login API.
- A product preview that reflects the real RAG workflow: question, cited answer, sources,
  and source preview.
- Short trust signals around course sources, grounded answers, and indexed materials.

After login, keep the existing workbench layout. For platform learners, show only learner
tabs:

- Chat
- Mindmap
- Sources

Hide admin-side tabs and admin-only controls:

- Admin Uploads
- Provider Ops
- Audit Log
- Feedback / Evals
- Source document lifecycle controls inside the Sources panel

In local development with platform auth unconfigured, keep the full workbench visible so
development/admin workflows remain available.

## Implementation Design

Mark admin-side tabs and panels with `data-admin-only`. Mark the admin-only source
lifecycle section the same way. Add a small client-side access policy:

- A restricted learner is `authRequired && authenticated`.
- Restricted learners hide all `data-admin-only` surfaces.
- `activateTab()` refuses admin-only tab names while restricted.
- Keyboard navigation skips hidden tabs.
- If the active tab becomes restricted after login, switch back to Chat.

This is a UX/access hardening layer, not the security boundary. Backend admin endpoints
remain protected by `X-KB-Admin-Key`, and learner APIs continue to use platform session
and CSRF validation.

## Testing

Add E2E/static UI tests that prove:

- The landing page contains the new learner login shell and product-preview content.
- Admin-only tabs/panels are marked with `data-admin-only`.
- Student-mode JS hides admin-only surfaces after authenticated platform login.
- `activateTab()` refuses restricted admin tabs.
- Keyboard navigation uses visible tabs, not hidden admin tabs.

Run the focused UI tests, then lint/typecheck. Use browser validation if a local server can
be started cleanly.
