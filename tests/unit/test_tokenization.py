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
