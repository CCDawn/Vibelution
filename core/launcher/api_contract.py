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

    Known top-level fields remain explicit for OpenAPI and route consumers,
    while forward-compatible tray/control-plane extras pass through. Routes
    use response_model_exclude_unset=True so defaults are never injected.
    """

    model_config = ConfigDict(extra="allow")


class LauncherStatusResponse(LauncherJsonResponse):
    launcher: dict[str, Any] = Field(default_factory=dict)
    projectBundle: dict[str, Any] = Field(default_factory=dict)
    controlPlaneEvidence: dict[str, Any] = Field(default_factory=dict)
    guardianAdapter: dict[str, Any] = Field(default_factory=dict)
    runtimeManager: dict[str, Any] = Field(default_factory=dict)
    lifecycleProof: dict[str, Any] = Field(default_factory=dict)
    settings: dict[str, Any] = Field(default_factory=dict)
    overallState: str = ""
    observedState: str = ""
    phase: str = ""
    lifecycleConsistency: str = ""
    failureMessage: str = ""
    lastErrorMessage: str = ""
    lastErrorScope: str = ""
    lastErrorAt: str = ""
    stateVersion: str = ""


class LauncherFreshnessResponse(LauncherJsonResponse):
    schemaVersion: int = 1
    current: bool | None = None
    label: str = ""
    runningCommit: str = ""
    runningShort: str = ""
    runningBranch: str = ""
    headCommit: str = ""
    headShort: str = ""
    headBranch: str = ""
    startedAt: str = ""


class LauncherBranchInstanceListResponse(LauncherJsonResponse):
    schemaVersion: int = 1
    integrationRoot: str = ""
    branchPool: str = ""
    currentId: str = ""
    currentShortName: str = ""
    currentWorkbenchTitle: str = ""
    currentLauncherTitle: str = ""
    items: list[dict[str, Any]] = Field(default_factory=list)


class WorkbenchWindowModeSettingResponse(LauncherJsonResponse):
    mode: str = ""
    effectiveMode: str = ""
    envOverride: str = ""
    configPath: str = ""
    configHash: str = ""
    restartRequired: bool = True
    options: list[dict[str, Any]] = Field(default_factory=list)


class WorkbenchWindowModeUpdateResponse(LauncherJsonResponse):
    ok: bool = False
    mode: str = ""
    setting: WorkbenchWindowModeSettingResponse = Field(
        default_factory=WorkbenchWindowModeSettingResponse
    )
    message: str = ""


class LauncherStartupSettingsResponse(LauncherJsonResponse):
    launcher: dict[str, Any] = Field(default_factory=dict)
    runtime: dict[str, Any] = Field(default_factory=dict)
    workbench: dict[str, Any] = Field(default_factory=dict)
    interface: dict[str, Any] = Field(default_factory=dict)
    configPath: str = ""
    configHash: str = ""
    restartRequired: bool = True


class LauncherStartupSettingsUpdateResponse(LauncherJsonResponse):
    ok: bool = False
    setting: LauncherStartupSettingsResponse = Field(
        default_factory=LauncherStartupSettingsResponse
    )
    message: str = ""


class LauncherDeveloperModeSettingResponse(LauncherJsonResponse):
    schemaVersion: int = 1
    enabled: bool = False
    defaulted: bool = False
    updatedAt: str = ""
    updatedBy: str = ""
    controller: str = ""
    scope: str = ""
    mode: str = ""
    configPath: str = ""
    configHash: str = ""
    sandbox: dict[str, Any] = Field(default_factory=dict)
    policy: dict[str, Any] = Field(default_factory=dict)


class LauncherDeveloperModeUpdateResponse(LauncherJsonResponse):
    ok: bool = False
    setting: LauncherDeveloperModeSettingResponse = Field(
        default_factory=LauncherDeveloperModeSettingResponse
    )
    message: str = ""


class LauncherDeveloperNoiseOverviewResponse(LauncherJsonResponse):
    schemaVersion: int = 1
    developerMode: LauncherDeveloperModeSettingResponse = Field(
        default_factory=LauncherDeveloperModeSettingResponse
    )
    projectRoot: str = ""
    items: list[dict[str, Any]] = Field(default_factory=list)
    updatedAt: str = ""


class LauncherAcceptedCommandResponse(LauncherJsonResponse):
    accepted: bool = False
    commandId: str = ""
    message: str = ""
    instanceId: str = ""
    operation: str = ""


class LauncherCleanupPlanResponse(LauncherJsonResponse):
    planId: str = ""
    action: str = ""
    ok: bool = False


class LauncherLifecycleIntentResponse(LauncherJsonResponse):
    intentId: str = ""
    status: str = ""
    action: str = ""


class LauncherWorkbenchCloseResponse(LauncherJsonResponse):
    closeId: str = ""
    phase: str = ""
    desktopSessionId: str = ""


class LauncherDesktopActionResponse(LauncherJsonResponse):
    actionId: str = ""
    desktopSessionId: str = ""


class LauncherDesktopSessionResponse(LauncherJsonResponse):
    desktopSessionId: str = ""
    revision: int = 0
    status: str = ""


class LauncherRuntimeSceneEventResponse(LauncherJsonResponse):
    accepted: bool = False
    runtimeSceneId: str = ""


def launcher_error_detail(code: str, exc: Exception | str, **extra: Any) -> dict[str, Any]:
    detail: dict[str, Any] = {
        "code": str(code or "").strip(),
        "message": str(exc),
    }
    detail.update(extra)
    return detail


def launcher_http_error(status_code: int, code: str, exc: Exception | str, **extra: Any) -> HTTPException:
    return HTTPException(status_code=status_code, detail=launcher_error_detail(code, exc, **extra))
