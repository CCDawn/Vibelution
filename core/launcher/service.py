"""Standalone Launcher service for the managed Vibelution project bundle."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal, TypedDict

from core.runtime_manager import ensure_daemon_running, submit_command
from core.runtime_manager.constants import (
    EVENTS_PATH,
    INBOX_DIR,
    LAUNCHER_STATE_PATH,
    PROCESSING_DIR,
    PROJECT_ROOT,
    RESULTS_DIR,
    STATE_PATH,
)
from core.runtime_manager.evolution_store import load_active_run_snapshot
from core.runtime_manager.scene_logging import append_runtime_manager_file_event
from core.runtime_manager.state_store import load_pid, load_state
from core.runtime_manager import work_run_store
from core.runtime_manager.work_run_store import WorkRunStore
from core.runtime_manager.workbench_controller import _is_process_alive, observe_workbench


LauncherOperation = Literal["start", "stop", "restart"]
LauncherSupervisorOperation = Literal["supervisor_reattach"]

ACTIVE_WORK_BLOCK_MESSAGE_RESTART = "有进行中的任务，无法重启 Vibelution。请等待任务完成或先停止任务。"
ACTIVE_WORK_BLOCK_MESSAGE_STOP = "有进行中的任务，无法停止 Vibelution。请等待任务完成或先停止任务。"
_ACTIVE_WORK_BLOCKING_STATUSES = {
    "",
    "active",
    "queued",
    "running",
    "stopping",
    "started",
    "in_progress",
    "pausing",
    "resuming",
    "force_stopping",
}
_ACTIVE_WORK_NON_BLOCKING_STATUSES = {
    "cancelled",
    "closed",
    "completed",
    "done",
    "failed",
    "failed_provider",
    "failed_runtime",
    "idle",
    "needs_continue",
    "partial",
    "paused_limit",
    "ready",
    "routed",
    "stopped",
    "stopped_by_user",
    "stop_failed",
    "superseded",
}
_ACTIVE_WORK_KINDS = (
    "chat_turn",
    "chat_room_round",
    "self_evolution_run",
    "supervised_evolution_run",
    "supervised_worktree_evolution_run",
)
_STALE_SNAPSHOT_GRACE = timedelta(hours=6)


class LauncherActiveWorkBlocked(Exception):
    """Raised when a Launcher lifecycle command would interrupt active work."""

    def __init__(self, message: str, active_work_runs: list[dict[str, str]]) -> None:
        super().__init__(message)
        self.message = message
        self.active_work_runs = active_work_runs


class LauncherCommandResponse(TypedDict, total=False):
    accepted: bool
    mode: str
    launcherMode: str
    commandId: str
    operation: LauncherOperation
    message: str
    activeWorkRuns: list[dict[str, str]]


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
    """Return standalone Launcher status without importing the Web service layer."""

    runtime_state = _runtime_manager_state()
    launcher_state = _load_launcher_state()
    observed_workbench = _observed_workbench()
    workbench = _workbench_payload(runtime_state=runtime_state, observed_workbench=observed_workbench)
    active_work_runs = launcher_active_work_runs()
    runtime_manager = _runtime_manager_payload(runtime_state)
    lifecycle_proof = _lifecycle_proof(
        runtime_manager=runtime_manager,
        workbench=workbench,
        active_work_runs=active_work_runs,
    )
    return {
        "launcher": {
            "mode": "standalone_control_plane",
            "phase": "phase_2a",
            "stableControlPlane": True,
            "controlPlane": {
                "independent": True,
                "adapter": "runtime_manager",
                "nextPhase": "standalone_launcher_frontend",
            },
            "message": "Launcher 已作为独立控制面运行；项目工作台前后端现在是被管理对象。",
        },
        "projectBundle": _project_bundle_from_workbench(workbench, lifecycle_proof=lifecycle_proof, launcher_state=launcher_state),
        "controlPlaneEvidence": _control_plane_evidence(),
        "guardianAdapter": _guardian_adapter_from_workbench(runtime_manager=runtime_manager, workbench=workbench),
        "runtimeManager": runtime_manager,
        "lifecycleProof": lifecycle_proof,
    }


def launcher_active_work_runs() -> list[dict[str, str]]:
    """Return active project work from runtime-manager-owned files only."""

    items: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    store = WorkRunStore(root=work_run_store.WORK_RUNS_DIR)
    for kind in ("chat_turn", "chat_room_round", "supervised_worktree_evolution_run"):
        active_run_id = str(store.load_run_index(kind).get("activeRunId") or "").strip()
        for payload in store.list_snapshots(kind):
            _append_active_work_run(
                items,
                seen,
                kind=kind,
                payload=payload,
                force_current=str(payload.get("runId") or "").strip() == active_run_id,
            )

    for kind, storage_kind in (
        ("self_evolution_run", "self"),
        ("supervised_evolution_run", "supervised"),
    ):
        try:
            payload = load_active_run_snapshot(storage_kind)
        except Exception:
            payload = None
        _append_active_work_run(items, seen, kind=kind, payload=payload)

    return items


def request_launcher_start() -> LauncherCommandResponse:
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
            fields={"mode": "standalone_control_plane", "errorType": type(exc).__name__, "errorMessage": str(exc)},
        )
        raise

    command_id = str(command.get("commandId") or "")
    _record_launcher_event(
        "launcher.bundle.start.accepted",
        phase="start",
        message="Launcher project bundle start queued.",
        outcome="accepted",
        fields={"mode": "standalone_control_plane", "commandId": command_id},
    )
    return {
        "accepted": True,
        "mode": "runtime_manager",
        "launcherMode": "standalone_control_plane",
        "operation": "start",
        "commandId": command_id,
        "message": "正在通过 Launcher 启动项目整体。",
    }


def request_launcher_stop() -> LauncherCommandResponse:
    """Request the managed project bundle to stop, blocked by active work."""

    _record_launcher_event(
        "launcher.bundle.stop.requested",
        phase="stop",
        message="Launcher project bundle stop requested.",
        fields={"source": "launcher_api"},
    )
    _raise_if_active_work("stop")
    try:
        ensure_daemon_running()
        command = submit_command(
            "close_workbench",
            args={"reason": "launcher_stop_button", "source": "launcher_api", "stopManager": False},
            requested_by="launcher_api",
        )
    except Exception as exc:
        _record_launcher_event(
            "launcher.bundle.stop.failed",
            phase="stop",
            message="Launcher project bundle stop could not be queued.",
            outcome="failed",
            level="error",
            fields={"mode": "standalone_control_plane", "errorType": type(exc).__name__, "errorMessage": str(exc)},
        )
        raise

    command_id = str(command.get("commandId") or "")
    _record_launcher_event(
        "launcher.bundle.stop.accepted",
        phase="stop",
        message="Launcher project bundle stop queued through runtime manager.",
        outcome="accepted",
        fields={"mode": "standalone_control_plane", "commandId": command_id},
    )
    return {
        "accepted": True,
        "mode": "runtime_manager",
        "launcherMode": "standalone_control_plane",
        "operation": "stop",
        "commandId": command_id,
        "message": "正在关闭项目工作台，Launcher 控制面会保持可再次启动。",
    }


def request_launcher_restart() -> LauncherCommandResponse:
    """Request the managed project bundle to restart as one lifecycle unit."""

    _record_launcher_event(
        "launcher.bundle.restart.requested",
        phase="restart",
        message="Launcher project bundle restart requested.",
        fields={"source": "launcher_api"},
    )
    _raise_if_active_work("restart")
    try:
        ensure_daemon_running()
        command = submit_command(
            "restart_workbench",
            args={"reason": "launcher_restart_button", "source": "launcher_api", "noBrowser": False},
            requested_by="launcher_api",
        )
    except Exception as exc:
        _record_launcher_event(
            "launcher.bundle.restart.failed",
            phase="restart",
            message="Launcher project bundle restart could not be queued.",
            outcome="failed",
            level="error",
            fields={"mode": "standalone_control_plane", "errorType": type(exc).__name__, "errorMessage": str(exc)},
        )
        raise

    command_id = str(command.get("commandId") or "")
    _record_launcher_event(
        "launcher.bundle.restart.accepted",
        phase="restart",
        message="Launcher project bundle restart queued through runtime manager.",
        outcome="accepted",
        fields={"mode": "standalone_control_plane", "commandId": command_id},
    )
    return {
        "accepted": True,
        "mode": "runtime_manager",
        "launcherMode": "standalone_control_plane",
        "operation": "restart",
        "commandId": command_id,
        "message": "正在安全重启工作台。运行时管理器会先停稳旧后端，再重新拉起前后端。",
    }


def request_launcher_supervisor_reattach() -> LauncherSupervisorCommandResponse:
    """Request the legacy desktop supervisor to reattach for a live bundle."""

    runtime_state = _runtime_manager_state()
    launcher_state = _load_launcher_state()
    workbench = _workbench_payload(runtime_state=runtime_state, observed_workbench=_observed_workbench())
    supervisor = _launcher_supervisor_snapshot()
    blockers = _launcher_supervisor_reattach_blockers(
        state=launcher_state,
        supervisor=supervisor,
        workbench=workbench,
    )
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
            "mode": "runtime_manager",
            "launcherMode": "standalone_control_plane",
            "operation": "supervisor_reattach",
            "message": f"Supervisor 重新接管未提交：{blocked_reason}",
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
            fields={"mode": "standalone_control_plane", "errorType": type(exc).__name__, "errorMessage": str(exc)},
        )
        raise

    command_id = str(command.get("commandId") or "")
    _record_launcher_event(
        "launcher.supervisor.reattach.accepted",
        phase="supervisor",
        message="Launcher supervisor reattach queued through the runtime manager.",
        outcome="accepted",
        fields={"mode": "standalone_control_plane", "commandId": command_id},
    )
    return {
        "accepted": True,
        "mode": "runtime_manager",
        "launcherMode": "standalone_control_plane",
        "operation": "supervisor_reattach",
        "commandId": command_id,
        "message": "已请求 Launcher 重新接管 supervisor。",
    }


def _raise_if_active_work(operation: Literal["stop", "restart"]) -> None:
    active_work_runs = launcher_active_work_runs()
    if not active_work_runs:
        return
    message = ACTIVE_WORK_BLOCK_MESSAGE_RESTART if operation == "restart" else ACTIVE_WORK_BLOCK_MESSAGE_STOP
    _record_launcher_event(
        f"launcher.bundle.{operation}.blocked_active_work",
        phase=operation,
        message=f"Launcher project bundle {operation} blocked by active work.",
        outcome="blocked",
        level="warning",
        fields={"activeWorkCount": len(active_work_runs), "activeWorkRuns": active_work_runs[:8]},
    )
    raise LauncherActiveWorkBlocked(message, active_work_runs[:8])


def _runtime_manager_state() -> dict[str, Any]:
    try:
        state = load_state()
    except Exception:
        state = {}
    payload = dict(state) if isinstance(state, dict) else {}
    try:
        manager_pid = load_pid()
        manager_running = _is_process_alive(manager_pid)
    except Exception:
        manager_pid = 0
        manager_running = False
    if not manager_running:
        manager_pid = 0
    payload["daemonRunning"] = manager_running
    payload["managerPid"] = int(manager_pid or 0)
    payload.setdefault("projectRoot", str(PROJECT_ROOT))
    return payload


def _observed_workbench() -> dict[str, Any]:
    try:
        observed = observe_workbench()
    except Exception:
        return {}
    return observed if isinstance(observed, dict) else {}


def _workbench_payload(*, runtime_state: dict[str, Any], observed_workbench: dict[str, Any]) -> dict[str, Any]:
    state_workbench = runtime_state.get("workbench") if isinstance(runtime_state.get("workbench"), dict) else {}
    observed = observed_workbench if isinstance(observed_workbench, dict) else {}
    desired_state = str(state_workbench.get("desiredState") or "closed").strip() or "closed"
    observed_state = str(observed.get("observedState") or state_workbench.get("observedState") or "closed").strip() or "closed"
    phase = str(state_workbench.get("phase") or "steady").strip() or "steady"
    if observed_state == desired_state and phase != "failed":
        phase = "steady"
    elif desired_state == "open" and observed_state != "open" and phase != "failed":
        phase = "opening"
    elif desired_state == "closed" and observed_state != "closed" and phase != "failed":
        phase = "closing"
    raw_session_role = str(observed.get("sessionRole") or state_workbench.get("sessionRole") or "workbench").strip() or "workbench"
    project_window_alive = bool(observed.get("browserWindowAlive"))
    session_role = "workbench" if raw_session_role == "launcher_control_surface" and project_window_alive else raw_session_role
    if raw_session_role == "launcher_control_surface":
        if project_window_alive:
            observed_state = "open"
            desired_state = "open"
        elif desired_state == "open" and phase not in {"opening", "failed"}:
            desired_state = "closed"
    failure_message = str(state_workbench.get("failureMessage") or "").strip()
    frontend_orphaned = bool(observed.get("frontendOrphaned") or state_workbench.get("frontendOrphaned"))
    lifecycle_consistency = str(
        observed.get("lifecycleConsistency") or state_workbench.get("lifecycleConsistency") or "consistent"
    ).strip() or "consistent"
    if frontend_orphaned:
        status_line = failure_message or "前端窗口仍在，但后端服务已经离线。"
    elif phase == "failed":
        status_line = failure_message or "工作台生命周期遇到了错误。"
    elif desired_state == "closed" and observed_state != "closed":
        status_line = "正在关闭工作台。"
    elif desired_state == "open" and observed_state != "open":
        status_line = "正在打开工作台。"
    elif session_role == "launcher_control_surface":
        status_line = "Launcher 控制台正在运行，项目生命周期尚未启动。"
    elif observed_state == "open":
        status_line = "工作台正在运行。"
    else:
        status_line = "工作台已关闭。"

    return {
        "desiredState": desired_state,
        "observedState": observed_state,
        "sessionRole": session_role,
        "phase": phase,
        "backendPid": int(observed.get("backendPid") or state_workbench.get("backendPid") or 0),
        "browserWindowPid": int(observed.get("browserWindowPid") or state_workbench.get("browserWindowPid") or 0),
        "backendAlive": bool(observed.get("backendAlive")),
        "backendHealthy": bool(observed.get("backendHealthy")),
        "backendObserved": bool(observed.get("backendObserved")),
        "backendPort": int(observed.get("backendPort") or state_workbench.get("backendPort") or 0),
        "backendPortListening": bool(observed.get("backendPortListening") or state_workbench.get("backendPortListening")),
        "backendPortOwnerPid": int(observed.get("backendPortOwnerPid") or 0),
        "backendPortConflict": bool(observed.get("backendPortConflict")),
        "browserWindowAlive": bool(observed.get("browserWindowAlive")),
        "browserManaged": bool(observed.get("browserManaged", state_workbench.get("browserManaged", True))),
        "backendMissing": bool(observed.get("backendMissing")),
        "frontendOrphaned": frontend_orphaned,
        "lifecycleConsistency": lifecycle_consistency,
        "url": str(observed.get("url") or state_workbench.get("url") or "").strip(),
        "lastReason": str(state_workbench.get("lastReason") or "").strip(),
        "lastSource": str(state_workbench.get("lastSource") or "").strip(),
        "lastTransitionAt": str(state_workbench.get("lastTransitionAt") or "").strip(),
        "statusLine": status_line,
        "failureMessage": failure_message,
    }


def _runtime_manager_payload(runtime_state: dict[str, Any]) -> dict[str, Any]:
    return {
        "running": bool(runtime_state.get("daemonRunning")),
        "runtimeState": str(runtime_state.get("runtimeState") or "idle"),
        "managerPid": int(runtime_state.get("managerPid") or 0),
        "stateVersion": int(runtime_state.get("stateVersion") or 0),
    }


def _lifecycle_proof(
    *,
    runtime_manager: dict[str, Any],
    workbench: dict[str, Any],
    active_work_runs: list[dict[str, str]],
) -> dict[str, Any]:
    verified_at = datetime.now(timezone.utc).isoformat()
    desired_state = str(workbench.get("desiredState") or "closed")
    observed_state = str(workbench.get("observedState") or "closed")
    phase = str(workbench.get("phase") or "steady")
    manager_running = bool(runtime_manager.get("running"))
    backend_alive = bool(workbench.get("backendAlive"))
    browser_managed = bool(workbench.get("browserManaged", True))
    browser_alive = bool(workbench.get("browserWindowAlive"))
    backend_ok = backend_alive and bool(workbench.get("backendHealthy")) and not bool(workbench.get("backendPortConflict"))
    browser_ok = browser_alive or not browser_managed
    active_work_ok = not active_work_runs

    components = [
        _proof_component(
            "runtime_manager",
            label="Runtime Manager",
            ok=manager_running,
            state="running" if manager_running else "missing",
            required_for_open=True,
            required_for_closed=False,
            detail=f"pid={int(runtime_manager.get('managerPid') or 0)}" if manager_running else "Runtime manager is not running.",
            pid=int(runtime_manager.get("managerPid") or 0),
            verified_at=verified_at,
        ),
        _proof_component(
            "backend",
            label="Backend",
            ok=backend_ok if desired_state == "open" else not backend_alive or backend_ok,
            state="running" if backend_alive else "missing",
            required_for_open=True,
            required_for_closed=False,
            detail=str(workbench.get("failureMessage") or ""),
            pid=int(workbench.get("backendPid") or 0),
            verified_at=verified_at,
        ),
        _proof_component(
            "workbench_window",
            label="Workbench Window",
            ok=browser_ok,
            state="running" if browser_alive else "missing",
            required_for_open=browser_managed,
            required_for_closed=False,
            detail="",
            pid=int(workbench.get("browserWindowPid") or 0),
            verified_at=verified_at,
        ),
        _proof_component(
            "active_work_runs",
            label="Active Work",
            ok=active_work_ok,
            state="verified" if active_work_ok else "running",
            required_for_open=False,
            required_for_closed=True,
            detail="" if active_work_ok else f"{len(active_work_runs)} active work item(s) block lifecycle commands.",
            pid=0,
            verified_at=verified_at,
        ),
    ]
    if phase == "failed":
        overall_state = "failed"
    elif active_work_runs and desired_state == "closed" and observed_state == "closed":
        overall_state = "partial"
    elif desired_state == "open" and observed_state == "open" and backend_ok and browser_ok:
        overall_state = "ready"
    elif desired_state == "open" and observed_state != "open":
        overall_state = "starting"
    elif desired_state == "closed" and observed_state != "closed":
        overall_state = "closing"
    elif desired_state == "closed" and observed_state == "closed":
        overall_state = "closed"
    else:
        overall_state = "partial"
    return {
        "overallState": overall_state,
        "overallLabel": overall_state,
        "summary": str(workbench.get("statusLine") or ""),
        "verifiedAt": verified_at,
        "desiredState": desired_state,
        "observedState": observed_state,
        "phase": phase,
        "browserManaged": browser_managed,
        "projectRootMatches": True,
        "components": components,
        "activeWorkRuns": {
            "count": len(active_work_runs),
            "kinds": sorted({item["kind"] for item in active_work_runs if item.get("kind")}),
            "items": active_work_runs[:8],
        },
        "residualProcesses": {"count": 0, "items": []},
    }


def _project_bundle_from_workbench(
    workbench: dict[str, Any],
    *,
    lifecycle_proof: dict[str, Any],
    launcher_state: dict[str, Any],
) -> dict[str, Any]:
    if (
        isinstance(launcher_state, dict)
        and str(launcher_state.get("sessionRole") or "") == "launcher_control_surface"
        and str(workbench.get("sessionRole") or "") == "launcher_control_surface"
    ):
        workbench = dict(workbench)
        workbench["sessionRole"] = "launcher_control_surface"
        workbench["desiredState"] = "closed"
        workbench["observedState"] = "closed"
        workbench["phase"] = "steady"
        workbench["statusLine"] = "Launcher 控制台正在运行，项目生命周期尚未启动。"
        workbench["browserManaged"] = bool(launcher_state.get("browserManaged", False))
        workbench["browserWindowAlive"] = False
        workbench["browserWindowPid"] = 0

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
        "sessionRole": str(workbench.get("sessionRole") or "workbench"),
        "desiredState": str(workbench.get("desiredState") or "closed"),
        "observedState": str(workbench.get("observedState") or "closed"),
        "phase": str(workbench.get("phase") or "steady"),
        "overallState": str(lifecycle_proof.get("overallState") or ""),
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


def _guardian_adapter_from_workbench(*, runtime_manager: dict[str, Any], workbench: dict[str, Any]) -> dict[str, Any]:
    supervisor = _launcher_supervisor_snapshot()
    manager_running = bool(runtime_manager.get("running"))
    manager_pid = int(runtime_manager.get("managerPid") or 0)
    browser_managed = bool(workbench.get("browserManaged", True))
    responsibilities = [
        _guardian_responsibility(
            "project_bundle_lifecycle",
            owner="standalone_launcher",
            adapter="runtime_manager",
            status="active",
            detail="Launcher owns the project-bundle lifecycle command facade; execution is delegated to runtime manager commands.",
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
            owner="launcher_adapter",
            adapter="vibelution_launcher",
            status=str(supervisor.get("status") or "unknown"),
            detail=str(supervisor.get("detail") or ""),
        ),
        _guardian_responsibility(
            "backend_process",
            owner="runtime_manager",
            adapter="runtime_manager",
            status="running" if bool(workbench.get("backendAlive")) else "observed",
            detail="Backend process ownership is inferred from launcher state and port observation.",
        ),
        _guardian_responsibility(
            "browser_window",
            owner="launcher_adapter",
            adapter="vibelution_launcher",
            status="managed" if browser_managed else "external",
            detail="Workbench browser lifecycle remains managed by the launcher adapter until standalone Launcher owns the window controller.",
        ),
        _guardian_responsibility(
            "runtime_scene_logging",
            owner="runtime_manager_events",
            adapter="events_jsonl",
            status="active",
            detail="Standalone Launcher writes audit evidence to runtime-manager events without depending on the Web app service layer.",
        ),
    ]
    return {
        "schemaVersion": 1,
        "mode": "standalone_control_plane",
        "targetMode": "standalone_launcher_guardian",
        "statusLine": "守护职责正在归并到独立 Launcher；当前仍复用 runtime manager 执行生命周期命令。",
        "ownedCount": sum(1 for item in responsibilities if item["owner"] in {"standalone_launcher", "runtime_manager", "runtime_manager_events"}),
        "adapterCount": sum(1 for item in responsibilities if item["owner"] not in {"standalone_launcher", "runtime_manager", "runtime_manager_events"}),
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


def _launcher_supervisor_reattach_blockers(
    *,
    state: dict[str, Any],
    supervisor: dict[str, Any],
    workbench: dict[str, Any],
) -> list[str]:
    blockers: list[str] = []
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


def _load_launcher_state() -> dict[str, Any]:
    try:
        payload = json.loads(LAUNCHER_STATE_PATH.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _control_plane_evidence() -> dict[str, Any]:
    state = _load_json_file(STATE_PATH)
    pending_commands = _recent_command_files(INBOX_DIR, limit=5)
    processing_commands = _recent_command_files(PROCESSING_DIR, limit=5)
    recent_results = _recent_result_files(RESULTS_DIR, limit=5)
    recent_events = _recent_runtime_manager_events(EVENTS_PATH, limit=8)
    active_command = state.get("command") if isinstance(state.get("command"), dict) else {}
    restart_queue = _restart_queue_summary(pending_commands=pending_commands, active_command=active_command)
    return {
        "schemaVersion": 1,
        "state": {
            "stateVersion": int(state.get("stateVersion") or 0),
            "runtimeState": str(state.get("runtimeState") or ""),
            "managerPid": int(state.get("managerPid") or 0),
            "updatedAt": str(state.get("updatedAt") or ""),
            "activeCommand": _command_summary(active_command),
        },
        "queue": {
            "pendingCount": _file_count(INBOX_DIR),
            "processingCount": _file_count(PROCESSING_DIR),
            "pending": pending_commands,
            "processing": processing_commands,
        },
        "results": {"recent": recent_results},
        "events": {"recent": recent_events},
        "recovery": _runtime_manager_recovery_summary(recent_events=recent_events, recent_results=recent_results),
        "restartQueue": restart_queue,
    }


def _append_active_work_run(
    items: list[dict[str, str]],
    seen: set[tuple[str, str]],
    *,
    kind: str,
    payload: dict[str, Any] | None,
    force_current: bool = False,
) -> None:
    if not isinstance(payload, dict):
        return
    if str(payload.get("finishedAt") or payload.get("endedAt") or "").strip():
        return
    item = _active_work_run_item(kind, payload)
    if not item["kind"]:
        return
    if not _active_work_payload_blocks_lifecycle(payload):
        return
    if not force_current and _snapshot_is_stale(payload):
        return
    key = (item["kind"], item["runId"] or item["sessionId"])
    if key in seen:
        return
    seen.add(key)
    items.append(item)


def _active_work_run_item(kind: str, payload: dict[str, Any]) -> dict[str, str]:
    run_id = str(
        payload.get("runId")
        or payload.get("roundId")
        or payload.get("sessionId")
        or payload.get("id")
        or ""
    ).strip()
    status = str(payload.get("status") or payload.get("currentPhase") or payload.get("phase") or "").strip().lower()
    session_id = str(payload.get("sessionId") or payload.get("conversationId") or "").strip()
    return {
        "kind": str(payload.get("runKind") or kind or "").strip(),
        "runId": run_id,
        "status": status,
        "sessionId": session_id,
    }


def _active_work_payload_blocks_lifecycle(payload: dict[str, Any]) -> bool:
    if str(payload.get("finishedAt") or payload.get("endedAt") or "").strip():
        return False
    status = str(
        payload.get("status")
        or payload.get("currentPhase")
        or payload.get("phase")
        or payload.get("runtimeStatus")
        or ""
    ).strip().lower()
    if status in _ACTIVE_WORK_NON_BLOCKING_STATUSES:
        return False
    if status in _ACTIVE_WORK_BLOCKING_STATUSES:
        return True
    return bool(status)


def _snapshot_is_stale(payload: dict[str, Any]) -> bool:
    updated = _parse_datetime(str(payload.get("updatedAt") or payload.get("startedAt") or ""))
    if updated is None:
        return False
    return datetime.now(timezone.utc) - updated > _STALE_SNAPSHOT_GRACE


def _parse_datetime(value: str) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _load_json_file(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _file_count(directory: Path) -> int:
    try:
        return sum(1 for path in directory.glob("*.json") if path.is_file())
    except OSError:
        return 0


def _recent_command_files(directory: Path, *, limit: int) -> list[dict[str, Any]]:
    commands: list[dict[str, Any]] = []
    try:
        files = sorted((path for path in directory.glob("*.json") if path.is_file()), key=lambda path: path.stat().st_mtime, reverse=True)
    except OSError:
        return commands
    for path in files[: max(0, limit)]:
        payload = _load_json_file(path)
        if payload:
            commands.append(_command_summary(payload))
    return commands


def _recent_result_files(directory: Path, *, limit: int) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    try:
        files = sorted((path for path in directory.glob("*.json") if path.is_file()), key=lambda path: path.stat().st_mtime, reverse=True)
    except OSError:
        return results
    for path in files[: max(0, limit)]:
        payload = _load_json_file(path)
        if payload:
            results.append(_result_summary(payload))
    return results


def _recent_runtime_manager_events(path: Path, *, limit: int) -> list[dict[str, Any]]:
    if limit <= 0:
        return []
    try:
        with path.open("rb") as handle:
            handle.seek(0, 2)
            size = handle.tell()
            handle.seek(max(0, size - 65536))
            raw = handle.read()
    except OSError:
        return []
    lines = raw.decode("utf-8", errors="replace").splitlines()
    events: list[dict[str, Any]] = []
    for line in reversed(lines):
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue
        event_payload = payload.get("payload") if isinstance(payload.get("payload"), dict) else {}
        events.append(
            {
                "type": str(payload.get("type") or ""),
                "at": str(payload.get("at") or ""),
                "commandId": str(event_payload.get("commandId") or ""),
                "commandType": str(event_payload.get("type") or ""),
                "ok": bool(event_payload.get("ok")) if "ok" in event_payload else None,
                "message": _truncate(str(event_payload.get("message") or ""), 180),
            }
        )
        if len(events) >= limit:
            break
    return events


def _runtime_manager_recovery_summary(
    *, recent_events: list[dict[str, Any]], recent_results: list[dict[str, Any]]
) -> dict[str, Any]:
    recovered = next(
        (event for event in recent_events if str(event.get("type") or "") == "command_queue.processing_recovered"),
        None,
    )
    if not recovered:
        return {
            "active": False,
            "commandId": "",
            "commandType": "",
            "recoveredAt": "",
            "resultMessage": "",
            "resultOk": None,
            "statusLine": "",
        }
    command_id = str(recovered.get("commandId") or "")
    matching_result = next((result for result in recent_results if str(result.get("commandId") or "") == command_id), {})
    result_message = str(matching_result.get("message") or "")
    result_ok = bool(matching_result.get("ok")) if matching_result else None
    return {
        "active": True,
        "commandId": command_id,
        "commandType": str(recovered.get("commandType") or ""),
        "recoveredAt": str(recovered.get("at") or ""),
        "resultMessage": result_message,
        "resultOk": result_ok,
        "statusLine": _recovery_status_line(command_id=command_id, result_message=result_message, result_ok=result_ok),
    }


def _recovery_status_line(*, command_id: str, result_message: str, result_ok: bool | None) -> str:
    if result_ok is True:
        return f"已恢复并完成未结束的生命周期命令：{result_message or command_id}"
    if result_ok is False:
        return f"已恢复未结束的生命周期命令，但结果需要检查：{result_message or command_id}"
    return f"检测到生命周期管理器恢复了未结束命令：{command_id}"


def _command_summary(command: dict[str, Any]) -> dict[str, Any]:
    args = command.get("args") if isinstance(command.get("args"), dict) else {}
    return {
        "commandId": str(command.get("commandId") or command.get("activeCommandId") or ""),
        "type": str(command.get("type") or command.get("activeType") or ""),
        "requestedBy": str(command.get("requestedBy") or ""),
        "requestedAt": str(command.get("requestedAt") or command.get("startedAt") or ""),
        "reason": str(args.get("reason") or ""),
        "source": str(args.get("source") or ""),
        "noBrowser": bool(command.get("noBrowser") if "noBrowser" in command else args.get("noBrowser")),
        "stopManager": bool(command.get("stopManager") if "stopManager" in command else args.get("stopManager")),
        "deferredUntilActiveWorkClear": bool(args.get("deferredUntilActiveWorkClear")),
        "queuedBecauseActiveWork": bool(args.get("queuedBecauseActiveWork")),
        "deferUntil": str(args.get("deferUntil") or ""),
        "activeWorkDeferCount": int(args.get("activeWorkDeferCount") or 0),
        "lastActiveWorkCount": int(args.get("lastActiveWorkCount") or args.get("queuedActiveWorkCount") or 0),
    }


def _restart_queue_summary(
    *, pending_commands: list[dict[str, Any]], active_command: dict[str, Any] | None
) -> dict[str, Any]:
    pending_restarts = [
        command
        for command in pending_commands
        if str(command.get("type") or "") == "restart_workbench"
        and (bool(command.get("deferredUntilActiveWorkClear")) or bool(command.get("queuedBecauseActiveWork")))
    ]
    active_command = active_command if isinstance(active_command, dict) else {}
    active_type = str(active_command.get("activeType") or active_command.get("type") or "")
    active_restart = active_type == "restart_workbench"
    next_command = pending_restarts[0] if pending_restarts else {}
    active_work_count = int(next_command.get("lastActiveWorkCount") or 0) if next_command else 0
    pending_count = len(pending_restarts)
    return {
        "pending": bool(pending_restarts),
        "pendingCount": pending_count,
        "active": active_restart,
        "commandId": str(next_command.get("commandId") or active_command.get("activeCommandId") or ""),
        "deferUntil": str(next_command.get("deferUntil") or ""),
        "activeWorkDeferCount": int(next_command.get("activeWorkDeferCount") or 0) if next_command else 0,
        "lastActiveWorkCount": active_work_count,
        "statusLine": _restart_queue_status_line(
            pending_count=pending_count,
            active_restart=active_restart,
            active_work_count=active_work_count,
        ),
    }


def _restart_queue_status_line(*, pending_count: int, active_restart: bool, active_work_count: int) -> str:
    if active_restart:
        return "正在执行历史重启命令。"
    if pending_count <= 0:
        return ""
    if active_work_count > 0:
        return f"检测到旧版等待重启命令；当前还有 {active_work_count} 个任务，本版不会自动重启，请任务结束后重新提交。"
    return "检测到旧版等待重启命令；本版不会自动重启，请确认状态后重新提交。"


def _result_summary(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "commandId": str(result.get("commandId") or ""),
        "ok": bool(result.get("ok")),
        "completed": bool(result.get("completed")),
        "message": _truncate(str(result.get("message") or ""), 220),
        "errorType": str(result.get("errorType") or ""),
        "stateVersion": int(result.get("stateVersion") or 0),
    }


def _proof_component(
    component_id: str,
    *,
    label: str,
    ok: bool,
    state: str,
    required_for_open: bool,
    required_for_closed: bool,
    detail: str,
    pid: int,
    verified_at: str,
) -> dict[str, Any]:
    return {
        "id": component_id,
        "label": label,
        "state": state,
        "ok": bool(ok),
        "requiredForOpen": bool(required_for_open),
        "requiredForClosed": bool(required_for_closed),
        "detail": detail,
        "pid": int(pid or 0),
        "verifiedAt": verified_at,
    }


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


def _record_launcher_event(
    event_code: str,
    *,
    phase: str,
    message: str,
    outcome: str = "observed",
    level: str = "info",
    fields: dict[str, object] | None = None,
) -> None:
    payload = {
        "phase": phase,
        "message": _truncate(message, 240),
        "outcome": outcome,
        "level": level,
        "fields": fields or {},
    }
    try:
        append_runtime_manager_file_event(event_code, payload, suppress_io_errors=True)
    except Exception:
        return


def _truncate(value: str, limit: int) -> str:
    text = str(value or "")
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)] + "..."
