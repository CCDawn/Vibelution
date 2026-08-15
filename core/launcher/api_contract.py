"""Shared Launcher API payload and error contracts."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field


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


class BranchInstanceLifecyclePayload(BaseModel):
    instanceId: str


class BranchInstanceCleanupPayload(BaseModel):
    instanceIds: list[str] = Field(default_factory=list)
    confirm: bool = False


class WorkbenchCloseTransactionPayload(BaseModel):
    desktopSessionId: str
    idempotencyKey: str
    mode: str = "normal"
    reason: str = ""
    confirmationCloseId: str = ""


class WorkbenchCloseWindowClosedPayload(BaseModel):
    desktopSessionId: str
    desktopSessionRevision: int = 0


class DesktopActionClaimPayload(BaseModel):
    desktopSessionId: str
    leaseSeconds: int = 30
    waitMs: int = Field(default=0, ge=0, le=2000)


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


class DesktopSessionRevisionPayload(BaseModel):
    revision: int = 0


class LauncherRuntimeSceneEventPayload(BaseModel):
    eventCode: str
    message: str = ""
    fields: dict = Field(default_factory=dict)
    level: str = "info"
    outcome: str = "observed"
    occurredAt: str = ""


class LauncherJsonResponse(BaseModel):
    """Evolving Launcher JSON envelopes.

    Status and settings shapes still grow tray/control-plane extras. Keep
    declared fields empty so FastAPI cannot inject defaults or drop unknown
    nested keys. Routes must use response_model_exclude_unset=True.
    """

    model_config = ConfigDict(extra="allow")


class LauncherStatusResponse(LauncherJsonResponse):
    pass


class LauncherFreshnessResponse(LauncherJsonResponse):
    pass


class LauncherBranchInstanceListResponse(LauncherJsonResponse):
    pass


class WorkbenchWindowModeSettingResponse(LauncherJsonResponse):
    pass


class WorkbenchWindowModeUpdateResponse(LauncherJsonResponse):
    pass


class LauncherStartupSettingsResponse(LauncherJsonResponse):
    pass


class LauncherStartupSettingsUpdateResponse(LauncherJsonResponse):
    pass


class LauncherDeveloperModeSettingResponse(LauncherJsonResponse):
    pass


class LauncherDeveloperModeUpdateResponse(LauncherJsonResponse):
    pass


class LauncherDeveloperNoiseOverviewResponse(LauncherJsonResponse):
    pass


def launcher_error_detail(code: str, exc: Exception | str, **extra: Any) -> dict[str, Any]:
    detail: dict[str, Any] = {
        "code": str(code or "").strip(),
        "message": str(exc),
    }
    detail.update(extra)
    return detail


def launcher_http_error(status_code: int, code: str, exc: Exception | str, **extra: Any) -> HTTPException:
    return HTTPException(status_code=status_code, detail=launcher_error_detail(code, exc, **extra))
