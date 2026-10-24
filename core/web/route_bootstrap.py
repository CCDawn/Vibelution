"""Two-phase web route bootstrap: health first, API/SPA when ready."""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from pathlib import Path
from typing import Any, Awaitable, Callable

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.routing import compile_path

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


_BOOTSTRAP_ROUTE_MODULE_NAMES = frozenset({
    "core.web.routes.agent_assets",
    "core.web.routes.config",
    "core.web.routes.launcher",
})
_BOOTSTRAP_ROUTE_OPERATIONS = (
    (frozenset({"GET", "HEAD"}), "/api/config/bootstrap"),
    (frozenset({"GET", "HEAD"}), "/api/launcher/current-instance"),
    (frozenset({"GET"}), "/api/config/avatar-image/{filename}"),
    (frozenset({"GET"}), "/api/config/theme-background-image/{filename}"),
    (frozenset({"GET"}), "/api/agents/avatar-image/{filename}"),
    # Electron publishes window identity before the first
    # Session reads finish. These handlers already mount with Launcher and
    # need no Agent catalog; treating them as feature demand defeats the lazy
    # import gate and starts every optional router against the first screen.
    (frozenset({"POST"}), "/api/launcher/desktop-sessions"),
    (frozenset({"PUT"}), "/api/launcher/desktop-sessions/{desktop_session_id}/windows/{role}"),
    (frozenset({"POST"}), "/api/launcher/desktop-sessions/{desktop_session_id}/heartbeat"),
)
_BOOTSTRAP_ROUTE_MATCHERS = tuple(
    (methods, compile_path(path)[0]) for methods, path in _BOOTSTRAP_ROUTE_OPERATIONS
)


def is_bootstrap_route_path(path: str, *, method: str = "GET") -> bool:
    """Match mounted shell operations that do not need the Session/Agent catalog."""
    normalized = str(path or "").split("?", 1)[0]
    return any(
        method in methods and pattern.fullmatch(normalized) is not None
        for methods, pattern in _BOOTSTRAP_ROUTE_MATCHERS
    )


# These handlers and their services are imported by the startup routers. The
# built-in Agent catalog is initialized before startup readiness is published.
# Keep methods and complete route shapes explicit: an entire /sessions prefix
# would also admit feature routers (archive/export) that have not mounted yet.
_STARTUP_ROUTE_OPERATIONS = (
    (frozenset({"GET", "HEAD"}), "/api/config/bootstrap"),
    (frozenset({"GET", "HEAD"}), "/api/launcher/current-instance"),
    (frozenset({"GET", "HEAD"}), "/api/runtime/summary"),
    # Normal Electron diagnostics need no optional router. Malformed-payload
    # alerts can access the Agent catalog, so retain its readiness prerequisite.
    (frozenset({"POST"}), "/api/launcher/runtime-scene/events"),
    (frozenset({"GET"}), "/api/agent-plugins/virtual-human-life/companion-activity"),
    (frozenset({"GET"}), "/api/agent-plugins/virtual-human-life/companion-bindings"),
    (frozenset({"GET", "HEAD"}), "/api/sessions/bootstrap"),
    (frozenset({"GET", "HEAD"}), "/api/sessions/query"),
    (frozenset({"GET", "HEAD"}), "/api/sessions/active"),
    (frozenset({"POST"}), "/api/sessions"),
    (frozenset({"GET"}), "/api/sessions/{session_id}"),
    (frozenset({"POST"}), "/api/sessions/{session_id}/select"),
    (frozenset({"POST"}), "/api/sessions/{session_id}/messages"),
    (frozenset({"GET"}), "/api/sessions/{session_id}/events"),
    (frozenset({"POST"}), "/api/sessions/{session_id}/stop"),
    (frozenset({"POST"}), "/api/sessions/{session_id}/guidance"),
    (frozenset({"GET"}), "/api/sessions/{session_id}/tool-approvals"),
    (frozenset({"POST"}), "/api/sessions/{session_id}/tool-approvals/{request_id}/decision"),
    (frozenset({"GET"}), "/api/sessions/{session_id}/llm-options"),
    (frozenset({"PATCH"}), "/api/sessions/{session_id}/model-parameters"),
    (frozenset({"GET", "PATCH"}), "/api/sessions/{session_id}/budget-parameters"),
)
_STARTUP_ROUTE_MATCHERS = tuple(
    (methods, compile_path(path)[0]) for methods, path in _STARTUP_ROUTE_OPERATIONS
)


