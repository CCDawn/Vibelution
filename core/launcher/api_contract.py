"""Shared Launcher API payload and error contracts."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from pydantic import BaseModel, Field


class WorkbenchWindowModePayload(BaseModel):
    mode: str
    baseHash: str = ""


class LauncherStartupSettingsPayload(BaseModel):
    launcher: dict = Field(default_factory=dict)
    runtime: dict = Field(default_factory=dict)
    workbench: dict = Field(default_factory=dict)
    interface: dict = Field(default_factory=dict)
    baseHash: str = ""


class DeveloperModePayload(BaseModel):
    enabled: bool
    baseHash: str = ""


class DeveloperCleanupPreviewPayload(BaseModel):
    action: str


class DeveloperCleanupApplyPayload(BaseModel):
    action: str
    planId: str
    planHash: str
    confirm: bool = False


class LauncherMaintenancePreviewPayload(BaseModel):
    profileId: str = "custom"
    itemIds: list[str] = Field(default_factory=list)


class LauncherMaintenanceApplyPayload(BaseModel):
    planId: str
    planHash: str
    profileId: str
    confirm: bool = False


class LifecycleIntentPayload(BaseModel):
    action: str
    reason: str = ""
    idempotencyKey: str


class DesktopActionClaimPayload(BaseModel):
    desktopSessionId: str
    leaseSeconds: int = 30


class DesktopActionResultPayload(BaseModel):
    desktopSessionId: str
    result: dict = Field(default_factory=dict)


class DesktopSessionPayload(BaseModel):
    desktopSessionId: str
    provider: str = "electron"
    workspaceRoot: str = ""
    capabilities: list[str] = Field(default_factory=list)


class DesktopSessionWindowPayload(BaseModel):
    revision: int = 0
    provider: str = "electron"
    open: bool = False
    focused: bool = False
    windowId: int = 0
    rendererProcessId: int = 0
    url: str = ""


class LauncherRuntimeSceneEventPayload(BaseModel):
    eventCode: str
    message: str = ""
    fields: dict = Field(default_factory=dict)
    level: str = "info"
    outcome: str = "observed"
    occurredAt: str = ""


def launcher_error_detail(code: str, exc: Exception | str, **extra: Any) -> dict[str, Any]:
    detail: dict[str, Any] = {
        "code": str(code or "").strip(),
        "message": str(exc),
    }
    detail.update(extra)
    return detail


def launcher_http_error(status_code: int, code: str, exc: Exception | str, **extra: Any) -> HTTPException:
    return HTTPException(status_code=status_code, detail=launcher_error_detail(code, exc, **extra))
