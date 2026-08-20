"""Per-row Launcher start/stop for Git-governed branch instances.

The current checkout keeps the existing Runtime Manager lifecycle. Other
checked-out worktrees are supervised by the current desktop shell: the current
``scripts/vibelution_launcher.py`` is spawned against the target cwd/venv.
See ``core/launcher/instance-lifecycle.md``.
Retired shells and not-checked-out refs cannot be started.
"""

from __future__ import annotations

import http.client
import json
import os
import subprocess
import sys
from collections.abc import Callable, Iterable
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from core.infrastructure.branch_workspace import list_branch_instances
from core.launcher.isolated_workbench_window import (
    close_isolated_workbench_window,
    open_isolated_workbench_window,
    overlay_instance_window_pid,
)
from core.launcher.slot_identity import (
    apply_slot_spawn_environment,
    slot_fields_for_project,
)
from core.runtime_manager import instances_registry as registry
from core.runtime_manager.constants import (
    LAUNCHER_STATE_PATH,
    PROJECT_ROOT,
    PYTHON_LAUNCHER_SCRIPT_PATH,
)
from scripts.windowless_subprocess import (
    detached_no_console_popen_kwargs,
    no_window_subprocess_kwargs,
)
from vibelution_storage import resolve_project_runtime_home

SpawnRunner = Callable[..., dict[str, Any]]

_STARTABLE_KINDS = {"main", "worktree"}
_ISOLATED_START_TIMEOUT_SECONDS = 180
_ISOLATED_STOP_TIMEOUT_SECONDS = 60
_ISOLATED_RESTART_TIMEOUT_SECONDS = 240


class BranchInstanceLifecycleError(RuntimeError):
    """Raised when a selected branch instance cannot accept a lifecycle action."""

    def __init__(self, code: str, message: str, *, status_code: int = 409) -> None:
        super().__init__(message)
        self.code = str(code or "instance_lifecycle_failed")
        self.message = str(message)
        self.status_code = int(status_code or 409)


