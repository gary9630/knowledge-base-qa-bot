from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any, cast

from sqlalchemy import or_

from app.auth.sessions import PlatformSession
from app.core.config import Settings

PUBLIC_VISIBILITY_LABEL = "public"
ANONYMOUS_ROLE = "anonymous"


@dataclass(frozen=True)
class SourcePrincipal:
    username: str | None
    role: str
    cohorts: tuple[str, ...] = ()
    extra_visibility_labels: tuple[str, ...] = ()


def source_principal_for_session(
    settings: Settings,
    session: PlatformSession | None,
) -> SourcePrincipal:
    if session is None:
        return SourcePrincipal(
            username=None,
            role=ANONYMOUS_ROLE,
            cohorts=(),
            extra_visibility_labels=(),
        )

    return SourcePrincipal(
        username=session.username,
        role=session.role,
        cohorts=_parse_label_list(settings.platform_cohorts),
        extra_visibility_labels=_parse_label_list(settings.platform_extra_visibility_labels),
    )


def visibility_labels_for_principal(principal: SourcePrincipal) -> tuple[str, ...]:
    labels = [PUBLIC_VISIBILITY_LABEL]
    if principal.role != ANONYMOUS_ROLE:
        labels.append(f"role:{principal.role}")
    if principal.username:
        labels.append(f"user:{principal.username}")
    labels.extend(f"cohort:{cohort}" for cohort in principal.cohorts)
    labels.extend(principal.extra_visibility_labels)
    return _dedupe(labels)


def source_is_visible(
    source_visibility: Sequence[str],
    principal: SourcePrincipal,
) -> bool:
    source_labels = set(_dedupe(source_visibility) or (PUBLIC_VISIBILITY_LABEL,))
    allowed_labels = set(visibility_labels_for_principal(principal))
    return bool(source_labels & allowed_labels)


def source_visibility_filter(
    visibility_column: object,
    principal: SourcePrincipal,
) -> Any:
    labels = visibility_labels_for_principal(principal)
    filters = [
        cast(Any, visibility_column).contains([visibility_label])
        for visibility_label in labels
    ]
    return or_(*filters)


def _parse_label_list(value: str) -> tuple[str, ...]:
    normalized = (
        value.replace("[", " ")
        .replace("]", " ")
        .replace(",", " ")
        .replace("'", " ")
        .replace('"', " ")
    )
    return _dedupe(label.strip() for label in normalized.split() if label.strip())


def _dedupe(values: Iterable[object]) -> tuple[str, ...]:
    labels: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, str):
            continue
        label = value.strip()
        if not label or label in seen:
            continue
        labels.append(label)
        seen.add(label)
    return tuple(labels)
