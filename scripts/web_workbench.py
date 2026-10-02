#!/usr/bin/env python3
"""Launch the local Vibelution web workbench."""

from __future__ import annotations

import argparse
import atexit
import json
import logging
import os
import re
import sys
import threading
import webbrowser
from pathlib import Path

import uvicorn


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.workbench import DEFAULT_WORKBENCH_HOST, configured_backend_port  # noqa: E402


USER_ENV_FALLBACK_ENV = "VIBELUTION_ENABLE_USER_ENV_FALLBACK"
DEFER_RUNTIME_SCENE_RETENTION_ENV = "VIBELUTION_DEFER_RUNTIME_SCENE_RETENTION"

# Runtime scene opened by this backend process (see bootstrap below); the exit
# seal only touches the pointer while it still references this scene.
_startup_runtime_scene_reference: dict[str, str] | None = None


class WorkbenchAccessLogFilter(logging.Filter):
    """Suppress high-frequency workbench access lines while keeping diagnostic requests."""

    _REQUEST_RE = re.compile(r'"(?P<method>[A-Z]+)\s+(?P<path>[^ ?"]+)')
    _SUPPRESSED_GET_PATHS = {
        "/api/health",
        "/api/runtime/summary",
        "/api/runtime/events",
        "/api/git/status",
        "/api/control-token",
        "/api/config/public",
        "/api/pet/summary",
        "/api/files/tree",
        "/api/sessions",
        "/api/evolution/active-run",
        "/api/evolution/active-run/events",
        "/api/evolution/runs",
        "/api/evolution/library",
        "/api/evolution/overview",
        "/api/evolution/workbench",
    }
    _SUPPRESSED_POST_PATHS = {
        "/api/runtime/browser-telemetry",
    }

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        match = self._REQUEST_RE.search(message)
        if not match:
            return True
        method = match.group("method").upper()
        path = match.group("path")
        if method == "GET" and path in self._SUPPRESSED_GET_PATHS:
            return False
        if method == "POST" and path in self._SUPPRESSED_POST_PATHS:
            return False
        return True


HealthAccessLogFilter = WorkbenchAccessLogFilter


def enable_user_env_fallback_for_workbench() -> None:
    """Let Windows launcher-started backends resolve user-scoped API keys."""

    if os.name != "nt":
        return
    if os.environ.get(USER_ENV_FALLBACK_ENV):
        return
    os.environ[USER_ENV_FALLBACK_ENV] = "1"
    logging.getLogger("uvicorn.error").info("Enabled Windows user environment fallback for workbench API key lookup.")


def default_port() -> int:
    return configured_backend_port()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Launch the Vibelution web workbench")
    parser.add_argument("--host", default=DEFAULT_WORKBENCH_HOST)
    parser.add_argument("--port", type=int, default=default_port())
    parser.add_argument("--reload", action="store_true")
    parser.add_argument(
        "--open-browser",
        action="store_true",
        help="Open the workbench URL in the default browser. The desktop launcher owns browser windows by default.",
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Keep the server headless. Accepted for compatibility and takes precedence over --open-browser.",
    )
    parser.add_argument(
        "--managed-by-launcher",
        action="store_true",
        help="Mark this process as owned by the Vibelution launcher/runtime manager.",
    )
    args = parser.parse_args(argv)
    args.open_browser = bool(args.open_browser and not args.no_browser)
    return args


def install_access_log_filters() -> None:
    logger = logging.getLogger("uvicorn.access")
    if any(isinstance(existing, WorkbenchAccessLogFilter) for existing in logger.filters):
        return
    logger.addFilter(WorkbenchAccessLogFilter())


def open_runtime_scene_for_startup() -> dict[str, object]:
    """Open a fresh runtime scene for this backend start.

    Ported from the retired Python launcher path: every backend start seals the
    previous scene as ``orphan_reconciled`` and repoints
    ``active-runtime-scene.json`` at a new timestamped scene, which is what
    makes query-side retention (keep newest 30, protect the current scene)
    effective again. Retention runs after route readiness so it cannot delay
    health startup. Kept as a pure function so tests can run it against an
    isolated service root without starting uvicorn.
    """
    from core.web.services.runtime_scene.lifecycle import (
        BACKEND_STARTUP_TRIGGER,
        start_runtime_scene,
    )
    reference = start_runtime_scene(BACKEND_STARTUP_TRIGGER)
    return {"runtimeScene": reference}


def seal_runtime_scene_on_exit() -> None:
    """Best-effort seal of this process's runtime scene at interpreter exit.

    Skips when the pointer already moved to a newer scene (a fresh start owns
    it). Pure file operations: never blocks, never spawns a process, never
    opens a console. Crashes are covered by the next start's
    ``orphan_reconciled`` seal.
    """
    try:
        from core.web.services.runtime_scene import lifecycle

        started = _startup_runtime_scene_reference
        if started:
            try:
                payload = json.loads(
                    lifecycle._active_runtime_scene_pointer_path().read_text(encoding="utf-8-sig")
                )
            except (OSError, json.JSONDecodeError, ValueError):
                return
            if (
                not isinstance(payload, dict)
                or str(payload.get("runtimeSceneId") or "")
                != str(started.get("runtimeSceneId") or "")
            ):
                return
        lifecycle.seal_active_runtime_scene(
            "backend_exited", "Workbench backend process exited cleanly."
        )
    except Exception:
        pass


def bootstrap_runtime_scene_for_workbench() -> bool:
    """Startup wiring: open scene + graceful-exit seal (best-effort).

    Deliberately NOT wired into the FastAPI lifespan: TestClient triggers the
    lifespan, which would create runtime scenes in every service test. Only
    the real entrypoint (``main``) calls this. Any failure here degrades to no
    scene rotation; backend startup must proceed. Return whether the entrypoint
    should enable the lifespan-owned post-routes retention task.
    """
    global _startup_runtime_scene_reference
    try:
        result = open_runtime_scene_for_startup()
        scene = result.get("runtimeScene") if isinstance(result, dict) else None
        _startup_runtime_scene_reference = scene if isinstance(scene, dict) else None
    except Exception as exc:
        _startup_runtime_scene_reference = None
        logging.getLogger("uvicorn.error").warning("Runtime scene bootstrap skipped: %s", type(exc).__name__)
    try:
        atexit.register(seal_runtime_scene_on_exit)
    except Exception:
        pass
    return _startup_runtime_scene_reference is not None


def main() -> None:
    args = parse_args()
    url = f"http://{args.host}:{args.port}"
    if args.open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    enable_user_env_fallback_for_workbench()
    install_access_log_filters()
    scene_opened = bootstrap_runtime_scene_for_workbench()
    previous_retention_flag = os.environ.get(DEFER_RUNTIME_SCENE_RETENTION_ENV)
    os.environ[DEFER_RUNTIME_SCENE_RETENTION_ENV] = "1" if scene_opened else "0"
    try:
        uvicorn.run("core.web.app:app", host=args.host, port=args.port, reload=args.reload)
    finally:
        if previous_retention_flag is None:
            os.environ.pop(DEFER_RUNTIME_SCENE_RETENTION_ENV, None)
        else:
            os.environ[DEFER_RUNTIME_SCENE_RETENTION_ENV] = previous_retention_flag


if __name__ == "__main__":
    main()
