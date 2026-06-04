"""Background runtime-manager daemon."""

from __future__ import annotations

import hashlib
import json
import os
import signal
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from core.runtime_manager.evolution_store import build_evolution_summary
from core.web.services import self_evolution_control_service, supervised_control_service

from .command_queue import claim_next_command, complete_command, recover_processing_queue, reject_pending_commands_for_shutdown
from .constants import (
    DAEMON_LOOP_INTERVAL_SECONDS,
    DAEMON_STDERR_PATH,
    DAEMON_STDOUT_PATH,
    EVENTS_PATH,
    PROJECT_ROOT,
    RESULTS_DIR,
    STATE_PATH,
    ensure_runtime_manager_dirs,
)
from .restart_coordinator import claim_next_restart_intent, complete_restart_intent
from .scene_logging import append_runtime_manager_file_event, record_runtime_manager_scene_event, runtime_manager_event_phase
from .state_store import clear_pid, default_state, load_pid, load_state, now_iso, save_pid, save_state
from .process_inventory import (
    list_repo_runtime_processes,
    residual_process_payload,
    terminate_process_descendants,
    terminate_unmanaged_workbench_processes,
)
from .workbench_controller import close_workbench, observe_workbench, open_workbench, restart_workbench


_WORKBENCH_LIFECYCLE_COMMANDS = {"open_workbench", "close_workbench", "restart_workbench", "toggle_workbench"}
_SOURCE_SIGNATURE_PATHS = (
    Path("core/runtime_manager/cli.py"),
    Path("core/runtime_manager/command_queue.py"),
    Path("core/runtime_manager/constants.py"),
    Path("core/runtime_manager/daemon.py"),
    Path("core/runtime_manager/evolution_store.py"),
    Path("core/runtime_manager/process_inventory.py"),
    Path("core/runtime_manager/restart_coordinator.py"),
    Path("core/runtime_manager/scene_logging.py"),
    Path("core/runtime_manager/state_store.py"),
    Path("core/runtime_manager/workbench_controller.py"),
    Path("core/web/services/self_evolution_control_service.py"),
    Path("core/web/services/supervised_control_service.py"),
)
_ACTIVE_COMMAND_RESTART_GRACE_SECONDS = 300.0
_OPEN_VERIFICATION_TIMEOUT_SECONDS = 60.0
_OPEN_VERIFICATION_POLL_INTERVAL_SECONDS = 0.4
_CLOSE_VERIFICATION_TIMEOUT_SECONDS = 8.0
_CLOSE_VERIFICATION_POLL_INTERVAL_SECONDS = 0.4


def _command_affects_workbench_lifecycle(command_type: str) -> bool:
    return str(command_type or "").strip() in _WORKBENCH_LIFECYCLE_COMMANDS


def _runtime_manager_source_signature() -> str:
    digest = hashlib.sha256()
    for relative_path in _SOURCE_SIGNATURE_PATHS:
        path = PROJECT_ROOT / relative_path
        digest.update(str(relative_path).replace("\\", "/").encode("utf-8"))
        try:
            digest.update(path.read_bytes())
        except OSError:
            digest.update(b"<missing>")
    return digest.hexdigest()


_PROCESS_SOURCE_SIGNATURE = _runtime_manager_source_signature()


def _process_source_signature() -> str:
    return _PROCESS_SOURCE_SIGNATURE


def _state_source_signature(state: dict[str, Any]) -> str:
    payload = state.get("runtimeManager") if isinstance(state.get("runtimeManager"), dict) else {}
    return str(payload.get("sourceSignature") or "").strip()


def _active_command_is_recent(state: dict[str, Any]) -> bool:
    command = state.get("command") if isinstance(state.get("command"), dict) else {}
    if not str(command.get("activeCommandId") or "").strip():
        return False
    started_at = str(command.get("startedAt") or "").strip()
    if not started_at:
        return False
    try:
        parsed = datetime.fromisoformat(started_at)
    except ValueError:
        return False
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    age_seconds = (datetime.now(UTC) - parsed.astimezone(UTC)).total_seconds()
    return age_seconds < _ACTIVE_COMMAND_RESTART_GRACE_SECONDS


