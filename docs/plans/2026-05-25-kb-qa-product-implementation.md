# Knowledge Base Q&A Product Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a production-oriented Knowledge Base Q&A product with FastAPI, Postgres, pgvector, hybrid retrieval, grounded chat, streaming, a three-column UI, tests, Docker Compose, and Makefile automation.

**Architecture:** Implement a Postgres-backed modular monolith. Markdown remains the canonical knowledge format; Postgres stores documents, sections, chunks, embeddings, jobs, messages, retrieval events, and feedback. pgvector provides semantic retrieval, Postgres full-text search provides lexical retrieval, and the UI exposes chat, mindmap, admin uploads, indexing, and source inspection.

**Tech Stack:** Python 3.12, FastAPI, Pydantic, SQLAlchemy 2, Alembic, psycopg, pgvector, OpenAI API behind provider interfaces, pytest, httpx, ruff, mypy, Docker Compose, Postgres with pgvector.

---

## Ground Rules

- Follow TDD for production behavior: write a failing test first, verify the failure, implement the smallest change, verify it passes.
- Use fake embedding and fake answer providers in tests; do not require network or API keys for tests.
- Do not make FAISS part of the MVP runtime path.
- Do not batch-delete files or directories.
- Keep `project-ideas.md` and `sample-docs/` intact unless the user explicitly asks to change them.
- Before implementing the OpenAI provider, use the `openai-docs` skill and official OpenAI documentation.
- Before implementing rendered UI work, use the relevant Build Web Apps frontend skill and verify in a browser.

## Task 1: Project Scaffold and Tooling

**Files:**
- Create: `pyproject.toml`
- Create: `app/__init__.py`
- Create: `app/main.py`
- Create: `app/api/__init__.py`
- Create: `app/api/health.py`
- Create: `tests/conftest.py`
- Create: `tests/unit/test_health_routes.py`

**Step 1: Write the failing test**

Create `tests/unit/test_health_routes.py`:

```python
from fastapi.testclient import TestClient

from app.main import create_app


def test_health_returns_ok():
    client = TestClient(create_app())

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
```

**Step 2: Run test to verify it fails**

Run:

```bash
uv run pytest tests/unit/test_health_routes.py -v
```

Expected: FAIL because `pyproject.toml`, FastAPI dependencies, or `app.main` are missing.

**Step 3: Write minimal implementation**

Create `pyproject.toml` with the project metadata, dependencies, and tool config:

```toml
[project]
name = "knowledge-base-qa-bot"
version = "0.1.0"
description = "Knowledge Base Q&A product with Postgres, pgvector, and grounded citations"
requires-python = ">=3.12"
dependencies = [
  "alembic>=1.13",
  "beautifulsoup4>=4.12",
  "fastapi>=0.115",
  "httpx>=0.27",
  "jinja2>=3.1",
  "markdownify>=0.13",
  "openai>=1.0",
  "pgvector>=0.3",
  "psycopg[binary]>=3.2",
  "pydantic>=2.8",
  "pydantic-settings>=2.4",
  "pypdf>=4.3",
  "python-multipart>=0.0.9",
  "sqlalchemy>=2.0",
  "sse-starlette>=2.1",
  "uvicorn[standard]>=0.30",
]

[project.optional-dependencies]
dev = [
  "mypy>=1.11",
  "pytest>=8.3",
  "pytest-asyncio>=0.23",
  "pytest-cov>=5.0",
  "ruff>=0.6",
]

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-ra"

[tool.ruff]
line-length = 100
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B"]

[tool.mypy]
python_version = "3.12"
strict = true
warn_unused_ignores = true
```

Create `app/main.py`:

```python
from fastapi import FastAPI

from app.api.health import router as health_router


def create_app() -> FastAPI:
    app = FastAPI(title="Knowledge Base Q&A Bot")
    app.include_router(health_router)
    return app


app = create_app()
```

Create `app/api/health.py`:

```python
from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
```

**Step 4: Run test to verify it passes**

Run:

```bash
uv run pytest tests/unit/test_health_routes.py -v
```

Expected: PASS.

