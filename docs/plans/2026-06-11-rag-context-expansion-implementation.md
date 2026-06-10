# RAG Context Expansion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Feed the answer LLM full sections plus a ±K neighboring-section window under a real token budget, fuse hybrid retrieval with RRF, count tokens with tiktoken, and prove the improvement with an auto-generated eval set.

**Architecture:** Retrieval stays chunk-level. A new context assembly layer between `HybridRetriever` and `AnswerService` expands hits into full sections + neighbors (requires a new `Section.position` column). Hybrid fusion switches from max-score merge to normalized Reciprocal Rank Fusion with a pre-fusion raw-score floor preserving the cannot-confirm gate. An eval-generation script produces ~25 cases so a baseline is recorded **before** any behavior change.

**Tech Stack:** FastAPI, SQLAlchemy 2 + Alembic, Postgres + pgvector, tiktoken, OpenAI SDK, pytest. Spec: `docs/plans/2026-06-11-rag-context-expansion-design.md`.

**Conventions for this repo:**
- Run Python via `uv run --python 3.12 ...` (matches Makefile `$(UV)`).
- DB-backed tests need `KB_DATABASE_URL_TEST` (Postgres with pgvector); they skip otherwise. Start it with `docker compose up -d postgres` and use `postgresql+psycopg://kb:kb@localhost:5432/kb_test` (check `docker-compose.yml` for the mapped port; Makefile loads `.env` which may set `KB_POSTGRES_PORT`).
- Lint/typecheck: `make lint` (ruff + mypy strict). Line length 100.
- All new modules need full type annotations (mypy strict).

**Task order matters:** Task 1 (eval generation) and Task 2 (baseline) MUST complete before Tasks 3–8 change retrieval behavior, so the baseline measures current behavior.

---

### Task 1: Eval case generation module + script + Make target

Additive only — no behavior change to retrieval/answering.

**Files:**
- Create: `scripts/generate_eval_cases.py`
- Test: `tests/unit/test_generate_eval_cases.py`
- Modify: `Makefile` (add `eval-generate` target, extend `.PHONY` on line 30)

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_generate_eval_cases.py`:

```python
from __future__ import annotations

import json

from scripts.generate_eval_cases import (
    SectionRecord,
    build_generation_prompt,
    build_negative_prompt,
    build_verification_prompt,
    generate_eval_seed_dicts,
    group_sections,
    parse_generated_cases,
    parse_negative_cases,
    verification_passed,
)


def _records(count: int, filename: str = "doc.md") -> list[SectionRecord]:
    return [
        SectionRecord(
            filename=filename,
            source_id=f"{filename}#sec-{index}",
            heading=f"Heading {index}",
            body_md=f"Body text {index}",
        )
        for index in range(count)
    ]


def test_group_sections_builds_consecutive_groups_per_file() -> None:
    records = _records(5)
    groups = group_sections(records, group_size=3)

    assert all(group.filename == "doc.md" for group in groups)
    assert [len(group.sections) for group in groups] == [3, 3]
    assert groups[0].sections[0].source_id == "doc.md#sec-0"
    assert groups[1].sections[0].source_id == "doc.md#sec-3"


def test_group_sections_does_not_mix_files() -> None:
    records = _records(2, filename="a.md") + _records(2, filename="b.md")
    groups = group_sections(records, group_size=3)

    filenames = {group.filename for group in groups}
    assert filenames == {"a.md", "b.md"}
    for group in groups:
        assert all(section.filename == group.filename for section in group.sections)


def test_parse_generated_cases_keeps_only_allowed_source_ids() -> None:
    raw = json.dumps(
        {
            "cases": [
                {
                    "name": "valid case",
                    "query": "課程網站在哪裡？",
                    "expected_source_ids": ["doc.md#sec-1"],
                },
                {
                    "name": "hallucinated source",
                    "query": "亂掰的問題",
                    "expected_source_ids": ["other.md#nope"],
                },
                {"name": "missing query"},
            ]
        }
    )

    cases = parse_generated_cases(raw, allowed_source_ids={"doc.md#sec-1"})

    assert len(cases) == 1
    assert cases[0]["query"] == "課程網站在哪裡？"
    assert cases[0]["expected_source_ids"] == ["doc.md#sec-1"]


def test_parse_generated_cases_rejects_invalid_json() -> None:
    assert parse_generated_cases("not json", allowed_source_ids=set()) == []


def test_parse_negative_cases_returns_queries_only() -> None:
    raw = json.dumps({"cases": [{"name": "neg", "query": "本課程有期末考嗎？"}]})

    cases = parse_negative_cases(raw)

    assert cases == [{"name": "neg", "query": "本課程有期末考嗎？"}]


def test_verification_passed_parses_answerable_flag() -> None:
    assert verification_passed(json.dumps({"answerable": True})) is True
    assert verification_passed(json.dumps({"answerable": False})) is False
    assert verification_passed("garbage") is False


def test_prompts_contain_sections_and_query() -> None:
    records = _records(2)
    group = group_sections(records, group_size=2)[0]

    generation = build_generation_prompt(group, case_count=2)
    assert "doc.md#sec-0" in generation
    assert "Body text 1" in generation

    negative = build_negative_prompt([group], case_count=2)
    assert "doc.md" in negative

    verification = build_verification_prompt(
        query="課程網站在哪裡？",
        sections=list(group.sections),
    )
    assert "課程網站在哪裡？" in verification
    assert "doc.md#sec-0" in verification


class FakeCaller:
    """Returns canned generation, then verification responses."""

    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self.calls: list[tuple[str, str]] = []

    def complete(self, *, system: str, user: str) -> str:
        self.calls.append((system, user))
        return self._responses.pop(0)


def test_generate_eval_seed_dicts_verifies_and_namespaces_cases() -> None:
    records = _records(3)
    groups = group_sections(records, group_size=3)
    generation_response = json.dumps(
        {
            "cases": [
                {
                    "name": "fact",
                    "query": "Heading 0 是什麼？",
                    "expected_source_ids": ["doc.md#sec-0"],
                },
                {
                    "name": "cross-section",
                    "query": "綜合問題？",
                    "expected_source_ids": ["doc.md#sec-0", "doc.md#sec-1"],
                },
            ]
        }
    )
    verification_ok = json.dumps({"answerable": True})
    verification_bad = json.dumps({"answerable": False})
    negative_response = json.dumps({"cases": [{"name": "neg", "query": "有期末考嗎？"}]})
    caller = FakeCaller(
        [generation_response, verification_ok, verification_bad, negative_response]
    )

    seed_dicts = generate_eval_seed_dicts(
        caller,
        groups,
        target_count=2,
        negative_count=1,
        max_rounds=1,
    )

    positive = [case for case in seed_dicts if case["expected_decision"] == "can_answer"]
    negative = [case for case in seed_dicts if case["expected_decision"] == "cannot_confirm"]
    assert len(positive) == 1  # second case failed verification
    assert len(negative) == 1
    assert positive[0]["seed_key"].startswith("auto.")
    assert positive[0]["tags"] == ["auto"]
    assert negative[0]["expected_source_ids"] == []
    seed_keys = [case["seed_key"] for case in seed_dicts]
    assert len(seed_keys) == len(set(seed_keys))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --python 3.12 pytest tests/unit/test_generate_eval_cases.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'scripts.generate_eval_cases'`

- [ ] **Step 3: Implement the module**

Create `scripts/generate_eval_cases.py`:

```python
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.document_lifecycle import active_document_filter
from app.models.tables import Document, Section

GENERATION_SYSTEM_PROMPT = (
    "You create evaluation cases for a course knowledge-base QA bot. "
    "Questions must be in Traditional Chinese, natural learner questions, and answerable "
    "ONLY from the provided sections. Cite expected_source_ids exactly as given. "
    "Prefer at least one question that needs MULTIPLE sections to answer. "
    'Return JSON: {"cases": [{"name": str, "query": str, '
    '"expected_source_ids": [str, ...]}]}'
)

NEGATIVE_SYSTEM_PROMPT = (
    "You create negative evaluation cases for a course knowledge-base QA bot. "
    "Write Traditional Chinese questions a learner might plausibly ask that CANNOT be "
    "answered from the provided course material excerpts. "
    'Return JSON: {"cases": [{"name": str, "query": str}]}'
)

VERIFICATION_SYSTEM_PROMPT = (
    "You verify evaluation cases. Decide whether the question can be fully answered "
    "using ONLY the provided sections. "
    'Return JSON: {"answerable": true} or {"answerable": false}'
)


@dataclass(frozen=True)
class SectionRecord:
    filename: str
    source_id: str
    heading: str
    body_md: str


@dataclass(frozen=True)
class SectionGroup:
    filename: str
    sections: tuple[SectionRecord, ...]


class ChatCaller(Protocol):
    def complete(self, *, system: str, user: str) -> str: ...