def _command_result_is_completed(command_id: str) -> bool:
    normalized = str(command_id or "").strip()
    if not normalized:
        return False
    result_path = RESULTS_DIR / f"{normalized}.json"
    try:
        payload = json.loads(result_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return bool(isinstance(payload, dict) and payload.get("completed"))


def _terminate_daemon_process(pid: int) -> None:
    if pid <= 0 or pid == os.getpid():
        return
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        pass
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        if not _is_process_alive(pid):
            clear_pid(pid)
            return
        time.sleep(0.1)
    if hasattr(signal, "SIGKILL"):
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass
    clear_pid(pid)


def _exit_current_process(exit_code: int = 0) -> None:
    os._exit(int(exit_code))


def _workbench_failure_should_stick(state: dict[str, Any], *, desired_state: str, observed_state: str) -> bool:
    if observed_state == desired_state:
        return False
    last_error = state.get("lastError") if isinstance(state.get("lastError"), dict) else {}
    scope = str(last_error.get("scope") or "").strip()
    return not scope or _command_affects_workbench_lifecycle(scope)


def _workbench_has_orphaned_browser(observation: dict[str, Any]) -> bool:
    consistency = str(observation.get("lifecycleConsistency") or "").strip().lower()
    if consistency == "orphaned_browser" or bool(observation.get("frontendOrphaned")):
        return True
    return bool(
        observation.get("browserManaged", True)
        and observation.get("browserWindowAlive")
        and not observation.get("backendObserved")
        and not observation.get("backendPortListening")
        and int(observation.get("backendPortOwnerPid") or 0) <= 0
    )


def _workbench_consistency_fields(observation: dict[str, Any]) -> dict[str, Any]:
    consistency = str(observation.get("lifecycleConsistency") or "").strip() or "consistent"
    return {
        "backendMissing": bool(observation.get("backendMissing")) or (
            str(observation.get("observedState") or "closed") == "open"
            and not bool(observation.get("backendObserved"))
        ),
        "frontendOrphaned": _workbench_has_orphaned_browser(observation),
        "lifecycleConsistency": consistency,
    }


def _workbench_orphaned_browser_failure_message(observation: dict[str, Any]) -> str:
    return (
        "Workbench frontend window is still open, but no backend service is reachable. "
        f"browserWindowPid={int(observation.get('browserWindowPid') or 0)} "
        f"backendPid={int(observation.get('backendPid') or 0)} "
        f"backendPort={int(observation.get('backendPort') or 0)}"
    )


def _orphaned_browser_event_payload(observation: dict[str, Any]) -> dict[str, Any]:
    return {
        "observedState": str(observation.get("observedState") or "closed"),
        "browserWindowPid": int(observation.get("browserWindowPid") or 0),
        "backendPid": int(observation.get("backendPid") or 0),
        "backendPort": int(observation.get("backendPort") or 0),
        "backendPortListening": bool(observation.get("backendPortListening")),
        "backendPortOwnerPid": int(observation.get("backendPortOwnerPid") or 0),
        "sessionId": str(observation.get("sessionId") or "").strip(),
    }


def _snapshot_should_persist_reconciliation(original_state: dict[str, Any], snapshot: dict[str, Any]) -> bool:
    if not isinstance(original_state, dict):
        return True
    scalar_keys = ("runtimeState", "managerPid", "daemonRunning")
    if any(original_state.get(key) != snapshot.get(key) for key in scalar_keys):
        return True
    original_workbench = original_state.get("workbench") if isinstance(original_state.get("workbench"), dict) else {}
    snapshot_workbench = snapshot.get("workbench") if isinstance(snapshot.get("workbench"), dict) else {}
    workbench_keys = (
        "desiredState",
        "observedState",
        "phase",
        "backendPid",
        "browserLaunchPid",
        "browserWindowPid",
        "backendAlive",
        "backendHealthy",
        "backendObserved",
        "backendPortListening",
        "backendPortOwnerPid",
        "backendPortOwnerKind",
        "backendPortOwnerResidual",
        "backendPortOwnerTrusted",
        "backendPortConflict",
        "browserWindowAlive",
        "backendMissing",
        "frontendOrphaned",
        "lifecycleConsistency",
        "statusLine",
        "failureMessage",
    )
    return any(original_workbench.get(key) != snapshot_workbench.get(key) for key in workbench_keys)


def _open_request_already_satisfied(observation: dict[str, Any], *, no_browser: bool) -> bool:
    if not _open_request_ready(observation, no_browser=no_browser):
        return False
    return bool(observation.get("launcherStatePresent"))


def _open_request_ready(observation: dict[str, Any], *, no_browser: bool) -> bool:
    if str(observation.get("observedState") or "closed") != "open":
        return False
    backend_ready = (
        bool(observation.get("backendHealthy"))
        and bool(observation.get("backendObserved"))
        and not bool(observation.get("backendPortConflict"))
    )
    if not backend_ready:
        return False
    if no_browser:
        return True
    if not bool(observation.get("browserManaged")):
        return False
    return bool(observation.get("browserWindowAlive"))


def _restart_should_preserve_visible_browser(observation: dict[str, Any]) -> bool:
    if str(observation.get("observedState") or "closed") != "open":
        return False
    if not bool(observation.get("browserManaged")):
        return False
    if not bool(observation.get("browserWindowAlive")):
        return False
    return int(observation.get("browserWindowPid") or 0) > 0


def _open_verification_failure_message(observation: dict[str, Any], *, no_browser: bool) -> str:
    backend_ready = (
        bool(observation.get("backendHealthy"))
        and bool(observation.get("backendObserved"))
        and not bool(observation.get("backendPortConflict"))
    )
    browser_ready = bool(no_browser) or (
        bool(observation.get("browserManaged")) and bool(observation.get("browserWindowAlive"))
    )
    parts = [
        "Workbench launcher exited successfully, but the workbench is not ready.",
        f"observedState={str(observation.get('observedState') or 'closed')}",
        f"backendHealthy={bool(observation.get('backendHealthy'))}",
        f"backendObserved={bool(observation.get('backendObserved'))}",
        f"backendPortListening={bool(observation.get('backendPortListening'))}",
        f"backendPortOwnerPid={int(observation.get('backendPortOwnerPid') or 0)}",
        f"backendPortOwnerKind={str(observation.get('backendPortOwnerKind') or '')}",
        f"backendPortOwnerResidual={bool(observation.get('backendPortOwnerResidual'))}",
        f"backendPortConflict={bool(observation.get('backendPortConflict'))}",
        f"browserManaged={bool(observation.get('browserManaged', True))}",
        f"browserWindowAlive={bool(observation.get('browserWindowAlive'))}",
        f"noBrowser={bool(no_browser)}",
        f"backendReady={backend_ready}",
        f"browserReady={browser_ready}",
    ]
    return " ".join(parts)


def _open_verification_event_payload(
    observation: dict[str, Any],
    *,
    no_browser: bool,
    message: str = "",
    command_id: str = "",
    launcher_result: Any = None,
) -> dict[str, Any]:
    payload = {
        "message": message,
        "commandId": str(command_id or ""),
        "noBrowser": bool(no_browser),
        "observedState": str(observation.get("observedState") or "closed"),
        "launcherStatePresent": bool(observation.get("launcherStatePresent")),
        "backendPid": int(observation.get("backendPid") or 0),
        "backendHealthy": bool(observation.get("backendHealthy")),
        "backendObserved": bool(observation.get("backendObserved")),
        "backendPort": int(observation.get("backendPort") or 0),
        "backendPortListening": bool(observation.get("backendPortListening")),
        "backendPortOwnerPid": int(observation.get("backendPortOwnerPid") or 0),
        "backendPortOwnerTrusted": bool(observation.get("backendPortOwnerTrusted")),
        "backendPortConflict": bool(observation.get("backendPortConflict")),
        "browserManaged": bool(observation.get("browserManaged", True)),
        "browserWindowPid": int(observation.get("browserWindowPid") or 0),
        "browserWindowAlive": bool(observation.get("browserWindowAlive")),
        "url": str(observation.get("url") or ""),
        "healthUrl": str(observation.get("healthUrl") or ""),
    }
    port_owner_kind = str(observation.get("backendPortOwnerKind") or "")
    lifecycle_consistency = str(observation.get("lifecycleConsistency") or "consistent")
    if port_owner_kind:
        payload["backendPortOwnerKind"] = port_owner_kind
    if bool(observation.get("backendPortOwnerResidual")):
        payload["backendPortOwnerResidual"] = True
    if lifecycle_consistency != "consistent":
        payload["lifecycleConsistency"] = lifecycle_consistency
    if not message:
        payload.pop("message", None)
    if not command_id:
        payload.pop("commandId", None)
    if launcher_result is not None:
        payload["launcher"] = {
            "returnCode": int(getattr(launcher_result, "returncode", 0) or 0),
            "stdout": str(getattr(launcher_result, "stdout", "") or "").strip()[-1200:],
            "stderr": str(getattr(launcher_result, "stderr", "") or "").strip()[-1200:],
        }
    return payload


def _open_verification_should_retry_stale_session(observation: dict[str, Any], *, no_browser: bool) -> bool:
    if _open_request_ready(observation, no_browser=no_browser):
        return False
    if not bool(observation.get("launcherStatePresent")):
        return False
    if str(observation.get("observedState") or "closed") != "open":
        return False
    if bool(observation.get("backendPortConflict")):
        return False

    backend_ready = (
        bool(observation.get("backendHealthy"))
        and bool(observation.get("backendObserved"))
        and not bool(observation.get("backendPortConflict"))
    )
    browser_ready = bool(no_browser) or (
        bool(observation.get("browserManaged")) and bool(observation.get("browserWindowAlive"))
    )
    return not backend_ready or not browser_ready


def _wait_for_open_verification(*, no_browser: bool) -> tuple[bool, dict[str, Any], int]:
    deadline = time.monotonic() + _OPEN_VERIFICATION_TIMEOUT_SECONDS
    attempts = 0
    latest: dict[str, Any] = {}
    while True:
        attempts += 1
        latest = observe_workbench()
        if _open_request_ready(latest, no_browser=no_browser):
            return True, latest, attempts
        if time.monotonic() >= deadline:
            return False, latest, attempts
        time.sleep(_OPEN_VERIFICATION_POLL_INTERVAL_SECONDS)


def _open_already_satisfied_event_payload(
    observation: dict[str, Any], *, command_id: str, no_browser: bool
) -> dict[str, Any]:
    return {
        "commandId": str(command_id or ""),
        "noBrowser": bool(no_browser),
        "focusRequested": not bool(no_browser),
        "observedState": str(observation.get("observedState") or "closed"),
        "backendPid": int(observation.get("backendPid") or 0),
        "backendHealthy": bool(observation.get("backendHealthy")),
        "backendObserved": bool(observation.get("backendObserved")),
        "browserManaged": bool(observation.get("browserManaged", True)),
        "browserWindowPid": int(observation.get("browserWindowPid") or 0),
        "browserWindowAlive": bool(observation.get("browserWindowAlive")),
        "sessionId": str(observation.get("sessionId") or ""),
        "url": str(observation.get("url") or ""),
    }


def _close_request_already_satisfied(observation: dict[str, Any]) -> bool:
    if str(observation.get("observedState") or "closed") != "closed":
        return False
    live_backend_evidence = (
        bool(observation.get("backendAlive"))
        or bool(observation.get("backendHealthy"))
        or bool(observation.get("backendObserved"))
        or bool(observation.get("backendPortListening"))
        or int(observation.get("backendPortOwnerPid") or 0) > 0
    )
    live_browser_evidence = bool(observation.get("browserWindowAlive"))
    return not live_backend_evidence and not live_browser_evidence


def _close_verification_failure_message(observation: dict[str, Any]) -> str:
    parts = [
        "Workbench launcher exited successfully, but the workbench is not fully stopped.",
        f"observedState={str(observation.get('observedState') or 'closed')}",
        f"backendAlive={bool(observation.get('backendAlive'))}",
        f"backendHealthy={bool(observation.get('backendHealthy'))}",
        f"backendObserved={bool(observation.get('backendObserved'))}",
        f"backendPortListening={bool(observation.get('backendPortListening'))}",
        f"backendPortOwnerPid={int(observation.get('backendPortOwnerPid') or 0)}",
        f"backendPortOwnerKind={str(observation.get('backendPortOwnerKind') or '')}",
        f"backendPortOwnerResidual={bool(observation.get('backendPortOwnerResidual'))}",
        f"backendPortConflict={bool(observation.get('backendPortConflict'))}",
        f"browserWindowAlive={bool(observation.get('browserWindowAlive'))}",
        f"browserWindowPid={int(observation.get('browserWindowPid') or 0)}",
    ]
    return " ".join(parts)


def _close_verification_event_payload(
    observation: dict[str, Any],
    *,
    command_id: str = "",
    message: str = "",
    cleanup_result: dict[str, Any] | None = None,
    launcher_result: Any = None,
) -> dict[str, Any]:
    payload = {
        "message": message,
        "commandId": str(command_id or ""),
        "observedState": str(observation.get("observedState") or "closed"),
        "launcherStatePresent": bool(observation.get("launcherStatePresent")),
        "backendPid": int(observation.get("backendPid") or 0),
        "backendLaunchPid": int(observation.get("backendLaunchPid") or 0),
        "backendAlive": bool(observation.get("backendAlive")),
        "backendHealthy": bool(observation.get("backendHealthy")),
        "backendObserved": bool(observation.get("backendObserved")),
        "backendPort": int(observation.get("backendPort") or 0),
        "backendPortListening": bool(observation.get("backendPortListening")),
        "backendPortOwnerPid": int(observation.get("backendPortOwnerPid") or 0),
        "backendPortOwnerTrusted": bool(observation.get("backendPortOwnerTrusted")),
        "backendPortConflict": bool(observation.get("backendPortConflict")),
        "browserManaged": bool(observation.get("browserManaged", True)),
        "browserLaunchPid": int(observation.get("browserLaunchPid") or 0),
        "browserWindowPid": int(observation.get("browserWindowPid") or 0),
        "browserWindowAlive": bool(observation.get("browserWindowAlive")),
        "url": str(observation.get("url") or ""),
        "healthUrl": str(observation.get("healthUrl") or ""),
        "residualCleanup": cleanup_result if isinstance(cleanup_result, dict) else {},
    }
    port_owner_kind = str(observation.get("backendPortOwnerKind") or "")
    lifecycle_consistency = str(observation.get("lifecycleConsistency") or "consistent")
    if port_owner_kind:
        payload["backendPortOwnerKind"] = port_owner_kind
    if bool(observation.get("backendPortOwnerResidual")):
        payload["backendPortOwnerResidual"] = True
    if lifecycle_consistency != "consistent":
        payload["lifecycleConsistency"] = lifecycle_consistency
    if launcher_result is not None:
        payload["launcher"] = {
            "returnCode": int(getattr(launcher_result, "returncode", 0) or 0),
            "stdout": str(getattr(launcher_result, "stdout", "") or "").strip()[-800:],
            "stderr": str(getattr(launcher_result, "stderr", "") or "").strip()[-800:],
        }
    if not message:
        payload.pop("message", None)
    if not command_id:
        payload.pop("commandId", None)
    return payload


def _wait_for_close_verification() -> tuple[bool, dict[str, Any], int]:
    deadline = time.monotonic() + _CLOSE_VERIFICATION_TIMEOUT_SECONDS
    attempts = 0
    latest: dict[str, Any] = {}
    while True:
        attempts += 1
        latest = observe_workbench()
        if _close_request_already_satisfied(latest):
            return True, latest, attempts
        if time.monotonic() >= deadline:
            return False, latest, attempts
        time.sleep(_CLOSE_VERIFICATION_POLL_INTERVAL_SECONDS)


def _is_process_alive_windows(pid: int) -> bool:
    import ctypes
    from ctypes import wintypes

    PROCESS_QUERY_INFORMATION = 0x0400
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    STILL_ACTIVE = 259

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = None
    for access in (PROCESS_QUERY_LIMITED_INFORMATION, PROCESS_QUERY_INFORMATION):
        handle = kernel32.OpenProcess(access, False, int(pid))
        if handle:
            break
    if not handle:
        return False

    try:
        exit_code = wintypes.DWORD()
        if kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)) == 0:
            return False
        return int(exit_code.value) == STILL_ACTIVE
    finally:
        kernel32.CloseHandle(handle)


