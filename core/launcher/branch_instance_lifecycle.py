"""Per-row Launcher start/stop for Git-governed branch instances.

The current checkout keeps the existing Runtime Manager lifecycle. Other
checked-out worktrees are started and stopped through that worktree's
``scripts/vibelution_launcher.py`` on isolated backend/control ports.
Retired shells and not-checked-out refs cannot be started.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Callable, Iterable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.infrastructure.branch_workspace import list_branch_instances
from core.launcher.isolated_workbench_window import (
    close_isolated_workbench_window,
    open_isolated_workbench_window,
    overlay_instance_window_pid,
)
from core.launcher.slot_identity import apply_slot_spawn_environment, slot_fields_for_project
from core.runtime_manager import instances_registry as registry
from core.runtime_manager.constants import LAUNCHER_STATE_PATH, PROJECT_ROOT
from scripts.windowless_subprocess import no_window_subprocess_kwargs

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
    phase = str(bundle.get("phase") or workbench.get("phase") or "steady").strip().lower()
    desired_state = str(bundle.get("desiredState") or workbench.get("desiredState") or "closed").strip().lower()
    failure_message = str(bundle.get("failureMessage") or workbench.get("failureMessage") or "").strip()
    registry_status = "" if bundle else str((entry or {}).get("status") or "").strip().lower()

    lifecycle_state, error_code = _instance_lifecycle_state(
        observed_state=observed_state,
        phase=phase,
        registry_status=registry_status,
        backend_alive=backend_alive,
        backend_healthy=backend_healthy,
        backend_listening=backend_listening,
        backend_conflict=backend_conflict,
        frontend_ready=frontend_ready,
        window_open=window_open,
        failure_message=failure_message,
    )
    if lifecycle_state == "error" and not failure_message:
        failure_message = {
            "backend_port_conflict": "后端端口被其他进程占用。",
            "registry_failed": "该分支上次启动失败。",
            "lifecycle_failed": "该分支生命周期进入失败状态。",
        }.get(error_code, "该分支运行状态异常。")

    runtime: dict[str, Any] = {
        "lifecycleState": lifecycle_state,
        "desiredState": desired_state or "closed",
        "observedState": observed_state or "closed",
        "phase": phase or "steady",
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
    return runtime


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
) -> tuple[str, str]:
    if phase in {"opening", "starting"}:
        return "starting", ""
    if phase in {"restarting", "restart"}:
        return "restarting", ""
    if phase in {"closing", "stopping", "force_stopping"}:
        return "stopping", ""
    if backend_conflict:
        return "error", "backend_port_conflict"
    if phase == "failed":
        return "error", "lifecycle_failed"
    if registry_status == "failed":
        return "error", "registry_failed"
    if failure_message:
        return "error", "runtime_error"

    backend_ready = backend_alive and backend_healthy and backend_listening and not backend_conflict
    if backend_ready and frontend_ready and window_open:
        return "running", ""
    has_runtime_signal = bool(
        backend_alive
        or backend_listening
        or window_open
        or observed_state in {"open", "partial", "running", "healthy"}
        or registry_status == "running"
    )
    if has_runtime_signal:
        return "partial", ""
    return "closed", ""


def _instance_start_block_reason(item: dict[str, Any], runtime: dict[str, Any]) -> str:
    if str(item.get("kind") or "") not in _STARTABLE_KINDS:
        return "unsupported_kind"
    if not item.get("checkedOut"):
        return "not_checked_out"
    path = str(item.get("path") or "").strip()
    if not path or not Path(path).is_dir():
        return "worktree_missing"
    state = str(runtime.get("lifecycleState") or "closed")
    if state != "closed":
        return "runtime_error" if state == "error" else "runtime_active"
    return ""


def _workbench_state_for_item(item: dict[str, Any]) -> dict[str, Any]:
    path = str(item.get("path") or "").strip()
    if not path:
        return {}
    payload = _read_json_file(Path(path) / ".runtime" / "launcher" / "state.json")
    workbench = payload.get("workbench") if isinstance(payload.get("workbench"), dict) else {}
    return dict(workbench)


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
) -> dict[str, Any]:
    """Start/stop/restart a non-current checked-out worktree on isolated ports."""

    assert_instance_operable(item, operation)
    instance_id = str(item.get("id") or "")
    worktree = Path(str(item.get("path")))
    used = set(current_live_ports())
    used.update(int(port) for port in (extra_used or []) if int(port or 0) > 0)
    spawn = runner or spawn_worktree_launcher
    if operation in {"start", "restart"}:
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
                status="running",
                window_pid=_positive_int(window.get("windowPid")),
                window_title=str(window.get("title") or ""),
            )
            return _isolated_response(
                operation,
                instance_id=instance_id,
                port=backend_port,
                control_port=control_port,
                message="已打开该分支工作台窗口。",
            )
        backend_port, control_port = registry.allocate_instance_ports(
            instance_id,
            preferred_backend=_positive_int(item.get("port")) or registry.DEFAULT_BASE_PORT,
            preferred_control=_positive_int(item.get("controlPort")) or registry.DEFAULT_CONTROL_PORT,
            extra_used=used,
        )
        action = "restart" if operation == "restart" else "start"
        try:
            spawn(
                worktree,
                action,
                backend_port,
                control_port,
                short_name=str(item.get("shortName") or ""),
            )
        except BranchInstanceLifecycleError:
            _upsert_instance_with_slot(
                instance_id,
                worktree,
                branch=str(item.get("branch") or ""),
                port=backend_port,
                control_port=control_port,
                status="failed",
            )
            raise
        window = _open_instance_window(item, backend_port=backend_port)
        _upsert_instance_with_slot(
            instance_id,
            worktree,
            branch=str(item.get("branch") or ""),
            port=backend_port,
            control_port=control_port,
            status="running",
            started_at=_now_iso(),
            window_pid=_positive_int(window.get("windowPid")),
            window_title=str(window.get("title") or ""),
        )
        return _isolated_response(
            operation,
            instance_id=instance_id,
            port=backend_port,
            control_port=control_port,
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
    close_item = dict(item)
    close_item["id"] = instance_id
    close_isolated_workbench_window(close_item)
    launcher_script = worktree / "scripts" / "vibelution_launcher.py"
    if runner is not None or launcher_script.is_file():
        try:
            spawn(worktree, "stop", backend_port, control_port)
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
        window_pid=0,
    )
    _clear_isolated_workbench_runtime(item)
    return _isolated_response(
        operation,
        instance_id=instance_id,
        port=backend_port,
        control_port=control_port,
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
) -> dict[str, Any]:
    """Run the target checkout's launcher script without a visible console."""

    root = Path(worktree)
    script = root / "scripts" / "vibelution_launcher.py"
    if not script.is_file():
        raise BranchInstanceLifecycleError(
            "instance_launcher_missing",
            f"工作区缺少 scripts/vibelution_launcher.py：{root}",
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
            **no_window_subprocess_kwargs(),
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
        "python": python,
        "script": str(script),
        "command": command,
    }


def resolve_no_console_python(worktree: Path) -> str:
    if os.name == "nt":
        candidates = (
            worktree / ".venv" / "Scripts" / "pythonw.exe",
            Path(sys.executable).with_name("pythonw.exe"),
            worktree / ".venv" / "Scripts" / "python.exe",
            Path(sys.executable),
        )
    else:
        candidates = (
            worktree / ".venv" / "bin" / "python3",
            worktree / ".venv" / "bin" / "python",
            Path(sys.executable),
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
) -> dict[str, Any]:
    return {
        "accepted": True,
        "mode": "isolated_worktree",
        "launcherMode": "standalone_control_plane",
        "operation": operation,
        "commandId": "",
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


def _positive_int(value: Any) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return 0
    return max(0, parsed)


def _open_instance_window(item: dict[str, Any], *, backend_port: int) -> dict[str, Any]:
    window_item = dict(item)
    window_item["port"] = int(backend_port)
    window_item["url"] = _loopback_url(backend_port)
    return open_isolated_workbench_window(window_item)


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
    registry.upsert_instance(instance_id, **fields)


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
