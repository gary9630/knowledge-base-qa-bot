from pathlib import Path

from app.api.chat import ChatRequest
from app.api.search import SearchRequest


def test_chat_and_search_default_retrieval_limit_is_ten() -> None:
    assert ChatRequest(query="How should RAG handle citations?").limit == 10
    assert SearchRequest(query="How should RAG handle citations?").limit == 10


def test_ui_chat_limit_defaults_to_ten() -> None:
    script = Path("app/ui/static/app.js").read_text(encoding="utf-8")

    assert 'const CHAT_LIMIT = 10;' in script
    assert 'const CHAT_STRATEGY = "hybrid";' in script