def _is_process_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        try:
            return _is_process_alive_windows(int(pid))
        except OSError:
            return False
    try:
        os.kill(int(pid), 0)
    except OSError:
        return False
    return True


def is_daemon_running() -> bool:
    return _is_process_alive(load_pid())


def _append_event(event_type: str, payload: dict[str, Any]) -> None:
    event_at = append_runtime_manager_file_event(
        event_type,
        payload,
        events_path=EVENTS_PATH,
        ensure_dirs=ensure_runtime_manager_dirs,
    )
    record_runtime_manager_scene_event(
        event_type,
        payload,
        phase=runtime_manager_event_phase(event_type),
        occurred_at=event_at,
    )


def _claim_workbench_reopen_intent() -> dict[str, Any] | None:
    intent = claim_next_restart_intent(target="workbench")
    if not intent:
        return None
    payload = intent.get("payload") if isinstance(intent.get("payload"), dict) else {}
    if str(payload.get("action") or "") != "reopen_after_close":
        complete_restart_intent(str(intent.get("intentId") or ""), status="failed", message="Unsupported workbench restart intent action.")
        return None
    return intent


def _workbench_reopen_intent_event_payload(intent: dict[str, Any], *, command_id: str) -> dict[str, Any]:
    payload = intent.get("payload") if isinstance(intent.get("payload"), dict) else {}
    return {
        "commandId": command_id,
        "intentId": str(intent.get("intentId") or ""),
        "target": str(intent.get("target") or ""),
        "reason": str(intent.get("reason") or ""),
        "requestedBy": str(intent.get("requestedBy") or ""),
        "sourceCommandId": str(intent.get("sourceCommandId") or ""),
        "noBrowser": bool(payload.get("noBrowser")),
    }


def _creation_flags() -> int:
    flags = 0
    for name in ("DETACHED_PROCESS", "CREATE_NEW_PROCESS_GROUP", "CREATE_NO_WINDOW"):
        flags |= int(getattr(subprocess, name, 0))
    return flags


def _select_daemon_python_runtime(python_executable: str) -> dict[str, Any]:
    """Select the Python runtime used for the long-lived daemon process."""

    raw = str(python_executable or "").strip()
    result = {
        "pythonExecutable": raw,
        "sourcePythonExecutable": raw,
        "consoleWindowSuppressed": False,
        "consoleFallbackReason": "empty_python_executable",
    }
    if not raw:
        return result
    candidate = Path(raw)
    if os.name != "nt":
        result["consoleFallbackReason"] = "non_windows"
        return result
    if candidate.name.lower() == "pythonw.exe":
        result["pythonExecutable"] = str(candidate.resolve()) if candidate.exists() else raw
        result["consoleWindowSuppressed"] = True
        result["consoleFallbackReason"] = ""
        return result
    sibling = candidate.with_name("pythonw.exe")
    if sibling.exists():
        result["pythonExecutable"] = str(sibling.resolve())
        result["consoleWindowSuppressed"] = True
        result["consoleFallbackReason"] = ""
        return result
    if candidate.name.lower() == "python.exe":
        result["pythonExecutable"] = str(candidate.resolve()) if candidate.exists() else raw
        result["consoleFallbackReason"] = "pythonw_sibling_missing"
        return result
    sibling = candidate.with_name("python.exe")
    if sibling.exists():
        result["pythonExecutable"] = str(sibling.resolve())
        result["consoleFallbackReason"] = "pythonw_sibling_missing"
        return result
    if candidate.exists():
        result["pythonExecutable"] = str(candidate.resolve())
        result["consoleFallbackReason"] = "pythonw_sibling_missing"
        return result
    result["consoleFallbackReason"] = "python_executable_missing"
    return result


def ensure_daemon_running(*, python_executable: str | None = None) -> bool:
    current_pid = load_pid()
    if _is_process_alive(current_pid):
        state = load_state()
        current_signature = _process_source_signature()
        if _state_source_signature(state) == current_signature or _active_command_is_recent(state):
            return False
        _append_event(
            "daemon.restart_requested",
            {"pid": current_pid, "reason": "runtime_manager_source_changed"},
        )
        _terminate_daemon_process(current_pid)

    ensure_runtime_manager_dirs()
    python_runtime = _select_daemon_python_runtime(python_executable or sys.executable)
    python_cmd = str(python_runtime["pythonExecutable"])
    with DAEMON_STDOUT_PATH.open("a", encoding="utf-8") as stdout_handle, DAEMON_STDERR_PATH.open(
        "a", encoding="utf-8"
    ) as stderr_handle:
        process = subprocess.Popen(
            [python_cmd, "-m", "core.runtime_manager.cli", "daemon"],
            cwd=str(PROJECT_ROOT),
            stdin=subprocess.DEVNULL,
            stdout=stdout_handle,
            stderr=stderr_handle,
            creationflags=_creation_flags(),
            close_fds=True,
        )
    _append_event(
        "daemon.start_requested",
        {
            "launchPid": int(getattr(process, "pid", 0) or 0),
            "pythonExecutable": python_cmd,
            "sourcePythonExecutable": str(python_runtime["sourcePythonExecutable"]),
            "consoleWindowSuppressed": bool(python_runtime["consoleWindowSuppressed"]),
            "consoleFallbackReason": str(python_runtime["consoleFallbackReason"]),
        },
    )

    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        if is_daemon_running():
            return True
        time.sleep(0.2)
    raise RuntimeError("Runtime manager daemon failed to start.")


