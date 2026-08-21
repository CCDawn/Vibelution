"""Open and close named Workbench windows for isolated branch instances.

Isolated worktrees keep their own backend. The product desktop shell stays
singular: Electron opens an extra titled window. Missing or unconfirmed
Electron is a hard failure; Edge --app is not a product fallback. Tests
inject openers so this module never touches the operator desktop during
pytest.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any
from uuid import uuid4

from core.infrastructure.atomic_io import atomic_write_json
from core.launcher import desktop_session_store, lifecycle_intent_store
from core.runtime_manager import instance_lock
from core.runtime_manager.constants import PROJECT_ROOT

from core.infrastructure.instance_display_name import workbench_window_title
from core.runtime_manager import instances_registry as registry
from vibelution_storage import resolve_project_runtime_home

OPEN_INSTANCE_WORKBENCH = "open_instance_workbench"
CLOSE_INSTANCE_WORKBENCH = "close_instance_workbench"
_WINDOW_OPEN_WAIT_SECONDS = 8.0
_WINDOW_OPEN_POLL_SECONDS = 0.2
_ELECTRON_WINDOW_REQUIRED_MESSAGE = (
    "Electron desktop shell is unavailable. Refusing Edge fallback for the isolated workbench window."
)

WindowOpener = Callable[[dict[str, Any]], dict[str, Any]]
WindowCloser = Callable[[dict[str, Any]], dict[str, Any]]


def instance_workbench_title(item: dict[str, Any]) -> str:
    explicit = str(item.get("workbenchTitle") or "").strip()
    if explicit:
        return explicit
    return workbench_window_title(str(item.get("shortName") or item.get("branch") or "detached"))


def overlay_instance_window_pid(item: dict[str, Any], entry: dict[str, Any] | None) -> None:
    """Copy a live registry window pid onto a non-current instance row."""

    if not isinstance(item, dict) or item.get("current"):
        return
    pid = _live_pid((entry or {}).get("windowPid"))
    if pid <= 0:
        return
    pids = item.get("pids")
    if not isinstance(pids, dict):
        pids = {}
        item["pids"] = pids
    pids["window"] = pid


def persist_instance_window_from_desktop_action(action: dict[str, Any]) -> None:
    """Write Electron ack renderer pid back to the instance registry."""

    if not isinstance(action, dict):
        return
    name = str(action.get("action") or "").strip()
    payload = action.get("payload") if isinstance(action.get("payload"), dict) else {}
    instance_id = str(payload.get("instanceId") or "").strip()
    if not instance_id:
        return
    if name == OPEN_INSTANCE_WORKBENCH:
        result = action.get("result") if isinstance(action.get("result"), dict) else {}
        window_state = result.get("windowState") if isinstance(result.get("windowState"), dict) else {}
        pid = _positive_int(window_state.get("rendererProcessId"))
        title = str(payload.get("windowTitle") or window_state.get("title") or "").strip()
        _persist_window_fields(instance_id, window_pid=pid, window_title=title)
        return
    if name == CLOSE_INSTANCE_WORKBENCH:
        _persist_window_fields(instance_id, window_pid=0)


def close_isolated_workbench_window(
    item: dict[str, Any],
    *,
    closer: WindowCloser | None = None,
) -> dict[str, Any]:
    """Close the named window without stopping the current main workbench."""

    instance_id = str(item.get("id") or "").strip()
    if _running_under_pytest() and closer is None:
        if instance_id:
            _persist_window_fields(instance_id, window_pid=0)
        return {"provider": "test", "windowPid": 0}
    runner = closer or _default_close
    result = runner(item) or {}
    if instance_id:
        _persist_window_fields(instance_id, window_pid=0)
    return result


def _submit_instance_window_action(
    action: str,
    item: dict[str, Any],
    *,
    reason: str,
    extra_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    instance_id = str(item.get("id") or "").strip()
    payload = {"instanceId": instance_id}
    if extra_payload:
        payload.update(extra_payload)
    return lifecycle_intent_store.submit_lifecycle_intent(
        {
            "action": action,
            "reason": reason,
            "idempotencyKey": f"{action}:{instance_id}:{uuid4().hex}",
        },
        actor_context={
            "actorType": "launcher_api",
            "actorId": "isolated-instance-window",
            "sourceRunId": "",
            "sourceTaskId": "",
            "sourceWorktree": str(item.get("path") or ""),
        },
        active_work_runs=[],
        desktop_action_payload=payload,
    )



def _electron_desktop_shell_available() -> bool:
    try:
        session = desktop_session_store.latest_active_desktop_session(
            provider="electron",
            workspace_root=str(PROJECT_ROOT),
        )
    except (OSError, TypeError, ValueError):
        return False
    return bool(session)


def _default_close(item: dict[str, Any]) -> dict[str, Any]:
    if _electron_desktop_shell_available():
        intent = _submit_instance_window_action(
            CLOSE_INSTANCE_WORKBENCH,
            item,
            reason="isolated_branch_instance_window_close",
        )
        return {"provider": "electron", "windowPid": 0, "intentId": str(intent.get("intentId") or "")}
    _terminate_edge_window_pid(item)
    return {"provider": "edge_app", "windowPid": 0}


def _persist_window_fields(instance_id: str, *, window_pid: int, window_title: str = "") -> None:
    fields: dict[str, Any] = {"windowPid": int(window_pid)}
    if window_title:
        fields["windowTitle"] = window_title
    registry.upsert_instance(instance_id, **fields)
    entry = registry.get_instance(instance_id)
    root = str(entry.get("projectRoot") or "").strip()
    if root:
        _write_worktree_window_pid(Path(root), int(window_pid))


def _write_worktree_window_pid(worktree: Path, pid: int) -> None:
    path = resolve_project_runtime_home(worktree) / "launcher" / "state.json"
    try:
        # The instance state is shared with the launcher/runtime manager. Keep
        # the read-modify-write under the same lockdir protocol and publish the
        # new document atomically so readers cannot observe torn JSON.
        with instance_lock.hold_instance_lock(path):
            try:
                payload = json.loads(path.read_text(encoding="utf-8-sig"))
            except FileNotFoundError:
                payload = {}
            except (OSError, json.JSONDecodeError, TypeError, ValueError):
                # Never replace an unreadable state file with a partial
                # projection; a later lifecycle observation can repair it.
                return
            if not isinstance(payload, dict):
                return
            payload["browserWindowPid"] = int(pid)
            payload["windowPid"] = int(pid)
            atomic_write_json(path, payload)
    except (OSError, TimeoutError):
        return


def _terminate_edge_window_pid(item: dict[str, Any]) -> None:
    instance_id = str(item.get("id") or "").strip()
    entry = registry.get_instance(instance_id) if instance_id else {}
    pid = _positive_int(entry.get("windowPid"))
    if pid <= 0:
        return
    try:
        from scripts.vibelution_launcher import _terminate_pid

        _terminate_pid(pid)
    except Exception:
        return


def _running_under_pytest() -> bool:
    return bool(os.environ.get("PYTEST_CURRENT_TEST"))


def _live_pid(value: Any) -> int:
    pid = _positive_int(value)
    if pid <= 0:
        return 0
    if os.name != "nt":
        try:
            os.kill(pid, 0)
        except OSError:
            return 0
        return pid
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = kernel32.OpenProcess(0x1000, False, pid) or kernel32.OpenProcess(0x0400, False, pid)
    if not handle:
        return 0
    try:
        exit_code = wintypes.DWORD()
        if kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)) == 0:
            return 0
        return pid if int(exit_code.value) == 259 else 0
    finally:
        kernel32.CloseHandle(handle)


def _positive_int(value: Any) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return 0
    return max(0, parsed)
