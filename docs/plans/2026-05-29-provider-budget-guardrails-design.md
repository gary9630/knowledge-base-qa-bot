# Provider Budget Guardrails Design

## Goal

Add app-native provider budget and alert guardrails so OpenAI/provider usage can be monitored, warned on, and optionally blocked before costs continue to accumulate.

## Approved Approach

Use Approach A: App-native Budget Guardrails.

This keeps the first production guardrail inside the FastAPI app and existing in-memory observability layer. It does not add Prometheus, OpenTelemetry, Redis, or a DB-backed provider ledger yet. The design is intentionally scoped to the current single-app process deployment model and can later be upgraded to a durable DB-backed daily ledger.

## Configuration

Add `KB_PROVIDER_BUDGET_*` settings:

- `KB_PROVIDER_BUDGET_ENABLED`: enable budget evaluation.
- `KB_PROVIDER_BUDGET_DAILY_TOKEN_LIMIT`: daily provider token budget. `0` means no token limit.
- `KB_PROVIDER_BUDGET_DAILY_CALL_LIMIT`: daily provider call budget. `0` means no call limit.
- `KB_PROVIDER_BUDGET_ERROR_RATE_LIMIT`: maximum provider error rate. `0` means no error-rate limit.
- `KB_PROVIDER_BUDGET_WARNING_RATIO`: ratio of budget usage that becomes a warning.
- `KB_PROVIDER_BUDGET_BLOCK_ON_EXCEEDED`: when true, block answer-provider calls once a budget is exceeded.

Defaults should be production-safe but non-disruptive: evaluation enabled, warning ratio present, hard numeric limits disabled, and blocking disabled until explicitly configured.

## Data Flow

Provider calls continue to be recorded through `ProviderCallRecord` and `InMemoryMetrics`.

A new budget evaluator reads the metrics snapshot and settings, calculates token, call, and error-rate budget states, and returns a structured budget response:

- overall status: `ok`, `warning`, or `exceeded`
- blocking decision
- per-policy status
- current usage, configured limit, warning threshold, and remaining budget
- human-readable reasons for admin UI and API responses

`GET /admin/provider-observability` returns the budget block alongside the existing provider summary, usage, latest calls, and answer traces.

## Enforcement

`/chat` and `/chat/stream` check the provider budget after retrieval and before answer-provider execution.

If the budget is `exceeded` and `KB_PROVIDER_BUDGET_BLOCK_ON_EXCEEDED=true`:

- `/chat` returns HTTP 429.
- `/chat/stream` returns a stable SSE `error` event.
- No answer-provider call is made.
- The user-facing error stays generic and does not expose internal budget numbers.

When blocking is disabled, requests continue but budget status remains visible in Provider Ops.

## UI

Provider Ops gains a Budget section with:

- overall budget state
- token, call, and error-rate cards
- warning/exceeded badges
- block mode state

The UI should remain admin-focused. Learner chat should not display cost or budget internals.

## Testing

Use TDD:

- Unit tests for settings defaults and overrides.
- Unit tests for budget evaluator thresholds, warning, exceeded, and blocking decisions.
- API tests that provider observability includes budget status.
- Chat tests proving block mode prevents provider execution and returns stable errors.
- E2E UI wiring tests for the Budget section.

## Deferred

- Durable DB-backed provider ledger.
- Per-user or per-cohort provider budgets.
- Actual currency estimates by model pricing.
- External alert delivery.