**Step 5: Commit**

```bash
git add pyproject.toml app tests
git commit -m "chore: scaffold fastapi project"
```

## Task 2: Configuration and App Settings

**Files:**
- Create: `app/core/__init__.py`
- Create: `app/core/config.py`
- Create: `.env.example`
- Test: `tests/unit/test_config.py`

**Step 1: Write the failing test**

Create `tests/unit/test_config.py`:

```python
from app.core.config import Settings


def test_settings_default_paths_are_product_defaults():
    settings = Settings()

    assert settings.docs_dir == "docs"
    assert settings.raw_dir == "raw"
    assert settings.kb_dir == ".kb"
    assert settings.default_retrieval_strategy == "hybrid"


def test_settings_support_fake_providers_for_tests():
    settings = Settings(embedding_provider="fake", answer_provider="fake")

    assert settings.embedding_provider == "fake"
    assert settings.answer_provider == "fake"
```

**Step 2: Run test to verify it fails**

Run:

```bash
uv run pytest tests/unit/test_config.py -v
```

Expected: FAIL because `app.core.config` is missing.

**Step 3: Write minimal implementation**

Create `app/core/config.py`:

```python
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="KB_", extra="ignore")

    app_env: str = "development"
    database_url: str = "postgresql+psycopg://kb:kb@localhost:5432/kb"
    docs_dir: str = "docs"
    raw_dir: str = "raw"
    kb_dir: str = ".kb"
    default_retrieval_strategy: str = "hybrid"
    embedding_provider: str = "fake"
    answer_provider: str = "fake"
    openai_api_key: str | None = Field(default=None, alias="OPENAI_API_KEY")
    openai_embedding_model: str | None = None
    openai_chat_model: str | None = None
    embedding_dimension: int = 1536
```

Create `.env.example`:

```dotenv
KB_APP_ENV=development
KB_DATABASE_URL=postgresql+psycopg://kb:kb@postgres:5432/kb
KB_DOCS_DIR=docs
KB_RAW_DIR=raw
KB_KB_DIR=.kb
KB_DEFAULT_RETRIEVAL_STRATEGY=hybrid
KB_EMBEDDING_PROVIDER=fake
KB_ANSWER_PROVIDER=fake
OPENAI_API_KEY=
KB_OPENAI_EMBEDDING_MODEL=
KB_OPENAI_CHAT_MODEL=
```

**Step 4: Run test to verify it passes**

Run:

```bash
uv run pytest tests/unit/test_config.py -v
```

Expected: PASS.

**Step 5: Commit**

```bash
git add app/core .env.example tests/unit/test_config.py
git commit -m "chore: add app settings"
```

## Task 3: Database Models and Migrations

**Files:**
- Create: `alembic.ini`
- Create: `migrations/env.py`
- Create: `migrations/versions/0001_initial_schema.py`
- Create: `app/core/database.py`
- Create: `app/models/__init__.py`
- Create: `app/models/tables.py`
- Test: `tests/integration/test_migrations.py`

**Step 1: Write the failing test**

Create `tests/integration/test_migrations.py`:

```python
from sqlalchemy import inspect, text


def test_initial_migration_creates_core_tables(db_engine):
    with db_engine.begin() as connection:
        connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        inspector = inspect(connection)

    table_names = set(inspector.get_table_names())

    assert {
        "documents",
        "sections",
        "chunks",
        "indexing_jobs",
        "conversations",
        "messages",
        "retrieval_events",
        "feedback",
    }.issubset(table_names)
```

Add a `db_engine` fixture in `tests/conftest.py` that reads `KB_DATABASE_URL_TEST`, applies Alembic migrations, and skips integration tests if no database URL is configured.

**Step 2: Run test to verify it fails**

Run:

```bash
uv run pytest tests/integration/test_migrations.py -v
```

Expected: FAIL or SKIP until database fixtures and migrations exist. When run with Docker test DB, it should FAIL because tables are missing.

**Step 3: Write minimal implementation**

Implement SQLAlchemy models for:

```text
documents
sections
chunks
indexing_jobs
conversations
messages
retrieval_events
feedback
```

