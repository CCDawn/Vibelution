"""Launcher lifecycle routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from core.launcher.api_contract import (
    BranchInstanceCleanupPayload,
    BranchInstanceLifecyclePayload,
    DesktopActionClaimPayload,
    DesktopActionResultPayload,
    DesktopSessionPayload,
    DesktopSessionRevisionPayload,
    DesktopSessionWindowPayload,
    DeveloperCleanupApplyPayload,
    DeveloperCleanupPreviewPayload,
    DeveloperModePayload,
    LauncherBranchInstanceListResponse,
    LauncherDeveloperModeSettingResponse,
    LauncherDeveloperModeUpdateResponse,
    LauncherDeveloperNoiseOverviewResponse,
    LauncherFreshnessResponse,
    LauncherRuntimeSceneEventPayload,
    LauncherStartupSettingsPayload,
    LauncherStartupSettingsResponse,
    LauncherStartupSettingsUpdateResponse,
    LauncherStatusResponse,
    LifecycleIntentPayload,
    WorkbenchCloseTransactionPayload,
    WorkbenchCloseWindowClosedPayload,
    WorkbenchWindowModePayload,
    WorkbenchWindowModeSettingResponse,
    WorkbenchWindowModeUpdateResponse,
)
from core.launcher import service as launcher_service
from core.launcher.desktop_session_store import DesktopSessionClosed, DesktopSessionRevisionConflict
from core.launcher.lifecycle_intent_store import WorkbenchCloseTransactionConflict
from core.web.services import runtime_scene_service


router = APIRouter(tags=["launcher"])


def _desktop_session_mutation_response(operation, *, invalid_code: str = "invalid_desktop_session_mutation"):
    try:
        return operation()
    except DesktopSessionRevisionConflict as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "desktop_session_revision_conflict",
                "message": str(exc),
                "expectedDesktopSessionRevision": exc.expected_revision,
                "actualDesktopSessionRevision": exc.actual_revision,
            },
        ) from exc
    except DesktopSessionClosed as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "desktop_session_closed",
                "message": str(exc),
                "actualDesktopSessionRevision": exc.actual_revision,
            },
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": invalid_code, "message": str(exc)},
        ) from exc


def _workbench_close_transaction_response(operation):
    try:
        return operation()
    except WorkbenchCloseTransactionConflict as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": exc.code, "message": str(exc), **exc.details},
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "invalid_workbench_close_transaction", "message": str(exc)},
        ) from exc


@router.get(
    "/launcher/status",
    response_model=LauncherStatusResponse,
    response_model_exclude_unset=True,
)
def launcher_status() -> dict:
    return launcher_service.get_launcher_status()


@router.get(
    "/launcher/freshness",
    response_model=LauncherFreshnessResponse,
    response_model_exclude_unset=True,
)
def launcher_freshness() -> dict:
    return launcher_service.get_launcher_freshness()


@router.get(
    "/launcher/branch-instances",
    response_model=LauncherBranchInstanceListResponse,
    response_model_exclude_unset=True,
)
def launcher_branch_instances() -> dict:
    return launcher_service.list_launcher_branch_instances()



def _branch_instance_lifecycle_response(payload: BranchInstanceLifecyclePayload, operation: str, request: Request):
    try:
        return launcher_service.request_branch_instance_operation(
            payload.instanceId,
            operation,
            _request_audit(request, operation=operation),
        )
    except launcher_service.BranchInstanceLifecycleError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"code": exc.code, "message": exc.message},
        ) from exc
    except launcher_service.LauncherActiveWorkBlocked as exc:
        code = "active_work_restart_blocked" if operation == "restart" else "active_work_stop_blocked"
        raise HTTPException(
            status_code=409,
            detail={
                "code": code,
                "message": exc.message,
                "activeWorkRuns": exc.active_work_runs,
            },
        ) from exc


@router.post("/launcher/branch-instances/start", status_code=202)
def launcher_branch_instance_start(payload: BranchInstanceLifecyclePayload, request: Request) -> dict:
    return _branch_instance_lifecycle_response(payload, "start", request)


@router.post("/launcher/branch-instances/stop", status_code=202)
def launcher_branch_instance_stop(payload: BranchInstanceLifecyclePayload, request: Request) -> dict:
    return _branch_instance_lifecycle_response(payload, "stop", request)


@router.post("/launcher/branch-instances/force-stop", status_code=202)
def launcher_branch_instance_force_stop(payload: BranchInstanceLifecyclePayload, request: Request) -> dict:
    return _branch_instance_lifecycle_response(payload, "force-stop", request)


@router.post("/launcher/branch-instances/restart", status_code=202)
def launcher_branch_instance_restart(payload: BranchInstanceLifecyclePayload, request: Request) -> dict:
    return _branch_instance_lifecycle_response(payload, "restart", request)


@router.post("/launcher/branch-instances/cleanup")
def launcher_branch_instances_cleanup(payload: BranchInstanceCleanupPayload) -> dict:
    try:
        return launcher_service.cleanup_launcher_branch_instances(
            payload.instanceIds,
            confirm=payload.confirm,
        )
    except launcher_service.BranchInstanceCleanupError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"code": exc.code, "message": exc.message},
        ) from exc


@router.get(
    "/launcher/settings/workbench-window",
    response_model=WorkbenchWindowModeSettingResponse,
    response_model_exclude_unset=True,
)
def launcher_workbench_window_setting() -> dict:
    return launcher_service.get_workbench_window_mode_setting()


@router.get(
    "/launcher/settings/startup",
    response_model=LauncherStartupSettingsResponse,
    response_model_exclude_unset=True,
)
def launcher_startup_settings() -> dict:
    return launcher_service.get_launcher_startup_settings()


@router.put(
    "/launcher/settings/startup",
    response_model=LauncherStartupSettingsUpdateResponse,
    response_model_exclude_unset=True,
)
def launcher_update_startup_settings(payload: LauncherStartupSettingsPayload) -> dict:
    try:
        return launcher_service.update_launcher_startup_settings(payload.model_dump())
    except launcher_service.LauncherSettingsConflict as exc:
        raise HTTPException(status_code=409, detail={"code": "launcher_startup_settings_conflict", "message": str(exc)}) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"code": "invalid_launcher_startup_settings", "message": str(exc)}) from exc


@router.put(
    "/launcher/settings/workbench-window",
    response_model=WorkbenchWindowModeUpdateResponse,
    response_model_exclude_unset=True,
)
def launcher_update_workbench_window_setting(payload: WorkbenchWindowModePayload) -> dict:
    try:
        return launcher_service.update_workbench_window_mode(payload.mode, base_hash=payload.baseHash)
    except launcher_service.LauncherSettingsConflict as exc:
        raise HTTPException(status_code=409, detail={"code": "launcher_workbench_window_mode_conflict", "message": str(exc)}) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"code": "invalid_workbench_window_mode", "message": str(exc)}) from exc


@router.get(
    "/launcher/developer-mode",
    response_model=LauncherDeveloperModeSettingResponse,
    response_model_exclude_unset=True,
)
def launcher_developer_mode_setting() -> dict:
    return launcher_service.get_launcher_developer_mode_setting()


@router.put(
    "/launcher/developer-mode",
    response_model=LauncherDeveloperModeUpdateResponse,
    response_model_exclude_unset=True,
)
def launcher_update_developer_mode(payload: DeveloperModePayload) -> dict:
    try:
        return launcher_service.update_launcher_developer_mode(payload.enabled, base_hash=payload.baseHash)
    except launcher_service.DeveloperCleanupPlanError as exc:
        raise HTTPException(status_code=409, detail={"code": exc.code, "message": exc.message, **exc.detail}) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"code": "invalid_developer_mode", "message": str(exc)}) from exc


@router.get(
    "/launcher/developer-mode/noise-overview",
    response_model=LauncherDeveloperNoiseOverviewResponse,
    response_model_exclude_unset=True,
)
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


@router.post("/launcher/rebuild-and-start", status_code=202)
def launcher_rebuild_and_start() -> dict:
    try:
        return launcher_service.request_launcher_rebuild_and_start()
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


@router.get("/launcher/lifecycle-intents/{intent_id}")
def launcher_get_lifecycle_intent(intent_id: str) -> dict:
    result = launcher_service.get_lifecycle_intent(intent_id)
    if not result:
        raise HTTPException(status_code=404, detail={"code": "lifecycle_intent_not_found"})
    return result


@router.post("/launcher/workbench-close-transactions", status_code=202)
def launcher_submit_workbench_close_transaction(payload: WorkbenchCloseTransactionPayload) -> dict:
    return _workbench_close_transaction_response(
        lambda: launcher_service.submit_workbench_close_transaction(payload.model_dump())
    )


@router.get("/launcher/workbench-close-transactions/{close_id}")
def launcher_get_workbench_close_transaction(close_id: str) -> dict:
    result = launcher_service.get_workbench_close_transaction(close_id)
    if not result:
        raise HTTPException(status_code=404, detail={"code": "workbench_close_transaction_not_found"})
    return result


@router.post("/launcher/workbench-close-transactions/{close_id}/window-closed", status_code=202)
def launcher_ack_workbench_close_transaction_window_closed(
    close_id: str, payload: WorkbenchCloseWindowClosedPayload
) -> dict:
    return _workbench_close_transaction_response(
        lambda: launcher_service.ack_workbench_close_transaction_window_closed(close_id, payload.model_dump())
    )


@router.post("/launcher/desktop-actions/claim")
def launcher_claim_desktop_action(payload: DesktopActionClaimPayload) -> dict:
    return launcher_service.claim_desktop_action(
        payload.desktopSessionId,
        lease_seconds=payload.leaseSeconds,
        wait_ms=payload.waitMs,
    )


@router.post("/launcher/desktop-actions/{action_id}/ack", status_code=202)
def launcher_ack_desktop_action(action_id: str, payload: DesktopActionResultPayload) -> dict:
    return launcher_service.ack_desktop_action(action_id, payload.desktopSessionId, payload.result)


@router.post("/launcher/desktop-actions/{action_id}/fail", status_code=202)
def launcher_fail_desktop_action(action_id: str, payload: DesktopActionResultPayload) -> dict:
    return launcher_service.fail_desktop_action(action_id, payload.desktopSessionId, payload.result)


@router.post("/launcher/desktop-sessions", status_code=201)
def launcher_register_desktop_session(payload: DesktopSessionPayload) -> dict:
    return launcher_service.register_desktop_session(payload.model_dump())


@router.put("/launcher/desktop-sessions/{desktop_session_id}/windows/{role}")
def launcher_update_desktop_session_window(
    desktop_session_id: str,
    role: str,
    payload: DesktopSessionWindowPayload,
) -> dict:
    return _desktop_session_mutation_response(
        lambda: launcher_service.update_desktop_session_window(desktop_session_id, role, payload.model_dump()),
        invalid_code="invalid_desktop_session_window",
    )


@router.post("/launcher/desktop-sessions/{desktop_session_id}/heartbeat")
def launcher_heartbeat_desktop_session(
    desktop_session_id: str, payload: DesktopSessionRevisionPayload
) -> dict:
    return _desktop_session_mutation_response(
        lambda: launcher_service.heartbeat_desktop_session(desktop_session_id, payload.model_dump())
    )


@router.delete("/launcher/desktop-sessions/{desktop_session_id}")
def launcher_close_desktop_session(
    desktop_session_id: str, payload: DesktopSessionRevisionPayload
) -> dict:
    return _desktop_session_mutation_response(
        lambda: launcher_service.close_desktop_session(desktop_session_id, payload.model_dump())
    )


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
