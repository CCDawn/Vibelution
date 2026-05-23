"""File-backed command queue for the runtime manager."""

from __future__ import annotations

import json
import os
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from .constants import (
    DEFAULT_COMMAND_WAIT_SECONDS,
    EVENTS_PATH,
    INBOX_DIR,
    PROCESSING_DIR,
    RESULTS_DIR,
    ensure_runtime_manager_dirs,
)
from .state_store import load_pid, load_state


def _command_timestamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def build_command(command_type: str, *, args: dict[str, Any] | None = None, requested_by: str = "unknown") -> dict[str, Any]:
    return {
        "commandId": f"cmd_{_command_timestamp()}_{uuid4().hex[:8]}",
        "type": str(command_type or "").strip(),
        "requestedBy": str(requested_by or "unknown").strip() or "unknown",
        "requestedAt": datetime.now(UTC).isoformat(),
        "args": args or {},
    }


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    ensure_runtime_manager_dirs()
    fd, temp_path = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
        os.replace(temp_path, path)
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


def submit_command(
    command_type: str,
    *,
    args: dict[str, Any] | None = None,
    requested_by: str = "unknown",
) -> dict[str, Any]:
    command = build_command(command_type, args=args, requested_by=requested_by)
    shutdown_state = _shutdown_in_progress_state()
    if shutdown_state is not None:
        _append_queue_event(
            "command_queue.command_rejected_shutdown",
            {
                "commandId": str(command.get("commandId") or ""),
                "type": str(command.get("type") or ""),
                "requestedBy": str(command.get("requestedBy") or ""),
                "stateVersion": int(shutdown_state.get("stateVersion") or 0),
                "managerPid": int(shutdown_state.get("managerPid") or 0),
            },
        )
        _complete_rejected_shutdown_command(command, shutdown_state=shutdown_state)
        return command
    _atomic_write_json(INBOX_DIR / f"{command['commandId']}.json", command)
    return command