Use UUID primary keys, timezone-aware timestamps, JSONB for flexible metadata, `TSVECTOR` for `sections.tsv`, and pgvector `Vector(1536)` for `chunks.embedding`.

Migration requirements:

```sql
CREATE EXTENSION IF NOT EXISTS vector;
CREATE INDEX ix_sections_tsv ON sections USING gin(tsv);
CREATE INDEX ix_chunks_embedding_hnsw ON chunks USING hnsw (embedding vector_cosine_ops);
CREATE UNIQUE INDEX ux_sections_source_id ON sections(source_id);
CREATE INDEX ix_documents_visibility ON documents USING gin(visibility);
```

**Step 4: Run test to verify it passes**

Run:

```bash
KB_DATABASE_URL_TEST=postgresql+psycopg://kb:kb@localhost:5432/kb_test uv run pytest tests/integration/test_migrations.py -v
```

Expected: PASS when the test Postgres container is running.

**Step 5: Commit**

```bash
git add alembic.ini migrations app/core/database.py app/models tests/integration/test_migrations.py tests/conftest.py
git commit -m "feat: add postgres schema"
```

## Task 4: Markdown Section Parsing and Citations

**Files:**
- Create: `app/indexing/markdown_parser.py`
- Create: `app/indexing/citations.py`
- Test: `tests/unit/test_markdown_parser.py`
- Test: `tests/unit/test_citations.py`

**Step 1: Write the failing tests**

Create tests for:

```python
from app.indexing.markdown_parser import parse_markdown_sections


def test_parse_markdown_sections_uses_headings_as_units():
    markdown = "# FAQ\n\nIntro\n\n## 課程網站\n\n課程網站是 https://buildmoat.org/\n"

    sections = parse_markdown_sections(filename="常見問題FAQ.md", body=markdown)

    assert [section.heading for section in sections] == ["FAQ", "課程網站"]
    assert sections[1].source_id == "常見問題FAQ.md#課程網站"
    assert "課程網站是" in sections[1].body_md
```

```python
from app.indexing.citations import citation_for


def test_citation_for_uses_filename_and_heading_slug():
    assert citation_for("refund_policy.md", "Refund Timeline") == "refund_policy.md#refund-timeline"
```

**Step 2: Run tests to verify they fail**

Run:

```bash
uv run pytest tests/unit/test_markdown_parser.py tests/unit/test_citations.py -v
```

Expected: FAIL because parser and citation utilities are missing.

**Step 3: Write minimal implementation**

Implement:

```text
parse_markdown_sections(filename, body) -> list[ParsedSection]
slugify_heading(heading) -> stable ASCII slug when possible, preserve CJK headings when needed
citation_for(filename, heading) -> filename#heading-slug
```

Rules:

```text
- If the document starts without a heading, create a synthetic title section from filename.
- Include the heading line in each section body.
- Preserve Chinese headings in display citations.
- Generate stable source IDs.
```

**Step 4: Run tests to verify they pass**

Run:

```bash
uv run pytest tests/unit/test_markdown_parser.py tests/unit/test_citations.py -v
```

Expected: PASS.

**Step 5: Commit**

```bash
git add app/indexing tests/unit/test_markdown_parser.py tests/unit/test_citations.py
git commit -m "feat: parse markdown sections"
```

## Task 5: Ingestion Importers

**Files:**
- Create: `app/ingestion/__init__.py`
- Create: `app/ingestion/importers.py`
- Create: `app/ingestion/service.py`
- Test: `tests/unit/test_importers.py`

**Step 1: Write the failing tests**

Cover `.md`, `.txt`, `.html`, and `.pdf` entry points. Keep PDF parsing test small by using a fixture or monkeypatched extractor.

Example:

```python
from app.ingestion.importers import import_text_to_markdown


def test_text_import_preserves_original_filename_in_frontmatter():
    markdown = import_text_to_markdown("faq.txt", "Question\n\nAnswer")

    assert "source_original: faq.txt" in markdown
    assert "# faq" in markdown
    assert "Question" in markdown
```

