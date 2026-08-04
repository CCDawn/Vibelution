"""Hold non-health requests until API/SPA routes are mounted."""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

from core.web.route_bootstrap import (
    is_early_ready_path,
    routes_not_ready_response,
    wait_for_web_routes,
)


class WaitForWebRoutesMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp, *, timeout_seconds: float = 120.0) -> None:
        super().__init__(app)
        self._timeout_seconds = float(timeout_seconds)

    async def dispatch(self, request: Request, call_next) -> Response:
        path = request.url.path
        if is_early_ready_path(path):
            return await call_next(request)

        app = request.app
        ready = await wait_for_web_routes(app, timeout_seconds=self._timeout_seconds)
        if not ready:
            return routes_not_ready_response(app)
        return await call_next(request)
