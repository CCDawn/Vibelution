"""Compatibility facade for the standalone Launcher service.

The Launcher control plane lives under ``core.launcher``.  This module keeps the
existing Web route imports stable while preventing Launcher lifecycle logic from
depending on ``core.web.services.runtime_service``.
"""

from __future__ import annotations

from core.launcher.service import (
    LauncherActiveWorkBlocked,
    LauncherCommandResponse,
    LauncherSupervisorCommandResponse,
    get_launcher_status,
    launcher_active_work_runs,
    request_launcher_restart,
    request_launcher_start,
    request_launcher_stop,
    request_launcher_supervisor_reattach,
)

__all__ = [
    "LauncherActiveWorkBlocked",
    "LauncherCommandResponse",
    "LauncherSupervisorCommandResponse",
    "get_launcher_status",
    "launcher_active_work_runs",
    "request_launcher_restart",
    "request_launcher_start",
    "request_launcher_stop",
    "request_launcher_supervisor_reattach",
]