**Step 2: Run tests to verify they fail**

Run:

```bash
uv run pytest tests/unit/test_importers.py -v
```

Expected: FAIL because ingestion modules are missing.

**Step 3: Write minimal implementation**

Implement import functions:

```text
import_markdown_to_markdown(filename, body)
import_text_to_markdown(filename, body)
import_html_to_markdown(filename, body)
import_pdf_to_markdown(filename, bytes)
```

Each output must include frontmatter:

```yaml
---
source_original: raw/<filename>
source_type: imported
imported_at: <iso timestamp>
---
```

**Step 4: Run tests to verify they pass**

Run:

```bash
uv run pytest tests/unit/test_importers.py -v
```

Expected: PASS.

**Step 5: Commit**

```bash
git add app/ingestion tests/unit/test_importers.py
git commit -m "feat: add document importers"
```

## Task 6: Embedding Providers

**Files:**
- Create: `app/retrieval/embeddings.py`
- Test: `tests/unit/test_embeddings.py`

**Step 1: Write the failing tests**

```python
from app.retrieval.embeddings import FakeEmbeddingProvider


def test_fake_embedding_provider_is_deterministic_and_1536_dimensional():
    provider = FakeEmbeddingProvider(dimension=1536)

    first = provider.embed_text("consistent hashing")
    second = provider.embed_text("consistent hashing")

    assert first == second
    assert len(first) == 1536
    assert any(value != 0 for value in first)
```

**Step 2: Run test to verify it fails**

Run:

```bash
uv run pytest tests/unit/test_embeddings.py -v
```

Expected: FAIL because embedding provider is missing.

**Step 3: Write minimal implementation**

Implement:

```text
EmbeddingProvider protocol
FakeEmbeddingProvider
OpenAIEmbeddingProvider placeholder behind config
```

The OpenAI provider should not be fully implemented until the `openai-docs` skill has been used in the implementation session.

**Step 4: Run test to verify it passes**

Run:

```bash
uv run pytest tests/unit/test_embeddings.py -v
```

Expected: PASS.

**Step 5: Commit**

```bash
git add app/retrieval/embeddings.py tests/unit/test_embeddings.py
git commit -m "feat: add embedding providers"
```

## Task 7: Indexing Service

**Files:**
- Create: `app/indexing/service.py`
- Create: `app/indexing/export.py`
- Test: `tests/integration/test_indexing_service.py`

**Step 1: Write the failing integration test**

```python
from pathlib import Path

from app.indexing.service import IndexingService
from app.retrieval.embeddings import FakeEmbeddingProvider


def test_indexing_service_writes_documents_sections_chunks_and_export(db_session, tmp_path):
    docs_dir = tmp_path / "docs"
    kb_dir = tmp_path / ".kb"
    docs_dir.mkdir()
    (docs_dir / "常見問題FAQ.md").write_text("# FAQ\n\n## 課程網站\n\n課程網站是 https://buildmoat.org/\n", encoding="utf-8")

    service = IndexingService(
        session=db_session,
        docs_dir=docs_dir,
        kb_dir=kb_dir,
        embedding_provider=FakeEmbeddingProvider(dimension=1536),
    )

    result = service.rebuild_index()

    assert result.files_indexed == 1
    assert result.sections_indexed == 2
    assert (kb_dir / "index.json").exists()
```

**Step 2: Run test to verify it fails**

Run:

```bash
KB_DATABASE_URL_TEST=postgresql+psycopg://kb:kb@localhost:5432/kb_test uv run pytest tests/integration/test_indexing_service.py -v
```

Expected: FAIL because `IndexingService` is missing.

**Step 3: Write minimal implementation**

Implement `IndexingService.rebuild_index()`:

```text
- scan docs_dir for *.md
- parse sections
- upsert documents by filename
- delete/recreate changed sections and chunks
- embed changed chunks through provider
- write tsv values
- write .kb/index.json
- create indexing_jobs row with stats
```

Use one transaction for each rebuild in MVP. Use content hashes so future work can make this incremental.

**Step 4: Run test to verify it passes**

