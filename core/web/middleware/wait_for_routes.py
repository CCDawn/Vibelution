"""Serve the pinned shell early while functional API requests wait for routes."""

from __future__ import annotations

import logging
import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

from core.web.route_bootstrap import (
    is_bootstrap_route_path,
    is_early_ready_path,
    is_startup_route_path,
    request_feature_routes,
    routes_not_ready_response,
    wait_for_web_routes,
)

logger = logging.getLogger("uvicorn.error")


class WaitForWebRoutesMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp, *, timeout_seconds: float = 120.0) -> None:
        super().__init__(app)
        self._timeout_seconds = float(timeout_seconds)

    async def dispatch(self, request: Request, call_next) -> Response:
        path = request.url.path
        if is_early_ready_path(path):
            return await call_next(request)

        app = request.app
        # Existing clients request this optional summary after their primary
        # startup data. It can also wake features when no feature URL is used.
        if request.method in {"GET", "HEAD"} and path == "/api/runtime/summary":
            request_feature_routes(app)
        if bool(getattr(app.state, "web_shell_ready", False)) and path != "/api" and not path.startswith("/api/"):
            return await call_next(request)
        admission_started = time.perf_counter()
        ready = await wait_for_web_routes(
            app, timeout_seconds=self._timeout_seconds,
            startup_only=is_startup_route_path(path, method=request.method),
            bootstrap_only=is_bootstrap_route_path(path, method=request.method),
        )
        waited_ms = (time.perf_counter() - admission_started) * 1000
        if waited_ms >= 50:
            logger.info("web route admission: %s %s waited %.1fms; ready=%s", request.method, path[:160], waited_ms, ready)
        if not ready:
            return routes_not_ready_response(app)
        return await call_next(request)