def load_runtime_snapshot() -> dict[str, Any]:
    loaded_state = load_state()
    state = json.loads(json.dumps(loaded_state)) if isinstance(loaded_state, dict) else loaded_state
    observation = observe_workbench()
    manager_running = is_daemon_running()
    manager_pid = load_pid() if manager_running else 0
    residual_processes = residual_process_payload(
        project_root=PROJECT_ROOT,
        exclude_pids=_snapshot_residual_excluded_pids(observation, manager_pid),
    )

    if not state:
        state = default_state()

    workbench = state.setdefault("workbench", {})
    active_command = str((state.get("command") or {}).get("activeCommandId") or "").strip()
    desired_state = str(workbench.get("desiredState") or "closed").strip() or "closed"
    observed_state = str(observation.get("observedState") or "closed").strip() or "closed"
    phase = str(workbench.get("phase") or "steady").strip() or "steady"
    consistency_fields = _workbench_consistency_fields(observation)
    orphaned_browser = bool(consistency_fields["frontendOrphaned"])

    if phase == "failed" and not _workbench_failure_should_stick(state, desired_state=desired_state, observed_state=observed_state):
        phase = "steady"
        workbench["failureMessage"] = ""
    if orphaned_browser and phase not in {"opening", "closing", "failed"}:
        desired_state = "closed"
        phase = "closing"
        workbench["failureMessage"] = _workbench_orphaned_browser_failure_message(observation)

    if (not manager_running or not active_command) and phase != "failed":
        if observed_state == "open" and desired_state != "open":
            desired_state = "open"
            phase = "steady"
        elif observed_state == "closed" and desired_state != "closed":
            desired_state = "closed"
            phase = "steady"
    if observed_state == "closed" and not manager_running and not active_command:
        phase = "steady"
        workbench["failureMessage"] = ""
        state["lastError"] = {"scope": "", "message": "", "at": ""}

    if observed_state == desired_state and phase != "failed":
        phase = "steady"
        workbench["failureMessage"] = ""
    elif desired_state == "closed" and observed_state != "closed" and phase != "failed":
        phase = "closing"
    elif desired_state == "open" and observed_state != "open" and phase != "failed":
        phase = "opening"

    workbench.update(
        {
            "desiredState": desired_state,
            "observedState": observed_state,
            "backendPid": int(observation.get("backendPid") or 0),
            "browserLaunchPid": int(observation.get("browserLaunchPid") or 0)
            if bool(observation.get("browserWindowAlive"))
            else 0,
            "browserWindowPid": int(observation.get("browserWindowPid") or 0)
            if bool(observation.get("browserWindowAlive"))
            else 0,
            "backendAlive": bool(observation.get("backendAlive")),
            "backendHealthy": bool(observation.get("backendHealthy")),
            "backendObserved": bool(observation.get("backendObserved")),
            "backendPort": int(observation.get("backendPort") or 0),
            "backendPortListening": bool(observation.get("backendPortListening")),
            "backendPortOwnerPid": int(observation.get("backendPortOwnerPid") or 0),
            "backendPortOwnerKind": str(observation.get("backendPortOwnerKind") or ""),
            "backendPortOwnerTrusted": bool(observation.get("backendPortOwnerTrusted")),
            "backendPortOwnerResidual": bool(observation.get("backendPortOwnerResidual")),
            "backendPortConflict": bool(observation.get("backendPortConflict")),
            "browserWindowAlive": bool(observation.get("browserWindowAlive")),
            "browserManaged": bool(observation.get("browserManaged", True)),
            "backendMissing": bool(consistency_fields["backendMissing"]),
            "frontendOrphaned": bool(consistency_fields["frontendOrphaned"]),
            "lifecycleConsistency": str(consistency_fields["lifecycleConsistency"]),
            "sessionId": str(observation.get("sessionId") or "").strip(),
            "url": str(observation.get("url") or workbench.get("url") or "").strip(),
            "phase": phase,
            "statusLine": _build_workbench_status_line(
                desired_state=desired_state,
                observed_state=observed_state,
                phase=phase,
                backend_pid=int(observation.get("backendPid") or 0),
                browser_pid=int(observation.get("browserWindowPid") or 0),
                lifecycle_consistency=str(consistency_fields["lifecycleConsistency"]),
            ),
        }
    )
    previous_runtime_state = str(state.get("runtimeState") or "").strip().lower()
    state["runtimeState"] = "stopping" if manager_running and previous_runtime_state == "stopping" else "running" if manager_running else "idle"
    state["managerPid"] = manager_pid
    state["daemonRunning"] = manager_running
    state["projectRoot"] = str(PROJECT_ROOT)
    state["statePath"] = str(STATE_PATH)
    state["evolution"] = build_evolution_summary()
    state["residualProcesses"] = residual_processes
    runtime_manager = state.get("runtimeManager") if isinstance(state.get("runtimeManager"), dict) else {}
    state["runtimeManager"] = {
        "sourceSignature": str(runtime_manager.get("sourceSignature") or "").strip(),
        "currentSourceSignature": _process_source_signature(),
        "sourceMatches": _state_source_signature(state) == _process_source_signature(),
    }
    if _snapshot_should_persist_reconciliation(loaded_state, state):
        state = save_state(state)
        _append_event(
            "runtime.snapshot.reconciled",
            {
                "managerRunning": bool(manager_running),
                "managerPid": int(manager_pid or 0),
                "desiredState": str(workbench.get("desiredState") or "closed"),
                "observedState": str(workbench.get("observedState") or "closed"),
                "backendPid": int(workbench.get("backendPid") or 0),
                "browserWindowPid": int(workbench.get("browserWindowPid") or 0),
                "lifecycleConsistency": str(workbench.get("lifecycleConsistency") or "consistent"),
            },
        )
    return state


def _snapshot_residual_excluded_pids(
    observation: dict[str, Any],
    manager_pid: int = 0,
    *,
    include_workbench: bool = True,
) -> set[int]:
    excluded = {os.getpid(), int(manager_pid or 0)}
    if not include_workbench:
        return {pid for pid in excluded if pid > 0}
    for key in ("backendPid", "backendLaunchPid", "browserLaunchPid", "browserWindowPid"):
        try:
            value = int(observation.get(key) or 0)
        except (TypeError, ValueError):
            value = 0
        if value > 0:
            excluded.add(value)
    try:
        port_owner_pid = int(observation.get("backendPortOwnerPid") or 0)
    except (TypeError, ValueError):
        port_owner_pid = 0
    if port_owner_pid > 0 and bool(observation.get("backendPortOwnerTrusted")):
        excluded.add(port_owner_pid)
    return _expand_excluded_workbench_ancestors(excluded)


def _expand_excluded_workbench_ancestors(excluded: set[int]) -> set[int]:
    try:
        processes = list_repo_runtime_processes(project_root=PROJECT_ROOT)
    except Exception:
        return excluded

    by_pid = {int(item.pid): item for item in processes}
    expanded = set(excluded)
    changed = True
    while changed:
        changed = False
        for pid in list(expanded):
            item = by_pid.get(int(pid))
            if item is None:
                continue
            parent_pid = int(getattr(item, "parent_pid", 0) or 0)
            parent = by_pid.get(parent_pid)
            if parent is None or str(getattr(parent, "kind", "") or "") != "unmanaged_workbench":
                continue
            if parent_pid not in expanded:
                expanded.add(parent_pid)
                changed = True
    return expanded


def _build_workbench_status_line(
    *,
    desired_state: str,
    observed_state: str,
    phase: str,
    backend_pid: int,
    browser_pid: int,
    lifecycle_consistency: str = "consistent",
) -> str:
    if phase == "failed":
        if lifecycle_consistency == "orphaned_browser":
            return "Workbench frontend is orphaned: browser window is open but backend is stopped."
        return "Workbench hit a lifecycle error."
    if desired_state == "closed" and observed_state != "closed":
        return "Runtime manager is closing the workbench."
    if desired_state == "open" and observed_state != "open":
        return "Runtime manager is opening the workbench."
    if observed_state == "open":
        return f"Workbench is open (backend PID={backend_pid or '-'}, window PID={browser_pid or '-'})"
    return "Workbench is closed."


def _launcher_error_detail(result: Any, fallback: str) -> str:
    if not result:
        return fallback
    stderr = str(getattr(result, "stderr", "") or "").strip()
    stdout = str(getattr(result, "stdout", "") or "").strip()
    return_code = int(getattr(result, "returncode", 0) or 0)
    parts: list[str] = []
    if stderr:
        parts.append(stderr)
    if stdout:
        stdout_lines = [line.strip() for line in stdout.splitlines() if line.strip()]
        progress_lines = [line for line in stdout_lines if line.startswith("[Vibelution]")]
        diagnostic_lines = [line for line in stdout_lines if not line.startswith("[Vibelution]")]
        if diagnostic_lines:
            parts.append("\n".join(diagnostic_lines))
        elif progress_lines:
            parts.append(f"Launcher progress before exit: {progress_lines[-1]}")
    if return_code:
        parts.append(f"Launcher exit code: {return_code}")
    detail = "\n".join(part for part in parts if part)
    return detail or fallback