Run:

```bash
KB_DATABASE_URL_TEST=postgresql+psycopg://kb:kb@localhost:5432/kb_test uv run pytest tests/integration/test_indexing_service.py -v
```

Expected: PASS.

**Step 5: Commit**

```bash
git add app/indexing tests/integration/test_indexing_service.py
git commit -m "feat: build postgres knowledge index"
```

## Task 8: Lexical, Vector, and Hybrid Retrieval

**Files:**
- Create: `app/retrieval/models.py`
- Create: `app/retrieval/lexical.py`
- Create: `app/retrieval/vector.py`
- Create: `app/retrieval/hybrid.py`
- Test: `tests/unit/test_hybrid_retrieval.py`
- Test: `tests/integration/test_retrieval.py`

**Step 1: Write failing tests**

Unit test the merge behavior:

```python
from app.retrieval.hybrid import merge_results
from app.retrieval.models import RetrievedCandidate


def test_merge_results_deduplicates_by_section_and_prefers_highest_score():
    candidates = [
        RetrievedCandidate(section_id="s1", source_id="a.md#a", score=0.4, strategy="lexical"),
        RetrievedCandidate(section_id="s1", source_id="a.md#a", score=0.8, strategy="vector"),
    ]

    merged = merge_results(candidates)

    assert len(merged) == 1
    assert merged[0].score == 0.8
```

Integration test:

```python
def test_hybrid_retrieval_finds_course_website(indexed_sample_kb):
    retriever = indexed_sample_kb.retriever

    results = retriever.search("課程網站在哪？", strategy="hybrid")

    assert results
    assert results[0].source_id == "常見問題FAQ.md#課程網站"
```

**Step 2: Run tests to verify they fail**

Run:

```bash
uv run pytest tests/unit/test_hybrid_retrieval.py tests/integration/test_retrieval.py -v
```

Expected: FAIL because retrieval modules are missing.

**Step 3: Write minimal implementation**

Implement:

```text
LexicalRetriever.search(query, limit)
VectorRetriever.search(query, limit)
HybridRetriever.search(query, strategy, limit, debug)
merge_results(candidates)
```

Threshold behavior:

```text
- If best merged score is below threshold, return decision cannot_confirm.
- Preserve rejected candidates in debug mode only.
- Always merge to section-level citations.
```

**Step 4: Run tests to verify they pass**

Run:

```bash
uv run pytest tests/unit/test_hybrid_retrieval.py tests/integration/test_retrieval.py -v
```

Expected: PASS.

**Step 5: Commit**

```bash
git add app/retrieval tests/unit/test_hybrid_retrieval.py tests/integration/test_retrieval.py
git commit -m "feat: add hybrid retrieval"
```

## Task 9: Answer Generation and Citation Validation

**Files:**
- Create: `app/answer/__init__.py`
- Create: `app/answer/providers.py`
- Create: `app/answer/citations.py`
- Create: `app/answer/service.py`
- Test: `tests/unit/test_answer_service.py`

**Step 1: Write failing tests**

```python
from app.answer.citations import validate_citations


def test_validate_citations_rejects_sources_not_in_context():
    result = validate_citations(
        answer="答案來源：missing.md#heading",
        allowed_source_ids={"faq.md#course-site"},
    )

    assert not result.valid
```

```python
from app.answer.service import AnswerService
from app.answer.providers import FakeAnswerProvider


def test_answer_service_returns_cannot_confirm_when_no_sources():
    service = AnswerService(provider=FakeAnswerProvider())

    result = service.answer(query="附近有哪些餐廳？", sources=[])

    assert result.answer == "我無法從知識庫確認這件事。"
    assert result.sources == []
```

**Step 2: Run tests to verify they fail**

Run:

```bash
uv run pytest tests/unit/test_answer_service.py -v
```

Expected: FAIL because answer modules are missing.

**Step 3: Write minimal implementation**

Implement:

```text
AnswerProvider protocol
FakeAnswerProvider
OpenAIAnswerProvider placeholder
AnswerService.answer()
validate_citations()
```

Rules:

