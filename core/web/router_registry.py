"""Router registration for the Web workbench app."""

from __future__ import annotations

import importlib
import logging
import time
from collections.abc import Callable
from typing import Any

from fastapi import FastAPI

# uvicorn.error is configured by the workbench entrypoint, so per-module import
# timings reach backend.stderr.log even before route modules are mounted.
logger = logging.getLogger("uvicorn.error")

# Stable include order. Imports stay single-threaded: concurrent importlib of
# interdependent route/service packages deadlocks on module locks (CPython).
_ROUTE_MODULE_NAMES: tuple[str, ...] = (
    "core.web.routes.runtime",
    "core.web.routes.launcher",
    "core.web.routes.workbench_ui",
    "core.web.routes.agents",
    "core.web.routes.conversations",
    "core.web.routes.sessions",
    "core.web.routes.chat_rooms",
    "core.web.routes.cli_agents",
    "core.web.routes.project_agent_bus",
    "core.web.routes.external_agent",
    "core.web.routes.kernel",
    "core.web.routes.team_templates",
    "core.web.routes.teams",
    "core.web.routes.team_workflows",
    "core.web.routes.skills",
    "core.web.routes.tools",
    "core.web.routes.computer_use",
    "core.web.routes.files",
    "core.web.routes.git",
    "core.web.routes.data_processing",
    "core.web.routes.knowledge",
    "core.web.routes.logs",
    "core.web.routes.usage",
    "core.web.routes.memory",
    "core.web.routes.user_content",
    "core.web.routes.research",
    "core.web.routes.research_evidence",
    "core.web.routes.research_loop",
    "core.web.routes.diagnostics",
    "core.web.routes.evolution",
    "core.web.routes.config",
    "core.web.routes.reset",
    "core.web.routes.pet",
)


def _import_route_module(module_name: str) -> Any:
    return importlib.import_module(module_name)


def import_web_route_modules(
    *,
    max_workers: int = 1,
    on_module_imported: Callable[[str, float], None] | None = None,
) -> list[Any]:
    """Import route modules in stable order (serial; max_workers kept for API compatibility)."""

    del max_workers  # concurrent import is unsafe with circular service packages
    modules: list[Any] = []
    for name in _ROUTE_MODULE_NAMES:
        started = time.perf_counter()
        module = _import_route_module(name)
        duration_ms = max(0.0, (time.perf_counter() - started) * 1000.0)
        if on_module_imported is not None:
            on_module_imported(name, duration_ms)
        logger.info("web route module imported: %s (%.1fms)", name, duration_ms)
        modules.append(module)
    return modules


def register_web_routers_from_modules(app: FastAPI, modules: list[Any]) -> None:
    for module in modules:
        app.include_router(module.router, prefix="/api")


def register_web_routers(app: FastAPI) -> None:
    register_web_routers_from_modules(app, import_web_route_modules())
