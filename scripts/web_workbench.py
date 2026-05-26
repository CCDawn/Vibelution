#!/usr/bin/env python3
"""Launch the local Vibelution web workbench."""

from __future__ import annotations

import argparse
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


def main() -> None:
    args = parse_args()
    url = f"http://{args.host}:{args.port}"
    if args.open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    install_access_log_filters()
    uvicorn.run("core.web.app:app", host=args.host, port=args.port, reload=args.reload)


if __name__ == "__main__":
    main()