```text
- No sources means cannot-confirm.
- Generated citations must be a subset of selected source IDs.
- Source content is included as evidence only.
- Retry once with stricter prompt if provider returns invalid citations.
```

**Step 4: Run tests to verify they pass**

Run:

```bash
uv run pytest tests/unit/test_answer_service.py -v
```

Expected: PASS.

**Step 5: Commit**

```bash
git add app/answer tests/unit/test_answer_service.py
git commit -m "feat: add grounded answer service"
```

## Task 10: Core API Routes

**Files:**
- Create: `app/api/indexing.py`
- Create: `app/api/imports.py`
- Create: `app/api/search.py`
- Create: `app/api/chat.py`
- Create: `app/api/sources.py`
- Create: `app/api/feedback.py`
- Modify: `app/main.py`
- Test: `tests/integration/test_api_workflow.py`

**Step 1: Write failing API workflow tests**

```python
from fastapi.testclient import TestClient


def test_chat_before_index_returns_not_indexed(app_with_test_db):
    client = TestClient(app_with_test_db)

    response = client.post("/chat", json={"query": "課程網站在哪？"})

    assert response.status_code == 200
    assert response.json()["answer"] == "知識庫尚未建立索引，請先建立索引。"
```

Add tests for:

```text
POST /index
GET /index/status
POST /search
POST /chat after indexing
GET /sources
POST /feedback
```

**Step 2: Run tests to verify they fail**

Run:

```bash
uv run pytest tests/integration/test_api_workflow.py -v
```

Expected: FAIL because API routes are missing.

**Step 3: Write minimal implementation**

Implement route handlers that call service classes:

```text
GET /ready checks DB and index readiness
POST /imports saves uploaded file and creates canonical Markdown
POST /index runs rebuild synchronously in MVP
GET /index/status returns latest indexing job
POST /search returns selected candidates
POST /chat retrieves and answers
GET /sources lists documents
GET /sources/{document_id} returns document
GET /sources/{document_id}/sections/{section_id} returns section
POST /feedback writes feedback row
```

**Step 4: Run tests to verify they pass**

Run:

```bash
uv run pytest tests/integration/test_api_workflow.py -v
```

Expected: PASS.

**Step 5: Commit**

```bash
git add app/api app/main.py tests/integration/test_api_workflow.py
git commit -m "feat: expose knowledge base api"
```

## Task 11: Streaming Chat API

**Files:**
- Modify: `app/api/chat.py`
- Test: `tests/integration/test_chat_stream.py`

**Step 1: Write failing streaming test**

```python
def test_chat_stream_sends_sources_tokens_and_done(app_with_indexed_sample_docs):
    client = app_with_indexed_sample_docs.test_client

    with client.stream("POST", "/chat/stream", json={"query": "課程網站在哪？"}) as response:
        body = "".join(response.iter_text())

    assert "event: sources" in body
    assert "event: token" in body
    assert "event: done" in body
```

**Step 2: Run test to verify it fails**

Run:

```bash
uv run pytest tests/integration/test_chat_stream.py -v
```

Expected: FAIL because `/chat/stream` does not exist.

**Step 3: Write minimal implementation**

Use `sse-starlette` to emit:

```text
event: sources
event: token
event: done
```

For fake provider, split answer text into deterministic token chunks.

**Step 4: Run test to verify it passes**

Run:

```bash
uv run pytest tests/integration/test_chat_stream.py -v
```

Expected: PASS.

**Step 5: Commit**

```bash
git add app/api/chat.py tests/integration/test_chat_stream.py
git commit -m "feat: stream grounded chat answers"
```

## Task 12: Three-Column Browser UI

**Files:**
- Create: `app/ui/static/app.css`
- Create: `app/ui/static/app.js`
- Create: `app/ui/templates/index.html`
- Create: `app/api/ui.py`
- Modify: `app/main.py`
- Test: `tests/e2e/test_ui.py`

**Step 1: Write failing UI test**

```python
def test_ui_serves_three_column_workbench(client):
    response = client.get("/")

    assert response.status_code == 200
    assert "Chat" in response.text
    assert "Mindmap" in response.text
    assert "Admin Uploads" in response.text
    assert "selected sources" in response.text.lower()
```

