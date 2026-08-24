"""Two-phase web route bootstrap: health first, API/SPA when ready."""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .router_registry import import_web_route_modules, register_web_routers_from_modules
from .static_spa import web_index_response, web_spa_fallback_response

logger = logging.getLogger("uvicorn.error")

# Paths that must work before API routers / SPA catch-all are mounted.
EARLY_READY_PATHS = frozenset(
    {
        "/api/health",
        "/api/control-token",
    }
)

_REGISTER_LOCK = threading.Lock()
_DEFAULT_ROUTE_WAIT_TIMEOUT_SECONDS = 120.0


def is_early_ready_path(path: str) -> bool:
    normalized = str(path or "").split("?", 1)[0]
    if normalized in EARLY_READY_PATHS:
        return True
    # OpenAPI/docs are optional early; they become complete after routers mount.
    if normalized in {"/api/docs", "/api/openapi.json", "/api/redoc", "/docs", "/openapi.json", "/redoc"}:
        return True
    return False


def _web_dist() -> Path:
    from core.launcher.frontend_build import resolve_active_frontend_dist

    return resolve_active_frontend_dist(Path(__file__).resolve().parents[2])


def register_spa_routes(app: FastAPI, web_dist: Path | None = None) -> None:
    """Mount SPA index + catch-all after API routers so /api/* is not swallowed."""

    pinned_dist = str(getattr(app.state, "serving_frontend_dist", "") or "").strip()
    # A process-created app may be instantiated before a build exists (and
    # tests intentionally provide a temporary dist through ``_web_dist``).
    # Only pin an actually published directory; an absent fallback must not
    # mask the normal resolver or make the SPA appear blank.
    pinned_path = Path(pinned_dist) if pinned_dist else None
    if web_dist is not None:
        dist = web_dist
    elif pinned_path is not None:
        # A running backend must keep serving the immutable release it pinned
        # during app construction.  Falling back to the mutable active pointer
        # after that release disappears would silently mix an old backend with
        # a newer frontend (or produce a blank, incompatible shell).
        if not pinned_path.is_dir():
            raise RuntimeError(f"Pinned serving frontend release is unavailable: {pinned_path}")
        dist = pinned_path
    else:
        dist = _web_dist()
    if not dist.is_dir():
        raise RuntimeError(f"Serving frontend directory is unavailable: {dist}")

    @app.get("/", include_in_schema=False)
    def index(request: Request):
        from .control import ensure_control_source

        ensure_control_source(request)
        return web_index_response(dist)

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa_fallback(full_path: str, request: Request):
        from .control import ensure_control_source

        ensure_control_source(request)
        return web_spa_fallback_response(full_path, dist)


def _mark_routes_ready(app: FastAPI, *, error: str = "") -> None:
    app.state.web_routes_registered = True
    app.state.web_routes_error = str(error or "")
    event = getattr(app.state, "web_routes_ready_event", None)
    if event is not None and not event.is_set():
        event.set()


def _new_module_timing_sink() -> tuple[list[dict[str, Any]], Any]:
    timings: list[dict[str, Any]] = []

    def sink(module_name: str, duration_ms: float) -> None:
        timings.append({"module": module_name, "importMs": round(duration_ms, 1)})

    return timings, sink


def _log_routes_bootstrap_summary(payload: dict[str, Any]) -> None:
    module_imports = payload.get("moduleImports")
    slowest = ""
    if isinstance(module_imports, list) and module_imports:
        entries = [
            (str(item.get("module", "")), float(item.get("importMs", 0.0) or 0.0))
            for item in module_imports
            if isinstance(item, dict)
        ]
        top = sorted(entries, key=lambda entry: entry[1], reverse=True)[:5]
        slowest = "; slowest: " + ", ".join(f"{name} {duration_ms:.1f}ms" for name, duration_ms in top)
    logger.info(
        "web routes mounted: %s modules, import %.1fms, mount %.1fms%s",
        payload.get("routeModuleCount", 0),
        float(payload.get("importMs", 0.0) or 0.0),
        float(payload.get("mountMs", 0.0) or 0.0),
        slowest,
    )


