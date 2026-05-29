# Live Answer Acceptance Runbook

Use this runbook after restoring the real-content artifact and before inviting learners.
It verifies the full RAG answer path, not only retrieval.

## Scope

Live answer acceptance sends the user query and selected course snippets to the configured
answer provider. When `KB_ANSWER_PROVIDER=openai`, get explicit operator approval before
running this check against private course material.

The current accepted launch configuration is:

- Embedding provider: `openai`
- Embedding model: `text-embedding-3-small`
- Embedding dimension: `KB_EMBEDDING_DIMENSION=768`
- Answer provider: `openai`
- Answer model: `gpt-5.4-mini`
- Retrieval strategy: `hybrid`

## Prerequisites

1. Restore or build the real-content artifact with `make real-content-package`.
2. Start the app with learner platform auth configured.
3. Keep `OPENAI_API_KEY` outside git and loaded through the deploy environment.
4. If local port `5432` is already in use, set `KB_POSTGRES_PORT=55432` for the
   isolated `kb-real-content` Compose project.

## Required Cases

Run these checks through `/chat` or `/chat/stream` after logging in as the learner:

| Case | Endpoint | Query intent | Expected cited source |
| --- | --- | --- | --- |
| CAP theorem | `/chat` | CAP theorem meaning and tradeoff | `1-基本觀念-03-CAP Theorem.md` |
| RAG flow | `/chat` | RAG retrieval/generation flow | `2-設計模式-08-RAG (Retrieval-Augmented Generation).md` |
| Message queue | `/chat/stream` | Message Queue use cases | `3-常用技術-07-Message Queue.md` |

## Pass Criteria

Each case must satisfy all of the following:

- `decision` is `can_answer`.
- `answer_quality.answer_valid` is `true`.
- `answer_quality.cannot_confirm_reason` is `null`.
- `answer_quality.cited_source_ids` is non-empty.
- Every cited source ID is present in `answer_quality.selected_source_ids`.
- The expected file appears in both selected and cited source IDs.
- The answer includes bracketed citations.
- For `/chat/stream`, the stream emits `sources`, one or more `token` events, and `done`.
  The selected sources come from the `sources` event; answer quality comes from `done`.

## Latest Local Acceptance

The current local real-content index was accepted with:

- Real-content package artifact: `backups/real-content-20260529T171708Z/`
- Indexed content: 35 files, 819 sections/chunks
- Retrieval acceptance: 5/5 passed
- Live answer acceptance: 3/3 passed

The artifact directory is intentionally ignored by git. Move it through an encrypted
artifact path when deploying.