**Step 2: Run test to verify it fails**

Run:

```bash
uv run pytest tests/e2e/test_ui.py -v
```

Expected: FAIL because UI route does not exist.

**Step 3: Write minimal implementation**

Build a responsive three-column workbench:

```text
left: functional tabs
center: active workspace
right: context inspector
```

Use vanilla JS to call:

```text
POST /chat/stream
POST /imports
POST /index
GET /index/status
GET /sources
```

Do not build a landing page. The first screen is the usable product workbench.

**Step 4: Run test to verify it passes**

Run:

```bash
uv run pytest tests/e2e/test_ui.py -v
```

Expected: PASS.

**Step 5: Commit**

```bash
git add app/ui app/api/ui.py app/main.py tests/e2e/test_ui.py
git commit -m "feat: add product workbench ui"
```

## Task 13: Mindmap Skeleton

**Files:**
- Create: `app/api/mindmap.py`
- Modify: `app/ui/static/app.js`
- Modify: `app/ui/templates/index.html`
- Test: `tests/integration/test_mindmap.py`

**Step 1: Write failing test**

```python
def test_mindmap_returns_document_and_section_nodes(app_with_indexed_sample_docs):
    client = app_with_indexed_sample_docs.test_client

    response = client.get("/mindmap")

    assert response.status_code == 200
    payload = response.json()
    assert payload["nodes"]
    assert payload["edges"]
```

**Step 2: Run test to verify it fails**

Run:

```bash
uv run pytest tests/integration/test_mindmap.py -v
```

Expected: FAIL because endpoint is missing.

**Step 3: Write minimal implementation**

Return a graph:

```json
{
  "nodes": [
    {"id": "doc:<id>", "label": "常見問題FAQ.md", "type": "document"},
    {"id": "section:<id>", "label": "課程網站", "type": "section"}
  ],
  "edges": [
    {"source": "doc:<id>", "target": "section:<id>", "type": "contains"}
  ]
}
```

Render it in the Mindmap tab as a simple SVG or HTML graph. Advanced concept extraction is deferred.

**Step 4: Run test to verify it passes**

Run:

```bash
uv run pytest tests/integration/test_mindmap.py -v
```

Expected: PASS.

**Step 5: Commit**

```bash
git add app/api/mindmap.py app/ui tests/integration/test_mindmap.py
git commit -m "feat: add knowledge mindmap skeleton"
```

## Task 14: Docker Compose and Makefile

**Files:**
- Create: `Dockerfile`
- Create: `docker-compose.yml`
- Create: `Makefile`
- Test: `tests/e2e/test_docker_compose.py`

**Step 1: Write failing smoke test**

Create an e2e test that assumes the app is running under Docker Compose:

```python
import httpx


def test_docker_app_health():
    response = httpx.get("http://localhost:8000/health", timeout=5)

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
```

**Step 2: Run test to verify it fails**

Run:

```bash
uv run pytest tests/e2e/test_docker_compose.py -v
```

Expected: FAIL if Docker Compose is not running.

**Step 3: Write minimal implementation**

`docker-compose.yml` services:

```text
app
worker
postgres
```

Postgres image must include pgvector, for example a pgvector-enabled Postgres image.

Makefile targets:

```text
dev
test
test-unit
test-integration
test-e2e
lint
format
migrate
index
docker-build
docker-up
docker-test
```

**Step 4: Run test to verify it passes**

Run:

```bash
make docker-up
uv run pytest tests/e2e/test_docker_compose.py -v
```

Expected: PASS.

**Step 5: Commit**

```bash
git add Dockerfile docker-compose.yml Makefile tests/e2e/test_docker_compose.py
git commit -m "chore: add docker compose workflow"
```

## Task 15: Sample Docs Seeding and README

**Files:**
- Modify: `README.md`
- Create: `scripts/seed_sample_docs.py`
- Test: `tests/unit/test_seed_sample_docs.py`

**Step 1: Write failing test**

