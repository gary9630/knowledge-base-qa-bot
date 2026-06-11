from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

ProviderCallStatus = Literal["succeeded", "failed"]


@dataclass(frozen=True)
class ProviderUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cached_tokens: int = 0
    reasoning_tokens: int = 0

    def to_dict(self) -> dict[str, int]:
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "cached_tokens": self.cached_tokens,
            "reasoning_tokens": self.reasoning_tokens,
        }


@dataclass(frozen=True)
class ProviderCallRecord:
    provider: str
    operation: str
    model: str
    status: ProviderCallStatus
    client_request_id: str | None = None
    provider_request_id: str | None = None
    usage: ProviderUsage | None = None
    usage_complete: bool = False
    latency_ms: int = 0
    error_type: str | None = None

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "provider": self.provider,
            "operation": self.operation,
            "model": self.model,
            "status": self.status,
            "usage_complete": self.usage_complete,
            "latency_ms": self.latency_ms,
        }
        if self.client_request_id:
            payload["client_request_id"] = self.client_request_id
        if self.provider_request_id:
            payload["provider_request_id"] = self.provider_request_id
        if self.error_type:
            payload["error_type"] = self.error_type
        if self.usage is not None:
            payload["usage"] = self.usage.to_dict()
        return payload


@dataclass
class ProviderCallContext:
    client_request_id: str | None = None
    records: list[ProviderCallRecord] = field(default_factory=list)
    _sequence: int = 0

    def next_client_request_id(self) -> str | None:
        if not self.client_request_id:
            return None
        self._sequence += 1
        return f"{self.client_request_id}-{self._sequence}"

    def record(self, record: ProviderCallRecord) -> None:
        self.records.append(record)


def completion_usage(response: object) -> ProviderUsage | None:
    """Extract token usage from an OpenAI-shaped completion response or chunk."""
    usage = _object_value(response, "usage")
    if usage is None:
        return None

    prompt_details = _object_value(usage, "prompt_tokens_details")
    completion_details = _object_value(usage, "completion_tokens_details")
    return ProviderUsage(
        prompt_tokens=_int_value(_object_value(usage, "prompt_tokens")),
        completion_tokens=_int_value(_object_value(usage, "completion_tokens")),
        total_tokens=_int_value(_object_value(usage, "total_tokens")),
        cached_tokens=_int_value(_object_value(prompt_details, "cached_tokens")),
        reasoning_tokens=_int_value(_object_value(completion_details, "reasoning_tokens")),
    )


def response_request_id(response: object) -> str | None:
    """Best-effort provider request id from an OpenAI-shaped response or chunk."""
    request_id = _object_value(response, "_request_id")
    if isinstance(request_id, str) and request_id:
        return request_id

    response_id = _object_value(response, "id")
    return response_id if isinstance(response_id, str) and response_id else None


def _object_value(value: object, key: str) -> object:
    if isinstance(value, dict):
        return value.get(key)
    return getattr(value, key, None)


def _int_value(value: object) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    return 0
