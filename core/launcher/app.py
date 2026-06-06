"""FastAPI app for the standalone Vibelution Launcher control plane."""

from __future__ import annotations

from fastapi import APIRouter, FastAPI, HTTPException

from . import service as launcher_service


router = APIRouter()


@router.get("/api/launcher/status")
@router.get("/api/project/status")
def launcher_status() -> dict:
    return launcher_service.get_launcher_status()


@router.post("/api/launcher/start", status_code=202)
@router.post("/api/project/start", status_code=202)
def project_start() -> dict:
    return launcher_service.request_launcher_start()


@router.post("/api/launcher/stop", status_code=202)
@router.post("/api/project/stop", status_code=202)
def project_stop() -> dict:
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


def create_launcher_app() -> FastAPI:
    app = FastAPI(
        title="Vibelution Launcher",
        version="0.1.0",
        description="Standalone lifecycle control plane for the Vibelution project bundle.",
    )
    app.include_router(router)
    return app


app = create_launcher_app()
