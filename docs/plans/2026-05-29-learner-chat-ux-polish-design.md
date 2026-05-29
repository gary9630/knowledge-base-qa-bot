# Learner Chat UX Polish Design

Date: 2026-05-29

## Goal

Make the learner-facing chat experience feel like a production course assistant without changing the existing three-column workbench architecture.

## Chosen Approach

Use a focused polish of the current chat surface.

This keeps the proven left-center-right layout intact while improving the first-run experience, streaming feedback, source trust cues, and citation interaction. The admin and ops tools remain in the app, but this work does not redesign those surfaces.

## User Experience Contract

The learner chat tab should clearly answer four questions:

1. What can I ask?
2. Is the assistant currently looking through course materials?
3. Which course sources shaped the answer?
4. Can I trust the answer, or did the knowledge base fail to confirm it?

The main transcript should stay student-readable. Retrieval diagnostics and score details remain in the right inspector.

## Chat Surface

The chat panel gets a course assistant header with concise status text, index freshness, and source count. The label should read as a learning tool, not an admin console.

The initial transcript becomes a structured empty state:

- a short "Course assistant" welcome
- sample prompt buttons drawn from current sample document themes
- a note that answers are grounded in indexed course sources

Sample prompts are static for this pass. They should cover course logistics, FAQ, and the Network Essentials sample content without requiring a new API.

## Composer

The composer should support normal chat behavior:

- Enter submits
- Shift+Enter inserts a newline
- submit is disabled while a stream is active
- empty input cannot submit
- the placeholder asks a course-specific question instead of generic "Ask the knowledge base"

During streaming, the composer shows a short status line. It starts with "Looking through course sources..." and updates when source candidates arrive.

## Streaming States

Streaming should expose a learner-friendly lifecycle:

1. User submits a query.
2. Assistant bubble appears with "Looking through course sources..."
3. When the `sources` event arrives, the bubble shows "Found N relevant source(s)."
4. When token events arrive, answer text replaces the status copy.
5. When the `done` event arrives, the answer footer shows grounding status and selected source chips.

Errors should produce a visible assistant error state and should re-enable the composer.

## Source Interaction

Each assistant answer should show source chips after completion:

- one chip per selected source
- chip label uses `source_id` when present
- clicking a chip previews that source in the right inspector

The chips are learner-facing. Score breakdowns stay in the inspector source rows and markdown preview.

## Answer Trust Copy

Answer quality should be translated into concise student-facing language:

- valid answer with selected sources: "Answered from N course source(s)."
- cannot confirm: "The knowledge base could not confirm this."
- invalid citations: "Answer needs source review."
- no indexed source answer: "The course knowledge base is not indexed yet."

The right inspector keeps the precise machine-readable diagnostics for debugging.

## Accessibility And Responsiveness

The polish must preserve keyboard navigation and screen reader labels:

- sample prompt buttons are real buttons
- source chips are buttons
- streaming status uses `aria-live`
- composer status uses `aria-live`
- mobile layout should avoid text overlap and keep the composer usable

## Testing

Use TDD for behavior changes.

Expected coverage:

- e2e/static UI test for the learner polish wiring
- JavaScript wiring strings for sample prompts, streaming status, answer footer, source chips, and keyboard submit
- existing chat stream and answer quality tests should keep passing
- browser smoke for desktop and mobile

No API or database schema change is expected.
