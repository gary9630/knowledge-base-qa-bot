from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from app.answer.providers import AnswerProvider, create_answer_provider
from app.core.config import Settings
from app.core.database import SessionLocal
from app.evals.runner import (
    EvalCasesNotFoundError,
    EvalExecutionFailedError,
    EvalRunOptions,
    NoActiveEvalCasesError,
    execution_from_run,
    record_failed_eval_run,
    run_eval_suite,
)
from app.indexing.service import IndexingResult, IndexingService
from app.ingestion.pipeline import IngestionPipeline, SqlAlchemyIngestionJobStore
from app.models.tables import BackgroundJob
from app.retrieval.embeddings import EmbeddingProvider, create_embedding_provider
from app.retrieval.models import RetrievalStrategy

from .service import (
    TASK_DOCUMENT_REINDEX,
    TASK_EVAL_RUN,
    TASK_INDEX_REBUILD,
    TASK_INGEST_UPLOAD,
    BackgroundJobService,
)

SessionFactory = Callable[[], Session]


class BackgroundWorker:
    def __init__(
        self,
        *,
        session_factory: SessionFactory = SessionLocal,
        settings: Settings | None = None,
        embedding_provider: EmbeddingProvider | None = None,
        answer_provider: AnswerProvider | None = None,
        worker_id: str | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.settings = settings or Settings()
        self.embedding_provider = embedding_provider
        self.answer_provider = answer_provider
        self.worker_id = worker_id or f"worker-{uuid4()}"

    def run_once(self) -> BackgroundJob | None:
        with self.session_factory() as session:
            claimed = BackgroundJobService(session).claim_next(worker_id=self.worker_id)
            if claimed is None:
                return None
            job_id = claimed.id
            task_type = claimed.task_type
            payload = dict(claimed.payload_json)

        try:
            result = self._execute_task(task_type, payload)
        except Exception as error:
            with self.session_factory() as session:
                return BackgroundJobService(session).fail(
                    job_id,
                    error=_error_message(error),
                )

        with self.session_factory() as session:
            return BackgroundJobService(session).complete(job_id, result=result)

    def _execute_task(
        self,
        task_type: str,
        payload: dict[str, object],
    ) -> dict[str, object]:
        if task_type == TASK_INDEX_REBUILD:
            return self._run_index_rebuild()
        if task_type == TASK_INGEST_UPLOAD:
            return self._run_ingest_upload(payload)
        if task_type == TASK_DOCUMENT_REINDEX:
            return self._run_document_reindex(payload)
        if task_type == TASK_EVAL_RUN:
            return self._run_eval(payload)
        raise ValueError(f"unsupported background job task: {task_type}")

    def _run_index_rebuild(self) -> dict[str, object]:
        with self.session_factory() as session:
            result = IndexingService(
                session=session,
                docs_dir=Path(self.settings.docs_dir),
                kb_dir=Path(self.settings.kb_dir),
                embedding_provider=self._embedding_provider(),
            ).rebuild_index()
        return _indexing_result_payload(result)

    def _run_document_reindex(self, payload: dict[str, object]) -> dict[str, object]:
        document_id = _payload_uuid(payload, "document_id")
        with self.session_factory() as session:
            result = IndexingService(
                session=session,
                docs_dir=Path(self.settings.docs_dir),
                kb_dir=Path(self.settings.kb_dir),
                embedding_provider=self._embedding_provider(),
            ).reindex_document(document_id)
        return {
            "document_id": str(document_id),
            **_indexing_result_payload(result),
        }

    def _run_ingest_upload(self, payload: dict[str, object]) -> dict[str, object]:
        ingestion_job_id = _payload_uuid(payload, "ingestion_job_id")
        index_after_import = _bool_payload(payload.get("index_after_import"), default=True)
        with self.session_factory() as session:
            pipeline = IngestionPipeline(
                store=SqlAlchemyIngestionJobStore(session),
                raw_dir=Path(self.settings.raw_dir),
                docs_dir=Path(self.settings.docs_dir),
            )
            existing_job = pipeline.store.get(ingestion_job_id)
            if existing_job is None:
                raise ValueError(f"Import job not found: {ingestion_job_id}")
            result = (
                existing_job
                if existing_job.status == "succeeded"
                else pipeline.run_queued_job(job_id=ingestion_job_id).job
            )

            index_job_id: str | None = None
            if result.status == "succeeded" and index_after_import:
                index_job = BackgroundJobService(session).enqueue(
                    task_type=TASK_INDEX_REBUILD,
                    payload={
                        "reason": TASK_INGEST_UPLOAD,
                        "ingestion_job_id": str(result.id),
                        "canonical_path": result.canonical_path,
                    },
                )
                session.commit()
                index_job_id = str(index_job.id)

        return {
            "ingestion_job_id": str(result.id),
            "import_status": result.status,
            "raw_path": result.raw_path,
            "canonical_path": result.canonical_path,
            "queued_index_job_id": index_job_id,
        }

    def _run_eval(self, payload: dict[str, object]) -> dict[str, object]:
        options = EvalRunOptions(
            trigger=str(payload.get("trigger") or "background_job"),
            strategy=_retrieval_strategy(payload.get("strategy")),
            limit=_int_payload(payload.get("limit"), default=5),
            case_ids=tuple(_uuid_sequence(payload.get("case_ids"))),
        )
        with self.session_factory() as session:
            try:
                eval_run, _ = run_eval_suite(
                    session=session,
                    embedding_provider=self._embedding_provider(),
                    answer_provider=self._answer_provider(),
                    options=options,
                )
            except (NoActiveEvalCasesError, EvalCasesNotFoundError) as error:
                eval_run = record_failed_eval_run(
                    session,
                    options=options,
                    error=error,
                )
                raise RuntimeError(f"eval run {eval_run.id} failed: {error}") from error
            except EvalExecutionFailedError:
                raise
            except Exception as error:
                eval_run = record_failed_eval_run(
                    session,
                    options=options,
                    error=error,
                )
                raise RuntimeError(f"eval run {eval_run.id} failed: {error}") from error

            execution = execution_from_run(eval_run)
            return {
                "run_id": str(execution.run_id),
                "status": execution.status,
                "stats": execution.stats,
                "error": execution.error,
            }

    def _embedding_provider(self) -> EmbeddingProvider:
        if self.embedding_provider is None:
            self.embedding_provider = create_embedding_provider(self.settings)
        return self.embedding_provider

    def _answer_provider(self) -> AnswerProvider:
        if self.answer_provider is None:
            self.answer_provider = create_answer_provider(self.settings)
        return self.answer_provider


def _indexing_result_payload(result: IndexingResult) -> dict[str, object]:
    return {
        "files_indexed": result.files_indexed,
        "sections_indexed": result.sections_indexed,
        "chunks_indexed": result.chunks_indexed,
        "export_path": str(result.export_path),
    }


def _payload_uuid(payload: dict[str, object], key: str) -> UUID:
    value = payload.get(key)
    if value is None:
        raise ValueError(f"{key} is required")
    return UUID(str(value))


def _uuid_sequence(value: object) -> Sequence[UUID]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ValueError("case_ids must be a list")
    return tuple(UUID(str(item)) for item in value)


def _retrieval_strategy(value: object) -> RetrievalStrategy:
    strategy = str(value or "hybrid")
    if strategy not in {"lexical", "markdown", "vector", "hybrid"}:
        raise ValueError(f"unsupported retrieval strategy: {strategy}")
    return strategy  # type: ignore[return-value]


def _int_payload(value: object, *, default: int) -> int:
    if value is None:
        return default
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float, str)):
        try:
            return int(value)
        except ValueError as error:
            raise ValueError("limit must be an integer") from error
    raise ValueError("limit must be an integer")


def _bool_payload(value: object, *, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _error_message(error: Exception) -> str:
    message = str(error).strip()
    return message or error.__class__.__name__
