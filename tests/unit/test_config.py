from app.core.config import Settings


def test_settings_default_paths_are_product_defaults() -> None:
    settings = Settings()

    assert settings.docs_dir == "docs"
    assert settings.raw_dir == "raw"
    assert settings.kb_dir == ".kb"
    assert settings.default_retrieval_strategy == "hybrid"


def test_settings_support_fake_providers_for_tests() -> None:
    settings = Settings(embedding_provider="fake", answer_provider="fake")

    assert settings.embedding_provider == "fake"
    assert settings.answer_provider == "fake"
