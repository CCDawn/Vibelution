"""Retired Web reset routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field


router = APIRouter(tags=["reset"])
RESET_MIGRATED_DETAIL = {
    "code": "reset_migrated_to_launcher",
    "message": "Reset 清理与恢复初始化已迁移到 Launcher 维护中心；Web backend 不再执行清理。",
    "launcherPath": "/launcher",
}


class ResetSelectionPayload(BaseModel):
    itemIds: list[str] = Field(default_factory=list)


class ResetExecutePayload(ResetSelectionPayload):
    confirmed: bool = False


@router.get("/reset/summary")
def reset_summary() -> dict:
    raise HTTPException(status_code=410, detail=RESET_MIGRATED_DETAIL)


@router.post("/reset/preview")
def reset_preview(payload: ResetSelectionPayload) -> dict:
    raise HTTPException(status_code=410, detail=RESET_MIGRATED_DETAIL)


@router.post("/reset/execute")
def reset_execute(payload: ResetExecutePayload) -> dict:
    raise HTTPException(status_code=410, detail=RESET_MIGRATED_DETAIL)
