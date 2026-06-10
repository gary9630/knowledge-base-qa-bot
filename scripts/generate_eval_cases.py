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
