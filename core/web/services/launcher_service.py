"""Launcher lifecycle facade for the project bundle."""

from __future__ import annotations

import json
from typing import Any, Literal, TypedDict

from core.runtime_manager import ensure_daemon_running, submit_command
from core.runtime_manager.constants import LAUNCHER_STATE_PATH
from core.runtime_manager.workbench_controller import _is_process_alive

from .i18n import get_web_language, text_for
from .runtime_scene_service import record_runtime_scene_event
from .runtime_service import (
    RuntimeRestartActiveWorkBlocked,
    get_runtime_summary,
    request_runtime_restart,
    request_runtime_shutdown,
)


LauncherOperation = Literal["start", "stop", "restart"]
LauncherSupervisorOperation = Literal["supervisor_reattach"]


class LauncherCommandResponse(TypedDict, total=False):
    accepted: bool
    mode: str
    launcherMode: str
    commandId: str
    operation: LauncherOperation
    message: str
    chatTurns: list[dict[str, object]]
    chatRoomRounds: list[dict[str, object]]
    evolutionRuns: list[dict[str, object]]


class LauncherSupervisorCommandResponse(TypedDict, total=False):
    accepted: bool
    mode: str
    launcherMode: str
    commandId: str
    operation: LauncherSupervisorOperation
    message: str
    blockedReason: str
    blockers: list[str]


