"""Launcher lifecycle routes."""

from __future__ import annotations

from pydantic import BaseModel
from fastapi import APIRouter, HTTPException

from core.launcher import service as launcher_service


router = APIRouter(tags=["launcher"])


class WorkbenchWindowModePayload(BaseModel):
    mode: str


@router.get("/launcher/status")
def launcher_status() -> dict:
    return launcher_service.get_launcher_status()


@router.get("/launcher/settings/workbench-window")
def launcher_workbench_window_setting() -> dict:
    return launcher_service.get_workbench_window_mode_setting()


@router.put("/launcher/settings/workbench-window")
def launcher_update_workbench_window_setting(payload: WorkbenchWindowModePayload) -> dict:
    try:
        return launcher_service.update_workbench_window_mode(payload.mode)
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
