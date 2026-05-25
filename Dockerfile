# syntax=docker/dockerfile:1

FROM ghcr.io/astral-sh/uv:0.7.13 AS uv

FROM python:3.12-slim AS app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_CACHE_DIR=/tmp/uv-cache \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

COPY --from=uv /uv /uvx /usr/local/bin/
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-cache --no-dev --no-install-project

COPY . .
RUN useradd --create-home --shell /usr/sbin/nologin appuser \
    && mkdir -p /app/docs /app/raw /app/.kb \
    && chown -R appuser:appuser /app /tmp/uv-cache

USER appuser

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

FROM app AS test

USER root
RUN uv sync --frozen --no-cache --group dev --no-install-project \
    && chown -R appuser:appuser /app

USER appuser
