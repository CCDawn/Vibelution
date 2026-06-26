"""Launcher lifecycle routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from core.launcher import service as launcher_service
from core.web.services import runtime_scene_service


router = APIRouter(tags=["launcher"])


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


class LauncherRuntimeSceneEventPayload(BaseModel):
    eventCode: str
    message: str = ""
    fields: dict = Field(default_factory=dict)
    level: str = "info"
    outcome: str = "observed"
    occurredAt: str = ""


@router.get("/launcher/status")
def launcher_status() -> dict:
    return launcher_service.get_launcher_status()


@router.get("/launcher/settings/workbench-window")
def launcher_workbench_window_setting() -> dict:
    return launcher_service.get_workbench_window_mode_setting()


@router.get("/launcher/settings/startup")
def launcher_startup_settings() -> dict:
    return launcher_service.get_launcher_startup_settings()


@router.put("/launcher/settings/startup")
def launcher_update_startup_settings(payload: LauncherStartupSettingsPayload) -> dict:
    try:
        return launcher_service.update_launcher_startup_settings(payload.model_dump())
    except launcher_service.LauncherSettingsConflict as exc:
        raise HTTPException(status_code=409, detail={"code": "launcher_startup_settings_conflict", "message": str(exc)}) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"code": "invalid_launcher_startup_settings", "message": str(exc)}) from exc


@router.put("/launcher/settings/workbench-window")
def launcher_update_workbench_window_setting(payload: WorkbenchWindowModePayload) -> dict:
    try:
        return launcher_service.update_workbench_window_mode(payload.mode, base_hash=payload.baseHash)
    except launcher_service.LauncherSettingsConflict as exc:
        raise HTTPException(status_code=409, detail={"code": "launcher_workbench_window_mode_conflict", "message": str(exc)}) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"code": "invalid_workbench_window_mode", "message": str(exc)}) from exc


@router.get("/launcher/developer-mode")
def launcher_developer_mode_setting() -> dict:
    return launcher_service.get_launcher_developer_mode_setting()


@router.put("/launcher/developer-mode")
def launcher_update_developer_mode(payload: DeveloperModePayload) -> dict:
    try:
        return launcher_service.update_launcher_developer_mode(payload.enabled, base_hash=payload.baseHash)
    except launcher_service.DeveloperCleanupPlanError as exc:
        raise HTTPException(status_code=409, detail={"code": exc.code, "message": exc.message, **exc.detail}) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"code": "invalid_developer_mode", "message": str(exc)}) from exc


@router.get("/launcher/developer-mode/noise-overview")
def launcher_developer_mode_noise_overview() -> dict:
    return launcher_service.get_launcher_developer_noise_overview()


@router.post("/launcher/developer-mode/cleanup/preview")
def launcher_preview_developer_cleanup(payload: DeveloperCleanupPreviewPayload) -> dict:
    try:
        return launcher_service.preview_launcher_developer_cleanup(payload.action)
    except launcher_service.DeveloperModeDisabled as exc:
        raise HTTPException(status_code=409, detail={"code": "mode_disabled", "message": str(exc)}) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"code": "invalid_developer_cleanup_action", "message": str(exc)}) from exc


@router.post("/launcher/developer-mode/cleanup/apply")
def launcher_apply_developer_cleanup(payload: DeveloperCleanupApplyPayload) -> dict:
    try:
        return launcher_service.apply_launcher_developer_cleanup(payload.model_dump())
    except launcher_service.DeveloperModeDisabled as exc:
        raise HTTPException(status_code=409, detail={"code": "mode_disabled", "message": str(exc)}) from exc
    except launcher_service.DeveloperCleanupPlanError as exc:
        raise HTTPException(status_code=409, detail={"code": exc.code, "message": exc.message, **exc.detail}) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"code": "invalid_developer_cleanup_apply", "message": str(exc)}) from exc


@router.post("/launcher/start", status_code=202)
def launcher_start() -> dict:
    return launcher_service.request_launcher_start()


@router.post("/launcher/stop", status_code=202)
def launcher_stop(request: Request) -> dict:
    try:
        return launcher_service.request_launcher_stop(_request_audit(request, operation="stop"))
    except launcher_service.LauncherActiveWorkBlocked as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "active_work_stop_blocked",
                "message": exc.message,
                "activeWorkRuns": exc.active_work_runs,
            },
        ) from exc


@router.post("/launcher/force-stop", status_code=202)
def launcher_force_stop(request: Request) -> dict:
    return launcher_service.request_launcher_force_stop(_request_audit(request, operation="force-stop"))


@router.post("/launcher/restart", status_code=202)
def launcher_restart() -> dict:
    try:
        return launcher_service.request_launcher_restart()
    except launcher_service.LauncherActiveWorkBlocked as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "active_work_restart_blocked",
                "message": exc.message,
                "activeWorkRuns": exc.active_work_runs,
            },
        ) from exc


@router.post("/launcher/lifecycle-intents", status_code=202)
def launcher_submit_lifecycle_intent(payload: LifecycleIntentPayload) -> dict:
    try:
        return launcher_service.submit_lifecycle_intent(payload.model_dump())
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "invalid_lifecycle_intent", "message": str(exc)},
        ) from exc


@router.post("/launcher/desktop-actions/claim")
def launcher_claim_desktop_action(payload: DesktopActionClaimPayload) -> dict:
    return launcher_service.claim_desktop_action(payload.desktopSessionId, lease_seconds=payload.leaseSeconds)


@router.post("/launcher/desktop-actions/{action_id}/ack", status_code=202)
def launcher_ack_desktop_action(action_id: str, payload: DesktopActionResultPayload) -> dict:
    return launcher_service.ack_desktop_action(action_id, payload.desktopSessionId, payload.result)


@router.post("/launcher/desktop-actions/{action_id}/fail", status_code=202)
def launcher_fail_desktop_action(action_id: str, payload: DesktopActionResultPayload) -> dict:
    return launcher_service.fail_desktop_action(action_id, payload.desktopSessionId, payload.result)


@router.post("/launcher/runtime-scene/events", status_code=202)
def launcher_runtime_scene_event(payload: LauncherRuntimeSceneEventPayload) -> dict:
    try:
        return runtime_scene_service.record_electron_supervisor_event(
            payload.eventCode,
            message=payload.message,
            fields=payload.fields,
            level=payload.level,
            outcome=payload.outcome,
            occurred_at=payload.occurredAt,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "invalid_electron_runtime_scene_event", "message": str(exc)},
        ) from exc


def _request_audit(request: Request, *, operation: str) -> launcher_service.LauncherRequestAudit:
    client = request.client.host if request.client else ""
    return launcher_service.launcher_request_audit(
        operation=operation,
        trigger=request.headers.get("X-Vibelution-Launcher-Trigger", ""),
        endpoint=request.url.path,
        method=request.method,
        client_host=client,
        referer=request.headers.get("referer", ""),
        origin=request.headers.get("origin", ""),
        user_agent=request.headers.get("user-agent", ""),
    )


@router.post("/launcher/supervisor/reattach", status_code=202)
def launcher_supervisor_reattach() -> dict:
    return launcher_service.request_launcher_supervisor_reattach()
