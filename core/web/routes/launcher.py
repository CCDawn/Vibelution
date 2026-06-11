"""Launcher lifecycle routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from core.launcher import service as launcher_service


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


@router.post("/launcher/start", status_code=202)
def launcher_start() -> dict:
    return launcher_service.request_launcher_start()


@router.post("/launcher/stop", status_code=202)
def launcher_stop() -> dict:
    try:
        return launcher_service.request_launcher_stop()
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
def launcher_force_stop() -> dict:
    return launcher_service.request_launcher_force_stop()


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


@router.post("/launcher/supervisor/reattach", status_code=202)
def launcher_supervisor_reattach() -> dict:
    return launcher_service.request_launcher_supervisor_reattach()
