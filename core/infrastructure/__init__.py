"""Infrastructure exports, loaded when requested by their consumer.

Low-level helpers (atomic I/O, Git and sandbox paths) also live in this package.
Importing them must not load model discovery, HTTP clients or tool execution.
"""

from __future__ import annotations

from importlib import import_module as _import_module
from typing import Any as _Any


_EXPORT_GROUPS = {
    ".tool_executor": ("ToolExecutor", "get_tool_executor"),
    ".state": ("AgentState", "StateManager", "get_state_manager"),
    ".event_bus": ("EventBus", "EventNames", "get_event_bus"),
    ".security": ("SecurityValidator", "get_security_validator"),
    ".model_discovery": ("ModelDiscovery", "DiscoveryStatus", "ModelInfo", "CompressionThresholds"),
    ".workspace_manager": ("WorkspaceManager", "get_workspace"),
    ".tool_result": ("truncate_result",),
    ".agent_session": ("AgentSessionState", "get_session_state"),
    ".background_tasks": ("BackgroundTaskManager", "get_background_task_manager"),
    ".cron_scheduler": ("CronScheduler", "get_cron_scheduler"),
    ".llm_utils": ("classify_llm_error", "build_system_message", "MAX_CONSECUTIVE_FAILURES"),
    ".mental_model": ("MentalModel", "CognitiveState", "Diagnosis", "ToolRecord", "get_mental_model", "reset_mental_model"),
    ".workspace_cleaner": (
        "classify_file", "scan_workspace_debris", "clean_debris", "auto_clean_session_debris",
        "list_workspace_debris_tool", "clean_workspace_debris_tool", "get_session_files_tool",
    ),
}
_EXPORTS = {name: module for module, names in _EXPORT_GROUPS.items() for name in names}
__all__ = list(_EXPORTS)


def __getattr__(name: str) -> _Any:
    module_name = _EXPORTS.get(name)
    if module_name is None:
        # Preserve Python's normal submodule import fallback for low-level
        # helpers such as `from core.infrastructure import atomic_io`.
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(_import_module(module_name, __name__), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()).union(_EXPORTS))
