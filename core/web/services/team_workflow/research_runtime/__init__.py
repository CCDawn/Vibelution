"""Research workflow runtime web facade (LangGraph authority)."""

from importlib import import_module
from typing import Any

__all__ = [
    "ResearchWorkflowRuntimeService",
    "get_research_workflow_runtime_service",
]


def __getattr__(name: str) -> Any:
    # Importing paths/contracts must not initialize the service dependency graph.
    if name not in __all__:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(".service", __name__), name)
    globals()[name] = value
    return value