def is_startup_route_path(path: str, *, method: str = "GET") -> bool:
    """Match only reviewed startup operations, without changing control guards."""
    normalized = str(path or "").split("?", 1)[0]
    return any(
        method in methods and pattern.fullmatch(normalized) is not None
        for methods, pattern in _STARTUP_ROUTE_MATCHERS
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
    """Publish the pinned shell, keeping its catch-all behind later API routes."""

    shell_routes = getattr(app.state, "web_shell_routes", ())
    if shell_routes:
        # The shell is available before imports finish. Reuse those exact routes
        # after API registration, otherwise the early catch-all swallows /api/*.
        app.router.routes[:] = [route for route in app.router.routes if route not in shell_routes]
        app.router.routes.extend(shell_routes)
        return

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

    first_shell_route = len(app.router.routes)

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

    app.state.web_shell_routes = tuple(app.router.routes[first_shell_route:])
    from core.launcher.frontend_build import validate_staging_release

    try:
        validate_staging_release(dist)
    except (OSError, RuntimeError) as exc:
        app.state.web_shell_ready = False
        app.state.web_shell_error = str(exc)
    else:
        app.state.web_shell_ready = True
        app.state.web_shell_error = ""


def _mark_routes_ready(app: FastAPI, *, error: str = "") -> None:
    app.state.web_routes_registered = True
    app.state.web_routes_error = str(error or "")
    event = getattr(app.state, "web_routes_ready_event", None)
    if event is not None and not event.is_set():
        event.set()
    _mark_startup_routes_ready(app)


def _mark_startup_routes_ready(app: FastAPI) -> None:
    app.state.web_startup_routes_registered = True
    event = getattr(app.state, "web_startup_routes_ready_event", None)
    if event is not None:
        event.set()
    _mark_bootstrap_routes_ready(app)


def _mark_bootstrap_routes_ready(app: FastAPI) -> None:
    app.state.web_bootstrap_routes_registered = True
    event = getattr(app.state, "web_bootstrap_routes_ready_event", None)
    if event is not None:
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
        "web routes mounted: %s modules, import %.1fms, mount %.1fms%s; first-frame %.1fms",
        payload.get("routeModuleCount", 0),
        float(payload.get("importMs", 0.0) or 0.0),
        float(payload.get("mountMs", 0.0) or 0.0),
        slowest,
        float(payload.get("startupReadyMs", payload.get("totalMs", 0.0)) or 0.0),
    )


async def _run_financial_team_coordinator_managed(
    run_sync: Callable[..., Awaitable[Any]],
) -> None:
    """Run the Finance Team coordinator through the workbench owner group."""

    from .services.financial_team.coordinator import run_forever

    await run_sync(
        "financial-team-coordinator",
        run_forever,
        stop_keyword="stop_requested",
    )


