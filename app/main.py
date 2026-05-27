from collections.abc import Callable

from fastapi import FastAPI
from sqlalchemy.orm import Session

from app.answer.providers import AnswerProvider, create_answer_provider
from app.api.audit import router as audit_router
from app.api.auth import router as auth_router
from app.api.chat import router as chat_router
from app.api.documents import router as documents_router
from app.api.evals import router as evals_router
from app.api.feedback import router as feedback_router
from app.api.health import router as health_router
from app.api.imports import router as imports_router
from app.api.indexing import router as indexing_router
from app.api.jobs import router as jobs_router
from app.api.mindmap import router as mindmap_router
from app.api.search import router as search_router
from app.api.sources import router as sources_router
from app.api.ui import mount_ui_static
from app.api.ui import router as ui_router
from app.core.config import Settings
from app.core.database import SessionLocal
from app.observability.metrics import InMemoryMetrics
from app.observability.middleware import (
    RequestObservabilityMiddleware,
    request_id_exception_handler,
)
from app.observability.rate_limit import RateLimitMiddleware
from app.retrieval.embeddings import EmbeddingProvider, create_embedding_provider

SessionFactory = Callable[[], Session]
SCHEMA_EMBEDDING_DIMENSION = 1536


def create_app(
    *,
    settings: Settings | None = None,
    session_factory: SessionFactory | None = None,
    embedding_provider: EmbeddingProvider | None = None,
    answer_provider: AnswerProvider | None = None,
) -> FastAPI:
    resolved_settings = settings or Settings()
    if resolved_settings.embedding_dimension != SCHEMA_EMBEDDING_DIMENSION:
        raise ValueError(
            f"embedding_dimension must match database schema ({SCHEMA_EMBEDDING_DIMENSION})"
        )
    app = FastAPI(title="Knowledge Base Q&A Bot")
    app.state.settings = resolved_settings
    app.state.session_factory = session_factory or SessionLocal
    app.state.embedding_provider = embedding_provider or create_embedding_provider(
        resolved_settings
    )
    app.state.answer_provider = answer_provider or create_answer_provider(resolved_settings)
    app.state.metrics = InMemoryMetrics()
    app.add_middleware(RateLimitMiddleware)
    app.add_middleware(RequestObservabilityMiddleware)
    app.add_exception_handler(Exception, request_id_exception_handler)

    mount_ui_static(app)
    app.include_router(ui_router)
    app.include_router(auth_router)
    app.include_router(health_router)
    app.include_router(indexing_router)
    app.include_router(imports_router)
    app.include_router(search_router)
    app.include_router(mindmap_router)
    app.include_router(chat_router)
    app.include_router(sources_router)
    app.include_router(feedback_router)
    app.include_router(evals_router)
    app.include_router(audit_router)
    app.include_router(documents_router)
    app.include_router(jobs_router)
    return app


app = create_app()
