"""FastAPI entrypoint for the Vibelution web workbench."""

from __future__ import annotations

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


class UTF8JSONResponse(JSONResponse):
    media_type = "application/json; charset=utf-8"


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

    app.state.web_routes_registered = False
    app.state.web_routes_error = ""
    app.state.web_routes_ready_event = None  # set by lifespan when background warm is used
    app.state.web_routes_bootstrap = {}

    @app.get("/api/health")
    def health() -> dict[str, object]:
        routes_ready = bool(getattr(app.state, "web_routes_registered", False))
        return {
            "status": "ok",
            "routesReady": routes_ready,
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