def load_section_records(session: Session) -> list[SectionRecord]:
    statement = (
        select(Section, Document)
        .join(Document, Document.id == Section.document_id)
        .where(active_document_filter())
        .order_by(Document.filename.asc(), Section.created_at.asc(), Section.id.asc())
    )
    return [
        SectionRecord(
            filename=document.filename,
            source_id=section.source_id,
            heading=section.heading,
            body_md=section.body_md,
        )
        for section, document in session.execute(statement)
    ]


def group_sections(records: list[SectionRecord], *, group_size: int = 3) -> list[SectionGroup]:
    by_file: dict[str, list[SectionRecord]] = {}
    for record in records:
        by_file.setdefault(record.filename, []).append(record)

    groups: list[SectionGroup] = []
    for filename, file_records in by_file.items():
        for start in range(0, len(file_records), group_size):
            window = file_records[start : start + group_size]
            if window:
                groups.append(SectionGroup(filename=filename, sections=tuple(window)))
    return groups


def _sections_payload(sections: list[SectionRecord]) -> str:
    return json.dumps(
        [
            {
                "source_id": section.source_id,
                "heading": section.heading,
                "content": section.body_md,
            }
            for section in sections
        ],
        ensure_ascii=False,
    )


def build_generation_prompt(group: SectionGroup, *, case_count: int) -> str:
    return (
        f"Create up to {case_count} eval cases from these sections of "
        f"{group.filename}:\n{_sections_payload(list(group.sections))}"
    )


def build_negative_prompt(groups: list[SectionGroup], *, case_count: int) -> str:
    topics = sorted({group.filename for group in groups})
    headings = [section.heading for group in groups for section in group.sections][:30]
    return (
        f"Create {case_count} unanswerable questions. Course files: {topics}. "
        f"Topics covered (do NOT make questions answerable by these): {headings}"
    )


def build_verification_prompt(*, query: str, sections: list[SectionRecord]) -> str:
    return f"Question: {query}\nSections:\n{_sections_payload(sections)}"


def parse_generated_cases(raw: str, *, allowed_source_ids: set[str]) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for item in _case_items(raw):
        name = item.get("name")
        query = item.get("query")
        source_ids = item.get("expected_source_ids")
        if not isinstance(name, str) or not name.strip():
            continue
        if not isinstance(query, str) or not query.strip():
            continue
        if not isinstance(source_ids, list) or not source_ids:
            continue
        valid_ids = [
            source_id
            for source_id in source_ids
            if isinstance(source_id, str) and source_id in allowed_source_ids
        ]
        if len(valid_ids) != len(source_ids):
            continue
        cases.append(
            {"name": name.strip(), "query": query.strip(), "expected_source_ids": valid_ids}
        )
    return cases


def parse_negative_cases(raw: str) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for item in _case_items(raw):
        name = item.get("name")
        query = item.get("query")
        if isinstance(name, str) and name.strip() and isinstance(query, str) and query.strip():
            cases.append({"name": name.strip(), "query": query.strip()})
    return cases


def _case_items(raw: str) -> list[dict[str, Any]]:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return []
    items = payload.get("cases") if isinstance(payload, dict) else None
    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, dict)]


def verification_passed(raw: str) -> bool:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return False
    return isinstance(payload, dict) and payload.get("answerable") is True


def generate_eval_seed_dicts(
    caller: ChatCaller,
    groups: list[SectionGroup],
    *,
    target_count: int,
    negative_count: int,
    max_rounds: int = 3,
) -> list[dict[str, Any]]:
    seed_dicts: list[dict[str, Any]] = []
    seen_queries: set[str] = set()
    cases_per_group = 2

    for _ in range(max_rounds):
        if len(seed_dicts) >= target_count:
            break
        for group in groups:
            if len(seed_dicts) >= target_count:
                break
            allowed = {section.source_id for section in group.sections}
            raw = caller.complete(
                system=GENERATION_SYSTEM_PROMPT,
                user=build_generation_prompt(group, case_count=cases_per_group),
            )
            for case in parse_generated_cases(raw, allowed_source_ids=allowed):
                if len(seed_dicts) >= target_count or case["query"] in seen_queries:
                    continue
                sections = [
                    section
                    for section in group.sections
                    if section.source_id in case["expected_source_ids"]
                ]
                verification_raw = caller.complete(
                    system=VERIFICATION_SYSTEM_PROMPT,
                    user=build_verification_prompt(query=case["query"], sections=sections),
                )
                if not verification_passed(verification_raw):
                    continue
                seen_queries.add(case["query"])
                seed_dicts.append(
                    {
                        "seed_key": f"auto.{len(seed_dicts):03d}",
                        "name": case["name"],
                        "query": case["query"],
                        "expected_decision": "can_answer",
                        "expected_source_ids": case["expected_source_ids"],
                        "tags": ["auto"],
                        "metadata": {"kind": "generated"},
                    }
                )

    if negative_count > 0 and groups:
        raw = caller.complete(
            system=NEGATIVE_SYSTEM_PROMPT,
            user=build_negative_prompt(groups, case_count=negative_count),
        )
        for case in parse_negative_cases(raw)[:negative_count]:
            if case["query"] in seen_queries:
                continue
            seen_queries.add(case["query"])
            seed_dicts.append(
                {
                    "seed_key": f"auto.neg.{len(seed_dicts):03d}",
                    "name": case["name"],
                    "query": case["query"],
                    "expected_decision": "cannot_confirm",
                    "expected_source_ids": [],
                    "tags": ["auto", "negative"],
                    "metadata": {"kind": "generated_negative"},
                }
            )
    return seed_dicts


