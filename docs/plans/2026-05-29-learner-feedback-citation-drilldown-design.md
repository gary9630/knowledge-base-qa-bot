# Learner Feedback and Citation Drilldown Design

## Goal

Make learner answers read like a production course assistant: citations use compact numeric markers, every marker opens the cited source, and learners can submit lightweight answer feedback that feeds the existing eval promotion workflow.

## Architecture

The backend keeps the existing source-id citation contract. Answer validation, eval cases, and feedback promotion continue to use exact source IDs such as `常見問題FAQ.md#課程網站`.

The learner UI maps those source IDs to display-only numbers based on the selected source order. The rendered answer replaces `[source_id]` with clickable `[1]` buttons. Clicking a citation or source chip previews the source section in the right inspector. Feedback posts to the existing protected `POST /feedback` endpoint using the assistant message ID returned by chat streaming.

## Data Flow

1. `/chat/stream` sends selected sources before answer tokens.
2. The UI stores selected sources and builds a `source_id -> display index` map.
3. When the `done` event arrives, the UI renders the assistant paragraph as text plus inline citation buttons.
4. Citation buttons call the existing candidate preview path.
5. Feedback controls post `{ message_id, rating, reason, expected_source, note }` to `/feedback`.
6. Admin eval promotion continues through the existing `/evals/cases/promote-feedback` route.

## UI Behavior

- Answer text uses inline citation buttons like `[1]`.
- Source chips use compact labels such as `[1] 常見問題FAQ`.
- Positive feedback can submit immediately.
- Negative feedback opens a compact note field and optional expected source selector.
- Successful feedback disables the controls for that answer and shows a short status.

## Testing

- Unit/e2e static UI tests cover citation helpers, feedback controls, and endpoint wiring.
- Integration tests continue to prove `/feedback` accepts assistant-message feedback and rejects user-message feedback.
- Browser verification checks that a real streamed answer renders numeric citations and that clicking a citation updates the preview pane.

