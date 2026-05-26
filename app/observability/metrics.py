from __future__ import annotations

from collections import Counter, deque
from dataclasses import dataclass
from threading import Lock
from typing import Any


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
        self._latest_requests: deque[RequestMetric] = deque(maxlen=latest_limit)

    def record_request(self, metric: RequestMetric, *, error: bool = False) -> None:
        with self._lock:
            self._requests_total += 1
            if error:
                self._errors_total += 1
            self._latency_total_ms += metric.duration_ms
            self._responses_by_status[str(metric.status_code)] += 1
            self._responses_by_route[metric.route] += 1
            self._latest_requests.appendleft(metric)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            average_latency = (
                self._latency_total_ms / self._requests_total if self._requests_total else 0.0
            )
            return {
                "requests_total": self._requests_total,
                "responses_by_status": dict(self._responses_by_status),
                "responses_by_route": dict(self._responses_by_route),
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
            }