class OpenAIChatCaller:
    def __init__(self, *, api_key: str, model: str, timeout_seconds: float) -> None:
        from openai import OpenAI

        self._client = OpenAI(api_key=api_key, timeout=timeout_seconds)
        self._model = model

    def complete(self, *, system: str, user: str) -> str:
        response = self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            response_format={"type": "json_object"},
        )
        return response.choices[0].message.content or ""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate eval cases from indexed sections.")
    parser.add_argument("--count", type=int, default=25)
    parser.add_argument("--negative-count", type=int, default=4)
    parser.add_argument("--output", type=Path, default=Path(".kb/auto-eval-cases.json"))
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Write the JSON file but do not seed the database.",
    )
    namespace = parser.parse_args(argv)

    from app.answer.providers import DEFAULT_OPENAI_CHAT_MODEL
    from app.core.config import Settings
    from app.core.database import SessionLocal
    from app.evals.cases import parse_seed_cases, seed_eval_cases

    settings = Settings()
    if not settings.openai_api_key:
        print("Error: OPENAI_API_KEY is required to generate eval cases.", file=sys.stderr)
        return 1

    caller = OpenAIChatCaller(
        api_key=settings.openai_api_key,
        model=settings.openai_chat_model or DEFAULT_OPENAI_CHAT_MODEL,
        timeout_seconds=settings.openai_request_timeout_seconds,
    )

    try:
        with SessionLocal() as session:
            records = load_section_records(session)
            if not records:
                print("Error: no indexed sections found; run make index first.", file=sys.stderr)
                return 1
            groups = group_sections(records)
            seed_dicts = generate_eval_seed_dicts(
                caller,
                groups,
                target_count=namespace.count,
                negative_count=namespace.negative_count,
            )
            namespace.output.parent.mkdir(parents=True, exist_ok=True)
            namespace.output.write_text(
                json.dumps(seed_dicts, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            if not namespace.dry_run:
                cases = parse_seed_cases(seed_dicts)
                summary, _ = seed_eval_cases(session, cases)
                session.commit()
                print(
                    f"Seeded generated eval cases: {summary.created} created, "
                    f"{summary.updated} updated, {summary.total} total."
                )
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(f"Wrote {namespace.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

Note: `DEFAULT_OPENAI_CHAT_MODEL` lives in `app/answer/providers.py` — verify the exact constant name there before running; if it differs, import the actual constant.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --python 3.12 pytest tests/unit/test_generate_eval_cases.py -v`
Expected: PASS (all tests)

- [ ] **Step 5: Add Make target**

In `Makefile`, append to the `.PHONY` list on line 30: ` eval-generate`, and add after the `eval-run` target (around line 140):

```makefile
eval-generate:
	$(UV) python -m scripts.generate_eval_cases
```

Verify: `make -n eval-generate` prints the command.

- [ ] **Step 6: Lint and commit**

Run: `make lint`
Expected: clean

```bash
git add scripts/generate_eval_cases.py tests/unit/test_generate_eval_cases.py Makefile
git commit -m "feat: add automated eval case generation"
```

---

### Task 2: Generate eval set and record baseline (BEFORE behavior changes)

Operational task — run against the local stack with real course content indexed. Requires `OPENAI_API_KEY` in `.env`.

- [ ] **Step 1: Ensure stack is up and content indexed**

```bash
docker compose up -d postgres
make migrate
make dev &        # or run the app in another terminal
sleep 5
curl -fsS http://localhost:8000/ready
make index        # uses already-imported course materials
```

If `/ready` reports index ready and sections exist, proceed. If the local DB is empty, restore from `backups/real-content-20260529T171708Z/` per `ops/backup-restore.md` first.

- [ ] **Step 2: Seed manual + generated cases**

```bash
make eval-seed
make eval-generate
```

Expected: `Seeded generated eval cases: N created ...` with N ≥ 15. If fewer, rerun `make eval-generate` (it tops up to the target). Sanity-check 3–5 cases in `.kb/auto-eval-cases.json` — readable Traditional Chinese questions with real source_ids.

- [ ] **Step 3: Run baseline eval and save the report**

```bash
mkdir -p tmp
make eval-run | tee tmp/eval-baseline-2026-06-11.txt
```

Record from output (or admin Evals tab): pass counts, retrieval_recall, citation_recall per run. This file is the comparison anchor for Task 9. Do not skip this step.

- [ ] **Step 4: Commit the generated case snapshot for reproducibility**

```bash
cp .kb/auto-eval-cases.json docs/plans/2026-06-11-auto-eval-cases.json
git add docs/plans/2026-06-11-auto-eval-cases.json
git commit -m "test: snapshot auto-generated eval baseline cases"
```

---

### Task 3: Settings for token encoding and context expansion

**Files:**
- Modify: `app/core/config.py`
- Test: `tests/unit/test_config.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_config.py`:

```python
import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_context_expansion_defaults() -> None:
    settings = Settings()
    assert settings.token_encoding == "o200k_base"
    assert settings.context_neighbor_sections == 1
    assert settings.context_token_budget == 8000


def test_token_encoding_rejects_unknown_encoding() -> None:
    with pytest.raises(ValidationError):
        Settings(token_encoding="not-a-real-encoding")


def test_context_token_budget_enforces_floor() -> None:
    with pytest.raises(ValidationError):
        Settings(context_token_budget=500)


def test_context_neighbor_sections_rejects_negative() -> None:
    with pytest.raises(ValidationError):
        Settings(context_neighbor_sections=-1)
```

(Match the existing import style at the top of that file; don't duplicate imports.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --python 3.12 pytest tests/unit/test_config.py -v -k context_or_token_encoding or uv run --python 3.12 pytest tests/unit/test_config.py -v`
Expected: FAIL (`Settings` has no field `token_encoding`)

- [ ] **Step 3: Add the dependency and settings**

```bash
uv add "tiktoken>=0.8"
```

In `app/core/config.py`, add `field_validator` to the pydantic import, then add fields to `Settings` (after `embedding_dimension`, line 59):

```python
    token_encoding: str = "o200k_base"
    context_neighbor_sections: int = Field(default=1, ge=0)
    context_token_budget: int = Field(default=8000, ge=1000)

    @field_validator("token_encoding")
    @classmethod
    def _validate_token_encoding(cls, value: str) -> str:
        import tiktoken

        tiktoken.get_encoding(value)  # raises for unknown encodings (fail fast at startup)
        return value
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --python 3.12 pytest tests/unit/test_config.py -v`
Expected: PASS. Note: the first run downloads the `o200k_base` BPE file (network needed once).

- [ ] **Step 5: Bake the encoding into the Docker image**

In `Dockerfile`, after dependencies are installed (after the `uv sync`/install layer, before the final CMD), add:

```dockerfile
ENV TIKTOKEN_CACHE_DIR=/opt/tiktoken-cache
RUN python -c "import tiktoken; tiktoken.get_encoding('o200k_base')"
```

This pre-downloads the BPE file at build time so containers never need network for tokenization. Adjust the `python` invocation to match how the Dockerfile runs Python (check whether it uses a venv path like `/app/.venv/bin/python`).

Verify: `docker build -t kb-tiktoken-check .` succeeds.

- [ ] **Step 6: Lint and commit**

Run: `make lint`

```bash
git add app/core/config.py tests/unit/test_config.py pyproject.toml uv.lock Dockerfile
git commit -m "feat: add tiktoken dependency and context expansion settings"
```

---

### Task 4: Tokenization module and token-accurate chunking

**Files:**
- Create: `app/indexing/tokenization.py`
- Test: `tests/unit/test_tokenization.py`
- Modify: `app/indexing/service.py` (chunking + token counts), `app/background_jobs/worker.py:134,145`, `app/api/indexing.py:95`, `app/api/documents.py:168` (pass `token_encoding`)

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_tokenization.py`:

```python
from __future__ import annotations

import pytest

from app.indexing.tokenization import (
    DEFAULT_TOKEN_ENCODING,
    count_tokens,
    get_token_encoding,
    split_token_windows,
    truncate_to_tokens,
)


def test_count_tokens_counts_chinese_text_realistically() -> None:
    chinese = "分散式系統的一致性協定是課程的核心主題之一" * 10
    # whitespace split would count 1; tiktoken must count many
    assert count_tokens(chinese) > 50


def test_count_tokens_empty_text_is_zero() -> None:
    assert count_tokens("") == 0


def test_split_token_windows_returns_single_window_when_under_limit() -> None:
    windows = split_token_windows("short text", token_limit=100, overlap=10)
    assert len(windows) == 1
    assert windows[0].text == "short text"
    assert windows[0].start_token == 0


def test_split_token_windows_chinese_text_splits_with_overlap() -> None:
    text = "知識庫問答系統需要將課程教材切分成適當大小的段落。" * 100
    windows = split_token_windows(text, token_limit=120, overlap=20)

    assert len(windows) > 1
    for window in windows:
        assert window.token_count <= 120
        assert window.text  # decoded text is non-empty
        assert "�" not in window.text  # no replacement chars from split multibyte chars
    # overlap: each next window starts (limit - overlap) tokens after the previous
    assert windows[1].start_token == 100


def test_split_token_windows_round_trip_covers_all_tokens() -> None:
    text = "Mixed 中英文 content with English words 與中文字元交錯出現。" * 50
    encoding = get_token_encoding(DEFAULT_TOKEN_ENCODING)
    total = len(encoding.encode(text))
    windows = split_token_windows(text, token_limit=80, overlap=16)
    assert windows[-1].end_token == total


def test_truncate_to_tokens_shortens_long_text() -> None:
    text = "課程內容包含許多重要的概念與定義。" * 100
    truncated = truncate_to_tokens(text, limit=50)
    assert count_tokens(truncated) <= 50
    assert truncated


def test_truncate_to_tokens_keeps_short_text_identical() -> None:
    assert truncate_to_tokens("hello world", limit=50) == "hello world"


def test_split_token_windows_validates_arguments() -> None:
    with pytest.raises(ValueError):
        split_token_windows("text", token_limit=0, overlap=0)
    with pytest.raises(ValueError):
        split_token_windows("text", token_limit=10, overlap=10)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --python 3.12 pytest tests/unit/test_tokenization.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement the tokenization module**

Create `app/indexing/tokenization.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

import tiktoken

DEFAULT_TOKEN_ENCODING = "o200k_base"


@dataclass(frozen=True)
class TokenWindow:
    text: str
    start_token: int
    end_token: int
    token_count: int


@lru_cache(maxsize=4)
def get_token_encoding(encoding_name: str = DEFAULT_TOKEN_ENCODING) -> tiktoken.Encoding:
    return tiktoken.get_encoding(encoding_name)


def count_tokens(text: str, *, encoding_name: str = DEFAULT_TOKEN_ENCODING) -> int:
    if not text:
        return 0
    return len(get_token_encoding(encoding_name).encode(text))


def truncate_to_tokens(
    text: str,
    *,
    limit: int,
    encoding_name: str = DEFAULT_TOKEN_ENCODING,
) -> str:
    if limit <= 0:
        raise ValueError("limit must be positive")
    encoding = get_token_encoding(encoding_name)
    tokens = encoding.encode(text)
    if len(tokens) <= limit:
        return text
    return _safe_decode(encoding, tokens[:limit]).strip()


def split_token_windows(
    text: str,
    *,
    token_limit: int,
    overlap: int,
    encoding_name: str = DEFAULT_TOKEN_ENCODING,
) -> list[TokenWindow]:
    if token_limit <= 0:
        raise ValueError("token_limit must be positive")
    if overlap < 0:
        raise ValueError("overlap must be non-negative")
    if overlap >= token_limit:
        raise ValueError("overlap must be smaller than token_limit")

    stripped = text.strip()
    if not stripped:
        return []

    encoding = get_token_encoding(encoding_name)
    tokens = encoding.encode(stripped)
    if len(tokens) <= token_limit:
        return [
            TokenWindow(
                text=stripped,
                start_token=0,
                end_token=len(tokens),
                token_count=len(tokens),
            )
        ]

    windows: list[TokenWindow] = []
    step = token_limit - overlap
    start = 0
    while start < len(tokens):
        end = min(len(tokens), start + token_limit)
        window_text = _safe_decode(encoding, tokens[start:end]).strip()
        windows.append(
            TokenWindow(
                text=window_text,
                start_token=start,
                end_token=end,
                token_count=end - start,
            )
        )
        if end == len(tokens):
            break
        start += step
    return windows


def _safe_decode(encoding: tiktoken.Encoding, tokens: list[int]) -> str:
    # Token windows can split a multi-byte character at the edges; decode at the byte
    # level and drop the partial bytes instead of emitting replacement characters.
    data = encoding.decode_bytes(tokens)
    return data.decode("utf-8", errors="ignore")
```

If `make lint` later reports missing type stubs for tiktoken, add to `pyproject.toml`:

```toml
[[tool.mypy.overrides]]
module = "tiktoken.*"
ignore_missing_imports = true
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --python 3.12 pytest tests/unit/test_tokenization.py -v`
Expected: PASS

- [ ] **Step 5: Write failing tests for token-accurate chunking**

Append to `tests/unit/test_indexing_service_unit.py` (match its existing imports; it already imports `split_section_chunks` or import it):

```python
from app.indexing.service import split_section_chunks


def test_split_section_chunks_splits_long_chinese_section() -> None:
    body = "課程介紹分散式系統的核心概念，包括一致性、可用性與分區容忍。" * 80
    chunks = split_section_chunks(body, token_limit=420, overlap=64)

    assert len(chunks) > 1  # whitespace counting produced exactly 1 chunk before
    for chunk in chunks:
        assert chunk.token_count <= 420
        assert "�" not in chunk.body_text


def test_split_section_chunks_token_counts_use_tiktoken() -> None:
    body = "短的中文段落，不需要切分。"
    chunks = split_section_chunks(body, token_limit=420, overlap=64)

    assert len(chunks) == 1
    assert chunks[0].token_count > 5  # whitespace counting would say 1
```

Run: `uv run --python 3.12 pytest tests/unit/test_indexing_service_unit.py -v -k chinese`
Expected: FAIL (one chunk produced, token_count == 1)

- [ ] **Step 6: Switch chunking and token counts to the tokenization module**

In `app/indexing/service.py`:

1. Add import: `from app.indexing.tokenization import DEFAULT_TOKEN_ENCODING, count_tokens, split_token_windows`
2. Add constructor parameter `token_encoding: str = DEFAULT_TOKEN_ENCODING` to `IndexingService.__init__` and store `self.token_encoding = token_encoding`.
3. Replace the body of `split_section_chunks` (keep the signature, add `encoding_name` kwarg):

```python
def split_section_chunks(
    body_md: str,
    *,
    token_limit: int = DEFAULT_CHUNK_TOKEN_LIMIT,
    overlap: int = DEFAULT_CHUNK_OVERLAP,
    encoding_name: str = DEFAULT_TOKEN_ENCODING,
) -> list[_ChunkText]:
    windows = split_token_windows(
        body_md,
        token_limit=token_limit,
        overlap=overlap,
        encoding_name=encoding_name,
    )
    return [
        _ChunkText(
            chunk_index=index,
            body_text=window.text,
            token_count=window.token_count,
            content_hash=_content_hash(window.text),
            start_token=window.start_token,
            end_token=window.end_token,
        )
        for index, window in enumerate(windows)
    ]
```

(The `ValueError` argument validation moves into `split_token_windows`; delete the now-unused `_chunk_text` helper and the old `_token_count` function.)

4. In `_create_chunks`, pass the encoding: `split_section_chunks(body_md, token_limit=self.chunk_token_limit, overlap=self.chunk_overlap, encoding_name=self.token_encoding)`, and add `"token_encoding": self.token_encoding` to the chunk `metadata_json` dict (line ~382).
5. In `_section_chunk_settings_match`, also require `metadata.get("token_encoding") == self.token_encoding` so changing the encoding forces a re-chunk.
6. Section token counts (lines 236 and 246): replace `_token_count(parsed_section.body_md)` with `count_tokens(parsed_section.body_md, encoding_name=self.token_encoding)`.
7. Update the four construction sites to pass the setting (each already has a `settings` object in scope):
   - `app/api/indexing.py:95` and `app/api/documents.py:168`: add `token_encoding=settings.token_encoding,`
   - `app/background_jobs/worker.py:134` and `:145`: add `token_encoding=self.settings.token_encoding,`

- [ ] **Step 7: Run the full unit suite**

Run: `uv run --python 3.12 pytest tests/unit -v`
Expected: PASS. Some existing chunking tests may assert whitespace-token counts — update their expected values to tiktoken counts (verify each updated expectation by computing `count_tokens` for the fixture text; do not weaken assertions to `> 0`).

- [ ] **Step 8: Lint and commit**

Run: `make lint`

```bash
git add app/indexing/tokenization.py app/indexing/service.py app/api/indexing.py \
  app/api/documents.py app/background_jobs/worker.py tests/unit/test_tokenization.py \
  tests/unit/test_indexing_service_unit.py pyproject.toml
git commit -m "feat: token-accurate chunking with tiktoken"
```

---

### Task 5: `Section.position` migration and indexing writes

**Files:**
- Create: `migrations/versions/0011_section_position.py`
- Modify: `app/models/tables.py:97-132` (Section), `app/indexing/service.py` (`_index_file`)
- Test: `tests/integration/test_section_position.py`

- [ ] **Step 1: Write the failing integration test**

Create `tests/integration/test_section_position.py`:

```python
from __future__ import annotations

from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.indexing.service import IndexingService
from app.models.tables import Section
from app.retrieval.embeddings import FakeEmbeddingProvider


def test_rebuild_index_writes_document_order_positions(
    db_session: Session, tmp_path: Path
) -> None:
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    kb_dir = tmp_path / ".kb"
    kb_dir.mkdir()
    (docs_dir / "course.md").write_text(
        "# 課程簡介\n\n第一段。\n\n## 評分方式\n\n第二段。\n\n## 課程網站\n\n第三段。\n",
        encoding="utf-8",
    )

    service = IndexingService(
        session=db_session,
        docs_dir=docs_dir,
        kb_dir=kb_dir,
        embedding_provider=FakeEmbeddingProvider(),
    )
    service.rebuild_index()

    sections = db_session.scalars(
        select(Section).order_by(Section.position.asc())
    ).all()
    assert [section.position for section in sections] == [0, 1, 2]
    assert sections[0].heading == "課程簡介"
    assert sections[2].heading == "課程網站"
```

Notes: `db_session` comes from `tests/conftest.py` (skips without `KB_DATABASE_URL_TEST`). `IndexingService.rebuild_index` requires a session with no active transaction — copy the session handling used in `tests/integration/test_indexing_service.py` if the fixture session conflicts with the transaction guard.

- [ ] **Step 2: Run test to verify it fails**

```bash
docker compose up -d postgres
KB_DATABASE_URL_TEST=postgresql+psycopg://kb:kb@localhost:5432/kb_test \
  uv run --python 3.12 pytest tests/integration/test_section_position.py -v
```

(Use the port from your `.env` `KB_POSTGRES_PORT` if set; the `kb_test` database is created by the existing docker test tooling — check `docker-compose.yml`/`Makefile` `docker-test` for the exact URL pattern.)
Expected: FAIL with `AttributeError: type object 'Section' has no attribute 'position'`

- [ ] **Step 3: Add model column and migration**

In `app/models/tables.py`, inside `Section` after `level` (line 115), add:

```python
    position: Mapped[int | None] = mapped_column(Integer)
```

and add to `Section.__table_args__`:

```python
        Index("ix_sections_document_position", "document_id", "position"),
```

Create `migrations/versions/0011_section_position.py`:

```python
"""add section document-order position

Revision ID: 0011_section_position
Revises: 0010_embedding_dimension_768
Create Date: 2026-06-11 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011_section_position"
down_revision: str | None = "0010_embedding_dimension_768"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("sections", sa.Column("position", sa.Integer(), nullable=True))
    op.create_index("ix_sections_document_position", "sections", ["document_id", "position"])


def downgrade() -> None:
    op.drop_index("ix_sections_document_position", table_name="sections")
    op.drop_column("sections", "position")
```

- [ ] **Step 4: Write positions during indexing**

In `app/indexing/service.py` `_index_file`, change the loop header (line 224) to:

```python
        for position, parsed_section in enumerate(parsed_sections):
```

In the create branch add `position=position,` to the `Section(...)` constructor; in the update branch add `section.position = position` next to the other assignments.

- [ ] **Step 5: Run the test to verify it passes**

```bash
KB_DATABASE_URL_TEST=postgresql+psycopg://kb:kb@localhost:5432/kb_test \
  uv run --python 3.12 pytest tests/integration/test_section_position.py -v
```

Expected: PASS (conftest runs `alembic upgrade head`, picking up 0011)

- [ ] **Step 6: Run full test suite, lint, commit**

Run: `make test-unit && make test-integration` (with `KB_DATABASE_URL_TEST` exported) and `make lint`
Expected: PASS / clean

```bash
git add migrations/versions/0011_section_position.py app/models/tables.py \
  app/indexing/service.py tests/integration/test_section_position.py
git commit -m "feat: record section document-order position"
```

---

### Task 6: RRF fusion in hybrid retrieval

**Files:**
- Modify: `app/retrieval/hybrid.py`
- Test: `tests/unit/test_hybrid_retrieval.py`

Semantics decision (from spec §4, made concrete): the `score_threshold` (0.05 via `API_RETRIEVAL_SCORE_THRESHOLD`) is applied to each strategy's **raw normalized scores before fusion**. This preserves the cannot-confirm gate (pure rank-based RRF has no absolute-quality floor — vector search always returns *something*). Fused candidates are ranked by normalized RRF + existing boosts.

- [ ] **Step 1: Rewrite the merge tests as fusion tests (failing)**

In `tests/unit/test_hybrid_retrieval.py`, replace the import of `merge_results` with `fuse_results` and replace the two `merge_results` tests with (keep the file's existing `_candidate` helper if present, else add one matching `RetrievedCandidate` fields):

```python
from uuid import uuid4

from app.retrieval.hybrid import RRF_K, fuse_results
from app.retrieval.models import RetrievedCandidate


def _candidate(
    *,
    section_id=None,
    source_id: str = "doc.md#sec",
    score: float = 0.5,
    strategy: str = "lexical",
    source_priority: int = 0,
) -> RetrievedCandidate:
    return RetrievedCandidate(
        section_id=section_id or uuid4(),
        source_id=source_id,
        filename="doc.md",
        heading="Heading",
        body_md="body",
        score=score,
        strategy=strategy,
        source_priority=source_priority,
    )


def test_fuse_results_section_in_both_strategies_outranks_single_strategy() -> None:
    shared_id = uuid4()
    lexical = [
        _candidate(section_id=shared_id, source_id="doc.md#both", score=0.4),
        _candidate(source_id="doc.md#lex-only", score=0.9),
    ]
    vector = [_candidate(section_id=shared_id, source_id="doc.md#both", score=0.3,
                         strategy="vector")]

    fused = fuse_results({"lexical": lexical, "vector": vector})

    assert fused[0].source_id == "doc.md#both"
    assert fused[0].strategy == "hybrid"
    # rank 1 in both strategies -> normalized RRF == 1.0
    assert fused[0].score == 1.0


def test_fuse_results_single_strategy_rank_one_scores_half() -> None:
    fused = fuse_results({"lexical": [_candidate(source_id="doc.md#only", score=0.8)]})

    assert len(fused) == 1
    assert fused[0].score == 0.5
    assert fused[0].strategy == "lexical"
    assert fused[0].debug_scores["lexical_rank"] == 1.0


def test_fuse_results_applies_source_priority_boost_after_normalization() -> None:
    plain = fuse_results({"lexical": [_candidate(source_id="doc.md#plain", score=0.8)]})
    boosted = fuse_results(
        {"lexical": [_candidate(source_id="doc.md#policy", score=0.8, source_priority=5)]}
    )

    assert boosted[0].score == min(1.0, plain[0].score + 0.05)
    assert boosted[0].debug_scores["source_priority_boost"] == 0.05


def test_fuse_results_prefers_lexical_body_on_rank_tie() -> None:
    shared_id = uuid4()
    lexical_candidate = RetrievedCandidate(
        section_id=shared_id,
        source_id="doc.md#both",
        filename="doc.md",
        heading="Heading",
        body_md="FULL SECTION BODY",
        score=0.4,
        strategy="lexical",
    )
    vector_candidate = RetrievedCandidate(
        section_id=shared_id,
        source_id="doc.md#both",
        filename="doc.md",
        heading="Heading",
        body_md="chunk text only",
        score=0.9,
        strategy="vector",
    )

    fused = fuse_results({"lexical": [lexical_candidate], "vector": [vector_candidate]})

    assert fused[0].body_md == "FULL SECTION BODY"


def test_rrf_constant_is_sixty() -> None:
    assert RRF_K == 60
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --python 3.12 pytest tests/unit/test_hybrid_retrieval.py -v`
Expected: FAIL with `ImportError: cannot import name 'fuse_results'`

- [ ] **Step 3: Implement RRF fusion**

In `app/retrieval/hybrid.py`:

Add near the top:

```python
from collections.abc import Mapping

RRF_K = 60
_RRF_MAX = 2.0 / (RRF_K + 1)
```

Replace `merge_results` (lines 106–135) with:

```python
def fuse_results(
    strategy_results: Mapping[str, Sequence[RetrievedCandidate]],
) -> list[RetrievedCandidate]:
    """Reciprocal Rank Fusion across per-strategy ranked lists, normalized to [0, 1]."""
    rrf_scores: dict[str, float] = {}
    ranks: dict[str, dict[str, int]] = {}
    candidates_by_strategy: dict[str, dict[str, RetrievedCandidate]] = {}

    for strategy, results in strategy_results.items():
        for rank, candidate in enumerate(results, start=1):
            key = str(candidate.section_id)
            rrf_scores[key] = rrf_scores.get(key, 0.0) + 1.0 / (RRF_K + rank)
            ranks.setdefault(key, {})[strategy] = rank
            candidates_by_strategy.setdefault(key, {})[strategy] = candidate

    fused: list[RetrievedCandidate] = []
    for key, rrf_score in rrf_scores.items():
        section_ranks = ranks[key]
        section_candidates = candidates_by_strategy[key]
        representative = _representative_candidate(section_ranks, section_candidates)
        normalized = min(1.0, rrf_score / _RRF_MAX)
        debug_scores = dict(representative.debug_scores)
        for strategy, candidate in section_candidates.items():
            debug_scores[f"{strategy}_score"] = candidate.score
            debug_scores[f"{strategy}_rank"] = float(section_ranks[strategy])
        debug_scores["rrf_score"] = rrf_score
        score, priority_debug_scores = _score_with_source_priority(
            normalized,
            representative.source_priority,
        )
        debug_scores.update(priority_debug_scores)
        debug_scores.setdefault("base_score", normalized)
        strategy = "hybrid" if len(section_candidates) > 1 else representative.strategy
        fused.append(
            replace(
                representative,
                score=score,
                strategy=strategy,
                debug_scores=debug_scores,
            )
        )

    return sorted(
        fused,
        key=lambda candidate: (-candidate.score, candidate.filename, candidate.source_id),
    )


def _representative_candidate(
    section_ranks: dict[str, int],
    section_candidates: dict[str, RetrievedCandidate],
) -> RetrievedCandidate:
    # Best (lowest) rank wins; on ties prefer lexical, whose body_md is the full section.
    def sort_key(strategy: str) -> tuple[int, int]:
        return (section_ranks[strategy], 0 if strategy == "lexical" else 1)

    best_strategy = min(section_candidates, key=sort_key)
    return section_candidates[best_strategy]
```

Update `HybridRetriever.search` (lines 73–96) to apply the pre-fusion floor and fusion:

```python
        normalized_strategy: RetrievalStrategy = "lexical" if strategy == "markdown" else strategy
        strategy_candidates: dict[str, list[RetrievedCandidate]] = {}
        if normalized_strategy in ("lexical", "hybrid"):
            strategy_candidates["lexical"] = self.lexical_retriever.search(query, limit)
        if normalized_strategy in ("vector", "hybrid"):
            strategy_candidates["vector"] = self.vector_retriever.search(query, limit)

        raw_candidates = [
            candidate
            for results in strategy_candidates.values()
            for candidate in results
        ]
        floored = {
            strategy_name: [c for c in results if c.score >= self.score_threshold]
            for strategy_name, results in strategy_candidates.items()
        }
        rejected = [
            candidate
            for results in strategy_candidates.values()
            for candidate in results
            if candidate.score < self.score_threshold
        ]
        merged = rerank_results_for_query(query, fuse_results(floored))
        accepted = merged[:limit]
```

Keep the existing `markdown` strategy relabeling, `decision`, and `retrieval_diagnostics(...)` calls as-is (pass `raw_candidates=raw_candidates`, `merged_candidates=merged`, `accepted_candidates=accepted`, `rejected_candidates=rejected`). Delete `_strategy_scores` and `_merged_debug_scores` (now unused).

- [ ] **Step 4: Run the unit suite**

Run: `uv run --python 3.12 pytest tests/unit/test_hybrid_retrieval.py tests/unit/test_retrieval_limit_defaults.py -v`
Expected: PASS. If other tests assert on old merged scores/debug keys, update expectations to RRF semantics (compute expected values by hand: single-strategy rank r → `(1/(60+r))/(2/61)`).

- [ ] **Step 5: Run integration tests, lint, commit**

```bash
KB_DATABASE_URL_TEST=... uv run --python 3.12 pytest tests/integration -v
make lint
git add app/retrieval/hybrid.py tests/unit/test_hybrid_retrieval.py
git commit -m "feat: switch hybrid retrieval to normalized RRF fusion"
```

---

### Task 7: Context assembly module

**Files:**
- Create: `app/answer/context_assembly.py`
- Test: `tests/unit/test_context_assembly.py`, `tests/integration/test_context_assembly_db.py`

- [ ] **Step 1: Write failing unit tests for the pure logic**

Create `tests/unit/test_context_assembly.py`:

```python
from __future__ import annotations

from uuid import uuid4

from app.answer.context_assembly import (
    CandidateEntry,
    order_for_output,
    select_within_budget,
)


def _entry(
    *,
    source_id: str,
    filename: str = "doc.md",
    is_hit: bool = True,
    score: float | None = 0.9,
    neighbor_distance: int = 0,
    anchor_score: float = 0.9,
    token_count: int = 100,
    position: int | None = 0,
) -> CandidateEntry:
    return CandidateEntry(
        section_id=uuid4(),
        source_id=source_id,
        filename=filename,
        heading=source_id,
        body_md="x " * token_count,
        score=score,
        is_hit=is_hit,
        neighbor_distance=neighbor_distance,
        anchor_score=anchor_score,
        token_count=token_count,
        position=position,
    )


def test_select_within_budget_prioritizes_hits_then_close_neighbors() -> None:
    hit = _entry(source_id="doc.md#hit", token_count=100)
    near = _entry(
        source_id="doc.md#near",
        is_hit=False,
        score=None,
        neighbor_distance=1,
        token_count=100,
        position=1,
    )
    far = _entry(
        source_id="doc.md#far",
        is_hit=False,
        score=None,
        neighbor_distance=2,
        token_count=100,
        position=2,
    )

    selection = select_within_budget([hit, far, near], token_budget=210)

    selected_ids = [entry.source_id for entry in selection.selected]
    assert selected_ids == ["doc.md#hit", "doc.md#near"]
    assert selection.dropped_count == 1
    assert selection.tokens_used == 200


def test_select_within_budget_always_keeps_top_hit_with_truncation() -> None:
    huge_hit = _entry(source_id="doc.md#huge", token_count=20_000)

    selection = select_within_budget([huge_hit], token_budget=1000)

    assert len(selection.selected) == 1
    assert selection.truncated_count == 1
    assert selection.selected[0].token_count <= 1000


def test_select_within_budget_orders_hits_by_score() -> None:
    low = _entry(source_id="doc.md#low", score=0.2, anchor_score=0.2, token_count=600)
    high = _entry(source_id="doc.md#high", score=0.9, anchor_score=0.9, token_count=600)

    selection = select_within_budget([low, high], token_budget=700)

    assert [entry.source_id for entry in selection.selected] == ["doc.md#high"]


def test_order_for_output_groups_by_document_in_reading_order() -> None:
    a_hit = _entry(source_id="a.md#2", filename="a.md", score=0.5, anchor_score=0.5,
                   position=2)
    a_neighbor = _entry(
        source_id="a.md#1",
        filename="a.md",
        is_hit=False,
        score=None,
        neighbor_distance=1,
        anchor_score=0.5,
        position=1,
    )
    b_hit = _entry(source_id="b.md#0", filename="b.md", score=0.9, anchor_score=0.9,
                   position=0)

    ordered = order_for_output([a_hit, a_neighbor, b_hit])

    # b.md group first (higher best hit score), then a.md in position order
    assert [entry.source_id for entry in ordered] == ["b.md#0", "a.md#1", "a.md#2"]


def test_order_for_output_handles_null_positions() -> None:
    with_position = _entry(source_id="a.md#0", position=0)
    without_position = _entry(source_id="a.md#x", position=None, score=0.99,
                              anchor_score=0.99)

    ordered = order_for_output([without_position, with_position])

    assert {entry.source_id for entry in ordered} == {"a.md#0", "a.md#x"}
    assert ordered[-1].source_id == "a.md#x"  # null position sorts after positioned ones
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --python 3.12 pytest tests/unit/test_context_assembly.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement the module**

Create `app/answer/context_assembly.py`:

```python
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.indexing.tokenization import (
    DEFAULT_TOKEN_ENCODING,
    count_tokens,
    truncate_to_tokens,
)
from app.models.tables import Section
from app.retrieval.models import RetrievedCandidate

DEFAULT_NEIGHBOR_SECTIONS = 1
DEFAULT_CONTEXT_TOKEN_BUDGET = 8000


@dataclass(frozen=True)
class CandidateEntry:
    section_id: UUID
    source_id: str
    filename: str
    heading: str
    body_md: str
    score: float | None
    is_hit: bool
    neighbor_distance: int
    anchor_score: float
    token_count: int
    position: int | None
    truncated: bool = False


@dataclass(frozen=True)
class BudgetSelection:
    selected: list[CandidateEntry]
    tokens_used: int
    dropped_count: int
    truncated_count: int


@dataclass(frozen=True)
class ContextAssemblyDiagnostics:
    neighbor_window: int
    token_budget: int
    tokens_used: int
    hit_count: int
    neighbor_count: int
    dropped_count: int
    truncated_count: int

    def to_payload(self) -> dict[str, Any]:
        return {
            "neighbor_window": self.neighbor_window,
            "token_budget": self.token_budget,
            "tokens_used": self.tokens_used,
            "hit_count": self.hit_count,
            "neighbor_count": self.neighbor_count,
            "dropped_count": self.dropped_count,
            "truncated_count": self.truncated_count,
        }


@dataclass(frozen=True)
class AssembledSource:
    section_id: UUID
    source_id: str
    filename: str
    heading: str
    body_md: str
    score: float | None
    is_hit: bool
    neighbor_distance: int
    truncated: bool


@dataclass(frozen=True)
class AssembledContext:
    sources: list[AssembledSource]
    diagnostics: ContextAssemblyDiagnostics


def select_within_budget(
    entries: Sequence[CandidateEntry],
    *,
    token_budget: int,
    encoding_name: str = DEFAULT_TOKEN_ENCODING,
) -> BudgetSelection:
    hits = sorted(
        (entry for entry in entries if entry.is_hit),
        key=lambda entry: -(entry.score or 0.0),
    )
    neighbors = sorted(
        (entry for entry in entries if not entry.is_hit),
        key=lambda entry: (entry.neighbor_distance, -entry.anchor_score),
    )

    selected: list[CandidateEntry] = []
    tokens_used = 0
    dropped_count = 0
    truncated_count = 0
    for entry in [*hits, *neighbors]:
        if tokens_used + entry.token_count <= token_budget:
            selected.append(entry)
            tokens_used += entry.token_count
            continue
        if not selected and entry.is_hit:
            truncated_body = truncate_to_tokens(
                entry.body_md,
                limit=token_budget,
                encoding_name=encoding_name,
            )
            truncated_tokens = count_tokens(truncated_body, encoding_name=encoding_name)
            selected.append(
                replace(
                    entry,
                    body_md=truncated_body,
                    token_count=truncated_tokens,
                    truncated=True,
                )
            )
            tokens_used += truncated_tokens
            truncated_count += 1
            continue
        dropped_count += 1

    return BudgetSelection(
        selected=selected,
        tokens_used=tokens_used,
        dropped_count=dropped_count,
        truncated_count=truncated_count,
    )


def order_for_output(entries: Sequence[CandidateEntry]) -> list[CandidateEntry]:
    best_hit_score: dict[str, float] = {}
    for entry in entries:
        score = entry.anchor_score
        best_hit_score[entry.filename] = max(best_hit_score.get(entry.filename, 0.0), score)

    def sort_key(entry: CandidateEntry) -> tuple[float, str, int, int, str]:
        position_known = 0 if entry.position is not None else 1
        return (
            -best_hit_score[entry.filename],
            entry.filename,
            position_known,
            entry.position if entry.position is not None else 0,
            entry.source_id,
        )

    return sorted(entries, key=sort_key)


class ContextAssembler:
    def __init__(
        self,
        *,
        session: Session,
        neighbor_sections: int = DEFAULT_NEIGHBOR_SECTIONS,
        token_budget: int = DEFAULT_CONTEXT_TOKEN_BUDGET,
        encoding_name: str = DEFAULT_TOKEN_ENCODING,
    ) -> None:
        if neighbor_sections < 0:
            raise ValueError("neighbor_sections must be non-negative")
        if token_budget <= 0:
            raise ValueError("token_budget must be positive")
        self.session = session
        self.neighbor_sections = neighbor_sections
        self.token_budget = token_budget
        self.encoding_name = encoding_name

    def assemble(self, candidates: Sequence[RetrievedCandidate]) -> AssembledContext:
        if not candidates:
            return AssembledContext(sources=[], diagnostics=self._diagnostics([], 0, 0, 0))

        entries = self._collect_entries(candidates)
        selection = select_within_budget(
            list(entries.values()),
            token_budget=self.token_budget,
            encoding_name=self.encoding_name,
        )
        ordered = order_for_output(selection.selected)
        sources = [
            AssembledSource(
                section_id=entry.section_id,
                source_id=entry.source_id,
                filename=entry.filename,
                heading=entry.heading,
                body_md=entry.body_md,
                score=entry.score,
                is_hit=entry.is_hit,
                neighbor_distance=entry.neighbor_distance,
                truncated=entry.truncated,
            )
            for entry in ordered
        ]
        return AssembledContext(
            sources=sources,
            diagnostics=self._diagnostics(
                ordered,
                selection.tokens_used,
                selection.dropped_count,
                selection.truncated_count,
            ),
        )

    def _collect_entries(
        self,
        candidates: Sequence[RetrievedCandidate],
    ) -> dict[UUID, CandidateEntry]:
        candidate_by_section: dict[UUID, RetrievedCandidate] = {
            candidate.section_id: candidate for candidate in candidates
        }
        sections = self.session.scalars(
            select(Section).where(Section.id.in_(list(candidate_by_section)))
        ).all()
        section_by_id = {section.id: section for section in sections}

        entries: dict[UUID, CandidateEntry] = {}
        for candidate in candidates:
            section = section_by_id.get(candidate.section_id)
            if section is None:
                # Section deleted between retrieval and assembly: fall back to the
                # candidate body so the answer path still works.
                entries[candidate.section_id] = self._entry_from_candidate(candidate)
                continue
            entries[section.id] = self._entry_from_section(
                section,
                score=candidate.score,
                is_hit=True,
                neighbor_distance=0,
                anchor_score=candidate.score,
                heading=candidate.heading,
                source_id=candidate.source_id,
                filename=candidate.filename,
            )

        if self.neighbor_sections > 0:
            for candidate in candidates:
                section = section_by_id.get(candidate.section_id)
                if section is None or section.position is None:
                    continue
                for neighbor in self._neighbors_for(section):
                    distance = abs((neighbor.position or 0) - (section.position or 0))
                    existing = entries.get(neighbor.id)
                    if existing is not None and (
                        existing.is_hit or existing.neighbor_distance <= distance
                    ):
                        continue
                    entries[neighbor.id] = self._entry_from_section(
                        neighbor,
                        score=None,
                        is_hit=False,
                        neighbor_distance=distance,
                        anchor_score=candidate.score,
                        heading=neighbor.heading,
                        source_id=neighbor.source_id,
                        filename=candidate.filename,
                    )
        return entries

    def _neighbors_for(self, section: Section) -> list[Section]:
        if section.position is None:
            return []
        return list(
            self.session.scalars(
                select(Section)
                .where(Section.document_id == section.document_id)
                .where(Section.position.is_not(None))
                .where(
                    Section.position.between(
                        section.position - self.neighbor_sections,
                        section.position + self.neighbor_sections,
                    )
                )
                .where(Section.id != section.id)
                .order_by(Section.position.asc())
            )
        )

    def _entry_from_section(
        self,
        section: Section,
        *,
        score: float | None,
        is_hit: bool,
        neighbor_distance: int,
        anchor_score: float,
        heading: str,
        source_id: str,
        filename: str,
    ) -> CandidateEntry:
        return CandidateEntry(
            section_id=section.id,
            source_id=source_id,
            filename=filename,
            heading=heading,
            body_md=section.body_md,
            score=score,
            is_hit=is_hit,
            neighbor_distance=neighbor_distance,
            anchor_score=anchor_score,
            token_count=count_tokens(section.body_md, encoding_name=self.encoding_name),
            position=section.position,
        )

    def _entry_from_candidate(self, candidate: RetrievedCandidate) -> CandidateEntry:
        return CandidateEntry(
            section_id=candidate.section_id,
            source_id=candidate.source_id,
            filename=candidate.filename,
            heading=candidate.heading,
            body_md=candidate.body_md,
            score=candidate.score,
            is_hit=True,
            neighbor_distance=0,
            anchor_score=candidate.score,
            token_count=count_tokens(candidate.body_md, encoding_name=self.encoding_name),
            position=None,
        )

    def _diagnostics(
        self,
        entries: list[CandidateEntry],
        tokens_used: int,
        dropped_count: int,
        truncated_count: int,
    ) -> ContextAssemblyDiagnostics:
        return ContextAssemblyDiagnostics(
            neighbor_window=self.neighbor_sections,
            token_budget=self.token_budget,
            tokens_used=tokens_used,
            hit_count=sum(1 for entry in entries if entry.is_hit),
            neighbor_count=sum(1 for entry in entries if not entry.is_hit),
            dropped_count=dropped_count,
            truncated_count=truncated_count,
        )
```

- [ ] **Step 4: Run unit tests to verify they pass**

Run: `uv run --python 3.12 pytest tests/unit/test_context_assembly.py -v`
Expected: PASS

- [ ] **Step 5: Write the DB-backed integration test**

Create `tests/integration/test_context_assembly_db.py`:

```python
from __future__ import annotations

from uuid import uuid4

from sqlalchemy.orm import Session

from app.answer.context_assembly import ContextAssembler
from app.models.tables import Document, Section
from app.retrieval.models import RetrievedCandidate


def _seed_document(db_session: Session, *, section_count: int = 5) -> list[Section]:
    document = Document(
        filename="course.md",
        canonical_path="/docs/course.md",
        source_type="markdown",
        content_hash="hash",
    )
    db_session.add(document)
    db_session.flush()
    sections = []
    for index in range(section_count):
        section = Section(
            document_id=document.id,
            source_id=f"course.md#sec-{index}",
            heading=f"Section {index}",
            heading_slug=f"sec-{index}",
            level=2,
            body_md=f"內容段落 {index}。",
            token_count=10,
            content_hash=f"hash-{index}",
            position=index,
        )
        db_session.add(section)
        sections.append(section)
    db_session.flush()
    return sections


def _hit(section: Section, *, score: float = 0.9) -> RetrievedCandidate:
    return RetrievedCandidate(
        section_id=section.id,
        source_id=section.source_id,
        filename="course.md",
        heading=section.heading,
        body_md="chunk excerpt",
        score=score,
        strategy="hybrid",
    )


def test_assemble_expands_hit_to_full_section_plus_neighbors(db_session: Session) -> None:
    sections = _seed_document(db_session)
    assembler = ContextAssembler(session=db_session, neighbor_sections=1, token_budget=8000)

    assembled = assembler.assemble([_hit(sections[2])])

    source_ids = [source.source_id for source in assembled.sources]
    assert source_ids == ["course.md#sec-1", "course.md#sec-2", "course.md#sec-3"]
    hit_source = next(source for source in assembled.sources if source.is_hit)
    assert hit_source.body_md == "內容段落 2。"  # full section body, not the chunk excerpt
    assert assembled.diagnostics.hit_count == 1
    assert assembled.diagnostics.neighbor_count == 2


def test_assemble_merges_overlapping_windows(db_session: Session) -> None:
    sections = _seed_document(db_session)
    assembler = ContextAssembler(session=db_session, neighbor_sections=1, token_budget=8000)

    assembled = assembler.assemble([_hit(sections[1]), _hit(sections[2], score=0.5)])

    source_ids = [source.source_id for source in assembled.sources]
    assert source_ids == [
        "course.md#sec-0",
        "course.md#sec-1",
        "course.md#sec-2",
        "course.md#sec-3",
    ]
    assert sum(1 for source in assembled.sources if source.is_hit) == 2


def test_assemble_without_positions_skips_neighbors(db_session: Session) -> None:
    sections = _seed_document(db_session)
    for section in sections:
        section.position = None
    db_session.flush()
    assembler = ContextAssembler(session=db_session, neighbor_sections=1, token_budget=8000)

    assembled = assembler.assemble([_hit(sections[2])])

    assert [source.source_id for source in assembled.sources] == ["course.md#sec-2"]
    assert assembled.sources[0].body_md == "內容段落 2。"


def test_assemble_with_zero_neighbor_window_expands_body_only(db_session: Session) -> None:
    sections = _seed_document(db_session)
    assembler = ContextAssembler(session=db_session, neighbor_sections=0, token_budget=8000)

    assembled = assembler.assemble([_hit(sections[2])])

    assert [source.source_id for source in assembled.sources] == ["course.md#sec-2"]
    assert assembled.sources[0].body_md == "內容段落 2。"
    assert assembled.diagnostics.neighbor_count == 0


def test_assemble_missing_section_falls_back_to_candidate(db_session: Session) -> None:
    assembler = ContextAssembler(session=db_session, neighbor_sections=1, token_budget=8000)
    ghost = RetrievedCandidate(
        section_id=uuid4(),
        source_id="ghost.md#gone",
        filename="ghost.md",
        heading="Gone",
        body_md="cached chunk text",
        score=0.7,
        strategy="vector",
    )

    assembled = assembler.assemble([ghost])

    assert len(assembled.sources) == 1
    assert assembled.sources[0].body_md == "cached chunk text"
```

- [ ] **Step 6: Run integration tests**

```bash
KB_DATABASE_URL_TEST=postgresql+psycopg://kb:kb@localhost:5432/kb_test \
  uv run --python 3.12 pytest tests/integration/test_context_assembly_db.py -v
```

Expected: PASS

- [ ] **Step 7: Lint and commit**

Run: `make lint`

```bash
git add app/answer/context_assembly.py tests/unit/test_context_assembly.py \
  tests/integration/test_context_assembly_db.py
git commit -m "feat: add context assembly with neighbor expansion and token budget"
```

---

### Task 8: Wire context assembly into /chat and /chat/stream

**Files:**
- Modify: `app/api/chat.py`
- Test: extend `tests/integration/test_api_workflow.py` (chat) and `tests/integration/test_chat_stream.py` (stream done event), plus `tests/unit/test_chat_stream_events.py` if event shapes are asserted there

- [ ] **Step 1: Write a failing integration test**

Append to `tests/integration/test_api_workflow.py` (it already indexes content and POSTs `/chat` with the fake providers — reuse its fixtures/helpers):

```python
def test_chat_answers_with_expanded_section_context(app_client, ...):  # match file fixtures
    # Arrange: index a document with >= 3 consecutive sections (reuse the file's
    # existing indexing fixture/helper), then ask a question that hits the middle
    # section.
    response = app_client.post("/chat", json={"query": "<query hitting middle section>"})
    payload = response.json()

    assert response.status_code == 200
    assert "context_assembly" in payload
    assert payload["context_assembly"]["hit_count"] >= 1
    assert payload["context_assembly"]["neighbor_count"] >= 1
    assert payload["context_assembly"]["token_budget"] == 8000
```

Adapt fixture names to the file's existing style — keep the three assertions on `context_assembly` exactly.

Run it; Expected: FAIL with KeyError/assertion on `context_assembly`.

- [ ] **Step 2: Add the response model and wiring**

In `app/api/chat.py`:

1. Imports (also add `Sequence` to the existing `collections.abc` import line):

```python
from app.answer.context_assembly import AssembledContext, AssembledSource, ContextAssembler
```

2. Add after `AnswerQualityResponse`:

```python
class ContextAssemblyResponse(BaseModel):
    neighbor_window: int
    token_budget: int
    tokens_used: int
    hit_count: int
    neighbor_count: int
    dropped_count: int
    truncated_count: int
```

Add to `ChatResponse`:

```python
    context_assembly: ContextAssemblyResponse | None = None
```

3. Add helpers near `_answer_quality_response`:

```python
def _assemble_context(
    *,
    request: Request,
    session: Session,
    retrieval_result: RetrievalResult,
) -> AssembledContext:
    settings = get_app_settings(request)
    assembler = ContextAssembler(
        session=session,
        neighbor_sections=settings.context_neighbor_sections,
        token_budget=settings.context_token_budget,
        encoding_name=settings.token_encoding,
    )
    return assembler.assemble(retrieval_result.candidates)


def assembled_source_response(source: AssembledSource) -> CandidateResponse:
    return CandidateResponse(
        section_id=source.section_id,
        source_id=source.source_id,
        filename=source.filename,
        heading=source.heading,
        body_md=source.body_md,
        score=source.score or 0.0,
        strategy="context",
        source_type="unknown",
        source_priority=0,
        debug_scores={
            "is_hit": 1.0 if source.is_hit else 0.0,
            "neighbor_distance": float(source.neighbor_distance),
        },
    )


def _context_assembly_response(context: AssembledContext) -> ContextAssemblyResponse:
    diagnostics = context.diagnostics
    return ContextAssemblyResponse(
        neighbor_window=diagnostics.neighbor_window,
        token_budget=diagnostics.token_budget,
        tokens_used=diagnostics.tokens_used,
        hit_count=diagnostics.hit_count,
        neighbor_count=diagnostics.neighbor_count,
        dropped_count=diagnostics.dropped_count,
        truncated_count=diagnostics.truncated_count,
    )
```

4. In `_build_chat_response` (lines 166–198): after retrieval and the budget check, assemble and use assembled sources for answering and citations:

```python
    assembled = _assemble_context(
        request=request, session=session, retrieval_result=retrieval_result
    )
    answer_result = _answer_provider_error_response(
        provider=get_answer_provider(request),
        payload=payload,
        request=request,
        sources=assembled.sources,
    )
    cited_source_ids = {source.source_id for source in answer_result.sources}
    cited_source_responses = [
        assembled_source_response(source)
        for source in assembled.sources
        if source.source_id in cited_source_ids
    ]
```

Rename `_answer_provider_error_response`'s `candidates` parameter to `sources: Sequence[AssembledSource]` (it forwards to `AnswerService.answer`, which accepts any objects exposing `source_id`/`filename`/`heading`/`body_md`/`score`).

5. Change `_persist_chat_response` signature: replace `cited_candidates: list[RetrievedCandidate]` with `cited_source_responses: list[CandidateResponse]` and use it directly for `source_responses` (delete the `candidate_response(...)` mapping over cited candidates). Add parameter `context_assembly: ContextAssemblyResponse | None` and include it in the returned `ChatResponse` and in `_retrieval_scores_payload` (add `"context_assembly": context_assembly.model_dump(mode="json") if context_assembly else None` to the dict). Update the two not-indexed call sites to pass `cited_source_responses=[]` and `context_assembly=None`.

6. Stream path `_unsafe_chat_stream_response_events` / `_stream_answer_response_events`: after emitting the `sources` event, assemble identically; pass `assembled.sources` to `stream_answer` and `validate_generated_answer`; build `cited_source_responses` the same way; pass `context_assembly=_context_assembly_response(assembled)`. Add `"context_assembly"` to the `_done_event` payload:

```python
                "context_assembly": (
                    response.context_assembly.model_dump(mode="json")
                    if response.context_assembly
                    else None
                ),
```

- [ ] **Step 3: Run the failing test again**

Expected: PASS

- [ ] **Step 4: Run the full test suite**

```bash
KB_DATABASE_URL_TEST=... uv run --python 3.12 pytest tests -v
```

Expected: PASS. Likely fallout to fix (update expectations, don't weaken):
- `tests/unit/test_chat_stream_events.py` — done event now includes `context_assembly`
- Chat integration tests asserting `sources` body_md equals chunk text — now full section text
- Any test constructing `_persist_chat_response` arguments directly

- [ ] **Step 5: Lint and commit**

```bash
make lint
git add app/api/chat.py tests/
git commit -m "feat: feed full-section windows to the answer provider"
```

---

### Task 9: Reindex, post-change evals, comparison, acceptance

- [ ] **Step 1: Migrate and rebuild the index (new chunking + positions)**

```bash
make migrate
# restart the app so new code serves requests, then:
make index
```

Expected: index rebuild succeeds; `chunks_embedded` is large (re-chunked due to tokenizer change). Verify positions: `SELECT count(*) FROM sections WHERE position IS NULL;` → 0.

- [ ] **Step 2: Re-run the eval suite**

```bash
make eval-run | tee tmp/eval-after-2026-06-11.txt
```

- [ ] **Step 3: Compare against the baseline**

Compare `tmp/eval-baseline-2026-06-11.txt` vs `tmp/eval-after-2026-06-11.txt`:
- retrieval_recall and citation_recall must be ≥ baseline.
- Negative cases must still produce `cannot_confirm` (the pre-fusion floor preserves this; if negatives regress, raise `API_RETRIEVAL_SCORE_THRESHOLD` in `app/api/search.py:26` and re-run).
- Write the before/after table into the PR description / plan completion notes.

If recall regressed: debug per-case via the admin Evals tab `score_debug_by_source_id`; tuning order: (1) threshold, (2) `KB_CONTEXT_NEIGHBOR_SECTIONS`, (3) `KB_CONTEXT_TOKEN_BUDGET`.

- [ ] **Step 4: Run the live answer acceptance**

Run the three checks in `ops/live-answer-acceptance.md` against the local app with OpenAI enabled.
Expected: 3/3 pass.

- [ ] **Step 5: Full verification sweep**

```bash
make lint
make test          # with KB_DATABASE_URL_TEST exported
make docker-test
make deploy-check
```

Expected: all green.

- [ ] **Step 6: Update docs and commit**

- README "Launch Configuration": add the three new `KB_` settings and a note that retrieval fusion is RRF.
- `ops/deploy.md`: add "run `make migrate` + `make index` after deploying this change (re-chunks all content)" and the provider daily-token-limit note from the spec's cost section.
- `AGENTS.md` project snapshot: mention context assembly layer.

```bash
git add README.md ops/deploy.md AGENTS.md
git commit -m "docs: document context expansion settings and reindex requirement"
```

---

## Completion checklist (gates from the spec)

- [ ] Existing acceptance: retrieval 5/5, live answers 3/3 (`ops/live-answer-acceptance.md`)
- [ ] New eval set: retrieval_recall and citation_recall ≥ baseline (before/after table recorded)
- [ ] `make test` and `make lint` green
- [ ] `make docker-test` green (Docker image builds with tiktoken cache baked in)
- [ ] Reindex performed; no NULL `sections.position` remaining