def get_launcher_status() -> dict[str, Any]:
    """Return the launcher-facing project bundle lifecycle status."""

    runtime = get_runtime_summary()
    return {
        "launcher": {
            "mode": "runtime_manager_adapter",
            "phase": "phase_1b",
            "stableControlPlane": False,
            "controlPlane": {
                "independent": False,
                "adapter": "runtime_manager",
                "nextPhase": "standalone_launcher_process",
            },
            "message": text_for(
                get_web_language(),
                zh="Launcher 入口已建立，当前仍通过 runtime manager 适配层控制项目整体生命周期。",
                en="Launcher entrypoint is available and currently controls the project bundle through the runtime-manager adapter.",
            ),
        },
        "projectBundle": _project_bundle_from_runtime(runtime),
        "guardianAdapter": _guardian_adapter_from_runtime(runtime),
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
        "launcherMode": "runtime_manager_adapter",
        "operation": "start",
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
    return _launcher_command_response("stop", result)


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
    return _launcher_command_response("restart", result)


def request_launcher_supervisor_reattach() -> LauncherSupervisorCommandResponse:
    """Request the legacy launcher adapter to reattach supervisor for a live bundle."""

    runtime = get_runtime_summary()
    state = _load_launcher_state()
    supervisor = _launcher_supervisor_snapshot()
    blockers = _launcher_supervisor_reattach_blockers(runtime=runtime, state=state, supervisor=supervisor)
    _record_launcher_event(
        "launcher.supervisor.reattach.requested",
        phase="supervisor",
        message="Launcher supervisor reattach requested.",
        fields={
            "source": "launcher_api",
            "supervisorPid": int(supervisor.get("pid") or 0),
            "supervisorAlive": bool(supervisor.get("alive")),
            "blockers": blockers,
        },
    )
    if blockers:
        blocked_reason = "; ".join(blockers)
        _record_launcher_event(
            "launcher.supervisor.reattach.blocked",
            phase="supervisor",
            message="Launcher supervisor reattach blocked by guard checks.",
            outcome="blocked",
            level="warning",
            fields={"source": "launcher_api", "blockers": blockers},
        )
        return {
            "accepted": False,
            "mode": "runtime_manager_adapter",
            "launcherMode": "runtime_manager_adapter",
            "operation": "supervisor_reattach",
            "message": text_for(
                get_web_language(),
                zh=f"Supervisor 重新接管未提交：{blocked_reason}",
                en=f"Supervisor reattach was not queued: {blocked_reason}",
            ),
            "blockedReason": blocked_reason,
            "blockers": blockers,
        }

    try:
        ensure_daemon_running()
        command = submit_command(
            "open_workbench",
            args={"reason": "launcher_supervisor_reattach", "source": "launcher_api", "noBrowser": False},
            requested_by="launcher_api",
        )
    except Exception as exc:
        _record_launcher_event(
            "launcher.supervisor.reattach.failed",
            phase="supervisor",
            message="Launcher supervisor reattach could not be queued.",
            outcome="failed",
            level="error",
            fields={"mode": "runtime_manager_adapter", "errorType": type(exc).__name__, "errorMessage": str(exc)},
        )
        raise

    command_id = str(command.get("commandId") or "")
    _record_launcher_event(
        "launcher.supervisor.reattach.accepted",
        phase="supervisor",
        message="Launcher supervisor reattach queued through the workbench adapter.",
        outcome="accepted",
        fields={"mode": "runtime_manager_adapter", "commandId": command_id},
    )
    return {
        "accepted": True,
        "mode": "runtime_manager_adapter",
        "launcherMode": "runtime_manager_adapter",
        "operation": "supervisor_reattach",
        "commandId": command_id,
        "message": text_for(
            get_web_language(),
            zh="已请求 Launcher 重新接管 supervisor。",
            en="Launcher supervisor reattach has been requested.",
        ),
    }


def _project_bundle_from_runtime(runtime: dict[str, Any]) -> dict[str, Any]:
    workbench = runtime.get("workbench") if isinstance(runtime.get("workbench"), dict) else {}
    lifecycle = runtime.get("lifecycleProof") if isinstance(runtime.get("lifecycleProof"), dict) else {}
    frontend_dist_ready = not bool(workbench.get("frontendOrphaned"))
    backend_component = _component_state(
        "backend",
        ok=bool(workbench.get("backendHealthy")) and not bool(workbench.get("backendPortConflict")),
        state="running" if bool(workbench.get("backendAlive")) else "stopped",
        required_for_running=True,
        pid=int(workbench.get("backendPid") or 0),
        detail=str(workbench.get("failureMessage") or ""),
    )
    frontend_component = _component_state(
        "frontend",
        ok=frontend_dist_ready,
        state="ready" if frontend_dist_ready else "orphaned",
        required_for_running=True,
        pid=0,
        detail="",
    )
    browser_component = _component_state(
        "browser",
        ok=bool(workbench.get("browserWindowAlive")) or not bool(workbench.get("browserManaged", True)),
        state="running" if bool(workbench.get("browserWindowAlive")) else "stopped",
        required_for_running=bool(workbench.get("browserManaged", True)),
        pid=int(workbench.get("browserWindowPid") or 0),
        detail="",
    )
    return {
        "schemaVersion": 1,
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
        "lastOperation": {
            "reason": str(workbench.get("lastReason") or ""),
            "source": str(workbench.get("lastSource") or ""),
            "transitionAt": str(workbench.get("lastTransitionAt") or ""),
        },
        "components": [backend_component, frontend_component, browser_component],
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


def _guardian_adapter_from_runtime(runtime: dict[str, Any]) -> dict[str, Any]:
    runtime_manager = runtime.get("runtimeManager") if isinstance(runtime.get("runtimeManager"), dict) else {}
    workbench = runtime.get("workbench") if isinstance(runtime.get("workbench"), dict) else {}
    lifecycle = runtime.get("lifecycleProof") if isinstance(runtime.get("lifecycleProof"), dict) else {}
    supervisor = _launcher_supervisor_snapshot()
    manager_running = bool(runtime_manager.get("running"))
    manager_pid = int(runtime_manager.get("managerPid") or 0)
    browser_managed = bool(workbench.get("browserManaged", True))
    responsibilities = [
        _guardian_responsibility(
            "project_bundle_lifecycle",
            owner="launcher_api",
            adapter="runtime_manager",
            status="active",
            detail="Launcher API owns the project-bundle lifecycle command facade; execution still goes through runtime manager commands.",
        ),
        _guardian_responsibility(
            "runtime_manager_daemon",
            owner="runtime_manager",
            adapter="runtime_manager",
            status="running" if manager_running else "offline",
            detail=f"Runtime manager daemon pid={manager_pid}." if manager_running else "Runtime manager daemon is not observed as running.",
        ),
        _guardian_responsibility(
            "desktop_supervisor",
            owner="powershell_launcher",
            adapter="vibelution_launcher.ps1",
            status=str(supervisor.get("status") or "unknown"),
            detail=str(supervisor.get("detail") or ""),
        ),
        _guardian_responsibility(
            "backend_process",
            owner="powershell_launcher",
            adapter="vibelution_launcher.ps1",
            status="running" if bool(workbench.get("backendAlive")) else "observed",
            detail="Backend process ownership is inferred from launcher state and port observation.",
        ),
        _guardian_responsibility(
            "browser_window",
            owner="powershell_launcher",
            adapter="vibelution_launcher.ps1",
            status="managed" if browser_managed else "external",
            detail="Browser lifecycle remains managed by the legacy launcher until standalone Launcher owns the window controller.",
        ),
        _guardian_responsibility(
            "runtime_scene_logging",
            owner="runtime_scene_service",
            adapter="runtime_scene",
            status="active" if lifecycle else "partial",
            detail="Lifecycle evidence is written through runtime scene helpers and existing launcher logs.",
        ),
    ]
    return {
        "schemaVersion": 1,
        "mode": "adapter_migration",
        "targetMode": "standalone_launcher_guardian",
        "statusLine": text_for(
            get_web_language(),
            zh="守护职责正在归并到 Launcher；当前 supervisor、浏览器窗口和后端进程仍由旧启动器适配层承载。",
            en="Guardian responsibilities are being folded into Launcher; supervisor, browser window, and backend process ownership still run through the legacy launcher adapter.",
        ),
        "ownedCount": sum(1 for item in responsibilities if item["owner"] in {"launcher_api", "runtime_scene_service"}),
        "adapterCount": sum(1 for item in responsibilities if item["owner"] not in {"launcher_api", "runtime_scene_service"}),
        "supervisor": supervisor,
        "responsibilities": responsibilities,
    }


def _launcher_supervisor_snapshot() -> dict[str, Any]:
    state = _load_launcher_state()
    supervisor_pid = int(state.get("supervisorPid") or 0)
    alive = _is_process_alive(supervisor_pid)
    stdout_path = str(state.get("supervisorStdout") or "").strip()
    stderr_path = str(state.get("supervisorStderr") or "").strip()
    runtime_scene_id = str(state.get("runtimeSceneId") or "").strip()
    runtime_scene_dir = str(state.get("runtimeSceneDir") or "").strip()
    status = "running" if alive else "stopped" if supervisor_pid > 0 else "not_started"
    if not state:
        detail = "Launcher state is unavailable; supervisor health cannot be observed yet."
    elif alive:
        detail = f"Supervisor process is alive pid={supervisor_pid}."
    elif supervisor_pid > 0:
        detail = f"Supervisor pid={supervisor_pid} is recorded but no longer alive."
    else:
        detail = "Supervisor process has not been recorded in launcher state."
    return {
        "pid": supervisor_pid,
        "alive": alive,
        "status": status,
        "stdoutPath": stdout_path,
        "stderrPath": stderr_path,
        "runtimeSceneId": runtime_scene_id,
        "runtimeSceneDir": runtime_scene_dir,
        "detail": detail,
    }


def _load_launcher_state() -> dict[str, Any]:
    try:
        payload = json.loads(LAUNCHER_STATE_PATH.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _launcher_supervisor_reattach_blockers(
    *,
    runtime: dict[str, Any],
    state: dict[str, Any],
    supervisor: dict[str, Any],
) -> list[str]:
    blockers: list[str] = []
    workbench = runtime.get("workbench") if isinstance(runtime.get("workbench"), dict) else {}
    if not state:
        blockers.append("launcher_state_missing")
    if not str(state.get("sessionId") or "").strip():
        blockers.append("session_id_missing")
    if not str(state.get("runtimeSceneId") or "").strip() or not str(state.get("runtimeSceneDir") or "").strip():
        blockers.append("runtime_scene_missing")
    if bool(supervisor.get("alive")):
        blockers.append("supervisor_already_alive")
    if not bool(workbench.get("backendAlive")):
        blockers.append("backend_not_alive")
    if not bool(workbench.get("backendHealthy")):
        blockers.append("backend_not_healthy")
    if str(workbench.get("observedState") or "").strip().lower() != "open":
        blockers.append("workbench_not_open")
    if not bool(workbench.get("browserWindowAlive")):
        blockers.append("browser_window_not_alive")
    return blockers


def _guardian_responsibility(
    responsibility_id: str,
    *,
    owner: str,
    adapter: str,
    status: str,
    detail: str,
) -> dict[str, object]:
    return {
        "id": responsibility_id,
        "owner": owner,
        "adapter": adapter,
        "status": status,
        "detail": detail,
    }


def _component_state(
    component_id: str,
    *,
    ok: bool,
    state: str,
    required_for_running: bool,
    pid: int,
    detail: str,
) -> dict[str, object]:
    return {
        "id": component_id,
        "ok": bool(ok),
        "state": str(state or "unknown"),
        "requiredForRunning": bool(required_for_running),
        "pid": int(pid or 0),
        "detail": str(detail or ""),
    }


def _launcher_command_response(operation: LauncherOperation, result: dict[str, Any]) -> LauncherCommandResponse:
    payload: LauncherCommandResponse = {
        "accepted": bool(result.get("accepted")),
        "mode": str(result.get("mode") or "runtime_manager_adapter"),
        "launcherMode": "runtime_manager_adapter",
        "operation": operation,
        "message": str(result.get("message") or ""),
    }
    command_id = str(result.get("commandId") or "").strip()
    if command_id:
        payload["commandId"] = command_id
    for key in ("chatTurns", "chatRoomRounds", "evolutionRuns"):
        value = result.get(key)
        if isinstance(value, list):
            payload[key] = value
    return payload


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
