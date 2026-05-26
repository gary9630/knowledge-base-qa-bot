# Eval Automation and Reporting Design

Date: 2026-05-26

## Goal

Turn the existing eval workflow into an operational regression system. Admins can seed baseline eval cases, promote bad feedback into regression cases, run evals from Docker/CLI on a schedule, and inspect eval health in the workbench.

## Chosen Approach

Use a Docker/CLI runner for scheduled eval execution.

This keeps scheduling outside the FastAPI process, which is safer for deploys with multiple app replicas. A cron job, GitHub Actions workflow, Codex automation, or platform scheduler can run the same command inside Docker. The app remains responsible for admin APIs and the report dashboard; the CLI runner reuses the same eval service and database models.

## Data Model

Extend `eval_cases`:

```text
source_kind             manual | seed | feedback
seed_key                stable unique key for seeded baseline cases
promoted_feedback_id    optional link to feedback that produced the case
```

Extend `eval_runs`:

```text
trigger                 manual | scheduled | api | cli
```

`metadata` remains the flexible place for provenance details such as fixture version, feedback rating, assistant message id, and source document hints.

## Seed Cases

Seed cases are idempotent. Each seed has a stable `seed_key`; re-running seed import updates the same eval case instead of creating duplicates.

Seed inputs:

```json
{
  "seed_key": "faq-course-site",
  "name": "FAQ course site",
  "query": "課程網站在哪？",
  "expected_decision": "can_answer",
  "expected_source_ids": ["常見問題FAQ.md#課程網站"],
  "tags": ["seed", "faq"]
}
```

Runtime entry points:

```text
POST /evals/seed              # admin API, uses bundled defaults or request cases
scripts/seed_eval_cases.py    # CLI for deploy/bootstrap
make eval-seed
```

## Feedback Promotion

Feedback remains attached to assistant messages. Promotion creates or updates an eval case from a feedback record.

Promotion flow:

```text
feedback -> assistant message -> preceding user message -> eval case
```

The eval query is the preceding user message. Expected sources come from the promotion request first, then `feedback.expected_source`. Metadata stores feedback id, assistant message id, conversation id, rating, reason, and note. A unique `promoted_feedback_id` makes promotion idempotent.

Runtime entry points:

```text
GET  /feedback                # admin list for promotion queue
POST /evals/cases/promote-feedback
```

## Scheduled Eval Runner

The CLI runner calls the same core eval runner used by the API.

```text
scripts/run_evals.py --trigger scheduled --strategy hybrid --limit 5
make eval-run
docker compose --profile eval run --rm eval-runner
```

The runner writes `eval_runs` and `eval_results`. The command exits non-zero only when execution fails unless `--fail-on-regression` is set, in which case failed eval cases also produce a non-zero exit.

## Report Dashboard

`GET /evals/report` returns:

```text
case totals: total, active, by source kind
latest run: status, trigger, pass rate, average score
recent runs: newest N run summaries
latest failures: failing results from the latest run
worst cases: cases with the most failures across recent runs
```

The UI keeps the existing three-column workbench. The `Feedback / Evals` tab gains:

```text
report cards
recent run history
latest failed cases
feedback promotion queue
seed/run controls
```

## Error Handling

- Seed import rejects blank names, blank queries, duplicate seed keys in one request, and invalid expected decisions.
- Promotion returns 404 when feedback does not exist and 400 when the feedback is not attached to an assistant message with a preceding user message.
- Scheduled runs persist failed `EvalRun` records with error text.
- Report endpoint returns an empty report, not 404, when no runs exist.

## Testing

Unit tests:

```text
seed upsert behavior
feedback promotion query/source mapping
report aggregation
CLI argument handling and exit codes
```

Integration tests:

```text
POST /evals/seed is idempotent
POST /evals/cases/promote-feedback creates one case per feedback
scripts/run_evals.py persists scheduled runs
GET /evals/report returns trends and failures
admin endpoints require admin key
```

E2E tests:

```text
UI exposes seed, promotion, report, and run dashboard wiring
Docker app serves the dashboard
```
