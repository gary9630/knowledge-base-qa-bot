from __future__ import annotations

import argparse
import sys
from collections.abc import Callable

from sqlalchemy.orm import Session

from app.answer.providers import AnswerProvider, create_answer_provider
from app.core.config import Settings
from app.core.database import SessionLocal
from app.evals.runner import (
    EvalCasesNotFoundError,
    EvalRunExecution,
    EvalRunOptions,
    NoActiveEvalCasesError,
    execution_from_run,
    record_failed_eval_run,
    run_eval_suite,
)
from app.retrieval.embeddings import EmbeddingProvider, create_embedding_provider

EvalCliRunner = Callable[[EvalRunOptions], EvalRunExecution]
SessionFactory = Callable[[], Session]


def main(
    argv: list[str] | None = None,
    *,
    runner: EvalCliRunner | None = None,
    session_factory: SessionFactory | None = None,
    embedding_provider: EmbeddingProvider | None = None,
    answer_provider: AnswerProvider | None = None,
    settings: Settings | None = None,
) -> int:
    parser = argparse.ArgumentParser(description="Run eval cases against the knowledge base.")
    parser.add_argument("--trigger", default="manual")
    parser.add_argument(
        "--strategy",
        choices=["lexical", "markdown", "vector", "hybrid"],
        default="hybrid",
    )
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--fail-on-regression", action="store_true")
    namespace = parser.parse_args(argv)

    options = EvalRunOptions(
        trigger=namespace.trigger,
        strategy=namespace.strategy,
        limit=namespace.limit,
    )
    resolved_runner = runner or _runner_from_dependencies(
        session_factory=session_factory,
        embedding_provider=embedding_provider,
        answer_provider=answer_provider,
        settings=settings,
    )
    try:
        execution = resolved_runner(options)
    except Exception as exc:
        print(f"Eval run failed: {exc}", file=sys.stderr)
        return 1

    if execution.status == "failed":
        if execution.error:
            print(f"Eval run failed: {execution.error}", file=sys.stderr)
        return 1

    failed = _int_stat(execution.stats.get("failed"))
    total = _int_stat(execution.stats.get("total"))
    passed = _int_stat(execution.stats.get("passed"))
    print(
        f"Eval run {execution.status}: {passed}/{total} passed "
        f"(run_id={execution.run_id})"
    )
    if namespace.fail_on_regression and failed > 0:
        return 2
    return 0


def _runner_from_dependencies(
    *,
    session_factory: SessionFactory | None,
    embedding_provider: EmbeddingProvider | None,
    answer_provider: AnswerProvider | None,
    settings: Settings | None,
) -> EvalCliRunner:
    resolved_settings = settings or Settings()
    resolved_session_factory = session_factory or SessionLocal

    def run(options: EvalRunOptions) -> EvalRunExecution:
        with resolved_session_factory() as session:
            try:
                resolved_embedding_provider = embedding_provider or create_embedding_provider(
                    resolved_settings
                )
                resolved_answer_provider = answer_provider or create_answer_provider(
                    resolved_settings
                )
            except Exception as error:
                eval_run = record_failed_eval_run(
                    session,
                    options=options,
                    error=error,
                )
                return execution_from_run(eval_run)

            try:
                eval_run, _ = run_eval_suite(
                    session=session,
                    embedding_provider=resolved_embedding_provider,
                    answer_provider=resolved_answer_provider,
                    options=options,
                )
            except (NoActiveEvalCasesError, EvalCasesNotFoundError) as error:
                eval_run = record_failed_eval_run(
                    session,
                    options=options,
                    error=error,
                )
                return execution_from_run(eval_run)

            return execution_from_run(eval_run)

    return run


def _int_stat(value: object) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float, str)):
        return int(value)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
