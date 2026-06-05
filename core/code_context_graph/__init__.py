"""Project-wide code context graph helpers."""

from typing import Any


def code_context_graph_tool(**kwargs: Any) -> dict[str, Any]:
    from . import service

    return service.code_context_graph_tool(**kwargs)

__all__ = ["code_context_graph_tool"]
