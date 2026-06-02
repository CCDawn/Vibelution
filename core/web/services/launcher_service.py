"""Launcher lifecycle facade for the project bundle."""

from __future__ import annotations

from typing import Any

from core.runtime_manager import ensure_daemon_running, submit_command

from .i18n import get_web_language, text_for
from .runtime_scene_service import record_runtime_scene_event
from .runtime_service import (
    RuntimeRestartActiveWorkBlocked,
    get_runtime_summary,
    request_runtime_restart,
    request_runtime_shutdown,
)


def get_launcher_status() -> dict[str, Any]:
    """Return the launcher-facing project bundle lifecycle status."""

    runtime = get_runtime_summary()
    return {
        "launcher": {
            "mode": "runtime_manager_adapter",
            "phase": "phase_1a",
            "stableControlPlane": False,
            "message": text_for(
                get_web_language(),
                zh="Launcher 入口已建立，当前仍通过 runtime manager 适配层控制项目整体生命周期。",
                en="Launcher entrypoint is available and currently controls the project bundle through the runtime-manager adapter.",
            ),
        },
        "projectBundle": _project_bundle_from_runtime(runtime),
        "runtimeManager": runtime.get("runtimeManager") or {},
        "lifecycleProof": runtime.get("lifecycleProof") or {},
    }


def request_launcher_start() -> dict[str, Any]:
    """Request the managed project bundle to start."""

    _record_launcher_event(
        "launcher.bundle.start.requested",
        phase="start",
        message="Launcher project bundle start requested.",
        fields={"source": "launcher_api"},
    )
    try:
        ensure_daemon_running()
        command = submit_command(
            "open_workbench",
            args={"reason": "launcher_start_button", "source": "launcher_api", "noBrowser": False},
            requested_by="launcher_api",
        )
    except Exception as exc:
        _record_launcher_event(
            "launcher.bundle.start.failed",
            phase="start",
            message="Launcher project bundle start could not be queued.",
            outcome="failed",
            level="error",
            fields={"mode": "runtime_manager_adapter", "errorType": type(exc).__name__, "errorMessage": str(exc)},
        )
        raise

    command_id = str(command.get("commandId") or "")
    _record_launcher_event(
        "launcher.bundle.start.accepted",
        phase="start",
        message="Launcher project bundle start queued.",
        outcome="accepted",
        fields={"mode": "runtime_manager_adapter", "commandId": command_id},
    )
    return {
        "accepted": True,
        "mode": "runtime_manager_adapter",
        "commandId": command_id,
        "message": text_for(
            get_web_language(),
            zh="正在通过 Launcher 启动项目整体。",
            en="Starting the project bundle through Launcher.",
        ),
    }


def request_launcher_stop() -> dict[str, Any]:
    """Request the managed project bundle to stop."""

    _record_launcher_event(
        "launcher.bundle.stop.requested",
        phase="stop",
        message="Launcher project bundle stop requested.",
        fields={"source": "launcher_api"},
    )
    result = request_runtime_shutdown()
    _record_launcher_event(
        "launcher.bundle.stop.accepted",
        phase="stop",
        message="Launcher project bundle stop delegated to runtime shutdown.",
        outcome="accepted",
        fields={"mode": str(result.get("mode") or "runtime_manager_adapter")},
    )
    return {"launcherMode": "runtime_manager_adapter", **result}


def request_launcher_restart(*, confirmed_active_work: bool = False) -> dict[str, Any]:
    """Request the managed project bundle to restart as one lifecycle unit."""

    _record_launcher_event(
        "launcher.bundle.restart.requested",
        phase="restart",
        message="Launcher project bundle restart requested.",
        fields={"source": "launcher_api", "confirmedActiveWork": bool(confirmed_active_work)},
    )
    try:
        result = request_runtime_restart(confirmed_active_work=confirmed_active_work)
    except RuntimeRestartActiveWorkBlocked as exc:
        _record_launcher_event(
            "launcher.bundle.restart.blocked_active_work",
            phase="restart",
            message="Launcher project bundle restart blocked by active work.",
            outcome="blocked",
            level="warning",
            fields={"activeWorkCount": len(exc.active_work_runs), "activeWorkRuns": exc.active_work_runs[:8]},
        )
        raise

    _record_launcher_event(
        "launcher.bundle.restart.accepted",
        phase="restart",
        message="Launcher project bundle restart delegated to runtime manager.",
        outcome="accepted",
        fields={"mode": str(result.get("mode") or "runtime_manager_adapter"), "commandId": str(result.get("commandId") or "")},
    )
    return {"launcherMode": "runtime_manager_adapter", **result}


def _project_bundle_from_runtime(runtime: dict[str, Any]) -> dict[str, Any]:
    workbench = runtime.get("workbench") if isinstance(runtime.get("workbench"), dict) else {}
    lifecycle = runtime.get("lifecycleProof") if isinstance(runtime.get("lifecycleProof"), dict) else {}
    frontend_dist_ready = not bool(workbench.get("frontendOrphaned"))
    return {
        "id": "vibelution-project",
        "mode": "bundled",
        "desiredState": str(workbench.get("desiredState") or "closed"),
        "observedState": str(workbench.get("observedState") or "closed"),
        "phase": str(workbench.get("phase") or "steady"),
        "overallState": str(lifecycle.get("overallState") or ""),
        "statusLine": str(workbench.get("statusLine") or ""),
        "url": str(workbench.get("url") or ""),
        "lastReason": str(workbench.get("lastReason") or ""),
        "failureMessage": str(workbench.get("failureMessage") or ""),
        "backend": {
            "pid": int(workbench.get("backendPid") or 0),
            "alive": bool(workbench.get("backendAlive")),
            "healthy": bool(workbench.get("backendHealthy")),
            "port": int(workbench.get("backendPort") or 0),
            "portListening": bool(workbench.get("backendPortListening")),
            "portOwnerPid": int(workbench.get("backendPortOwnerPid") or 0),
            "portConflict": bool(workbench.get("backendPortConflict")),
        },
        "frontend": {
            "mode": "bundled_static_dist",
            "distReady": frontend_dist_ready,
            "orphaned": bool(workbench.get("frontendOrphaned")),
        },
        "browser": {
            "managed": bool(workbench.get("browserManaged", True)),
            "windowPid": int(workbench.get("browserWindowPid") or 0),
            "alive": bool(workbench.get("browserWindowAlive")),
        },
    }


def _record_launcher_event(
    event_code: str,
    *,
    phase: str,
    message: str,
    outcome: str = "observed",
    level: str = "info",
    fields: dict[str, object] | None = None,
) -> None:
    try:
        record_runtime_scene_event(
            "launcher",
            phase,
            event_code,
            message=message,
            level=level,
            outcome=outcome,
            fields=fields or {},
            lifecycle=True,
        )
    except Exception:
        return
