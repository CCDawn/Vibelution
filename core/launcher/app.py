"""FastAPI app for the standalone Vibelution Launcher control plane."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel
from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from core.version import get_product_version
from core.web.control import CONTROL_TOKEN_HEADER, control_token_payload, trusted_control_origins
from . import service as launcher_service


PROJECT_ROOT = Path(__file__).resolve().parents[2]
WEB_DIST = PROJECT_ROOT / "web" / "dist"
WEB_INDEX = WEB_DIST / "index.html"
INDEX_CACHE_HEADERS = {
    "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
    "Pragma": "no-cache",
    "Expires": "0",
}

router = APIRouter()


class WorkbenchWindowModePayload(BaseModel):
    mode: str


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


@router.put("/api/launcher/settings/workbench-window")
def update_workbench_window_setting(payload: WorkbenchWindowModePayload) -> dict:
    try:
        return launcher_service.update_workbench_window_mode(payload.mode)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"code": "invalid_workbench_window_mode", "message": str(exc)}) from exc


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
