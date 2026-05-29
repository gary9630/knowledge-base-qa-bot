from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel

from app.core.config import Settings

ProviderBudgetState = Literal["ok", "warning", "exceeded"]


class ProviderBudgetPolicyStatus(BaseModel):
    name: str
    label: str
    unit: str
    status: ProviderBudgetState
    used: float
    limit: float | None = None
    warning_threshold: float | None = None
    remaining: float | None = None
    reason: str | None = None


class ProviderBudgetStatus(BaseModel):
    enabled: bool
    status: ProviderBudgetState
    should_block: bool
    block_on_exceeded: bool
    reasons: list[str]
    policies: list[ProviderBudgetPolicyStatus]


def provider_budget_status(
    settings: Settings,
    *,
    metrics_snapshot: dict[str, Any],
) -> ProviderBudgetStatus:
    if not settings.provider_budget_enabled:
        return ProviderBudgetStatus(
            enabled=False,
            status="ok",
            should_block=False,
            block_on_exceeded=settings.provider_budget_block_on_exceeded,
            reasons=[],
            policies=[],
        )

    total_calls = _int_value(metrics_snapshot.get("provider_calls_total"))
    error_calls = _int_value(metrics_snapshot.get("provider_errors_total"))
    error_rate = error_calls / total_calls if total_calls else 0.0
    policies = [
        _threshold_policy(
            name="tokens",
            label="Daily Tokens",
            unit="tokens",
            used=float(_total_provider_tokens(metrics_snapshot)),
            limit=float(settings.provider_budget_daily_token_limit),
            warning_ratio=settings.provider_budget_warning_ratio,
        ),
        _threshold_policy(
            name="calls",
            label="Daily Calls",
            unit="calls",
            used=float(total_calls),
            limit=float(settings.provider_budget_daily_call_limit),
            warning_ratio=settings.provider_budget_warning_ratio,
        ),
        _threshold_policy(
            name="errors",
            label="Error Rate",
            unit="ratio",
            used=round(error_rate, 4),
            limit=float(settings.provider_budget_error_rate_limit),
            warning_ratio=settings.provider_budget_warning_ratio,
        ),
    ]
    overall = _overall_status(policies)
    reasons = [
        policy.reason
        for policy in policies
        if policy.status == "exceeded" and policy.reason is not None
    ]
    return ProviderBudgetStatus(
        enabled=True,
        status=overall,
        should_block=overall == "exceeded"
        and settings.provider_budget_block_on_exceeded,
        block_on_exceeded=settings.provider_budget_block_on_exceeded,
        reasons=reasons,
        policies=policies,
    )


def _threshold_policy(
    *,
    name: str,
    label: str,
    unit: str,
    used: float,
    limit: float,
    warning_ratio: float,
) -> ProviderBudgetPolicyStatus:
    if limit <= 0:
        return ProviderBudgetPolicyStatus(
            name=name,
            label=label,
            unit=unit,
            status="ok",
            used=used,
            reason="No limit configured.",
        )

    warning_threshold = limit * warning_ratio
    remaining = max(0.0, limit - used)
    status: ProviderBudgetState = "ok"
    reason: str | None = None
    if used >= limit:
        status = "exceeded"
        reason = f"{name} budget exceeded"
    elif used > 0 and used >= warning_threshold:
        status = "warning"
        reason = f"{name} budget warning"

    return ProviderBudgetPolicyStatus(
        name=name,
        label=label,
        unit=unit,
        status=status,
        used=used,
        limit=limit,
        warning_threshold=warning_threshold,
        remaining=remaining,
        reason=reason,
    )


def _overall_status(
    policies: list[ProviderBudgetPolicyStatus],
) -> ProviderBudgetState:
    if any(policy.status == "exceeded" for policy in policies):
        return "exceeded"
    if any(policy.status == "warning" for policy in policies):
        return "warning"
    return "ok"


def _total_provider_tokens(metrics_snapshot: dict[str, Any]) -> int:
    usage_by_key = _dict_value(metrics_snapshot.get("provider_usage_by_key"))
    total = 0
    for usage in usage_by_key.values():
        total += _int_value(_dict_value(usage).get("total_tokens"))
    return total


def _dict_value(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _int_value(value: object) -> int:
    if isinstance(value, bool):
        return 0
    return value if isinstance(value, int) else 0
