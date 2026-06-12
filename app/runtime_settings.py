"""Admin-tunable runtime overrides.

A small allowlist of provider/budget settings can be changed from the admin
console and applied immediately — no .env edit or service restart. Overrides
are persisted in the ``runtime_settings`` table and layered on top of the
env-derived :class:`~app.core.config.Settings` at request time.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models.tables import RuntimeSetting


class RuntimeOverrides(BaseModel):
    """Validated shape of the admin-tunable settings. None means "use the env default"."""

    model_config = ConfigDict(extra="forbid")

    openai_chat_model: str | None = Field(default=None, min_length=1)
    openai_chat_model_hard: str | None = Field(default=None, min_length=1)
    openai_router_model: str | None = Field(default=None, min_length=1)
    openai_chat_max_completion_tokens: int | None = Field(default=None, ge=1, le=64_000)
    openai_chat_temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    provider_budget_enabled: bool | None = None
    provider_budget_daily_token_limit: int | None = Field(default=None, ge=0)
    provider_budget_daily_call_limit: int | None = Field(default=None, ge=0)
    provider_budget_block_on_exceeded: bool | None = None


RUNTIME_SETTING_KEYS: tuple[str, ...] = tuple(RuntimeOverrides.model_fields)


def load_runtime_overrides(session: Session) -> dict[str, object]:
    """Read persisted overrides, dropping unknown keys and invalid values."""
    rows = session.scalars(select(RuntimeSetting)).all()
    raw = {row.key: row.value for row in rows if row.key in RUNTIME_SETTING_KEYS}
    return validate_runtime_overrides(raw)


def validate_runtime_overrides(raw: dict[str, Any]) -> dict[str, object]:
    """Return only the overrides that pass validation; raise on a fully invalid payload."""
    overrides = RuntimeOverrides(**raw)
    return {
        key: value
        for key, value in overrides.model_dump().items()
        if value is not None
    }


def safe_load_runtime_overrides(session: Session) -> dict[str, object]:
    """Like load_runtime_overrides, but tolerates rows that no longer validate."""
    rows = session.scalars(select(RuntimeSetting)).all()
    overrides: dict[str, object] = {}
    for row in rows:
        if row.key not in RUNTIME_SETTING_KEYS:
            continue
        try:
            validated = RuntimeOverrides(**{row.key: row.value})
        except ValidationError:
            continue
        value = getattr(validated, row.key)
        if value is not None:
            overrides[row.key] = value
    return overrides


def save_runtime_overrides(
    session: Session,
    overrides: dict[str, object],
) -> dict[str, object]:
    """Replace the persisted override set with the validated payload and commit."""
    validated = validate_runtime_overrides(overrides)

    existing = {row.key: row for row in session.scalars(select(RuntimeSetting)).all()}
    for key in RUNTIME_SETTING_KEYS:
        if key in validated:
            row = existing.get(key)
            if row is None:
                session.add(RuntimeSetting(key=key, value=validated[key]))
            else:
                row.value = validated[key]
        elif key in existing:
            session.delete(existing[key])
    session.commit()
    return validated


def apply_runtime_overrides(settings: Settings, overrides: dict[str, object]) -> Settings:
    """Layer validated overrides on top of the env-derived settings."""
    clean = {
        key: value
        for key, value in overrides.items()
        if key in RUNTIME_SETTING_KEYS and value is not None
    }
    if not clean:
        return settings
    return settings.model_copy(update=clean)


def runtime_setting_defaults(settings: Settings) -> dict[str, object]:
    """The env/default values shown beside overrides in the admin console."""
    return {key: getattr(settings, key) for key in RUNTIME_SETTING_KEYS}
