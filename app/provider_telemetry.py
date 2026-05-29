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
