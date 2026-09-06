"""Focused public-contract coverage for low-churn Web route modules."""

from __future__ import annotations

from fastapi.responses import FileResponse
from fastapi.routing import APIRoute

from core.web.routes import (
    computer_use,
    conversations,
    data_processing,
    diagnostics,
    files,
    kernel,
    logs,
    pet,
    project_agent_bus,
    research_evidence,
    research_loop,
    reset,
    skills,
    team_templates,
    usage,
    user_content,
    workbench_ui,
)

ROUTE_MODULES = (
    computer_use,
    conversations,
    data_processing,
    diagnostics,
    files,
    kernel,
    logs,
    pet,
    project_agent_bus,
    research_evidence,
    research_loop,
    reset,
    skills,
    team_templates,
    usage,
    user_content,
    workbench_ui,
)


def test_public_route_modules_declare_explicit_response_contracts() -> None:
    for module in ROUTE_MODULES:
        routes = [
            route for route in module.router.routes if isinstance(route, APIRoute)
        ]
        assert routes, f"{module.__name__} must expose at least one API route"

        for route in routes:
            response_class = route.response_class
            if isinstance(response_class, type) and issubclass(
                response_class, FileResponse
            ):
                continue
            assert route.response_model is not None, (
                f"{module.__name__}:{route.path} must declare a response_model unless it returns FileResponse"
            )
