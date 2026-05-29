from app.core.config import Settings
from app.provider_budget import (
    ProviderBudgetPolicyStatus,
    ProviderBudgetStatus,
    provider_budget_status,
)


def test_provider_budget_disabled_is_ok_and_never_blocks() -> None:
    status = provider_budget_status(
        Settings(provider_budget_enabled=False),
        metrics_snapshot=_metrics(total_calls=10, errors=5, total_tokens=1000),
    )

    assert status.enabled is False
    assert status.status == "ok"
    assert status.should_block is False
    assert status.reasons == []


def test_provider_budget_warns_when_token_usage_reaches_warning_ratio() -> None:
    status = provider_budget_status(
        Settings(
            provider_budget_daily_token_limit=1000,
            provider_budget_warning_ratio=0.8,
        ),
        metrics_snapshot=_metrics(total_calls=3, errors=0, total_tokens=800),
    )

    assert status.status == "warning"
    assert status.should_block is False
    token_policy = _policy(status, "tokens")
    assert token_policy.status == "warning"
    assert token_policy.used == 800
    assert token_policy.limit == 1000
    assert token_policy.warning_threshold == 800
    assert token_policy.remaining == 200


def test_provider_budget_exceeds_when_token_usage_reaches_limit() -> None:
    status = provider_budget_status(
        Settings(
            provider_budget_daily_token_limit=1000,
            provider_budget_block_on_exceeded=True,
        ),
        metrics_snapshot=_metrics(total_calls=3, errors=0, total_tokens=1000),
    )

    assert status.status == "exceeded"
    assert status.should_block is True
    assert "tokens" in status.reasons[0]


def test_provider_budget_exceeds_when_call_usage_reaches_limit() -> None:
    status = provider_budget_status(
        Settings(provider_budget_daily_call_limit=3),
        metrics_snapshot=_metrics(total_calls=3, errors=0, total_tokens=10),
    )

    assert status.status == "exceeded"
    assert _policy(status, "calls").remaining == 0


def test_provider_budget_exceeds_when_error_rate_is_above_limit() -> None:
    status = provider_budget_status(
        Settings(provider_budget_error_rate_limit=0.25),
        metrics_snapshot=_metrics(total_calls=10, errors=3, total_tokens=10),
    )

    assert status.status == "exceeded"
    error_policy = _policy(status, "errors")
    assert error_policy.used == 0.3
    assert error_policy.limit == 0.25


def _policy(status: ProviderBudgetStatus, name: str) -> ProviderBudgetPolicyStatus:
    return next(policy for policy in status.policies if policy.name == name)


def _metrics(*, total_calls: int, errors: int, total_tokens: int) -> dict[str, object]:
    return {
        "provider_calls_total": total_calls,
        "provider_errors_total": errors,
        "provider_usage_by_key": {
            "openai:gpt-test:chat.completions.stream": {
                "prompt_tokens": total_tokens,
                "completion_tokens": 0,
                "total_tokens": total_tokens,
                "cached_tokens": 0,
                "reasoning_tokens": 0,
            }
        },
    }