def overlay_instance_ports(
    payload: dict[str, Any],
    *,
    launcher_state: dict[str, Any] | None = None,
    current_bundle: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Attach ports and one explicit runtime contract to each branch instance."""

    items = payload.get("items")
    if not isinstance(items, list):
        return payload
    state = launcher_state if launcher_state is not None else _read_current_launcher_state()
    current_backend, current_control, current_url = _current_control_plane_ports(state)
    by_id: dict[str, dict[str, Any]] = {}
    by_root: dict[str, dict[str, Any]] = {}
    try:
        for entry in registry.list_instances():
            instance_id = str(entry.get("instanceId") or "").strip()
            if instance_id:
                by_id[instance_id] = entry
            root = _norm_path(entry.get("projectRoot") or "")
            if root:
                by_root[root] = entry
    except (OSError, TypeError, ValueError):
        by_id = {}
        by_root = {}

    for item in items:
        if not isinstance(item, dict):
            continue
        item.update(_slot_fields_for_path(item.get("path") or ""))
        entry = by_id.get(str(item.get("id") or "")) or by_root.get(_norm_path(item.get("path") or ""))
        if item.get("current"):
            if current_backend > 0:
                item["port"] = current_backend
            if current_control > 0:
                item["controlPort"] = current_control
            if current_url:
                item["url"] = current_url
            elif int(item.get("port") or 0) > 0:
                item["url"] = _loopback_url(int(item["port"]))
            item.setdefault("controlPort", current_control)
            item.setdefault("url", "")
            _attach_instance_runtime(item, entry=entry, current_bundle=current_bundle)
            continue
        reserved_port = _positive_int((entry or {}).get("port"))
        reserved_control = _positive_int((entry or {}).get("controlPort"))
        reserved_url = str((entry or {}).get("url") or "").strip()
        if reserved_port > 0 and _positive_int(item.get("port")) <= 0:
            item["port"] = reserved_port
        item["controlPort"] = reserved_control
        if reserved_url:
            item["url"] = reserved_url
        elif _positive_int(item.get("port")) > 0:
            item["url"] = _loopback_url(int(item["port"]))
        else:
            item["url"] = ""
        overlay_instance_window_pid(item, entry)
        _attach_instance_runtime(item, entry=entry)
    return payload


def list_overlayed_branch_instances(*, current_bundle: dict[str, Any] | None = None) -> dict[str, Any]:
    return overlay_instance_ports(list_branch_instances(PROJECT_ROOT), current_bundle=current_bundle)


def _attach_instance_runtime(
    item: dict[str, Any],
    *,
    entry: dict[str, Any] | None,
    current_bundle: dict[str, Any] | None = None,
) -> None:
    runtime = _instance_runtime_projection(item, entry=entry, current_bundle=current_bundle)
    item["runtime"] = runtime
    lease = str((entry or {}).get("portLeaseStatus") or "").strip()
    if lease:
        item["portLeaseStatus"] = lease
    block_reason = _instance_start_block_reason(item, runtime)
    item["startable"] = not block_reason
    item["startBlockReason"] = block_reason


def _instance_runtime_projection(
    item: dict[str, Any],
    *,
    entry: dict[str, Any] | None,
    current_bundle: dict[str, Any] | None,
) -> dict[str, Any]:
    workbench = _workbench_state_for_item(item)
    bundle = current_bundle if item.get("current") and isinstance(current_bundle, dict) else {}
    bundle_backend = bundle.get("backend") if isinstance(bundle.get("backend"), dict) else {}
    bundle_frontend = bundle.get("frontend") if isinstance(bundle.get("frontend"), dict) else {}
    bundle_browser = bundle.get("browser") if isinstance(bundle.get("browser"), dict) else {}

    pids = item.get("pids") if isinstance(item.get("pids"), dict) else {}
    backend_pid = _positive_int(bundle_backend.get("pid")) or _positive_int(pids.get("backend"))
    backend_alive = bool(bundle_backend.get("alive")) if bundle_backend else bool(item.get("alive"))
    backend_healthy = bool(bundle_backend.get("healthy")) if bundle_backend else bool(workbench.get("backendHealthy"))
    backend_listening = (
        bool(bundle_backend.get("portListening"))
        if bundle_backend
        else bool(workbench.get("backendPortListening"))
    )
    backend_conflict = (
        bool(bundle_backend.get("portConflict"))
        if bundle_backend
        else bool(workbench.get("backendPortConflict"))
    )
    backend_port = _positive_int(bundle_backend.get("port")) or _positive_int(item.get("port"))
    reserved_port = 0 if bundle else _positive_int((entry or {}).get("port"))

    window_pid = _positive_int(bundle_browser.get("windowPid")) or _positive_int(pids.get("window"))
    window_open = bool(bundle_browser.get("alive")) if bundle_browser else window_pid > 0
    observed_window_title = str((entry or {}).get("windowTitle") or "").strip()
    window_title = observed_window_title or str(item.get("workbenchTitle") or "").strip()

    frontend_mode = str(
        bundle_frontend.get("mode")
        or workbench.get("frontendMode")
        or "bundled_static_dist"
    ).strip()
    assets_ready = _bundled_frontend_ready(item)
    if frontend_mode == "bundled_static_dist":
        frontend_ready = assets_ready
    elif bundle_frontend:
        frontend_ready = bool(bundle_frontend.get("distReady"))
    else:
        frontend_ready = bool(workbench.get("frontendReady"))

    observed_state = str(bundle.get("observedState") or item.get("observedState") or "closed").strip().lower()
    workbench_phase = str(workbench.get("phase") or "steady").strip().lower()
    workbench_desired = str(workbench.get("desiredState") or "closed").strip().lower()
    workbench_failure = str(workbench.get("failureMessage") or "").strip()
    registry_status = "" if bundle else str((entry or {}).get("status") or "").strip().lower()
    registry_phase = "" if bundle else str((entry or {}).get("phase") or "").strip().lower()
    registry_desired = "" if bundle else str((entry or {}).get("desiredState") or "").strip().lower()
    registry_failure = "" if bundle else str((entry or {}).get("failureMessage") or "").strip()
    generation = 0 if bundle else _positive_int((entry or {}).get("generation"))

    if bundle:
        phase = str(bundle.get("phase") or workbench_phase or "steady").strip().lower()
        desired_state = str(bundle.get("desiredState") or workbench_desired or "closed").strip().lower()
        failure_message = str(bundle.get("failureMessage") or workbench_failure or "").strip()
    else:
        phase = registry_phase or workbench_phase or "steady"
        desired_state = registry_desired or workbench_desired or "closed"
        if registry_status in registry.IN_FLIGHT_STATUSES:
            failure_message = registry_failure
        else:
            failure_message = registry_failure or workbench_failure

    if (
        not bundle
        and backend_alive
        and backend_port > 0
        and not backend_conflict
        and not (backend_healthy and backend_listening)
        and _loopback_http_ready(backend_port)
    ):
        # Isolated slot state is often flat and omits nested listening/healthy
        # flags. Match Electron waitForWorkbenchHttp: GET / with status 1-499.
        backend_listening = True
        backend_healthy = True

    start_supervisor_lost = not bundle and registry.is_stale_in_flight_start(
        entry,
        backend_alive=backend_alive,
        backend_listening=backend_listening,
        window_open=window_open,
    )
    lifecycle_state, error_code = _instance_lifecycle_state(
        observed_state=observed_state,
        phase=phase,
        desired_state=desired_state,
        registry_status=registry_status,
        backend_alive=backend_alive,
        backend_healthy=backend_healthy,
        backend_listening=backend_listening,
        backend_conflict=backend_conflict,
        frontend_ready=frontend_ready,
        window_open=window_open,
        failure_message=failure_message,
        start_supervisor_lost=start_supervisor_lost,
    )
    if lifecycle_state == "error" and not failure_message:
        failure_message = {
            "backend_port_conflict": "后端端口被其他进程占用。",
            "registry_failed": "该分支上次启动失败。",
            "lifecycle_failed": "该分支生命周期进入失败状态。",
            "start_supervisor_lost": "启动监督进程已退出且超过启动期限，启动未完成。可直接重试启动。",
        }.get(error_code, "该分支运行状态异常。")

    runtime: dict[str, Any] = {
        "lifecycleState": lifecycle_state,
        "desiredState": desired_state or "closed",
        "observedState": observed_state or "closed",
        "phase": phase or "steady",
        "generation": generation,
        "registryStatus": registry_status,
        "backend": {
            "alive": backend_alive,
            "healthy": backend_alive and backend_healthy,
            "listening": backend_listening,
            "port": backend_port,
            "portReserved": bool(backend_port > 0 and reserved_port == backend_port and not backend_listening),
            "portConflict": backend_conflict,
            "pid": backend_pid,
        },
        "frontend": {
            "mode": frontend_mode,
            "ready": frontend_ready,
        },
        "window": {
            "open": window_open,
            "pid": window_pid,
            "title": window_title,
            "titleObserved": bool(observed_window_title),
        },
    }
    if error_code or failure_message:
        runtime["error"] = {
            "code": error_code or "runtime_error",
            "message": failure_message,
        }
    observation = (entry or {}).get("cleanupObservation") if isinstance(entry, dict) else None
    observation = observation if isinstance(observation, dict) else {}
    lease = str((entry or {}).get("portLeaseStatus") or "").strip()
    if lease:
        runtime["portLeaseStatus"] = lease
    classification = str(observation.get("classification") or "").strip()
    if classification:
        runtime["registryClassification"] = classification
    next_reconcile_at = str(observation.get("nextReconcileAt") or "").strip()
    if next_reconcile_at:
        runtime["nextReconcileAt"] = next_reconcile_at
    first_observed_at = str(observation.get("firstObservedAt") or "").strip()
    if first_observed_at:
        runtime["firstObservedAt"] = first_observed_at
    return runtime


# Deprecated by docs/plans/2026-08-20-launcher-lifecycle-ts-migration.md（迁移期保留）
def _instance_lifecycle_state(
    *,
    observed_state: str,
    phase: str,
    registry_status: str,
    backend_alive: bool,
    backend_healthy: bool,
    backend_listening: bool,
    backend_conflict: bool,
    frontend_ready: bool,
    window_open: bool,
    failure_message: str,
    desired_state: str = "",
    start_supervisor_lost: bool = False,
) -> tuple[str, str]:
    normalized_phase = str(phase or "").strip().lower()
    normalized_status = str(registry_status or "").strip().lower()
    normalized_desired = str(desired_state or "").strip().lower()
    # Leftover disk observedState is not a live signal; keep the argument for Python ≡ TS.
    _ = str(observed_state or "").strip().lower()
    backend_ready = backend_alive and backend_healthy and backend_listening and not backend_conflict
    # A start/restart claim whose supervisor died past its own deadline must not
    # pin the row in starting/restarting forever; only reachable for registry
    # in-flight start claims (see _registry_entry_stale_in_flight_start).
    if start_supervisor_lost and not backend_ready and not window_open:
        return "error", "start_supervisor_lost"
    if normalized_phase in {"restarting", "restart"} or normalized_status == "restarting":
        return "restarting", ""
    if normalized_phase in {"closing", "stopping", "force_stopping"} or normalized_status == "stopping":
        return "stopping", ""
    in_flight_start = (
        normalized_status in {"starting", "restarting"}
        and normalized_desired == "open"
    ) or normalized_phase in {"opening", "starting"}
    if in_flight_start and not backend_ready and not window_open:
        return "starting", ""
    if backend_conflict:
        return "error", "backend_port_conflict"
    if normalized_phase == "failed":
        return "error", "lifecycle_failed"
    if normalized_status == "failed":
        return "error", "registry_failed"
    if failure_message:
        return "error", "runtime_error"

    if backend_ready and frontend_ready and window_open:
        return "running", ""
    has_runtime_signal = bool(
        backend_alive
        or backend_listening
        or window_open
    )
    if has_runtime_signal:
        return "partial", ""
    return "closed", ""


def _lifecycle_projection_is_startable(lifecycle_state: str, has_live_runtime: bool) -> bool:
    state = str(lifecycle_state or "").strip().lower()
    if state == "closed":
        return True
    return state == "error" and not has_live_runtime


def _iso_timestamp_in_past(value: Any) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return False
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) > parsed.astimezone(timezone.utc)


def _pid_alive(pid: int) -> bool:
    if int(pid or 0) <= 0:
        return False
    try:
        import psutil
    except ImportError:
        psutil = None  # type: ignore[assignment]
    if psutil is not None:
        try:
            return bool(psutil.pid_exists(int(pid)))
        except (psutil.Error, OSError):
            return False
    if os.name == "nt":
        import ctypes

        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, int(pid))
        if handle:
            ctypes.windll.kernel32.CloseHandle(handle)
            return True
        return False
    try:
        os.kill(int(pid), 0)
    except OSError:
        return False
    return True


def _registry_entry_stale_in_flight_start(
    entry: dict[str, Any] | None,
    *,
    backend_alive: bool,
    backend_listening: bool,
    window_open: bool,
) -> bool:
    """True when a registry in-flight start outlived its supervisor lease.

    Hang recovery is lease-expired + deadlineAt, not spawnPid death. A hung
    child must not keep the row in ``starting``/``restarting`` forever after
    Electron dies.
    """

    return registry.is_stale_in_flight_start(
        entry,
        backend_alive=backend_alive,
        backend_listening=backend_listening,
        window_open=window_open,
    )


def _reclaim_stale_in_flight_start(
    instance_id: str,
    item: dict[str, Any],
    existing: dict[str, Any],
) -> bool:
    """Collapse a provably dead in-flight start claim so a retry can proceed.

    Returns True only when the registry row was reclaimed as ``failed`` under
    the registry lock; live or not-yet-expired claims stay busy (409).
    """

    wanted = str(instance_id or "").strip()
    if not wanted or not isinstance(existing, dict) or not existing:
        return False
    backend = _runtime_section(item, "backend")
    window = _runtime_section(item, "window")
    if not _registry_entry_stale_in_flight_start(
        existing,
        backend_alive=bool(item.get("alive")) or bool(backend.get("alive")),
        backend_listening=bool(backend.get("listening")),
        window_open=bool(window.get("open")),
    ):
        return False

    def mutator(payload: dict[str, Any]) -> dict[str, Any]:
        instances = payload.setdefault("instances", {})
        entry = instances.get(wanted)
        if not isinstance(entry, dict):
            return {}
        status = str(entry.get("status") or "").strip().lower()
        if status not in {"starting", "restarting"}:
            return dict(entry)
        if str(entry.get("desiredState") or "").strip().lower() != "open":
            return dict(entry)
        if not registry.is_stale_in_flight_start(entry):
            return dict(entry)
        entry["status"] = "failed"
        entry["phase"] = "failed"
        entry["failureMessage"] = registry.START_SUPERVISOR_LOST_MESSAGE
        entry.pop("ownerLease", None)
        return dict(entry)

    stored = registry.mutate_registry(mutator)
    return str(stored.get("status") or "").strip().lower() == "failed"


def _instance_start_block_reason(item: dict[str, Any], runtime: dict[str, Any]) -> str:
    if str(item.get("kind") or "") not in _STARTABLE_KINDS:
        return "unsupported_kind"
    if not item.get("checkedOut"):
        return "not_checked_out"
    path = str(item.get("path") or "").strip()
    if not path or not Path(path).is_dir():
        return "worktree_missing"
    state = str(runtime.get("lifecycleState") or "closed")
    if _lifecycle_projection_is_startable(state, _item_has_live_runtime(item)):
        return ""
    return "runtime_error" if state == "error" else "runtime_active"


def _workbench_state_for_item(item: dict[str, Any]) -> dict[str, Any]:
    path = str(item.get("path") or "").strip()
    if not path:
        return {}
    worktree = Path(path)
    slot_payload = _read_json_file(resolve_project_runtime_home(worktree) / "launcher" / "state.json")
    worktree_payload = _read_json_file(worktree / ".runtime" / "launcher" / "state.json")
    payload = slot_payload or worktree_payload
    nested = payload.get("workbench") if isinstance(payload.get("workbench"), dict) else {}
    if nested:
        return dict(nested)
    if not payload:
        return {}
    lifted: dict[str, Any] = {}
    for key in (
        "desiredState",
        "observedState",
        "phase",
        "failureMessage",
        "frontendMode",
        "frontendReady",
        "backendHealthy",
        "backendPortListening",
        "backendPortConflict",
    ):
        if key in payload:
            lifted[key] = payload[key]
    return lifted


def _clear_isolated_workbench_runtime(item: dict[str, Any]) -> None:
    """Drop leftover failed/open workbench flags so a stopped row can become startable."""

    path = str(item.get("path") or "").strip()
    if not path:
        return
    state_path = Path(path) / ".runtime" / "launcher" / "state.json"
    payload = _read_json_file(state_path)
    workbench = dict(payload.get("workbench") if isinstance(payload.get("workbench"), dict) else {})
    workbench["desiredState"] = "closed"
    workbench["observedState"] = "closed"
    workbench["phase"] = "steady"
    workbench["failureMessage"] = ""
    payload["workbench"] = workbench
    try:
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except OSError:
        return


def _bundled_frontend_ready(item: dict[str, Any]) -> bool:
    # Transitional dist probe (I1): TS projection does not inspect files.
    path = str(item.get("path") or "").strip()
    return bool(path and (Path(path) / "web" / "dist" / "index.html").is_file())


def resolve_branch_instance(instance_id: str) -> dict[str, Any]:
    wanted = str(instance_id or "").strip()
    if not wanted:
        raise BranchInstanceLifecycleError("instance_not_found", "未指定分支实例。", status_code=400)
    payload = list_overlayed_branch_instances()
    for item in payload.get("items") or []:
        if isinstance(item, dict) and str(item.get("id") or "") == wanted:
            return dict(item)
    raise BranchInstanceLifecycleError("instance_not_found", f"找不到分支实例：{wanted}", status_code=404)


def assert_instance_operable(item: dict[str, Any], operation: str) -> None:
    if operation in {"observe-error", "observe-ready"}:
        return
    if operation not in {"start", "stop", "restart", "force-stop"}:
        raise BranchInstanceLifecycleError(
            "invalid_instance_operation",
            f"不支持的实例操作：{operation}",
            status_code=400,
        )
    if operation in {"stop", "force-stop"} and _is_dismissable_failed_leftover(item):
        return
    kind = str(item.get("kind") or "")
    if kind not in _STARTABLE_KINDS or not item.get("checkedOut"):
        raise BranchInstanceLifecycleError(
            "instance_not_startable",
            "未打开或已退役的分支不能启停。请先 checkout 到仓内 .worktrees。",
        )
    path = str(item.get("path") or "").strip()
    if not item.get("current") and (not path or not Path(path).exists()):
        raise BranchInstanceLifecycleError(
            "instance_not_startable",
            "该分支没有可用的工作区路径，无法启停。",
        )


def current_live_ports(launcher_state: dict[str, Any] | None = None) -> set[int]:
    state = launcher_state if launcher_state is not None else _read_current_launcher_state()
    backend, control, _url = _current_control_plane_ports(state)
    return {port for port in (backend, control) if port > 0}


def run_isolated_operation(
    item: dict[str, Any],
    operation: str,
    *,
    runner: SpawnRunner | None = None,
    extra_used: Iterable[int] | None = None,
    terminate_pid: Callable[[int], dict[str, Any]] | None = None,
    claimed_generation: int | None = None,
) -> dict[str, Any]:
    """Start/stop/restart a non-current checked-out worktree on isolated ports."""

    if operation in {"observe-error", "observe-ready"}:
        raise BranchInstanceLifecycleError(
            "invalid_instance_operation",
            f"观察回调请使用 observe_isolated_transition：{operation}",
            status_code=400,
        )
    assert_instance_operable(item, operation)
    instance_id = str(item.get("id") or "")
    worktree = Path(str(item.get("path")))
    used = set(current_live_ports())
    used.update(int(port) for port in (extra_used or []) if int(port or 0) > 0)
    spawn = runner or spawn_worktree_launcher
    if operation in {"start", "restart"}:
        existing = registry.get_instance(instance_id)
        if str(existing.get("status") or "").strip().lower() in registry.IN_FLIGHT_STATUSES:
            if _reclaim_stale_in_flight_start(instance_id, item, existing):
                existing = registry.get_instance(instance_id)
            else:
                raise BranchInstanceLifecycleError(
                    "instance_busy",
                    "该分支实例正在执行生命周期操作。",
                    status_code=409,
                )
        if operation == "start" and _isolated_backend_alive(item):
            backend_port = _positive_int(item.get("port")) or registry.DEFAULT_BASE_PORT
            control_port = _positive_int(item.get("controlPort")) or registry.DEFAULT_CONTROL_PORT
            window = _open_instance_window(item, backend_port=backend_port)
            _upsert_instance_with_slot(
                instance_id,
                worktree,
                branch=str(item.get("branch") or ""),
                port=backend_port,
                control_port=control_port,
                status=str(existing.get("status") or "steady") or "steady",
                desired_state="open",
                phase="steady",
                window_pid=_positive_int(window.get("windowPid")),
                window_title=str(window.get("title") or ""),
            )
            return _isolated_response(
                operation,
                instance_id=instance_id,
                port=backend_port,
                control_port=control_port,
                generation=_positive_int(existing.get("generation")),
                command_id=str(existing.get("commandId") or ""),
                message="已打开该分支工作台窗口。",
            )
        claimed = _existing_matching_start_claim(instance_id, claimed_generation)
        if claimed is None:
            try:
                claimed = _claim_isolated_start(
                    item,
                    operation,
                    extra_used=used,
                )
            except registry.InstanceBusyError as exc:
                raise BranchInstanceLifecycleError(
                    "instance_busy",
                    "该分支实例正在执行生命周期操作。",
                    status_code=409,
                ) from exc
        backend_port = _positive_int(claimed.get("port"))
        control_port = _positive_int(claimed.get("controlPort"))
        generation = _positive_int(claimed.get("generation"))
        command_id = str(claimed.get("commandId") or "")
        try:
            spawned = spawn(
                worktree,
                "restart" if operation == "restart" else "start",
                backend_port,
                control_port,
                short_name=str(item.get("shortName") or ""),
                detach=True,
            )
        except BranchInstanceLifecycleError as exc:
            observe_isolated_transition(
                instance_id,
                "observe-error",
                generation=generation,
                message=exc.message,
            )
            raise
        spawn_pid = _positive_int((spawned or {}).get("pid"))
        if spawn_pid > 0:
            applied = registry.record_spawn_pid(instance_id, spawn_pid, generation)
            if not applied:
                killer = terminate_pid or terminate_pid_tree
                killer(spawn_pid)
        return _isolated_response(
            operation,
            instance_id=instance_id,
            port=backend_port,
            control_port=control_port,
            generation=generation,
            command_id=command_id,
            message="已在隔离端口启动选中工作区。" if operation == "start" else "已在隔离端口重启选中工作区。",
        )

    instance_id = _resolve_registry_instance_id(item) or instance_id
    existing = registry.get_instance(instance_id)
    backend_port = _positive_int(existing.get("port")) or _positive_int(item.get("port")) or registry.DEFAULT_BASE_PORT
    control_port = (
        _positive_int(existing.get("controlPort"))
        or _positive_int(item.get("controlPort"))
        or registry.DEFAULT_CONTROL_PORT
    )
    claimed_stop = _existing_matching_stop_claim(instance_id, claimed_generation)
    if claimed_stop is None:
        claimed_stop = _claim_isolated_stop(instance_id, item, existing)
    spawn_pid = _positive_int(claimed_stop.get("spawnPid"))
    killer = terminate_pid or terminate_pid_tree
    if spawn_pid > 0:
        killer(spawn_pid)
    if not _electron_main_orchestrates_windows():
        close_item = dict(item)
        close_item["id"] = instance_id
        close_isolated_workbench_window(close_item)
    launcher_script = PYTHON_LAUNCHER_SCRIPT_PATH
    if runner is not None or Path(launcher_script).is_file():
        try:
            spawn(worktree, "stop", backend_port, control_port, detach=False)
        except BranchInstanceLifecycleError:
            if _item_has_live_runtime(item):
                raise
    _upsert_instance_with_slot(
        instance_id,
        worktree,
        branch=str(item.get("branch") or ""),
        port=backend_port,
        control_port=control_port,
        status="closed",
        desired_state="closed",
        phase="steady",
        spawn_pid=0,
        failure_message="",
        window_pid=0,
        expected_generation=_positive_int(claimed_stop.get("generation")),
    )
    _clear_isolated_workbench_runtime(item)
    return _isolated_response(
        operation,
        instance_id=instance_id,
        port=backend_port,
        control_port=control_port,
        generation=_positive_int(registry.get_instance(instance_id).get("generation")),
        message="已停止选中工作区。",
    )


def spawn_worktree_launcher(
    worktree: Path | str,
    action: str,
    backend_port: int,
    control_port: int,
    *,
    timeout: float | None = None,
    short_name: str = "",
    detach: bool = False,
) -> dict[str, Any]:
    """Run the current supervisor launcher against the target worktree cwd."""

    root = Path(worktree)
    script = Path(PYTHON_LAUNCHER_SCRIPT_PATH)
    if not script.is_file():
        raise BranchInstanceLifecycleError(
            "instance_launcher_missing",
            f"当前监督者缺少 scripts/vibelution_launcher.py：{script}",
        )
    python = resolve_no_console_python(root)
    env = apply_slot_spawn_environment(
        os.environ,
        root,
        backend_port=int(backend_port),
        control_port=int(control_port),
        mkdir=True,
    )
    name = str(short_name or "").strip()
    if name:
        env["VIBELUTION_INSTANCE_SHORT_NAME"] = name
    if action in {"start", "restart"}:
        env["VIBELUTION_ALLOW_DIRTY_LAUNCH"] = "1"
        env["VIBELUTION_ALLOW_NON_MAIN_LAUNCH"] = "1"
    if timeout is None:
        if action == "start":
            timeout = _ISOLATED_START_TIMEOUT_SECONDS
        elif action == "restart":
            timeout = _ISOLATED_RESTART_TIMEOUT_SECONDS
        else:
            timeout = _ISOLATED_STOP_TIMEOUT_SECONDS
    command = [python, str(script), "--action", str(action), "--port", str(int(backend_port))]
    if action in {"start", "restart"}:
        command.append("--no-browser")
    popen_kwargs = detached_no_console_popen_kwargs() if detach else no_window_subprocess_kwargs()
    if detach:
        try:
            process = subprocess.Popen(
                command,
                cwd=str(root),
                env=env,
                **popen_kwargs,
            )
        except OSError as exc:
            raise BranchInstanceLifecycleError(
                "instance_lifecycle_failed",
                f"隔离实例 {action} 无法启动：{exc}",
            ) from exc
        return {
            "returncode": 0,
            "pid": int(getattr(process, "pid", 0) or 0),
            "python": python,
            "script": str(script),
            "command": command,
            "detached": True,
        }
    try:
        result = subprocess.run(
            command,
            cwd=str(root),
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=float(timeout),
            check=False,
            **popen_kwargs,
        )
    except subprocess.TimeoutExpired as exc:
        raise BranchInstanceLifecycleError(
            "instance_lifecycle_failed",
            f"隔离实例 {action} 超时（{timeout}s）：{root}",
        ) from exc
    if int(result.returncode or 0) != 0:
        detail = str(result.stderr or result.stdout or "").strip()[-800:]
        raise BranchInstanceLifecycleError(
            "instance_lifecycle_failed",
            f"隔离实例 {action} 失败（exit {result.returncode}）：{detail or 'no output'}",
        )
    return {
        "returncode": int(result.returncode or 0),
        "pid": 0,
        "python": python,
        "script": str(script),
        "command": command,
        "detached": False,
    }


def resolve_no_console_python(worktree: Path) -> str:
    # Spawn the supervisor launcher with the current-shell interpreter. A leftover
    # incomplete worktree .venv must not win over a ready supervisor pythonw.
    if os.name == "nt":
        candidates = (
            Path(sys.executable).with_name("pythonw.exe"),
            Path(sys.executable),
            worktree / ".venv" / "Scripts" / "pythonw.exe",
            worktree / ".venv" / "Scripts" / "python.exe",
        )
    else:
        candidates = (
            Path(sys.executable),
            worktree / ".venv" / "bin" / "python3",
            worktree / ".venv" / "bin" / "python",
        )
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate.resolve())
    raise BranchInstanceLifecycleError(
        "python_runtime_missing",
        f"工作区没有可用的无控制台 Python：{worktree}",
    )


def _isolated_response(
    operation: str,
    *,
    instance_id: str,
    port: int,
    control_port: int,
    message: str,
    generation: int = 0,
    command_id: str = "",
) -> dict[str, Any]:
    return {
        "accepted": True,
        "mode": "isolated_worktree",
        "launcherMode": "standalone_control_plane",
        "operation": operation,
        "commandId": str(command_id or ""),
        "generation": int(generation or 0),
        "instanceId": instance_id,
        "port": int(port),
        "controlPort": int(control_port),
        "url": _loopback_url(port),
        "message": message,
    }


def _read_current_launcher_state() -> dict[str, Any]:
    return _read_json_file(LAUNCHER_STATE_PATH)


def _read_json_file(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _current_control_plane_ports(state: dict[str, Any]) -> tuple[int, int, str]:
    workbench = state.get("workbench") if isinstance(state.get("workbench"), dict) else {}
    backend = _positive_int(
        workbench.get("backendPort") or state.get("backendPort") or state.get("port")
    )
    control = _positive_int(state.get("launcherControlPort") or workbench.get("launcherControlPort"))
    url = str(workbench.get("url") or state.get("url") or "").strip()
    if not url and backend > 0:
        url = _loopback_url(backend)
    return backend, control, url


def _loopback_url(port: int) -> str:
    return f"http://127.0.0.1:{int(port)}"


def _loopback_http_ready(port: int, *, timeout_seconds: float = 0.4) -> bool:
    """One-shot loopback probe matching Electron ``waitForWorkbenchHttp``.

    GET ``http://127.0.0.1:<port>/`` is ready when the status is in ``1..499``.
    Isolated list projection uses this when the backend pid is alive but disk
    nested ``backendPortListening`` / ``backendHealthy`` flags are missing.
    """

    normalized = _positive_int(port)
    if normalized <= 0:
        return False
    connection: http.client.HTTPConnection | None = None
    try:
        connection = http.client.HTTPConnection("127.0.0.1", normalized, timeout=timeout_seconds)
        connection.request("GET", "/", headers={"Accept": "*/*"})
        response = connection.getresponse()
        status = int(response.status or 0)
        response.read()
        return 0 < status < 500
    except (OSError, TimeoutError, ValueError, http.client.HTTPException):
        return False
    finally:
        if connection is not None:
            try:
                connection.close()
            except OSError:
                pass


def _positive_int(value: Any) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return 0
    return max(0, parsed)


def _open_instance_window(item: dict[str, Any], *, backend_port: int) -> dict[str, Any]:
    if _electron_main_orchestrates_windows():
        # T6: the Electron main opens the isolated window after the backend is live.
        return {
            "windowPid": 0,
            "title": str(item.get("workbenchTitle") or item.get("shortName") or item.get("branch") or ""),
            "url": _loopback_url(backend_port),
        }
    window_item = dict(item)
    window_item["port"] = int(backend_port)
    window_item["url"] = _loopback_url(backend_port)
    return open_isolated_workbench_window(window_item)


def _electron_main_orchestrates_windows() -> bool:
    return str(os.environ.get("VIBELUTION_ELECTRON_MAIN_ORCHESTRATES_WINDOWS", "")).strip() == "1"


def _isolated_backend_alive(item: dict[str, Any]) -> bool:
    if not item.get("alive"):
        return False
    return _positive_int(item.get("port")) > 0


def _runtime_bundle(item: dict[str, Any]) -> dict[str, Any]:
    runtime = item.get("runtime")
    return runtime if isinstance(runtime, dict) else {}


def _runtime_section(item: dict[str, Any], key: str) -> dict[str, Any]:
    section = _runtime_bundle(item).get(key)
    return section if isinstance(section, dict) else {}


def _item_has_live_runtime(item: dict[str, Any]) -> bool:
    backend = _runtime_section(item, "backend")
    window = _runtime_section(item, "window")
    return bool(
        item.get("alive")
        or backend.get("alive")
        or backend.get("listening")
        or window.get("open")
        or _isolated_backend_alive(item)
    )


def _is_dismissable_failed_leftover(item: dict[str, Any]) -> bool:
    if _item_has_live_runtime(item):
        return False
    state = str(_runtime_bundle(item).get("lifecycleState") or "").strip().lower()
    return state in {"error", "partial"}


def _resolve_registry_instance_id(item: dict[str, Any]) -> str:
    instance_id = str(item.get("id") or "").strip()
    if instance_id and registry.get_instance(instance_id):
        return instance_id
    found = registry.find_instance_by_project_root(str(item.get("path") or ""))
    found_id = str(found.get("instanceId") or "").strip()
    return found_id or instance_id


def observe_isolated_transition(
    instance_id: str,
    operation: str,
    *,
    generation: int | None = None,
    message: str = "",
) -> dict[str, Any]:
    """Apply a generation-scoped supervisor observation to one registry row."""

    wanted = str(instance_id or "").strip()
    if not wanted:
        raise BranchInstanceLifecycleError("instance_not_found", "未指定分支实例。", status_code=400)
    if operation not in {"observe-error", "observe-ready"}:
        raise BranchInstanceLifecycleError(
            "invalid_instance_operation",
            f"不支持的实例操作：{operation}",
            status_code=400,
        )
    expected = int(generation or 0)

    def mutator(payload: dict[str, Any]) -> dict[str, Any]:
        _applied, entry = registry.apply_observe(
            payload,
            instance_id=wanted,
            operation=operation,
            expected_generation=expected,
            message=message,
        )
        return entry

    stored = registry.mutate_registry(mutator)
    return {
        "accepted": True,
        "operation": operation,
        "instanceId": wanted,
        "generation": int(stored.get("generation") or 0),
        "status": str(stored.get("status") or ""),
        "message": str(stored.get("failureMessage") or ""),
    }


def terminate_pid_tree(pid: int, *, timeout_seconds: float = 5.0) -> dict[str, Any]:
    """Terminate a spawnPid process tree without taskkill.exe."""

    target = int(pid or 0)
    if target <= 0:
        return {"supported": True, "rootPid": 0, "requested": [], "terminated": []}
    try:
        import psutil
    except ImportError:
        return {"supported": False, "rootPid": target, "requested": [target], "terminated": []}
    try:
        root = psutil.Process(target)
        processes = list(root.children(recursive=True))
        processes.reverse()
        processes.append(root)
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return {"supported": True, "rootPid": target, "requested": [target], "terminated": []}
    requested = [int(proc.pid) for proc in processes]
    for proc in processes:
        try:
            proc.terminate()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    try:
        _gone, alive = psutil.wait_procs(processes, timeout=max(0.1, float(timeout_seconds)))
    except (OSError, psutil.Error):
        alive = []
    for proc in alive:
        try:
            proc.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    if alive:
        try:
            psutil.wait_procs(alive, timeout=1.0)
        except (OSError, psutil.Error):
            pass
    return {"supported": True, "rootPid": target, "requested": requested, "terminated": requested}


def _existing_matching_start_claim(instance_id: str, claimed_generation: int | None) -> dict[str, Any] | None:
    expected = int(claimed_generation or 0)
    if expected <= 0:
        return None
    existing = registry.get_instance(instance_id)
    if int(existing.get("generation") or 0) != expected:
        return None
    if str(existing.get("status") or "").strip().lower() not in {"starting", "restarting"}:
        return None
    return existing


def _existing_matching_stop_claim(instance_id: str, claimed_generation: int | None) -> dict[str, Any] | None:
    expected = int(claimed_generation or 0)
    if expected <= 0:
        return None
    existing = registry.get_instance(instance_id)
    if int(existing.get("generation") or 0) != expected:
        return None
    if str(existing.get("status") or "").strip().lower() != "stopping":
        return None
    return existing


def _claim_isolated_start(
    item: dict[str, Any],
    operation: str,
    *,
    extra_used: set[int],
) -> dict[str, Any]:
    instance_id = str(item.get("id") or "")
    worktree = Path(str(item.get("path")))
    preferred_backend = _positive_int(item.get("port")) or registry.DEFAULT_BASE_PORT
    preferred_control = _positive_int(item.get("controlPort")) or registry.DEFAULT_CONTROL_PORT
    command_id = str(uuid4())
    deadline_at = _deadline_iso(_ISOLATED_START_TIMEOUT_SECONDS)
    slot_fields = _slot_fields_for_path(worktree)

    def mutator(payload: dict[str, Any]) -> dict[str, Any]:
        registry._reconcile_payload(
            payload,
            git_worktree_roots=None,
            electron_window_instance_ids=(),
            now=datetime.now(timezone.utc),
            identity_inspector=registry.inspect_process_identity,
            listener_inspector=registry.inspect_listener_identity,
            pid_existence_inspector=registry._pid_is_present,
        )
        return registry.apply_claim_start(
            payload,
            instance_id=instance_id,
            project_root=str(worktree),
            branch=str(item.get("branch") or ""),
            operation=operation,
            command_id=command_id,
            deadline_at=deadline_at,
            owner_pid=os.getpid(),
            extra_used=set(extra_used),
            preferred_backend=preferred_backend,
            preferred_control=preferred_control,
            started_at=_now_iso(),
            slot_fields=slot_fields,
        )

    return registry.mutate_registry(mutator)


def _claim_isolated_stop(
    instance_id: str,
    item: dict[str, Any],
    existing: dict[str, Any],
) -> dict[str, Any]:
    worktree = Path(str(item.get("path") or existing.get("projectRoot") or ""))

    def mutator(payload: dict[str, Any]) -> dict[str, Any]:
        return registry.apply_claim_stop(
            payload,
            instance_id=instance_id,
            project_root=str(worktree),
        )

    return registry.mutate_registry(mutator)


def _deadline_iso(seconds: float) -> str:
    deadline = datetime.now(timezone.utc) + timedelta(seconds=max(0.0, float(seconds)))
    return deadline.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _upsert_instance_with_slot(
    instance_id: str,
    worktree: Path,
    *,
    branch: str,
    port: int,
    control_port: int,
    status: str,
    started_at: str | None = None,
    window_pid: int | None = None,
    window_title: str | None = None,
    desired_state: str | None = None,
    phase: str | None = None,
    generation: int | None = None,
    expected_generation: int | None = None,
    command_id: str | None = None,
    spawn_pid: int | None = None,
    deadline_at: str | None = None,
    failure_message: str | None = None,
) -> None:
    fields: dict[str, Any] = {
        "projectRoot": str(worktree),
        "branch": branch,
        "port": int(port),
        "controlPort": int(control_port),
        "url": _loopback_url(port),
        "status": status,
        **_slot_fields_for_path(worktree),
    }
    if started_at:
        fields["startedAt"] = started_at
    if window_pid is not None:
        fields["windowPid"] = int(window_pid)
    if window_title is not None:
        fields["windowTitle"] = str(window_title)
    if desired_state is not None:
        fields["desiredState"] = str(desired_state)
    if phase is not None:
        fields["phase"] = str(phase)
    if generation is not None:
        fields["generation"] = int(generation)
    if command_id is not None:
        fields["commandId"] = str(command_id)
    if spawn_pid is not None:
        fields["spawnPid"] = int(spawn_pid)
    if deadline_at is not None:
        fields["deadlineAt"] = str(deadline_at)
    if failure_message is not None:
        fields["failureMessage"] = str(failure_message)
    cas_generation = expected_generation if expected_generation is not None else generation
    registry.upsert_instance(instance_id, expected_generation=cas_generation, **fields)


def _slot_fields_for_path(project_root: Path | str) -> dict[str, Any]:
    text = str(project_root or "").strip()
    if not text:
        return {}
    try:
        return slot_fields_for_project(text)
    except (OSError, TypeError, ValueError):
        return {}


def _norm_path(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return os.path.normcase(os.path.normpath(text))


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
