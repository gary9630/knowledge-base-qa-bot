from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.orm import Session

from app.api.dependencies import (
    get_app_settings,
    get_request_db_session,
    get_runtime_overrides,
    require_admin_access,
    set_runtime_overrides,
)
from app.runtime_settings import (
    RUNTIME_SETTING_KEYS,
    apply_runtime_overrides,
    runtime_setting_defaults,
    save_runtime_overrides,
)

router = APIRouter(dependencies=[Depends(require_admin_access)])


class RuntimeSettingsUpdateRequest(BaseModel):
    overrides: dict[str, object] = Field(default_factory=dict)


class RuntimeSettingsResponse(BaseModel):
    keys: list[str]
    defaults: dict[str, object | None]
    overrides: dict[str, object | None]
    effective: dict[str, object | None]


@router.get("/admin/settings", response_model=RuntimeSettingsResponse)
def get_runtime_settings(request: Request) -> RuntimeSettingsResponse:
    return _runtime_settings_response(request, get_runtime_overrides(request))


@router.put("/admin/settings", response_model=RuntimeSettingsResponse)
def update_runtime_settings(
    payload: RuntimeSettingsUpdateRequest,
    request: Request,
    session: Annotated[Session, Depends(get_request_db_session)],
) -> RuntimeSettingsResponse:
    unknown_keys = sorted(set(payload.overrides) - set(RUNTIME_SETTING_KEYS))
    if unknown_keys:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown runtime settings: {', '.join(unknown_keys)}",
        )

    try:
        saved = save_runtime_overrides(session, payload.overrides)
    except ValidationError as error:
        raise HTTPException(status_code=422, detail=_validation_detail(error)) from error

    set_runtime_overrides(request, saved)
    return _runtime_settings_response(request, saved)


def _runtime_settings_response(
    request: Request,
    overrides: dict[str, object],
) -> RuntimeSettingsResponse:
    settings = get_app_settings(request)
    effective = apply_runtime_overrides(settings, overrides)
    return RuntimeSettingsResponse(
        keys=list(RUNTIME_SETTING_KEYS),
        defaults=runtime_setting_defaults(settings),
        overrides={key: overrides.get(key) for key in RUNTIME_SETTING_KEYS},
        effective=runtime_setting_defaults(effective),
    )


def _validation_detail(error: ValidationError) -> str:
    problems = [
        f"{'.'.join(str(part) for part in item['loc'])}: {item['msg']}"
        for item in error.errors()
    ]
    return "; ".join(problems) or "Invalid runtime settings."
