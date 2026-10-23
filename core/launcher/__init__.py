"""Launcher public API, loaded only when a service export is requested."""

from __future__ import annotations

from importlib import import_module as _import_module
from typing import Any as _Any


_EXPORT_GROUPS = {
    '.service': (
        'DeveloperCleanupPlanError', 'DeveloperModeDisabled', 'LauncherActiveWorkBlocked',
        'apply_launcher_developer_cleanup', 'get_launcher_developer_mode_setting', 'get_launcher_developer_noise_overview',
        'get_launcher_status', 'launcher_active_work_runs', 'preview_launcher_developer_cleanup',
        'reset_launcher_developer_sandbox', 'update_launcher_developer_mode',
    ),
}
_EXPORTS = {name: module for module, names in _EXPORT_GROUPS.items() for name in names}
__all__ = [
    'DeveloperCleanupPlanError',
    'DeveloperModeDisabled',
    'LauncherActiveWorkBlocked',
    'apply_launcher_developer_cleanup',
    'get_launcher_developer_mode_setting',
    'get_launcher_developer_noise_overview',
    'get_launcher_status',
    'launcher_active_work_runs',
    'preview_launcher_developer_cleanup',
    'reset_launcher_developer_sandbox',
    'update_launcher_developer_mode',
]


def __getattr__(name: str) -> _Any:
    module_name = _EXPORTS.get(name)
    if module_name is None:
        # Let Python resolve real submodules through its normal import fallback.
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(_import_module(module_name, __name__), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()).union(_EXPORTS))