def _start_financial_team_coordinator(
    app: FastAPI,
    *,
    run_sync: Callable[..., Awaitable[Any]] | None,
) -> None:
    """Start one lifespan-managed coordinator after routes are ready."""

    if (
        run_sync is None
        or not bool(getattr(app.state, "web_routes_registered", False))
        or str(getattr(app.state, "web_routes_error", "") or "").strip()
    ):
        return
    current = getattr(app.state, "financial_team_coordinator_task", None)
    if isinstance(current, asyncio.Task) and not current.done():
        return

    task = asyncio.create_task(
        _run_financial_team_coordinator_managed(run_sync),
        name="financial-team-coordinator-owner",
    )
    app.state.financial_team_coordinator_task = task

    def consume_result(completed: asyncio.Task[Any]) -> None:
        if completed.cancelled():
            return
        try:
            completed.result()
        except Exception as exc:  # noqa: BLE001 - surface owner failures without an unhandled task
            logger.warning(
                "Financial Team coordinator owner failed (%s).",
                type(exc).__name__,
            )

    task.add_done_callback(consume_result)


async def _run_financial_job_scheduler_managed(
    run_sync: Callable[..., Awaitable[Any]],
) -> None:
    from .services.financial_job_service import run_forever

    await run_sync("financial-job-scheduler", run_forever, stop_keyword="stop_requested")


def _start_financial_job_scheduler(
    app: FastAPI, *, run_sync: Callable[..., Awaitable[Any]] | None,
) -> None:
    if (
        run_sync is None
        or not bool(getattr(app.state, "web_routes_registered", False))
        or str(getattr(app.state, "web_routes_error", "") or "").strip()
    ):
        return
    current = getattr(app.state, "financial_job_scheduler_task", None)
    if isinstance(current, asyncio.Task) and not current.done():
        return
    task = asyncio.create_task(
        _run_financial_job_scheduler_managed(run_sync), name="financial-job-scheduler-owner",
    )
    app.state.financial_job_scheduler_task = task

    def consume_result(completed: asyncio.Task[Any]) -> None:
        if completed.cancelled():
            return
        try:
            completed.result()
        except Exception as exc:  # noqa: BLE001 - surface bounded owner failure
            logger.warning("Financial job scheduler owner failed (%s).", type(exc).__name__)

    task.add_done_callback(consume_result)


async def _run_financial_backtest_worker_managed(
    run_sync: Callable[..., Awaitable[Any]],
) -> None:
    from .services.financial_backtest.runtime import run_forever

    await run_sync("financial-ai-backtest-worker", run_forever, stop_keyword="stop_requested")


def _start_financial_backtest_worker(
    app: FastAPI, *, run_sync: Callable[..., Awaitable[Any]] | None,
) -> None:
    if (
        run_sync is None
        or not bool(getattr(app.state, "web_routes_registered", False))
        or str(getattr(app.state, "web_routes_error", "") or "").strip()
    ):
        return
    current = getattr(app.state, "financial_backtest_worker_task", None)
    if isinstance(current, asyncio.Task) and not current.done():
        return
    task = asyncio.create_task(
        _run_financial_backtest_worker_managed(run_sync),
        name="financial-ai-backtest-worker-owner",
    )
    app.state.financial_backtest_worker_task = task

    def consume_result(completed: asyncio.Task[Any]) -> None:
        if completed.cancelled():
            return
        try:
            completed.result()
        except Exception as exc:  # noqa: BLE001 - expose lifecycle owner failure without unhandled task
            logger.warning("Financial AI backtest worker failed (%s).", type(exc).__name__)

    task.add_done_callback(consume_result)


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
            from .services.agent_directory.bootstrap import initialize_builtin_agent_catalog

            initialize_builtin_agent_catalog()
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


def request_feature_routes(app: FastAPI) -> None:
    """Wake the single route-import owner when a feature is actually needed."""
    event = getattr(app.state, "web_feature_routes_requested_event", None)
    if event is not None:
        event.set()


async def _await_feature_route_demand(app: FastAPI) -> float:
    """Give startup requests priority; demand bypasses the bounded idle wait."""
    from .lifecycle import _startup_cache_prewarm_gate_enabled, _startup_prewarm_stagger_seconds

    event = getattr(app.state, "web_feature_routes_requested_event", None)
    if event is None or not _startup_cache_prewarm_gate_enabled():
        return 0.0
    timeout = _startup_prewarm_stagger_seconds()
    if timeout <= 0:
        return 0.0
    started = time.perf_counter()
    try:
        await asyncio.wait_for(event.wait(), timeout=timeout)
    except TimeoutError:
        pass  # Headless/older clients still get a complete API without a request.
    return max(0.0, (time.perf_counter() - started) * 1000)