def _close_active_evolution_runs_for_shutdown() -> list[dict[str, Any]]:
    reason = "Runtime manager is closing the workbench."
    closed: list[dict[str, Any]] = []
    for kind, closer in (
        ("self_evolution_run", self_evolution_control_service.force_cancel_active_self_evolution_runs_for_shutdown),
        ("supervised_evolution_run", supervised_control_service.force_cancel_active_supervised_runs_for_shutdown),
    ):
        try:
            snapshots = closer(reason)
        except Exception as exc:
            closed.append(
                {
                    "kind": kind,
                    "runId": "",
                    "status": "failed",
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
            continue
        for snapshot in list(snapshots or []):
            if not isinstance(snapshot, dict):
                continue
            closed.append(
                {
                    "kind": kind,
                    "runId": str(snapshot.get("runId") or ""),
                    "status": str(snapshot.get("status") or ""),
                }
            )
    return closed


def _prepare_daemon_shutdown() -> dict[str, Any]:
    closed_runs = _close_active_evolution_runs_for_shutdown()
    descendants = terminate_process_descendants(os.getpid(), exclude_pids={os.getpid()}, timeout_seconds=5.0)
    rejected_commands = reject_pending_commands_for_shutdown(shutdown_state=load_state())
    if int(rejected_commands.get("count") or 0) > 0:
        _append_event(
            "daemon.shutdown.rejected_pending_commands",
            {
                "count": int(rejected_commands.get("count") or 0),
                "commands": [
                    {
                        "commandId": str(item.get("commandId") or ""),
                        "type": str(item.get("type") or ""),
                        "status": str(item.get("status") or ""),
                    }
                    for item in list(rejected_commands.get("items") or [])
                    if isinstance(item, dict)
                ],
            },
        )
    return {
        "closedEvolutionRuns": closed_runs,
        "descendantCleanup": descendants,
        "rejectedPendingCommands": rejected_commands,
    }


def _finalize_daemon_stopped_state(*, manager_pid: int) -> None:
    state = load_state()
    if not isinstance(state, dict):
        state = default_state()
    workbench = state.setdefault("workbench", {})
    workbench.update(
        {
            "desiredState": "closed",
            "observedState": "closed",
            "phase": "steady",
            "backendPid": 0,
            "browserLaunchPid": 0,
            "browserWindowPid": 0,
            "backendAlive": False,
            "backendHealthy": False,
            "backendObserved": False,
            "backendPortListening": False,
            "backendPortOwnerPid": 0,
            "backendPortOwnerKind": "",
            "backendPortOwnerTrusted": False,
            "backendPortOwnerResidual": False,
            "backendPortConflict": False,
            "browserWindowAlive": False,
            "backendMissing": False,
            "frontendOrphaned": False,
            "lifecycleConsistency": "consistent",
            "failureMessage": "",
            "statusLine": "Workbench is closed.",
        }
    )
    state.setdefault("command", {}).update(
        {
            "activeCommandId": "",
            "activeType": "",
            "requestedBy": "",
            "startedAt": "",
            "stopManager": False,
        }
    )
    state["runtimeState"] = "idle"
    state["managerPid"] = 0
    state["daemonRunning"] = False
    state["lastStoppedAt"] = now_iso()
    state["lastStoppedManagerPid"] = int(manager_pid)
    save_state(state)


def _mark_daemon_not_running_after_exit(*, manager_pid: int) -> None:
    state = load_state()
    if not isinstance(state, dict):
        state = default_state()
    if int(state.get("managerPid") or 0) not in {0, int(manager_pid)}:
        return
    state["runtimeState"] = "idle"
    state["managerPid"] = 0
    state["daemonRunning"] = False
    state["lastStoppedAt"] = now_iso()
    state["lastStoppedManagerPid"] = int(manager_pid)
    save_state(state)


class RuntimeManagerDaemon:
    def __init__(self) -> None:
        self._pid = os.getpid()

    def run_forever(self) -> None:
        ensure_runtime_manager_dirs()
        recover_processing_queue()
        save_pid(self._pid)

        state = load_state()
        if not isinstance(state, dict):
            state = default_state()
        state["runtimeState"] = "running"
        state["managerPid"] = self._pid
        state["daemonRunning"] = True
        state["runtimeManager"] = {"sourceSignature": _process_source_signature()}
        state["startedAt"] = now_iso()
        state = self._reconcile_observation(state)
        save_state(state)

        try:
            while True:
                command = claim_next_command()
                if command is not None:
                    path, payload = command
                    result = self._handle_command(payload)
                    if bool(result.get("stopDaemon")):
                        shutdown_cleanup = _prepare_daemon_shutdown()
                        if shutdown_cleanup.get("closedEvolutionRuns"):
                            result["closedEvolutionRuns"] = shutdown_cleanup["closedEvolutionRuns"]
                        result["descendantCleanup"] = shutdown_cleanup.get("descendantCleanup")
                        result["rejectedPendingCommands"] = shutdown_cleanup.get("rejectedPendingCommands")
                        state = load_state()
                        if isinstance(state, dict):
                            state["runtimeState"] = "stopping"
                            state["managerPid"] = self._pid
                            state["daemonRunning"] = True
                            save_state(state)
                        _append_event("daemon.stopped", {"commandId": str(result.get("commandId") or "")})
                    complete_command(path, result)
                    if bool(result.get("runDeferredWorkbenchOpen")):
                        self._run_deferred_workbench_open(result)
                    if bool(result.get("stopDaemon")):
                        _finalize_daemon_stopped_state(manager_pid=self._pid)
                        clear_pid(self._pid)
                        _exit_current_process(0)
                        return
                    continue

                self._process_self_evolution_restart_intent()
                state = self._reconcile_observation(load_state())
                save_state(state)
                time.sleep(DAEMON_LOOP_INTERVAL_SECONDS)
        finally:
            clear_pid(self._pid)
            _mark_daemon_not_running_after_exit(manager_pid=self._pid)

    def _handle_command(self, payload: dict[str, Any]) -> dict[str, Any]:
        command_id = str(payload.get("commandId") or "").strip()
        command_type = str(payload.get("type") or "").strip()
        requested_by = str(payload.get("requestedBy") or "unknown").strip() or "unknown"
        args = payload.get("args") if isinstance(payload.get("args"), dict) else {}

        state = load_state()
        command_state = state.setdefault("command", {})
        command_state.update(
            {
                "activeCommandId": command_id,
                "activeType": command_type,
                "requestedBy": requested_by,
                "startedAt": now_iso(),
                "stopManager": command_type == "close_workbench" and bool(args.get("stopManager")),
                "noBrowser": command_type in {"open_workbench", "restart_workbench"} and bool(args.get("noBrowser")),
            }
        )
        state = self._reconcile_observation(state)
        state = save_state(state)

        handler = getattr(self, f"_handle_{command_type}", None)
        if handler is None:
            result = self._finish_command(
                command_id,
                ok=False,
                message=f"Unsupported runtime-manager command: {command_type}",
                error_scope="command",
                failure_message=f"Unsupported command: {command_type}",
            )
            _append_event("command.failed", {"commandId": command_id, "type": command_type, "message": result["message"]})
            return result

        try:
            result = handler(command_id=command_id, args=args)
            _append_event("command.completed", {"commandId": command_id, "type": command_type, "ok": result["ok"]})
            return result
        except Exception as exc:
            result = self._finish_command(
                command_id,
                ok=False,
                message=str(exc),
                error_scope=command_type or "command",
                failure_message=str(exc),
                error_type=type(exc).__name__,
            )
            _append_event("command.failed", {"commandId": command_id, "type": command_type, "message": str(exc)})
            return result

    def _finish_command(
        self,
        command_id: str,
        *,
        ok: bool,
        message: str,
        error_scope: str = "",
        failure_message: str = "",
        error_type: str = "",
        result_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        state = load_state()
        state.setdefault("command", {}).update(
            {
                "activeCommandId": "",
                "activeType": "",
                "requestedBy": "",
                "startedAt": "",
                "stopManager": False,
                "noBrowser": False,
            }
        )
        if ok and isinstance(result_data, dict) and bool(result_data.get("stopDaemon")):
            state["runtimeState"] = "stopping"
            state["managerPid"] = self._pid
            state["daemonRunning"] = True
        if ok:
            state["lastError"] = {"scope": "", "message": "", "at": ""}
        else:
            state["lastError"] = {"scope": error_scope, "message": message, "at": now_iso()}
            if _command_affects_workbench_lifecycle(error_scope):
                state.setdefault("workbench", {})["phase"] = "failed"
                state["workbench"]["failureMessage"] = failure_message or message
        state = self._reconcile_observation(state)
        state = save_state(state)
        result = {
            "commandId": command_id,
            "accepted": True,
            "completed": True,
            "ok": ok,
            "message": message,
            "stateVersion": int(state.get("stateVersion") or 0),
        }
        if error_type:
            result["errorType"] = error_type
        if isinstance(result_data, dict):
            result.update(result_data)
        return result

    def _reconcile_observation(self, state: dict[str, Any]) -> dict[str, Any]:
        observation = observe_workbench()
        residual_processes = residual_process_payload(
            project_root=PROJECT_ROOT,
            exclude_pids=_snapshot_residual_excluded_pids(observation, self._pid),
        )
        workbench = state.setdefault("workbench", {})
        desired_state = str(workbench.get("desiredState") or "closed").strip() or "closed"
        observed_state = str(observation.get("observedState") or "closed").strip() or "closed"
        session_role = str(observation.get("sessionRole") or "workbench").strip() or "workbench"
        phase = str(workbench.get("phase") or "steady").strip() or "steady"
        command_state = state.setdefault("command", {})
        active_command = str(command_state.get("activeCommandId") or "").strip()
        if active_command and _command_result_is_completed(active_command):
            _append_event(
                "command.active_completed_cleared",
                {
                    "commandId": active_command,
                    "activeType": str(command_state.get("activeType") or ""),
                    "requestedBy": str(command_state.get("requestedBy") or ""),
                },
            )
            command_state.update(
                {
                    "activeCommandId": "",
                    "activeType": "",
                    "requestedBy": "",
                    "startedAt": "",
                    "stopManager": False,
                    "noBrowser": False,
                }
            )
            active_command = ""
        previous_frontend_orphaned = bool(workbench.get("frontendOrphaned"))
        consistency_fields = _workbench_consistency_fields(observation)
        orphaned_browser = bool(consistency_fields["frontendOrphaned"])

        if phase == "failed" and not _workbench_failure_should_stick(
            state,
            desired_state=desired_state,
            observed_state=observed_state,
        ):
            phase = "steady"
            workbench["failureMessage"] = ""
        if orphaned_browser and phase not in {"opening", "closing", "failed"}:
            desired_state = "closed"
            phase = "closing"
            workbench["failureMessage"] = _workbench_orphaned_browser_failure_message(observation)
            payload = _orphaned_browser_event_payload(observation)
            if not previous_frontend_orphaned:
                _append_event(
                    "workbench.consistency.orphaned_browser_detected",
                    payload,
                )
            _append_event("workbench.consistency.orphaned_browser_cleanup_requested", payload)
            result = close_workbench()
            cleanup_payload = payload | {
                "returnCode": int(result.returncode),
                "stdout": str(getattr(result, "stdout", "") or "").strip()[-400:],
                "stderr": str(getattr(result, "stderr", "") or "").strip()[-400:],
            }
            if result.returncode == 0:
                _append_event("workbench.consistency.orphaned_browser_cleanup_succeeded", cleanup_payload)
                observation = observe_workbench()
                observed_state = str(observation.get("observedState") or "closed").strip() or "closed"
                consistency_fields = _workbench_consistency_fields(observation)
                orphaned_browser = bool(consistency_fields["frontendOrphaned"])
                if not orphaned_browser and observed_state == "closed":
                    phase = "steady"
                    workbench["failureMessage"] = ""
            else:
                phase = "failed"
                _append_event("workbench.consistency.orphaned_browser_cleanup_failed", cleanup_payload)

        if (
            not active_command
            and desired_state == "closed"
            and phase not in {"opening", "closing", "failed"}
            and int(residual_processes.get("count") or 0) > 0
        ):
            cleanup_payload = {
                "desiredState": desired_state,
                "observedState": observed_state,
                "lifecycleConsistency": str(consistency_fields["lifecycleConsistency"]),
                "residualProcesses": residual_processes,
            }
            _append_event("workbench.consistency.closed_residual_cleanup_requested", cleanup_payload)
            cleanup_result = self._cleanup_residual_workbench_processes()
            cleanup_payload = cleanup_payload | {"cleanup": cleanup_result}
            if isinstance(cleanup_result, dict) and not cleanup_result.get("remaining"):
                _append_event("workbench.consistency.closed_residual_cleanup_succeeded", cleanup_payload)
            else:
                _append_event("workbench.consistency.closed_residual_cleanup_incomplete", cleanup_payload)
            observation = observe_workbench()
            observed_state = str(observation.get("observedState") or "closed").strip() or "closed"
            consistency_fields = _workbench_consistency_fields(observation)
            residual_processes = residual_process_payload(
                project_root=PROJECT_ROOT,
                exclude_pids=_snapshot_residual_excluded_pids(observation, self._pid),
            )

        if not active_command and phase != "failed":
            if observed_state == "open" and desired_state != "open":
                desired_state = "open"
                phase = "steady"
                workbench["lastReason"] = "external_open"
            elif observed_state == "closed" and desired_state != "closed":
                desired_state = "closed"
                if phase != "failed":
                    phase = "steady"
                if not workbench.get("lastReason"):
                    workbench["lastReason"] = "external_close"
            elif observed_state == desired_state and phase != "failed":
                phase = "steady"

        if desired_state == "closed" and observed_state != "closed" and phase != "failed":
            phase = "closing"
        elif desired_state == "open" and observed_state != "open" and phase != "failed":
            phase = "opening"

        workbench.update(
            {
                "desiredState": desired_state,
                "observedState": observed_state,
                "phase": phase,
                "sessionId": str(observation.get("sessionId") or "").strip(),
                "sessionRole": session_role,
                "backendPid": int(observation.get("backendPid") or 0),
                "browserLaunchPid": int(observation.get("browserLaunchPid") or 0),
                "browserWindowPid": int(observation.get("browserWindowPid") or 0),
                "backendAlive": bool(observation.get("backendAlive")),
                "backendHealthy": bool(observation.get("backendHealthy")),
                "backendObserved": bool(observation.get("backendObserved")),
                "backendPort": int(observation.get("backendPort") or 0),
                "backendPortListening": bool(observation.get("backendPortListening")),
                "backendPortOwnerPid": int(observation.get("backendPortOwnerPid") or 0),
                "backendPortOwnerKind": str(observation.get("backendPortOwnerKind") or ""),
                "backendPortOwnerTrusted": bool(observation.get("backendPortOwnerTrusted")),
                "backendPortOwnerResidual": bool(observation.get("backendPortOwnerResidual")),
                "backendPortConflict": bool(observation.get("backendPortConflict")),
                "browserWindowAlive": bool(observation.get("browserWindowAlive")),
                "browserManaged": bool(observation.get("browserManaged", True)),
                "backendMissing": bool(consistency_fields["backendMissing"]),
                "frontendOrphaned": bool(consistency_fields["frontendOrphaned"]),
                "lifecycleConsistency": str(consistency_fields["lifecycleConsistency"]),
                "url": str(observation.get("url") or workbench.get("url") or "").strip(),
                "statusLine": _build_workbench_status_line(
                    desired_state=desired_state,
                    observed_state=observed_state,
                    phase=phase,
                    backend_pid=int(observation.get("backendPid") or 0),
                    browser_pid=int(observation.get("browserWindowPid") or 0),
                    lifecycle_consistency=str(consistency_fields["lifecycleConsistency"]),
                ),
            }
        )
        previous_runtime_state = str(state.get("runtimeState") or "").strip().lower()
        state["runtimeState"] = "stopping" if previous_runtime_state == "stopping" else "running"
        state["managerPid"] = self._pid
        state["daemonRunning"] = True
        state["runtimeManager"] = {"sourceSignature": _process_source_signature()}
        state["evolution"] = build_evolution_summary()
        state["residualProcesses"] = residual_processes
        return state

    def _process_self_evolution_restart_intent(self) -> None:
        intent = claim_next_restart_intent(target="self_evolution_run")
        if not intent:
            return
        intent_id = str(intent.get("intentId") or "").strip()
        try:
            result = self_evolution_control_service._LOCAL_FULFILL_SELF_EVOLUTION_RESTART(intent)
            snapshot = result.get("snapshot") if isinstance(result.get("snapshot"), dict) else {}
            complete_restart_intent(
                intent_id,
                status="completed",
                message=str(result.get("message") or "Self-evolution restart queued."),
            )
            _append_event(
                "self_evolution.restarted_from_intent",
                {
                    "intentId": intent_id,
                    "runId": str(snapshot.get("runId") or result.get("runId") or ""),
                    "status": str(snapshot.get("status") or ""),
                    "reason": str(intent.get("reason") or ""),
                },
            )
        except Exception as exc:
            if intent_id:
                complete_restart_intent(intent_id, status="failed", message=f"{type(exc).__name__}: {exc}")
            _append_event(
                "self_evolution.restart_intent_failed",
                {
                    "intentId": intent_id,
                    "reason": str(intent.get("reason") or ""),
                    "errorType": type(exc).__name__,
                    "message": str(exc),
                },
            )

    def _handle_open_workbench(self, *, command_id: str, args: dict[str, Any]) -> dict[str, Any]:
        state = load_state()
        workbench = state.setdefault("workbench", {})
        no_browser = bool(args.get("noBrowser"))
        observation = observe_workbench()
        if _open_request_already_satisfied(observation, no_browser=no_browser) and str(workbench.get("phase") or "") != "failed":
            workbench["desiredState"] = "open"
            workbench["phase"] = "steady"
            workbench["failureMessage"] = ""
            save_state(self._reconcile_observation(state))
            _append_event(
                "workbench.open.already_satisfied",
                _open_already_satisfied_event_payload(observation, command_id=command_id, no_browser=no_browser),
            )
            if not no_browser:
                result = open_workbench(no_browser=False)
                if result.returncode != 0:
                    _append_event(
                        "workbench.open.focus_failed",
                        {
                            "commandId": command_id,
                            "returnCode": int(result.returncode),
                            "detail": _launcher_error_detail(result, "Focusing the workbench failed."),
                        },
                    )
                    raise RuntimeError(_launcher_error_detail(result, "Focusing the workbench failed."))
                _append_event(
                    "workbench.open.focus_requested",
                    {
                        "commandId": command_id,
                        "returnCode": int(result.returncode),
                        "stdout": str(getattr(result, "stdout", "") or "").strip()[-400:],
                        "stderr": str(getattr(result, "stderr", "") or "").strip()[-400:],
                    },
                )
            else:
                _append_event(
                    "workbench.open.focus_skipped",
                    {"commandId": command_id, "reason": "no_browser"},
                )
            return self._finish_command(command_id, ok=True, message="Workbench is already open.")

        workbench.update(
            {
                "desiredState": "open",
                "phase": "opening",
                "lastReason": str(args.get("reason") or "explicit_open"),
                "lastSource": str(args.get("source") or "").strip(),
                "lastTransitionAt": now_iso(),
                "failureMessage": "",
            }
        )
        save_state(self._reconcile_observation(state))
        if bool(observation.get("backendPortOwnerResidual")):
            cleanup_result = self._cleanup_residual_workbench_processes()
            _append_event(
                "workbench.open.residual_cleanup",
                {
                    "commandId": command_id,
                    "backendPort": int(observation.get("backendPort") or 0),
                    "backendPortOwnerPid": int(observation.get("backendPortOwnerPid") or 0),
                    "backendPortOwnerKind": str(observation.get("backendPortOwnerKind") or ""),
                    "cleanup": cleanup_result,
                },
            )
        result = open_workbench(no_browser=no_browser)
        if result.returncode != 0:
            raise RuntimeError(_launcher_error_detail(result, "Opening the workbench failed."))
        ready, verification, verification_attempts = _wait_for_open_verification(no_browser=no_browser)
        if not ready:
            if _open_verification_should_retry_stale_session(verification, no_browser=no_browser):
                _append_event(
                    "workbench.open.stale_session_retry",
                    _open_verification_event_payload(
                        verification,
                        no_browser=no_browser,
                        message="Open verification found an incomplete stale session; retrying launcher cleanup once.",
                        command_id=command_id,
                        launcher_result=result,
                    )
                    | {"attempts": verification_attempts},
                )
                retry_result = open_workbench(no_browser=no_browser)
                if retry_result.returncode != 0:
                    raise RuntimeError(_launcher_error_detail(retry_result, "Opening the workbench failed."))
                ready, verification, retry_attempts = _wait_for_open_verification(no_browser=no_browser)
                verification_attempts += retry_attempts
                result = retry_result
                if ready:
                    _append_event(
                        "workbench.open.verification_succeeded",
                        _open_verification_event_payload(
                            verification,
                            no_browser=no_browser,
                            command_id=command_id,
                            launcher_result=retry_result,
                        )
                        | {"attempts": verification_attempts, "retry": "stale_session_cleanup"},
                    )
                    return self._finish_command(command_id, ok=True, message="Workbench opened.")
            message = _open_verification_failure_message(verification, no_browser=no_browser)
            _append_event(
                "workbench.open.verification_failed",
                _open_verification_event_payload(
                    verification,
                    no_browser=no_browser,
                    message=message,
                    command_id=command_id,
                    launcher_result=result,
                )
                | {"attempts": verification_attempts},
            )
            raise RuntimeError(message)
        _append_event(
            "workbench.open.verification_succeeded",
            _open_verification_event_payload(
                verification,
                no_browser=no_browser,
                command_id=command_id,
            )
            | {"attempts": verification_attempts},
        )
        return self._finish_command(command_id, ok=True, message="Workbench opened.")

    def _handle_close_workbench(self, *, command_id: str, args: dict[str, Any]) -> dict[str, Any]:
        state = load_state()
        workbench = state.setdefault("workbench", {})
        observation = observe_workbench()
        if _close_request_already_satisfied(observation) and str(workbench.get("phase") or "") != "failed":
            closed_runs = _close_active_evolution_runs_for_shutdown()
            workbench["desiredState"] = "closed"
            workbench["phase"] = "steady"
            workbench["failureMessage"] = ""
            save_state(self._reconcile_observation(state))
            cleanup_result = self._cleanup_residual_workbench_processes()
            reopen_intent = _claim_workbench_reopen_intent() if bool(args.get("stopManager")) else None
            if bool(args.get("stopManager")):
                if reopen_intent:
                    _append_event(
                        "workbench.reopen_after_close.claimed",
                        _workbench_reopen_intent_event_payload(reopen_intent, command_id=command_id),
                    )
                else:
                    _append_event("daemon.stop_requested", {"commandId": command_id, "reason": "close_workbench"})
            return self._finish_command(
                command_id,
                ok=True,
                message="Workbench is already closed.",
                result_data={
                    "residualCleanup": cleanup_result,
                    "closedEvolutionRuns": closed_runs,
                    "stopDaemon": bool(args.get("stopManager")) and not bool(reopen_intent),
                    "runDeferredWorkbenchOpen": bool(reopen_intent),
                    "restartIntent": reopen_intent or {},
                },
            )

        closed_runs = _close_active_evolution_runs_for_shutdown()
        workbench.update(
            {
                "desiredState": "closed",
                "phase": "closing",
                "lastReason": str(args.get("reason") or "explicit_close"),
                "lastSource": str(args.get("source") or "").strip(),
                "lastTransitionAt": now_iso(),
                "failureMessage": "",
            }
        )
        save_state(self._reconcile_observation(state))
        result = close_workbench()
        if result.returncode != 0:
            raise RuntimeError(_launcher_error_detail(result, "Closing the workbench failed."))
        cleanup_result = self._cleanup_residual_workbench_processes()
        closed, verification, verification_attempts = _wait_for_close_verification()
        if not closed:
            message = _close_verification_failure_message(verification)
            _append_event(
                "workbench.close.verification_failed",
                _close_verification_event_payload(
                    verification,
                    command_id=command_id,
                    message=message,
                    cleanup_result=cleanup_result,
                    launcher_result=result,
                )
                | {"attempts": verification_attempts},
            )
            raise RuntimeError(message)
        _append_event(
            "workbench.close.verification_succeeded",
            _close_verification_event_payload(
                verification,
                command_id=command_id,
                cleanup_result=cleanup_result,
                launcher_result=result,
            )
            | {"attempts": verification_attempts},
        )
        reopen_intent = _claim_workbench_reopen_intent() if bool(args.get("stopManager")) else None
        final_result = self._finish_command(
            command_id,
            ok=True,
            message="Workbench closed.",
            result_data={
                "residualCleanup": cleanup_result,
                "closedEvolutionRuns": closed_runs,
                "stopDaemon": bool(args.get("stopManager")) and not bool(reopen_intent),
                "runDeferredWorkbenchOpen": bool(reopen_intent),
                "restartIntent": reopen_intent or {},
            },
        )
        if bool(args.get("stopManager")):
            if reopen_intent:
                _append_event(
                    "workbench.reopen_after_close.claimed",
                    _workbench_reopen_intent_event_payload(reopen_intent, command_id=command_id),
                )
            else:
                _append_event("daemon.stop_requested", {"commandId": command_id, "reason": "close_workbench"})
        return final_result

    def _run_deferred_workbench_open(self, result: dict[str, Any]) -> None:
        intent = result.get("restartIntent") if isinstance(result.get("restartIntent"), dict) else {}
        intent_id = str(intent.get("intentId") or "").strip()
        payload = intent.get("payload") if isinstance(intent.get("payload"), dict) else {}
        command_id = str(intent.get("sourceCommandId") or intent_id or "deferred-open").strip()
        try:
            _append_event(
                "workbench.reopen_after_close.started",
                _workbench_reopen_intent_event_payload(intent, command_id=command_id),
            )
            open_result = self._handle_open_workbench(
                command_id=command_id,
                args={
                    "reason": "reopen_after_close",
                    "noBrowser": bool(payload.get("noBrowser")),
                    "source": "restart_coordinator",
                },
            )
            if intent_id:
                complete_restart_intent(intent_id, status="completed", message=str(open_result.get("message") or "Workbench reopened."))
            _append_event(
                "workbench.reopen_after_close.completed",
                _workbench_reopen_intent_event_payload(intent, command_id=command_id)
                | {"ok": bool(open_result.get("ok")), "message": str(open_result.get("message") or "")},
            )
        except Exception as exc:
            if intent_id:
                complete_restart_intent(intent_id, status="failed", message=f"{type(exc).__name__}: {exc}")
            _append_event(
                "workbench.reopen_after_close.failed",
                _workbench_reopen_intent_event_payload(intent, command_id=command_id)
                | {"errorType": type(exc).__name__, "message": str(exc)},
            )

    def _cleanup_residual_workbench_processes(self) -> dict[str, Any]:
        return terminate_unmanaged_workbench_processes(
            project_root=PROJECT_ROOT,
            exclude_pids=_snapshot_residual_excluded_pids(observe_workbench(), self._pid, include_workbench=False),
        )

    def _handle_restart_workbench(self, *, command_id: str, args: dict[str, Any]) -> dict[str, Any]:
        state = load_state()
        workbench = state.setdefault("workbench", {})
        requested_no_browser = bool(args.get("noBrowser"))
        workbench.update(
            {
                "desiredState": "open",
                "phase": "opening",
                "lastReason": str(args.get("reason") or "explicit_restart"),
                "lastSource": str(args.get("source") or "").strip(),
                "lastTransitionAt": now_iso(),
                "failureMessage": "",
            }
        )
        state = save_state(self._reconcile_observation(state))
        workbench = state.setdefault("workbench", {})
        effective_no_browser = requested_no_browser
        if requested_no_browser and _restart_should_preserve_visible_browser(workbench):
            effective_no_browser = False
            _append_event(
                "workbench.restart.no_browser_overridden",
                {
                    "commandId": command_id,
                    "requestedNoBrowser": True,
                    "effectiveNoBrowser": False,
                    "reason": "preserve_existing_managed_browser_window",
                    "browserWindowPid": int(workbench.get("browserWindowPid") or 0),
                    "browserManaged": bool(workbench.get("browserManaged")),
                    "browserWindowAlive": bool(workbench.get("browserWindowAlive")),
                    "requestedReason": str(args.get("reason") or ""),
                    "requestedSource": str(args.get("source") or ""),
                },
            )
        result = restart_workbench(no_browser=effective_no_browser)
        if result.returncode != 0:
            raise RuntimeError(_launcher_error_detail(result, "Restarting the workbench failed."))
        return self._finish_command(command_id, ok=True, message="Workbench restarted.")

    def _handle_toggle_workbench(self, *, command_id: str, args: dict[str, Any]) -> dict[str, Any]:
        state = load_state()
        observed_state = str(state.setdefault("workbench", {}).get("observedState") or "closed").strip() or "closed"
        if observed_state == "open":
            return self._handle_close_workbench(command_id=command_id, args=args)
        return self._handle_open_workbench(command_id=command_id, args=args)

    def _handle_start_self_evolution_run(self, *, command_id: str, args: dict[str, Any]) -> dict[str, Any]:
        payload = args.get("payload") if isinstance(args.get("payload"), dict) else {}
        snapshot = self_evolution_control_service._LOCAL_START_SELF_EVOLUTION_RUN(payload)
        return self._finish_command(
            command_id,
            ok=True,
            message="Self-evolution run started.",
            result_data={"runId": str(snapshot.get("runId") or ""), "snapshot": snapshot},
        )

    def _handle_pause_self_evolution_run(self, *, command_id: str, args: dict[str, Any]) -> dict[str, Any]:
        run_id = str(args.get("runId") or "").strip()
        snapshot = self_evolution_control_service._LOCAL_REQUEST_PAUSE_SELF_EVOLUTION_RUN(run_id)
        return self._finish_command(
            command_id,
            ok=True,
            message="Self-evolution pause requested.",
            result_data={"runId": run_id, "snapshot": snapshot},
        )

    def _handle_resume_self_evolution_run(self, *, command_id: str, args: dict[str, Any]) -> dict[str, Any]:
        run_id = str(args.get("runId") or "").strip()
        snapshot = self_evolution_control_service._LOCAL_RESUME_SELF_EVOLUTION_RUN(run_id)
        return self._finish_command(
            command_id,
            ok=True,
            message="Self-evolution run resumed.",
            result_data={"runId": run_id, "snapshot": snapshot},
        )

    def _handle_stop_self_evolution_run(self, *, command_id: str, args: dict[str, Any]) -> dict[str, Any]:
        run_id = str(args.get("runId") or "").strip()
        snapshot = self_evolution_control_service._LOCAL_REQUEST_STOP_SELF_EVOLUTION_RUN(run_id)
        return self._finish_command(
            command_id,
            ok=True,
            message="Self-evolution stop requested.",
            result_data={"runId": run_id, "snapshot": snapshot},
        )

    def _handle_restart_self_evolution_run(self, *, command_id: str, args: dict[str, Any]) -> dict[str, Any]:
        run_id = str(args.get("runId") or "").strip()
        payload = args.get("payload") if isinstance(args.get("payload"), dict) else {}
        reason = str(args.get("reason") or payload.get("reason") or "self_evolution_restart").strip() or "self_evolution_restart"
        intent = self_evolution_control_service._LOCAL_REQUEST_SELF_EVOLUTION_RESTART(run_id=run_id, reason=reason)
        snapshot = intent.get("snapshot") if isinstance(intent.get("snapshot"), dict) else {}
        return self._finish_command(
            command_id,
            ok=True,
            message="Self-evolution restart requested.",
            result_data={
                "runId": str(snapshot.get("runId") or run_id),
                "snapshot": snapshot,
                "restartIntent": {key: value for key, value in intent.items() if key != "snapshot"},
            },
        )

    def _handle_start_supervised_run(self, *, command_id: str, args: dict[str, Any]) -> dict[str, Any]:
        payload = args.get("payload") if isinstance(args.get("payload"), dict) else {}
        snapshot = supervised_control_service._LOCAL_START_SUPERVISED_RUN(payload)
        return self._finish_command(
            command_id,
            ok=True,
            message="Supervised run started.",
            result_data={"runId": str(snapshot.get("runId") or ""), "snapshot": snapshot},
        )

    def _handle_pause_supervised_run(self, *, command_id: str, args: dict[str, Any]) -> dict[str, Any]:
        run_id = str(args.get("runId") or "").strip()
        snapshot = supervised_control_service._LOCAL_REQUEST_PAUSE_SUPERVISED_RUN(run_id)
        return self._finish_command(
            command_id,
            ok=True,
            message="Supervised run pause requested.",
            result_data={"runId": run_id, "snapshot": snapshot},
        )

    def _handle_resume_supervised_run(self, *, command_id: str, args: dict[str, Any]) -> dict[str, Any]:
        run_id = str(args.get("runId") or "").strip()
        snapshot = supervised_control_service._LOCAL_REQUEST_RESUME_SUPERVISED_RUN(run_id)
        return self._finish_command(
            command_id,
            ok=True,
            message="Supervised run resumed.",
            result_data={"runId": run_id, "snapshot": snapshot},
        )

    def _handle_stop_supervised_run(self, *, command_id: str, args: dict[str, Any]) -> dict[str, Any]:
        run_id = str(args.get("runId") or "").strip()
        snapshot = supervised_control_service._LOCAL_REQUEST_STOP_SUPERVISED_RUN(run_id)
        return self._finish_command(
            command_id,
            ok=True,
            message="Supervised run stop requested.",
            result_data={"runId": run_id, "snapshot": snapshot},
        )

    def _handle_delete_supervised_run(self, *, command_id: str, args: dict[str, Any]) -> dict[str, Any]:
        run_id = str(args.get("runId") or "").strip()
        result = supervised_control_service._LOCAL_DELETE_SUPERVISED_RUN_SNAPSHOT(run_id)
        return self._finish_command(
            command_id,
            ok=True,
            message="Supervised run record deleted.",
            result_data={"runId": run_id, "deleteResult": result},
        )


def run_daemon() -> None:
    RuntimeManagerDaemon().run_forever()
