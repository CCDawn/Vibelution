"""Router registration for the Web workbench app."""

from __future__ import annotations

import importlib
from typing import Any

from fastapi import FastAPI

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


def import_web_route_modules(*, max_workers: int = 1) -> list[Any]:
    """Import route modules in stable order (serial; max_workers kept for API compatibility)."""

    del max_workers  # concurrent import is unsafe with circular service packages
    return [_import_route_module(name) for name in _ROUTE_MODULE_NAMES]


def register_web_routers_from_modules(app: FastAPI, modules: list[Any]) -> None:
    for module in modules:
        app.include_router(module.router, prefix="/api")


def register_web_routers(app: FastAPI) -> None:
    register_web_routers_from_modules(app, import_web_route_modules())