async def warm_web_routes_in_background(
    app: FastAPI,
    *,
    web_dist: Path | None = None,
    run_sync: Callable[..., Awaitable[Any]] | None = None,
) -> dict[str, Any]:
    """Import route modules off-thread, mount on the event-loop thread."""

    if bool(getattr(app.state, "web_routes_registered", False)):
        _start_financial_team_coordinator(app, run_sync=run_sync)
        _start_financial_job_scheduler(app, run_sync=run_sync)
        _start_financial_backtest_worker(app, run_sync=run_sync)
        return {
            "registered": True,
            "alreadyReady": True,
            "error": str(getattr(app.state, "web_routes_error", "") or ""),
        }

    started = time.perf_counter()
    module_imports, on_module_imported = _new_module_timing_sink()
    app.state.web_routes_cancelled = False
    try:
        if run_sync is None:
            startup_modules = await asyncio.to_thread(
                import_web_route_modules,
                on_module_imported=on_module_imported,
                startup_only=True,
            )
        else:
            startup_modules = await run_sync(
                "web-route-import",
                import_web_route_modules,
                on_module_imported=on_module_imported,
                startup_only=True,
            )
        import_ms = max(0.0, (time.perf_counter() - started) * 1000.0)
        # include_router must stay on the main thread / event loop.
        bootstrap_modules = [
            module for module in startup_modules
            if getattr(module, "__name__", "") in _BOOTSTRAP_ROUTE_MODULE_NAMES
        ]
        mount_ms = 0.0
        with _REGISTER_LOCK:
            if bootstrap_modules and not bool(getattr(app.state, "web_routes_registered", False)):
                mount_started = time.perf_counter()
                register_web_routers_from_modules(app, bootstrap_modules)
                register_spa_routes(app, web_dist=web_dist)
                mount_ms += max(0.0, (time.perf_counter() - mount_started) * 1000.0)
                _mark_bootstrap_routes_ready(app)
        from .services.agent_directory.bootstrap import initialize_builtin_agent_catalog

        if run_sync is None:
            await asyncio.to_thread(initialize_builtin_agent_catalog)
        else:
            await run_sync("builtin-agent-bootstrap", initialize_builtin_agent_catalog)
        with _REGISTER_LOCK:
            if not bool(getattr(app.state, "web_routes_registered", False)):
                mount_started = time.perf_counter()
                if startup_modules:
                    register_web_routers_from_modules(app, startup_modules)
                    register_spa_routes(app, web_dist=web_dist)
                mount_ms += max(0.0, (time.perf_counter() - mount_started) * 1000.0)
                _mark_startup_routes_ready(app)
        startup_ready_ms = max(0.0, (time.perf_counter() - started) * 1000.0)
        feature_demand_wait_ms = await _await_feature_route_demand(app)
        remaining_started = time.perf_counter()
        if run_sync is None:
            modules = await asyncio.to_thread(
                import_web_route_modules, startup_only=False,
                on_module_imported=on_module_imported,
            )
        else:
            modules = await run_sync(
                "web-route-import", import_web_route_modules, startup_only=False,
                on_module_imported=on_module_imported,
            )
        import_ms += max(0.0, (time.perf_counter() - remaining_started) * 1000.0)
        # First-frame reads are already admitted. Full feature readiness also
        # owns runtime composition, so a cold formal request cannot race its
        # startup after waking both owners through the same demand event.
        workflow_startup = getattr(app.state, "web_workflow_runtime_startup_task", None)
        if workflow_startup is not None:
            await asyncio.shield(workflow_startup)
        with _REGISTER_LOCK:
            if bool(getattr(app.state, "web_routes_registered", False)):
                _start_financial_team_coordinator(app, run_sync=run_sync)
                _start_financial_job_scheduler(app, run_sync=run_sync)
                _start_financial_backtest_worker(app, run_sync=run_sync)
                return {
                    "registered": True,
                    "alreadyReady": True,
                    "error": str(getattr(app.state, "web_routes_error", "") or ""),
                }
            mount_started = time.perf_counter()
            register_web_routers_from_modules(app, modules)
            register_spa_routes(app, web_dist=web_dist)
            mount_ms += max(0.0, (time.perf_counter() - mount_started) * 1000.0)
            payload = {
                "registered": True,
                "alreadyReady": False,
                "error": "",
                "routeModuleCount": len(startup_modules) + len(modules),
                "importMs": round(import_ms, 1),
                "mountMs": round(mount_ms, 1),
                "totalMs": round(max(0.0, (time.perf_counter() - started) * 1000.0), 1),
                "moduleImports": module_imports,
                "startupReadyMs": round(startup_ready_ms, 1),
                "featureDemandWaitMs": round(feature_demand_wait_ms, 1),
            }
            app.state.web_routes_bootstrap = payload
            _log_routes_bootstrap_summary(payload)
            _mark_routes_ready(app)
            _start_financial_team_coordinator(app, run_sync=run_sync)
            _start_financial_job_scheduler(app, run_sync=run_sync)
            _start_financial_backtest_worker(app, run_sync=run_sync)
            return payload
    except (Exception, asyncio.CancelledError) as exc:
        app.state.web_routes_error = f"{type(exc).__name__}: {exc}"
        app.state.web_routes_cancelled = isinstance(exc, asyncio.CancelledError)
        # Signal waiters so they can fall back / fail fast instead of hanging.
        for event_name in (
            "web_routes_ready_event", "web_startup_routes_ready_event", "web_bootstrap_routes_ready_event",
        ):
            event = getattr(app.state, event_name, None)
            if event is not None:
                event.set()
        raise


