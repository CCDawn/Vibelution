"""Retired Web reset routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from core.web.routes.reset_models import (
    ResetExecutePayload,
    ResetMigratedResponse,
    ResetSelectionPayload,
)


router = APIRouter(tags=["reset"])
RESET_MIGRATED_DETAIL = {
    "code": "reset_migrated_to_launcher",
    "message": "Reset 清理与恢复初始化已迁移到 Launcher 维护中心；Web backend 不再执行清理。",
    "launcherPath": "/launcher",
}


@router.get(
    "/reset/summary",
    response_model=ResetMigratedResponse,
    response_model_exclude_unset=True,
)
def reset_summary() -> dict:
    raise HTTPException(status_code=410, detail=RESET_MIGRATED_DETAIL)


@router.post(
    "/reset/preview",
    response_model=ResetMigratedResponse,
    response_model_exclude_unset=True,
)
def reset_preview(payload: ResetSelectionPayload) -> dict:
    raise HTTPException(status_code=410, detail=RESET_MIGRATED_DETAIL)


@router.post(
    "/reset/execute",
    response_model=ResetMigratedResponse,
    response_model_exclude_unset=True,
)
def reset_execute(payload: ResetExecutePayload) -> dict:
    raise HTTPException(status_code=410, detail=RESET_MIGRATED_DETAIL)
