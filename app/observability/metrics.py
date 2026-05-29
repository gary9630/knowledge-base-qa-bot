from __future__ import annotations

from collections import Counter, deque
from dataclasses import dataclass
from threading import Lock
from typing import Any

from app.provider_telemetry import ProviderCallRecord, ProviderUsage


@dataclass(frozen=True)
class RequestMetric:
    request_id: str
    method: str
    path: str
    route: str
    status_code: int
    duration_ms: int


class InMemoryMetrics:
    def __init__(self, latest_limit: int = 20) -> None:
        self._lock = Lock()
        self._requests_total = 0
        self._errors_total = 0
        self._latency_total_ms = 0
        self._responses_by_status: Counter[str] = Counter()
        self._responses_by_route: Counter[str] = Counter()
        self._rate_limited_by_policy: Counter[str] = Counter()
        self._concurrency_limited_by_policy: Counter[str] = Counter()
        self._latest_requests: deque[RequestMetric] = deque(maxlen=latest_limit)
        self._provider_calls_total = 0
        self._provider_errors_total = 0
        self._provider_calls_by_key: Counter[str] = Counter()
        self._provider_usage_by_key: dict[str, ProviderUsage] = {}
        self._latest_provider_calls: deque[ProviderCallRecord] = deque(maxlen=latest_limit)

    def record_request(self, metric: RequestMetric, *, error: bool = False) -> None:
        with self._lock:
            self._requests_total += 1
            if error:
                self._errors_total += 1
            self._latency_total_ms += metric.duration_ms
            self._responses_by_status[str(metric.status_code)] += 1
            self._responses_by_route[metric.route] += 1
            self._latest_requests.appendleft(metric)

    def record_rate_limited(self, policy: str) -> None:
        with self._lock:
            self._rate_limited_by_policy[policy] += 1

    def record_concurrency_limited(self, policy: str) -> None:
        with self._lock:
            self._concurrency_limited_by_policy[policy] += 1

    def record_provider_call(self, record: ProviderCallRecord) -> None:
        key = _provider_key(record)
        with self._lock:
            self._provider_calls_total += 1
            if record.status == "failed":
                self._provider_errors_total += 1
            self._provider_calls_by_key[key] += 1
            if record.usage is not None:
                self._provider_usage_by_key[key] = _sum_provider_usage(
                    self._provider_usage_by_key.get(key),
                    record.usage,
                )
            self._latest_provider_calls.appendleft(record)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            average_latency = (
                self._latency_total_ms / self._requests_total if self._requests_total else 0.0
            )
            return {
                "requests_total": self._requests_total,
                "responses_by_status": dict(self._responses_by_status),
                "responses_by_route": dict(self._responses_by_route),
                "rate_limited_total": sum(self._rate_limited_by_policy.values()),
                "rate_limited_by_policy": dict(self._rate_limited_by_policy),
                "concurrency_limited_total": sum(
                    self._concurrency_limited_by_policy.values()
                ),
                "concurrency_limited_by_policy": dict(
                    self._concurrency_limited_by_policy
                ),
                "errors_total": self._errors_total,
                "average_latency_ms": round(average_latency, 2),
                "latest_requests": [
                    {
                        "request_id": item.request_id,
                        "method": item.method,
                        "path": item.path,
                        "route": item.route,
                        "status_code": item.status_code,
                        "duration_ms": item.duration_ms,
                    }
                    for item in self._latest_requests
                ],
                "provider_calls_total": self._provider_calls_total,
                "provider_errors_total": self._provider_errors_total,
                "provider_calls_by_key": dict(self._provider_calls_by_key),
                "provider_usage_by_key": {
                    key: usage.to_dict()
                    for key, usage in self._provider_usage_by_key.items()
                },
                "latest_provider_calls": [
                    item.to_dict() for item in self._latest_provider_calls
                ],
            }


def _provider_key(record: ProviderCallRecord) -> str:
    return f"{record.provider}:{record.model}:{record.operation}"


def _sum_provider_usage(
    existing: ProviderUsage | None,
    incoming: ProviderUsage,
) -> ProviderUsage:
    if existing is None:
        return incoming
    return ProviderUsage(
        prompt_tokens=existing.prompt_tokens + incoming.prompt_tokens,
        completion_tokens=existing.completion_tokens + incoming.completion_tokens,
        total_tokens=existing.total_tokens + incoming.total_tokens,
        cached_tokens=existing.cached_tokens + incoming.cached_tokens,
        reasoning_tokens=existing.reasoning_tokens + incoming.reasoning_tokens,
    )
