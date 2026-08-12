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
) -> dict[str, Any]:
    """Attach reserved/live ports to a branch-instance list without changing identity."""

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
    return payload


def list_overlayed_branch_instances() -> dict[str, Any]:
    return overlay_instance_ports(list_branch_instances(PROJECT_ROOT))


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
    if operation not in {"start", "stop", "restart", "force-stop"}:
        raise BranchInstanceLifecycleError(
            "invalid_instance_operation",
            f"不支持的实例操作：{operation}",
            status_code=400,
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
        backend_port, control_port = registry.allocate_instance_ports(
            instance_id,
            preferred_backend=_positive_int(item.get("port")) or registry.DEFAULT_BASE_PORT,
            preferred_control=_positive_int(item.get("controlPort")) or registry.DEFAULT_CONTROL_PORT,
            extra_used=used,
        )
        action = "restart" if operation == "restart" else "start"
        try:
            spawn(worktree, action, backend_port, control_port)
        except BranchInstanceLifecycleError:
            registry.upsert_instance(
                instance_id,
                projectRoot=str(worktree),
                branch=str(item.get("branch") or ""),
                port=backend_port,
                controlPort=control_port,
                url=_loopback_url(backend_port),
                status="failed",
            )
            raise
        registry.upsert_instance(
            instance_id,
            projectRoot=str(worktree),
            branch=str(item.get("branch") or ""),
            port=backend_port,
            controlPort=control_port,
            url=_loopback_url(backend_port),
            status="running",
            startedAt=_now_iso(),
        )
        return _isolated_response(
            operation,
            instance_id=instance_id,
            port=backend_port,
            control_port=control_port,
            message="已在隔离端口启动选中工作区。" if operation == "start" else "已在隔离端口重启选中工作区。",
        )

    existing = registry.get_instance(instance_id)
    backend_port = _positive_int(existing.get("port")) or _positive_int(item.get("port")) or registry.DEFAULT_BASE_PORT
    control_port = (
        _positive_int(existing.get("controlPort"))
        or _positive_int(item.get("controlPort"))
        or registry.DEFAULT_CONTROL_PORT
    )
    spawn(worktree, "stop", backend_port, control_port)
    registry.upsert_instance(
        instance_id,
        projectRoot=str(worktree),
        branch=str(item.get("branch") or ""),
        port=backend_port,
        controlPort=control_port,
        url=_loopback_url(backend_port),
        status="closed",
    )
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
    env = os.environ.copy()
    env["VIBELUTION_PORT"] = str(int(backend_port))
    env["VIBELUTION_LAUNCHER_PORT"] = str(int(control_port))
    env["AGENT_WORKBENCH_BACKEND_PORT"] = str(int(backend_port))
    env["AGENT_LAUNCHER_CONTROL_PORT"] = str(int(control_port))
    if timeout is None:
        if action == "start":
            timeout = _ISOLATED_START_TIMEOUT_SECONDS
        elif action == "restart":
            timeout = _ISOLATED_RESTART_TIMEOUT_SECONDS
        else:
            timeout = _ISOLATED_STOP_TIMEOUT_SECONDS
    command = [python, str(script), "--action", str(action), "--port", str(int(backend_port))]
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
    try:
        payload = json.loads(LAUNCHER_STATE_PATH.read_text(encoding="utf-8-sig"))
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


def _norm_path(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return os.path.normcase(os.path.normpath(text))


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