```python
from pathlib import Path

from scripts.seed_sample_docs import copy_sample_docs


def test_copy_sample_docs_copies_markdown_files(tmp_path):
    sample_dir = tmp_path / "sample-docs"
    docs_dir = tmp_path / "docs"
    sample_dir.mkdir()
    (sample_dir / "faq.md").write_text("# FAQ\n", encoding="utf-8")

    copied = copy_sample_docs(sample_dir=sample_dir, docs_dir=docs_dir)

    assert copied == 1
    assert (docs_dir / "faq.md").exists()
```

**Step 2: Run test to verify it fails**

Run:

```bash
uv run pytest tests/unit/test_seed_sample_docs.py -v
```

Expected: FAIL because script is missing.

**Step 3: Write minimal implementation**

Implement a script that copies sample Markdown files into `docs/` without deleting anything.

README must document:

```text
- local setup
- Docker Compose setup
- env vars
- import/index/chat workflow
- test commands
- production notes
```

**Step 4: Run test to verify it passes**

Run:

```bash
uv run pytest tests/unit/test_seed_sample_docs.py -v
```

Expected: PASS.

**Step 5: Commit**

```bash
git add README.md scripts/seed_sample_docs.py tests/unit/test_seed_sample_docs.py
git commit -m "docs: document product workflow"
```

## Task 16: OpenAI Providers

**Files:**
- Modify: `app/retrieval/embeddings.py`
- Modify: `app/answer/providers.py`
- Test: `tests/unit/test_openai_provider_config.py`

**Step 1: Use required docs skill**

Before writing implementation code, use `openai-docs` and official OpenAI documentation for the current SDK API.

**Step 2: Write failing tests**

```python
from app.retrieval.embeddings import create_embedding_provider
from app.answer.providers import create_answer_provider


def test_provider_factories_default_to_fake_without_api_key():
    assert create_embedding_provider(provider_name="fake").__class__.__name__ == "FakeEmbeddingProvider"
    assert create_answer_provider(provider_name="fake").__class__.__name__ == "FakeAnswerProvider"
```

Add tests that monkeypatch the OpenAI client so no network call happens.

**Step 3: Run tests to verify they fail**

Run:

```bash
uv run pytest tests/unit/test_openai_provider_config.py -v
```

Expected: FAIL until provider factories exist.

**Step 4: Write minimal implementation**

Implement OpenAI provider classes behind interfaces:

```text
OpenAIEmbeddingProvider.embed_text()
OpenAIAnswerProvider.generate_answer()
create_embedding_provider()
create_answer_provider()
```

Never call OpenAI in tests.

**Step 5: Run tests to verify they pass**

Run:

```bash
uv run pytest tests/unit/test_openai_provider_config.py -v
```

Expected: PASS.

**Step 6: Commit**

```bash
git add app/retrieval/embeddings.py app/answer/providers.py tests/unit/test_openai_provider_config.py
git commit -m "feat: add openai provider adapters"
```

## Task 17: Full Verification

**Files:**
- Modify only files required to fix verification failures.

**Step 1: Run unit tests**

```bash
make test-unit
```

Expected: PASS.

**Step 2: Run integration tests**

```bash
make test-integration
```

Expected: PASS with Docker Postgres running.

**Step 3: Run e2e tests**

```bash
make test-e2e
```

Expected: PASS.

**Step 4: Run lint and type checks**

```bash
make lint
```

Expected: PASS.

**Step 5: Run Docker workflow**

```bash
make docker-build
make docker-up
make docker-test
```

Expected: PASS.

**Step 6: Manual smoke test**

```bash
curl http://localhost:8000/health
curl http://localhost:8000/ready
curl -X POST http://localhost:8000/index
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"query":"課程網站在哪？"}'
```

Expected:

```text
/health returns {"status":"ok"}
/ready confirms DB readiness
/index returns files_indexed and sections_indexed
/chat returns a grounded answer citing 常見問題FAQ.md#課程網站
```

**Step 7: Commit verification fixes**

```bash
git add <changed-files>
git commit -m "test: complete product verification"
```
