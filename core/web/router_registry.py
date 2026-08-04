"""Router registration for the Web workbench app."""

from __future__ import annotations

import importlib
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from fastapi import FastAPI

# Import order is preserved for include_router; modules load concurrently.
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


def import_web_route_modules(*, max_workers: int = 8) -> list[Any]:
    """Import route modules, preferring concurrent loads to cut cold-start wall time."""

    workers = max(1, min(int(max_workers or 1), len(_ROUTE_MODULE_NAMES)))
    if workers == 1 or len(_ROUTE_MODULE_NAMES) <= 1:
        return [_import_route_module(name) for name in _ROUTE_MODULE_NAMES]

    modules_by_name: dict[str, Any] = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_import_route_module, name): name for name in _ROUTE_MODULE_NAMES}
        for future, name in futures.items():
            modules_by_name[name] = future.result()
    return [modules_by_name[name] for name in _ROUTE_MODULE_NAMES]


def register_web_routers(app: FastAPI) -> None:
    for module in import_web_route_modules():
        app.include_router(module.router, prefix="/api")
