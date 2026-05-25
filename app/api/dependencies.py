from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import cast

from fastapi import Request
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.database import SessionLocal
from app.retrieval.embeddings import EmbeddingProvider, create_embedding_provider

SessionFactory = Callable[[], Session]


def get_app_settings(request: Request) -> Settings:
    settings = getattr(request.app.state, "settings", None)
    if isinstance(settings, Settings):
        return settings

    settings = Settings()
    request.app.state.settings = settings
    return settings


def get_indexing_session_factory(request: Request) -> SessionFactory:
    session_factory = getattr(request.app.state, "session_factory", None)
    if callable(session_factory):
        return cast(SessionFactory, session_factory)

    return cast(SessionFactory, SessionLocal)


def get_request_db_session(request: Request) -> Iterator[Session]:
    with get_indexing_session_factory(request)() as session:
        yield session


def get_embedding_provider(request: Request) -> EmbeddingProvider:
    embedding_provider = getattr(request.app.state, "embedding_provider", None)
    if embedding_provider is not None:
        return cast(EmbeddingProvider, embedding_provider)

    embedding_provider = create_embedding_provider(get_app_settings(request))
    request.app.state.embedding_provider = embedding_provider
    return embedding_provider