def ensure_web_routes_registered(app: FastAPI, *, web_dist: Path | None = None) -> dict[str, Any]:
    """Idempotently import+mount API routers and SPA. Safe on the main thread."""

    if bool(getattr(app.state, "web_routes_registered", False)):
        return {
            "registered": True,
            "alreadyReady": True,
            "error": str(getattr(app.state, "web_routes_error", "") or ""),
        }

    with _REGISTER_LOCK:
        if bool(getattr(app.state, "web_routes_registered", False)):
            return {
                "registered": True,
                "alreadyReady": True,
                "error": str(getattr(app.state, "web_routes_error", "") or ""),
            }
        started = time.perf_counter()
        module_imports, on_module_imported = _new_module_timing_sink()
        try:
            modules = import_web_route_modules(on_module_imported=on_module_imported)
            import_ms = max(0.0, (time.perf_counter() - started) * 1000.0)
            mount_started = time.perf_counter()
            register_web_routers_from_modules(app, modules)
            register_spa_routes(app, web_dist=web_dist)
            mount_ms = max(0.0, (time.perf_counter() - mount_started) * 1000.0)
            _mark_routes_ready(app)
            payload = {
                "registered": True,
                "alreadyReady": False,
                "error": "",
                "routeModuleCount": len(modules),
                "importMs": round(import_ms, 1),
                "mountMs": round(mount_ms, 1),
                "totalMs": round(max(0.0, (time.perf_counter() - started) * 1000.0), 1),
                "moduleImports": module_imports,
            }
            app.state.web_routes_bootstrap = payload
            _log_routes_bootstrap_summary(payload)
            return payload
        except Exception as exc:
            # Leave unregistered so a later attempt can retry; expose error for middleware.
            app.state.web_routes_error = f"{type(exc).__name__}: {exc}"
            raise


async def warm_web_routes_in_background(app: FastAPI, *, web_dist: Path | None = None) -> dict[str, Any]:
    """Import route modules off-thread, mount on the event-loop thread."""

    if bool(getattr(app.state, "web_routes_registered", False)):
        return {
            "registered": True,
            "alreadyReady": True,
            "error": str(getattr(app.state, "web_routes_error", "") or ""),
        }

    started = time.perf_counter()
    module_imports, on_module_imported = _new_module_timing_sink()
    try:
        modules = await asyncio.to_thread(import_web_route_modules, on_module_imported=on_module_imported)
        import_ms = max(0.0, (time.perf_counter() - started) * 1000.0)
        # include_router must stay on the main thread / event loop.
        with _REGISTER_LOCK:
            if bool(getattr(app.state, "web_routes_registered", False)):
                return {
                    "registered": True,
                    "alreadyReady": True,
                    "error": str(getattr(app.state, "web_routes_error", "") or ""),
                }
            mount_started = time.perf_counter()
            register_web_routers_from_modules(app, modules)
            register_spa_routes(app, web_dist=web_dist)
            mount_ms = max(0.0, (time.perf_counter() - mount_started) * 1000.0)
            payload = {
                "registered": True,
                "alreadyReady": False,
                "error": "",
                "routeModuleCount": len(modules),
                "importMs": round(import_ms, 1),
                "mountMs": round(mount_ms, 1),
                "totalMs": round(max(0.0, (time.perf_counter() - started) * 1000.0), 1),
                "moduleImports": module_imports,
            }
            app.state.web_routes_bootstrap = payload
            _log_routes_bootstrap_summary(payload)
            _mark_routes_ready(app)
            return payload
    except Exception as exc:
        app.state.web_routes_error = f"{type(exc).__name__}: {exc}"
        # Signal waiters so they can fall back / fail fast instead of hanging.
        event = getattr(app.state, "web_routes_ready_event", None)
        if event is not None and not event.is_set():
            event.set()
        raise


async def wait_for_web_routes(
    app: FastAPI,
    *,
    timeout_seconds: float = _DEFAULT_ROUTE_WAIT_TIMEOUT_SECONDS,
) -> bool:
    """Wait until routes are mounted. Returns False on timeout."""

    if bool(getattr(app.state, "web_routes_registered", False)):
        return True

    event: asyncio.Event | None = getattr(app.state, "web_routes_ready_event", None)
    if event is None:
        # No lifespan warm task — register inline (TestClient / bare ASGI).
        ensure_web_routes_registered(app)
        return True

    if event.is_set():
        if bool(getattr(app.state, "web_routes_registered", False)):
            return True
        # Event set after failure — try synchronous recovery once.
        ensure_web_routes_registered(app)
        return bool(getattr(app.state, "web_routes_registered", False))

    try:
        await asyncio.wait_for(event.wait(), timeout=max(0.1, float(timeout_seconds)))
    except TimeoutError:
        return False

    if bool(getattr(app.state, "web_routes_registered", False)):
        return True
    # Background warm failed; last-chance sync register for diagnostics.
    try:
        ensure_web_routes_registered(app)
    except Exception:
        return False
    return bool(getattr(app.state, "web_routes_registered", False))


def routes_not_ready_response(app: FastAPI) -> JSONResponse:
    error = str(getattr(app.state, "web_routes_error", "") or "").strip()
    detail = "Workbench API routes are still starting."
    if error:
        detail = f"Workbench API routes failed to start: {error}"
    return JSONResponse(
        {
            "detail": detail,
            "status": "starting" if not error else "failed",
        },
        status_code=503,
        headers={"Retry-After": "1"},
    )
