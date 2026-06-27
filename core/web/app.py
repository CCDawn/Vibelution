"""FastAPI entrypoint for the Vibelution web workbench."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from core.version import get_product_version
from .control import WebControlGuardMiddleware, control_token_payload, ensure_control_source, trusted_control_origins
from .lifecycle import web_workbench_lifespan
from .middleware.runtime_scene_api import RuntimeSceneApiEventMiddleware
from .router_registry import register_web_routers
from .static_spa import FRONTEND_BUILD_HINT, INDEX_CACHE_HEADERS, web_index_response, web_spa_fallback_response


PROJECT_ROOT = Path(__file__).resolve().parents[2]
WEB_DIST = PROJECT_ROOT / "web" / "dist"


class UTF8JSONResponse(JSONResponse):
    media_type = "application/json; charset=utf-8"


def create_app() -> FastAPI:
    """Create the local web workbench app."""

    app = FastAPI(
        title="Vibelution Web Workbench",
        version=get_product_version(),
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        lifespan=web_workbench_lifespan,
        default_response_class=UTF8JSONResponse,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=sorted(trusted_control_origins()),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*", "X-Vibelution-Control-Token"],
    )
    app.add_middleware(WebControlGuardMiddleware)
    app.add_middleware(RuntimeSceneApiEventMiddleware)

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/control-token")
    def control_token(request: Request) -> dict[str, str]:
        ensure_control_source(request)
        return control_token_payload()

    register_web_routers(app)

    @app.get("/", include_in_schema=False)
    def index(request: Request):
        ensure_control_source(request)
        return web_index_response(WEB_DIST)

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa_fallback(full_path: str, request: Request):
        ensure_control_source(request)
        return web_spa_fallback_response(full_path, WEB_DIST)

    return app


app = create_app()
