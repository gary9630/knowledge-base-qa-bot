from __future__ import annotations

from app.auth.sessions import PlatformSession
from app.core.config import Settings
from app.source_access import (
    SourcePrincipal,
    source_is_visible,
    source_principal_for_session,
    visibility_labels_for_principal,
)


def test_anonymous_development_principal_only_sees_public_sources() -> None:
    principal = source_principal_for_session(Settings(app_env="development"), None)

    assert principal == SourcePrincipal(
        username=None,
        role="anonymous",
        cohorts=(),
        extra_visibility_labels=(),
    )
    assert visibility_labels_for_principal(principal) == ("public",)


def test_platform_principal_gets_public_role_user_and_cohort_labels() -> None:
    settings = Settings(platform_cohorts="spring-2026, alumni")
    session = PlatformSession(
        username="student",
        role="platform",
        csrf_token="csrf",
        expires_at=123,
    )

    principal = source_principal_for_session(settings, session)

    assert principal == SourcePrincipal(
        username="student",
        role="platform",
        cohorts=("spring-2026", "alumni"),
        extra_visibility_labels=(),
    )
    assert visibility_labels_for_principal(principal) == (
        "public",
        "role:platform",
        "user:student",
        "cohort:spring-2026",
        "cohort:alumni",
    )


def test_platform_principal_includes_explicit_extra_visibility_labels() -> None:
    settings = Settings(platform_extra_visibility_labels="staff, beta")
    session = PlatformSession(
        username="student",
        role="platform",
        csrf_token="csrf",
        expires_at=123,
    )

    principal = source_principal_for_session(settings, session)

    assert visibility_labels_for_principal(principal) == (
        "public",
        "role:platform",
        "user:student",
        "staff",
        "beta",
    )


def test_source_visibility_requires_a_matching_label() -> None:
    principal = SourcePrincipal(
        username="student",
        role="platform",
        cohorts=("spring-2026",),
        extra_visibility_labels=(),
    )

    assert source_is_visible(["public"], principal) is True
    assert source_is_visible(["cohort:spring-2026"], principal) is True
    assert source_is_visible(["cohort:fall-2026"], principal) is False
    assert source_is_visible(["staff"], principal) is False