def wait_for_result(command_id: str, *, timeout_seconds: float = DEFAULT_COMMAND_WAIT_SECONDS) -> dict[str, Any]:
    deadline = time.monotonic() + max(0.5, float(timeout_seconds))
    result_path = RESULTS_DIR / f"{command_id}.json"
    while time.monotonic() < deadline:
        if result_path.exists():
            payload = json.loads(result_path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                return payload
            break
        time.sleep(0.2)
    raise TimeoutError(f"Timed out waiting for runtime-manager command {command_id}.")


def recover_processing_queue() -> None:
    ensure_runtime_manager_dirs()
    for path in sorted(PROCESSING_DIR.glob("*.json")):
        target = INBOX_DIR / path.name
        try:
            os.replace(path, target)
        except OSError:
            continue


def claim_next_command() -> tuple[Path, dict[str, Any]] | None:
    ensure_runtime_manager_dirs()
    for path in sorted(INBOX_DIR.glob("*.json")):
        target = PROCESSING_DIR / path.name
        try:
            os.replace(path, target)
        except OSError:
            continue
        try:
            payload = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            payload = {}
        if isinstance(payload, dict):
            return target, payload
        try:
            target.unlink(missing_ok=True)
        except OSError:
            pass
    return None


def complete_command(path: Path, result: dict[str, Any]) -> None:
    command_id = str(result.get("commandId") or path.stem).strip() or path.stem
    _atomic_write_json(RESULTS_DIR / f"{command_id}.json", result)
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def reject_pending_commands_for_shutdown(*, shutdown_state: dict[str, Any] | None = None) -> dict[str, Any]:
    state = shutdown_state if isinstance(shutdown_state, dict) else load_state()
    rejected: list[dict[str, Any]] = []
    for path in sorted(INBOX_DIR.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            payload = {}
        command = payload if isinstance(payload, dict) else {}
        command_id = str(command.get("commandId") or path.stem).strip() or path.stem
        command["commandId"] = command_id
        try:
            _complete_rejected_shutdown_command(command, shutdown_state=state)
            path.unlink(missing_ok=True)
        except OSError as exc:
            rejected.append(
                {
                    "commandId": command_id,
                    "type": str(command.get("type") or ""),
                    "status": "failed",
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
            continue
        rejected.append(
            {
                "commandId": command_id,
                "type": str(command.get("type") or ""),
                "status": "completed",
            }
        )
    return {
        "count": len(rejected),
        "items": rejected,
    }


def _shutdown_in_progress_state() -> dict[str, Any] | None:
    manager_pid = load_pid()
    if not _process_is_alive(manager_pid):
        return None
    state = load_state()
    if not isinstance(state, dict):
        return None
    if not _state_belongs_to_current_manager(state, manager_pid):
        if _state_mentions_runtime_manager_shutdown(state):
            _append_queue_event(
                "command_queue.stale_shutdown_state_ignored",
                {
                    "stateVersion": int(state.get("stateVersion") or 0),
                    "stateManagerPid": int(state.get("managerPid") or 0),
                    "currentManagerPid": int(manager_pid or 0),
                    "runtimeState": str(state.get("runtimeState") or ""),
                },
            )
        return None
    if str(state.get("runtimeState") or "").strip().lower() == "stopping":
        return state
    command = state.get("command") if isinstance(state.get("command"), dict) else {}
    if not str(command.get("activeCommandId") or "").strip():
        return None
    if str(command.get("activeType") or "").strip() != "close_workbench":
        return None
    if not bool(command.get("stopManager")):
        return None
    return state


def _state_belongs_to_current_manager(state: dict[str, Any], manager_pid: int) -> bool:
    try:
        state_manager_pid = int(state.get("managerPid") or 0)
    except (TypeError, ValueError):
        state_manager_pid = 0
    return state_manager_pid > 0 and state_manager_pid == int(manager_pid or 0)


def _state_mentions_runtime_manager_shutdown(state: dict[str, Any]) -> bool:
    if str(state.get("runtimeState") or "").strip().lower() == "stopping":
        return True
    command = state.get("command") if isinstance(state.get("command"), dict) else {}
    return (
        str(command.get("activeCommandId") or "").strip() != ""
        and str(command.get("activeType") or "").strip() == "close_workbench"
        and bool(command.get("stopManager"))
    )


def _append_queue_event(event_type: str, payload: dict[str, Any]) -> None:
    try:
        ensure_runtime_manager_dirs()
        event = {
            "type": event_type,
            "at": datetime.now(UTC).isoformat(),
            "payload": payload,
        }
        with EVENTS_PATH.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False) + "\n")
    except OSError:
        pass


def _complete_rejected_shutdown_command(command: dict[str, Any], *, shutdown_state: dict[str, Any]) -> None:
    command_type = str(command.get("type") or "").strip()
    args = command.get("args") if isinstance(command.get("args"), dict) else {}
    duplicate_shutdown = command_type == "close_workbench" and bool(args.get("stopManager"))
    message = (
        "Runtime manager shutdown is already in progress."
        if duplicate_shutdown
        else "Runtime manager is shutting down; command was not queued."
    )
    result: dict[str, Any] = {
        "commandId": str(command.get("commandId") or "").strip(),
        "accepted": True,
        "completed": True,
        "ok": duplicate_shutdown,
        "message": message,
        "stateVersion": int(shutdown_state.get("stateVersion") or 0),
        "runtimeManagerStopping": True,
    }
    if not duplicate_shutdown:
        result["errorType"] = "RuntimeManagerStoppingError"
    _atomic_write_json(RESULTS_DIR / f"{command['commandId']}.json", result)


def _process_is_alive(pid: int) -> bool:
    normalized_pid = int(pid or 0)
    if normalized_pid <= 0:
        return False
    if os.name == "nt":
        return _process_is_alive_windows(normalized_pid)
    try:
        os.kill(normalized_pid, 0)
    except OSError:
        return False
    return True


def _process_is_alive_windows(pid: int) -> bool:
    import ctypes
    from ctypes import wintypes

    process_query_limited_information = 0x1000
    still_active = 259

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = kernel32.OpenProcess(process_query_limited_information, False, int(pid))
    if not handle:
        return False
    try:
        exit_code = wintypes.DWORD()
        if kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)) == 0:
            return False
        return int(exit_code.value) == still_active
    finally:
        kernel32.CloseHandle(handle)
