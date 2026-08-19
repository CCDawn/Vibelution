"""Process identity checks used by Runtime Manager and Launcher governance."""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path
from typing import Any


def _normalized_executable(value: Any) -> str:
    text = str(value or "").strip()
    return os.path.normcase(os.path.normpath(text)) if text else ""


def capture_process_identity(
    pid: int,
    *,
    process_factory: Callable[[int], Any] | None = None,
) -> dict[str, Any]:
    """Capture the stable fields required to distinguish PID reuse."""
    normalized_pid = int(pid or 0)
    if normalized_pid <= 0:
        return {}
    try:
        import psutil
    except ImportError:
        return {}
    factory = process_factory or psutil.Process
    try:
        process = factory(normalized_pid)
        executable = str(process.exe() or "").strip()
        create_time = float(process.create_time())
    except (psutil.NoSuchProcess, psutil.ZombieProcess, psutil.AccessDenied, OSError, ValueError):
        return {}
    if not executable or create_time <= 0:
        return {}
    return {
        "pid": normalized_pid,
        "createTime": create_time,
        "executable": executable,
    }


def inspect_process_identity(
    expected: dict[str, Any],
    *,
    process_factory: Callable[[int], Any] | None = None,
) -> dict[str, Any]:
    """Return ``match``, ``dead``, ``mismatch`` or ``unknown`` fail-closed."""
    try:
        pid = int(expected.get("pid") or 0)
        expected_create_time = float(expected.get("createTime") or 0)
    except (AttributeError, TypeError, ValueError):
        return {"status": "unknown", "reason": "invalid_expected_identity"}
    expected_executable = str(expected.get("executable") or "").strip()
    if pid <= 0 or expected_create_time <= 0 or not expected_executable:
        return {"status": "unknown", "reason": "incomplete_expected_identity"}

    try:
        import psutil
    except ImportError:
        return {"status": "unknown", "reason": "psutil_unavailable"}
    factory = process_factory or psutil.Process
    try:
        process = factory(pid)
        actual_create_time = float(process.create_time())
        actual_executable = str(process.exe() or "").strip()
    except (psutil.NoSuchProcess, psutil.ZombieProcess, ProcessLookupError):
        return {"status": "dead", "reason": "process_not_found"}
    except (psutil.AccessDenied, PermissionError):
        return {"status": "unknown", "reason": "access_denied"}
    except (OSError, TypeError, ValueError):
        return {"status": "unknown", "reason": "identity_probe_failed"}

    if abs(actual_create_time - expected_create_time) > 0.001:
        return {"status": "mismatch", "reason": "create_time_mismatch"}
    if _normalized_executable(actual_executable) != _normalized_executable(expected_executable):
        return {"status": "mismatch", "reason": "executable_mismatch"}
    return {"status": "match", "reason": "identity_match"}


def _identity_matches(actual: dict[str, Any], expected: dict[str, Any]) -> bool:
    try:
        same_pid = int(actual.get("pid") or 0) == int(expected.get("pid") or 0)
        same_time = abs(float(actual.get("createTime") or 0) - float(expected.get("createTime") or 0)) <= 0.001
    except (AttributeError, TypeError, ValueError):
        return False
    actual_exe = _normalized_executable(actual.get("executable"))
    expected_exe = _normalized_executable(expected.get("executable"))
    return bool(same_pid and same_time and actual_exe and actual_exe == expected_exe)


def inspect_listener_identity(
    port: int,
    expected_identities: Any,
    *,
    identity_capture: Callable[[int], dict[str, Any]] = capture_process_identity,
) -> dict[str, Any]:
    """Classify a listener without using port ownership as kill authority."""
    normalized_port = int(port or 0)
    if normalized_port <= 0:
        return {"status": "none"}
    try:
        import psutil
    except ImportError:
        return {"status": "unknown", "reason": "psutil_unavailable"}
    try:
        connections = psutil.net_connections(kind="tcp")
    except (psutil.AccessDenied, OSError):
        return {"status": "unknown", "reason": "listener_probe_failed"}

    expected = [dict(item) for item in expected_identities if isinstance(item, dict)]
    owned_pids: list[int] = []
    external_pids: list[int] = []
    unknown_pids: list[int] = []
    for connection in connections:
        if str(getattr(connection, "status", "")).upper() != "LISTEN":
            continue
        address = getattr(connection, "laddr", None)
        try:
            listener_port = int(address.port if hasattr(address, "port") else address[1])
        except (IndexError, TypeError, ValueError):
            continue
        if listener_port != normalized_port:
            continue
        try:
            pid = int(getattr(connection, "pid", 0) or 0)
        except (TypeError, ValueError):
            pid = 0
        if pid <= 0:
            unknown_pids.append(0)
            continue
        actual = identity_capture(pid)
        if not actual:
            unknown_pids.append(pid)
            continue
        if any(_identity_matches(actual, item) for item in expected):
            owned_pids.append(pid)
        else:
            external_pids.append(pid)
    if external_pids:
        return {"status": "external", "pid": external_pids[0]}
    if unknown_pids:
        return {"status": "unknown", "reason": "listener_identity_unavailable", "pid": unknown_pids[0]}
    if owned_pids:
        return {"status": "owned", "pid": owned_pids[0]}
    return {"status": "none"}


def command_line_text(parts: Any) -> str:
    if isinstance(parts, str):
        return parts
    if isinstance(parts, (list, tuple)):
        return " ".join(str(part) for part in parts if part is not None)
    return ""


def runtime_manager_command_line_for_pid(pid: int) -> str:
    if int(pid or 0) <= 0:
        return ""
    try:
        import psutil
    except ImportError:
        psutil = None  # type: ignore[assignment]
    if psutil is not None:
        try:
            process = psutil.Process(int(pid))
            return command_line_text(process.cmdline())
        except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
            pass
    proc_cmdline_path = Path("/proc") / str(int(pid)) / "cmdline"
    try:
        return proc_cmdline_path.read_bytes().replace(b"\x00", b" ").decode("utf-8", errors="replace").strip()
    except OSError:
        return ""


def command_line_is_runtime_manager_daemon(command_line: str) -> bool:
    normalized = str(command_line or "").replace("\\", "/").lower()
    if not normalized:
        return False
    return (
        ("core.runtime_manager.cli" in normalized or "core/runtime_manager/cli.py" in normalized)
        and "daemon" in normalized.split()
    )


def is_runtime_manager_process(pid: int) -> bool:
    return command_line_is_runtime_manager_daemon(runtime_manager_command_line_for_pid(int(pid or 0)))