async def wait_for_web_routes(
    app: FastAPI,
    *,
    timeout_seconds: float = _DEFAULT_ROUTE_WAIT_TIMEOUT_SECONDS,
    startup_only: bool = False,
    bootstrap_only: bool = False,
) -> bool:
    """Wait until routes are mounted. Returns False on timeout."""

    def ready() -> bool:
        return bool(getattr(app.state, "web_routes_registered", False)) or (
            (startup_only or bootstrap_only) and bool(getattr(app.state, "web_startup_routes_registered", False))
        ) or (
            bootstrap_only and bool(getattr(app.state, "web_bootstrap_routes_registered", False))
        )

    if not startup_only and not bootstrap_only:
        request_feature_routes(app)
    if ready():
        return True
    if bool(getattr(app.state, "web_routes_cancelled", False)):
        return False

    event: asyncio.Event | None = getattr(app.state, "web_routes_ready_event", None)
    if startup_only or bootstrap_only:
        event = getattr(app.state, "web_startup_routes_ready_event", None) or event
    if bootstrap_only:
        event = getattr(app.state, "web_bootstrap_routes_ready_event", None) or event
    if event is None:
        # No lifespan warm task — register inline (TestClient / bare ASGI).
        ensure_web_routes_registered(app)
        return True

    if event.is_set():
        if ready():
            return True
        # Event set after failure — try synchronous recovery once.
        try:
            ensure_web_routes_registered(app)
        except Exception:
            return False
        return bool(getattr(app.state, "web_routes_registered", False))

    try:
        await asyncio.wait_for(event.wait(), timeout=max(0.1, float(timeout_seconds)))
    except TimeoutError:
        return False

    if ready():
        return True
    if bool(getattr(app.state, "web_routes_cancelled", False)):
        return False
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
