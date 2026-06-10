from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

import tiktoken

DEFAULT_TOKEN_ENCODING = "o200k_base"


@dataclass(frozen=True)
class TokenWindow:
    text: str
    start_token: int
    end_token: int
    token_count: int


@lru_cache(maxsize=4)
def get_token_encoding(encoding_name: str = DEFAULT_TOKEN_ENCODING) -> tiktoken.Encoding:
    return tiktoken.get_encoding(encoding_name)


def count_tokens(text: str, *, encoding_name: str = DEFAULT_TOKEN_ENCODING) -> int:
    if not text:
        return 0
    return len(get_token_encoding(encoding_name).encode(text))


def truncate_to_tokens(
    text: str,
    *,
    limit: int,
    encoding_name: str = DEFAULT_TOKEN_ENCODING,
) -> str:
    if limit <= 0:
        raise ValueError("limit must be positive")
    encoding = get_token_encoding(encoding_name)
    tokens = encoding.encode(text)
    if len(tokens) <= limit:
        return text
    return _safe_decode(encoding, tokens[:limit]).strip()


def split_token_windows(
    text: str,
    *,
    token_limit: int,
    overlap: int,
    encoding_name: str = DEFAULT_TOKEN_ENCODING,
) -> list[TokenWindow]:
    if token_limit <= 0:
        raise ValueError("token_limit must be positive")
    if overlap < 0:
        raise ValueError("overlap must be non-negative")
    if overlap >= token_limit:
        raise ValueError("overlap must be smaller than token_limit")

    stripped = text.strip()
    if not stripped:
        return []

    encoding = get_token_encoding(encoding_name)
    tokens = encoding.encode(stripped)
    if len(tokens) <= token_limit:
        return [
            TokenWindow(
                text=stripped,
                start_token=0,
                end_token=len(tokens),
                token_count=len(tokens),
            )
        ]

    windows: list[TokenWindow] = []
    step = token_limit - overlap
    start = 0
    while start < len(tokens):
        end = min(len(tokens), start + token_limit)
        window_text = _safe_decode(encoding, tokens[start:end]).strip()
        windows.append(
            TokenWindow(
                text=window_text,
                start_token=start,
                end_token=end,
                token_count=end - start,
            )
        )
        if end == len(tokens):
            break
        start += step
    return windows


def _safe_decode(encoding: tiktoken.Encoding, tokens: list[int]) -> str:
    # Token windows can split a multi-byte character at the edges; decode at the byte
    # level and drop the partial bytes instead of emitting replacement characters.
    data = encoding.decode_bytes(tokens)
    return data.decode("utf-8", errors="ignore")
