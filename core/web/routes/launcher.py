"""Launcher lifecycle routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from core.web.services.launcher_service import (
    get_launcher_status,
    request_launcher_restart,
    request_launcher_start,
    request_launcher_stop,
)
from core.web.services.runtime_service import RuntimeRestartActiveWorkBlocked


router = APIRouter(tags=["launcher"])


@router.get("/launcher/status")
def launcher_status() -> dict:
    return get_launcher_status()


@router.post("/launcher/start", status_code=202)
def launcher_start() -> dict:
    return request_launcher_start()


@router.post("/launcher/stop", status_code=202)
def launcher_stop() -> dict:
    return request_launcher_stop()


@router.post("/launcher/restart", status_code=202)
def launcher_restart(confirmed_active_work: bool = Query(default=False, alias="confirmedActiveWork")) -> dict:
    try:
        return request_launcher_restart(confirmed_active_work=confirmed_active_work)
    except RuntimeRestartActiveWorkBlocked as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "active_work_requires_confirmation",
                "message": exc.message,
                "activeWorkRuns": exc.active_work_runs,
            },
        ) from exc
