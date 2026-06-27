"""FastAPI app for the standalone Vibelution Launcher control plane."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from core.version import get_product_version
from core.web.control import CONTROL_TOKEN_HEADER, control_token_payload, trusted_control_origins, validate_control_request
from core.web.services import runtime_scene_service
from . import service as launcher_service
from .api_contract import (
    DesktopActionClaimPayload,
    DesktopActionResultPayload,
    DesktopSessionPayload,
    DesktopSessionWindowPayload,
    DeveloperCleanupApplyPayload,
    DeveloperCleanupPreviewPayload,
    DeveloperModePayload,
    LauncherMaintenanceApplyPayload,
    LauncherMaintenancePreviewPayload,
    LauncherRuntimeSceneEventPayload,
    LauncherStartupSettingsPayload,
    LifecycleIntentPayload,
    WorkbenchWindowModePayload,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
WEB_DIST = PROJECT_ROOT / "web" / "dist"
WEB_INDEX = WEB_DIST / "index.html"
INDEX_CACHE_HEADERS = {
    "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
    "Pragma": "no-cache",
    "Expires": "0",
}

router = APIRouter()


@router.get("/api/health")
def launcher_health() -> dict:
    return {"status": "ok", "service": "launcher"}


@router.get("/api/control-token")
def launcher_control_token() -> dict:
    return control_token_payload()


@router.get("/api/launcher/status")
@router.get("/api/project/status")
def launcher_status() -> dict:
    return launcher_service.get_launcher_status()


@router.get("/api/launcher/settings/workbench-window")
def workbench_window_setting() -> dict:
    return launcher_service.get_workbench_window_mode_setting()


@router.get("/api/launcher/settings/startup")
def launcher_startup_settings() -> dict:
    return launcher_service.get_launcher_startup_settings()


@router.put("/api/launcher/settings/startup")
def update_launcher_startup_settings(payload: LauncherStartupSettingsPayload) -> dict:
    try:
        return launcher_service.update_launcher_startup_settings(payload.model_dump())
    except launcher_service.LauncherSettingsConflict as exc:
        raise HTTPException(status_code=409, detail={"code": "launcher_startup_settings_conflict", "message": str(exc)}) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"code": "invalid_launcher_startup_settings", "message": str(exc)}) from exc


@router.put("/api/launcher/settings/workbench-window")
def update_workbench_window_setting(payload: WorkbenchWindowModePayload) -> dict:
    try:
        return launcher_service.update_workbench_window_mode(payload.mode, base_hash=payload.baseHash)
    except launcher_service.LauncherSettingsConflict as exc:
        raise HTTPException(status_code=409, detail={"code": "launcher_workbench_window_mode_conflict", "message": str(exc)}) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"code": "invalid_workbench_window_mode", "message": str(exc)}) from exc


@router.get("/api/launcher/developer-mode")
def developer_mode_setting() -> dict:
    return launcher_service.get_launcher_developer_mode_setting()


@router.put("/api/launcher/developer-mode")
def update_developer_mode(payload: DeveloperModePayload) -> dict:
    try:
        return launcher_service.update_launcher_developer_mode(payload.enabled, base_hash=payload.baseHash)
    except launcher_service.DeveloperCleanupPlanError as exc:
        raise HTTPException(status_code=409, detail={"code": exc.code, "message": exc.message, **exc.detail}) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"code": "invalid_developer_mode", "message": str(exc)}) from exc


@router.get("/api/launcher/developer-mode/noise-overview")
def developer_mode_noise_overview() -> dict:
    return launcher_service.get_launcher_developer_noise_overview()


@router.post("/api/launcher/developer-mode/reset-sandbox")
def reset_developer_sandbox() -> dict:
    try:
        return launcher_service.reset_launcher_developer_sandbox()
    except launcher_service.DeveloperModeDisabled as exc:
        raise HTTPException(status_code=409, detail={"code": "mode_disabled", "message": str(exc)}) from exc


@router.post("/api/launcher/developer-mode/cleanup/preview")
def preview_developer_cleanup(payload: DeveloperCleanupPreviewPayload) -> dict:
    try:
        return launcher_service.preview_launcher_developer_cleanup(payload.action)
    except launcher_service.DeveloperModeDisabled as exc:
        raise HTTPException(status_code=409, detail={"code": "mode_disabled", "message": str(exc)}) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"code": "invalid_developer_cleanup_action", "message": str(exc)}) from exc


@router.post("/api/launcher/developer-mode/cleanup/apply")
def apply_developer_cleanup(payload: DeveloperCleanupApplyPayload) -> dict:
    try:
        return launcher_service.apply_launcher_developer_cleanup(payload.model_dump())
    except launcher_service.DeveloperModeDisabled as exc:
        raise HTTPException(status_code=409, detail={"code": "mode_disabled", "message": str(exc)}) from exc
    except launcher_service.DeveloperCleanupPlanError as exc:
        raise HTTPException(status_code=409, detail={"code": exc.code, "message": exc.message, **exc.detail}) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"code": "invalid_developer_cleanup_apply", "message": str(exc)}) from exc


@router.get("/api/launcher/maintenance/reset/summary")
def launcher_maintenance_reset_summary() -> dict:
    return launcher_service.get_launcher_maintenance_summary()


@router.post("/api/launcher/maintenance/reset/preview")
def preview_launcher_maintenance_reset(payload: LauncherMaintenancePreviewPayload) -> dict:
    try:
        return launcher_service.preview_launcher_maintenance_plan(payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"code": "invalid_launcher_maintenance_preview", "message": str(exc)}) from exc


@router.post("/api/launcher/maintenance/reset/apply")
def apply_launcher_maintenance_reset(payload: LauncherMaintenanceApplyPayload) -> dict:
    try:
        return launcher_service.apply_launcher_maintenance_plan(payload.model_dump())
    except launcher_service.LauncherMaintenancePlanError as exc:
        status_code = 409 if exc.code != "invalid_plan_id" else 400
        raise HTTPException(status_code=status_code, detail={"code": exc.code, "message": exc.message, **exc.detail}) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"code": "invalid_launcher_maintenance_apply", "message": str(exc)}) from exc


@router.post("/api/launcher/start", status_code=202)
@router.post("/api/project/start", status_code=202)
def project_start() -> dict:
    return launcher_service.request_launcher_start()


@router.post("/api/launcher/stop", status_code=202)
@router.post("/api/project/stop", status_code=202)
def project_stop(request: Request) -> dict:
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


@router.post("/api/launcher/force-stop", status_code=202)
@router.post("/api/project/force-stop", status_code=202)
def project_force_stop(request: Request) -> dict:
    return launcher_service.request_launcher_force_stop(_request_audit(request, operation="force-stop"))


@router.post("/api/launcher/restart", status_code=202)
@router.post("/api/project/restart", status_code=202)
def project_restart() -> dict:
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


@router.post("/api/launcher/lifecycle-intents", status_code=202)
def launcher_submit_lifecycle_intent(request: Request, payload: LifecycleIntentPayload) -> dict:
    _ensure_control_request(request)
    try:
        return launcher_service.submit_lifecycle_intent(payload.model_dump())
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "invalid_lifecycle_intent", "message": str(exc)},
        ) from exc


@router.get("/api/launcher/lifecycle-intents/{intent_id}")
def launcher_get_lifecycle_intent(request: Request, intent_id: str) -> dict:
    _ensure_control_request(request)
    result = launcher_service.get_lifecycle_intent(intent_id)
    if not result:
        raise HTTPException(status_code=404, detail={"code": "lifecycle_intent_not_found"})
    return result


@router.post("/api/launcher/desktop-actions/claim")
def launcher_claim_desktop_action(request: Request, payload: DesktopActionClaimPayload) -> dict:
    _ensure_control_request(request)
    return launcher_service.claim_desktop_action(payload.desktopSessionId, lease_seconds=payload.leaseSeconds)


@router.post("/api/launcher/desktop-actions/{action_id}/ack", status_code=202)
def launcher_ack_desktop_action(request: Request, action_id: str, payload: DesktopActionResultPayload) -> dict:
    _ensure_control_request(request)
    return launcher_service.ack_desktop_action(action_id, payload.desktopSessionId, payload.result)


@router.post("/api/launcher/desktop-actions/{action_id}/fail", status_code=202)
def launcher_fail_desktop_action(request: Request, action_id: str, payload: DesktopActionResultPayload) -> dict:
    _ensure_control_request(request)
    return launcher_service.fail_desktop_action(action_id, payload.desktopSessionId, payload.result)


@router.post("/api/launcher/desktop-sessions", status_code=201)
def launcher_register_desktop_session(request: Request, payload: DesktopSessionPayload) -> dict:
    _ensure_control_request(request)
    return launcher_service.register_desktop_session(payload.model_dump())


@router.put("/api/launcher/desktop-sessions/{desktop_session_id}/windows/{role}")
def launcher_update_desktop_session_window(
    request: Request,
    desktop_session_id: str,
    role: str,
    payload: DesktopSessionWindowPayload,
) -> dict:
    _ensure_control_request(request)
    try:
        return launcher_service.update_desktop_session_window(desktop_session_id, role, payload.model_dump())
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "invalid_desktop_session_window", "message": str(exc)},
        ) from exc


@router.post("/api/launcher/desktop-sessions/{desktop_session_id}/heartbeat")
def launcher_heartbeat_desktop_session(request: Request, desktop_session_id: str) -> dict:
    _ensure_control_request(request)
    return launcher_service.heartbeat_desktop_session(desktop_session_id)


@router.delete("/api/launcher/desktop-sessions/{desktop_session_id}")
def launcher_close_desktop_session(request: Request, desktop_session_id: str) -> dict:
    _ensure_control_request(request)
    return launcher_service.close_desktop_session(desktop_session_id)


@router.post("/api/launcher/runtime-scene/events", status_code=202)
def launcher_runtime_scene_event(request: Request, payload: LauncherRuntimeSceneEventPayload) -> dict:
    _ensure_control_request(request)
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


def _ensure_control_request(request: Request) -> None:
    error = validate_control_request(request)
    if error is not None:
        raise HTTPException(status_code=error.status_code, detail=error.detail)


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


def create_launcher_app() -> FastAPI:
    app = FastAPI(
        title="Vibelution Launcher",
        version=get_product_version(),
        description="Standalone lifecycle control plane for the Vibelution project bundle.",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=sorted(trusted_control_origins()),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*", CONTROL_TOKEN_HEADER],
    )
    app.include_router(router)

    @app.get("/launcher", include_in_schema=False)
    @app.get("/", include_in_schema=False)
    def launcher_index():
        if WEB_INDEX.is_file():
            return FileResponse(WEB_INDEX, headers=INDEX_CACHE_HEADERS)
        return JSONResponse(
            {
                "message": "Launcher frontend has not been built yet.",
                "next": "Build web/dist, then reopen the Launcher.",
            },
            status_code=503,
        )

    @app.get("/{full_path:path}", include_in_schema=False)
    def launcher_spa_fallback(full_path: str):
        if str(full_path or "").startswith("api/"):
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        if WEB_INDEX.is_file():
            candidate = (WEB_DIST / full_path).resolve()
            dist_root = WEB_DIST.resolve()
            if candidate.exists() and candidate.is_file() and (candidate == dist_root or dist_root in candidate.parents):
                return FileResponse(candidate)
            return FileResponse(WEB_INDEX, headers=INDEX_CACHE_HEADERS)
        return JSONResponse(
            {
                "message": "Launcher frontend has not been built yet.",
                "next": "Build web/dist, then reopen the Launcher.",
            },
            status_code=503,
        )

    return app


app = create_launcher_app()
