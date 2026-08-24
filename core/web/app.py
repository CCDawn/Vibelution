"""FastAPI entrypoint for the Vibelution web workbench."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from core.version import get_product_version
from .control import WebControlGuardMiddleware, control_token_payload, ensure_control_source, trusted_control_origins
from .lifecycle import web_workbench_lifespan
from .middleware.runtime_scene_api import RuntimeSceneApiEventMiddleware
from .middleware.wait_for_routes import WaitForWebRoutesMiddleware
from .route_bootstrap import ensure_web_routes_registered
from .router_registry import register_web_routers
from .static_spa import web_index_response
from .services.serving_version import build_serving_metadata


class UTF8JSONResponse(JSONResponse):
    media_type = "application/json; charset=utf-8"


def _health_workspace_root() -> str:
    env_root = str(os.environ.get("VIBELUTION_WORKSPACE_ROOT", "")).strip()
    if env_root:
        return env_root
    return str(Path(__file__).resolve().parents[2])


def create_app() -> FastAPI:
    """Create the local web workbench app.

    Phase 1 (immediate): middleware + /api/health + /api/control-token.
    Phase 2 (lifespan / first non-health request): API routers + SPA.
    This lets Launcher mark the backend healthy while heavy route imports continue.
    """

    app = FastAPI(
        title="Vibelution Web Workbench",
        version=get_product_version(),
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        lifespan=web_workbench_lifespan,
        default_response_class=UTF8JSONResponse,
    )
    # Starlette applies middleware in reverse add order; WaitForWebRoutes should run
    # outermost so early paths skip waiting before control/cors handling cost.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=sorted(trusted_control_origins()),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*", "X-Vibelution-Control-Token"],
    )
    app.add_middleware(WebControlGuardMiddleware)
    app.add_middleware(RuntimeSceneApiEventMiddleware)
    app.add_middleware(WaitForWebRoutesMiddleware)

    # Pin the release and backend identity at process construction time.  The
    # active.json pointer may change later, but a running process must continue
    # to report and serve the immutable release it mounted at startup.
    serving_root = Path(_health_workspace_root()).resolve()
    try:
        serving_metadata = build_serving_metadata(serving_root)
    except Exception as exc:  # noqa: BLE001 - health must remain available during degraded startup
        serving_metadata = {
            "schemaVersion": 1,
            "apiContractVersion": "v1",
            "frontend": {"buildKey": "", "release": "", "dist": "", "builtFromCommit": ""},
            "backend": {
                "schemaVersion": 1,
                "head": "",
                "dirty": False,
                "dirtyTreeDigest": "",
                "pid": os.getpid(),
                "createTime": None,
                "executable": "",
                "startedAt": "",
                "errorType": type(exc).__name__,
            },
        }
    app.state.serving_metadata = serving_metadata
    frontend_metadata = serving_metadata.get("frontend") if isinstance(serving_metadata, dict) else {}
    app.state.serving_frontend_dist = str(frontend_metadata.get("dist") or "").strip()
    app.state.web_routes_registered = False
    app.state.web_routes_error = ""
    app.state.web_routes_ready_event = None  # set by lifespan when background warm is used
    app.state.web_routes_bootstrap = {}

    @app.get("/api/health")
    def health() -> dict[str, object]:
        routes_ready = bool(getattr(app.state, "web_routes_registered", False))
        serving_value = getattr(app.state, "serving_metadata", {})
        serving = serving_value if isinstance(serving_value, dict) else {}
        serving_frontend = serving.get("frontend") if isinstance(serving.get("frontend"), dict) else {}
        return {
            "status": "ok",
            "routesReady": routes_ready,
            # Identity lets the launcher distinguish a stale same-project backend
            # (safe to reclaim) from a foreign process holding the preferred port.
            "pid": os.getpid(),
            "workspaceRoot": _health_workspace_root(),
            "apiContractVersion": str(serving.get("apiContractVersion") or "v1"),
            "serving": serving,
            # Keep the high-value fields flat for lightweight launcher clients
            # and older diagnostics that do not understand nested metadata.
            "servingBuildKey": str(serving_frontend.get("buildKey") or ""),
            "servingRelease": str(serving_frontend.get("release") or ""),
            "backendCodeFingerprint": serving.get("backend") or {},
        }

    @app.get("/api/control-token")
    def control_token(request: Request) -> dict[str, str]:
        ensure_control_source(request)
        return control_token_payload()

    return app


app = create_app()

__all__ = [
    "UTF8JSONResponse",
    "app",
    "create_app",
    "ensure_web_routes_registered",
    "register_web_routers",
    "web_index_response",
    "web_workbench_lifespan",
]
