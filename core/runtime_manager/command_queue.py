"""File-backed command queue for the runtime manager."""

from __future__ import annotations

import json
import os
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from .constants import (
    DEFAULT_COMMAND_WAIT_SECONDS,
    EVENTS_PATH,
    INBOX_DIR,
    INTERRUPTS_DIR,
    PROCESSING_DIR,
    RESULTS_DIR,
    ensure_runtime_manager_dirs,
)
from .scene_logging import (
    append_runtime_manager_file_event,
    command_event_payload,
    record_runtime_manager_scene_event,
    truncate_event_text,
)
from .state_store import load_pid, load_state
from .restart_coordinator import create_restart_intent


DEFERRED_COMMAND_POLL_SECONDS = 10.0
ACTIVE_LIFECYCLE_INTERRUPT_TYPES = {"open_workbench", "restart_workbench"}
LIFECYCLE_COMMAND_TYPES = {
    "open_workbench",
    "close_workbench",
    "force_close_workbench",
    "restart_workbench",
    "hot_restart_workbench",
    "toggle_workbench",
}
LIFECYCLE_CANCEL_TYPES = {
    "restart": {"restart_workbench"},
    "stop": {"close_workbench"},
    "close": {"close_workbench"},
    "shutdown": {"close_workbench"},
    "force-stop": {"force_close_workbench"},
}


def _command_timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def build_command(command_type: str, *, args: dict[str, Any] | None = None, requested_by: str = "unknown") -> dict[str, Any]:
    return {
        "commandId": f"cmd_{_command_timestamp()}_{uuid4().hex[:8]}",
        "type": str(command_type or "").strip(),
        "requestedBy": str(requested_by or "unknown").strip() or "unknown",
        "requestedAt": datetime.now(timezone.utc).isoformat(),
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


def _elapsed_ms_since(value: Any, *, now: datetime | None = None) -> float | None:
    started = _parse_datetime(str(value or ""))
    if started is None:
        return None
    current = now or datetime.now(timezone.utc)
    return round(max(0.0, (current - started).total_seconds() * 1000.0), 1)


def _queue_file_count(path: Path) -> int:
    try:
        return sum(1 for _ in path.glob("*.json"))
    except OSError:
        return 0


def _command_queue_timing_fields(command: dict[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    current = now or datetime.now(timezone.utc)
    fields: dict[str, Any] = {}
    requested_at = str(command.get("requestedAt") or "").strip()
    if requested_at:
        fields["requestedAt"] = requested_at
        queued_ms = _elapsed_ms_since(requested_at, now=current)
        if queued_ms is not None:
            fields["queuedMs"] = queued_ms
    claimed_at = str(command.get("claimedAt") or "").strip()
    if claimed_at:
        fields["claimedAt"] = claimed_at
    return fields


def _command_defer_until(command: dict[str, Any]) -> datetime | None:
    args = command.get("args") if isinstance(command.get("args"), dict) else {}
    return _parse_datetime(str(args.get("deferUntil") or ""))


def _command_is_deferred(command: dict[str, Any], *, now: datetime | None = None) -> bool:
    defer_until = _command_defer_until(command)
    if defer_until is None:
        return False
    current = now or datetime.now(timezone.utc)
    return defer_until > current


def submit_command(
    command_type: str,
    *,
    args: dict[str, Any] | None = None,
    requested_by: str = "unknown",
) -> dict[str, Any]:
    command = build_command(command_type, args=args, requested_by=requested_by)
    shutdown_state = _shutdown_in_progress_state()
    if shutdown_state is not None:
        if _should_defer_open_during_shutdown(command):
            _complete_deferred_open_command(command, shutdown_state=shutdown_state)
            return command
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
    superseded_commands = _supersede_pending_open_commands_for_close(command)
    active_interrupt = request_active_lifecycle_interrupt_for_close(command)
    joined_command_id = _joinable_lifecycle_command_id(command)
    if joined_command_id:
        command["commandId"] = joined_command_id
        command_type = str(command.get("type") or "")
        event_type = {
            "close_workbench": "command_queue.close_joined",
            "force_close_workbench": "command_queue.force_close_joined",
            "restart_workbench": "command_queue.restart_joined",
        }.get(command_type, "command_queue.open_joined")
        _append_queue_event(
            event_type,
            {
                "commandId": joined_command_id,
                "type": command_type,
                "requestedBy": str(command.get("requestedBy") or ""),
                "noBrowser": bool((command.get("args") or {}).get("noBrowser")),
                "stopManager": bool((command.get("args") or {}).get("stopManager")),
            },
        )
        return command
    _atomic_write_json(INBOX_DIR / f"{command['commandId']}.json", command)
    queued_payload = command_event_payload(command)
    queued_payload["queueDepthAfterEnqueue"] = _queue_file_count(INBOX_DIR)
    if superseded_commands:
        queued_payload["supersededPendingCommands"] = superseded_commands
    if active_interrupt:
        queued_payload["activeCommandInterrupt"] = active_interrupt
    _append_queue_event("command_queue.command_queued", queued_payload)
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
        command = _load_command_file(path)
        if _discard_recovered_command_with_existing_result(path, command):
            continue
        if _complete_recovered_satisfied_close_workbench(path, command):
            continue
        target = INBOX_DIR / path.name
        try:
            os.replace(path, target)
            _append_queue_event(
                "command_queue.processing_recovered",
                command_event_payload(command, queue_path=target.name)
                if isinstance(command, dict)
                else {"queuePath": target.name},
            )
        except OSError:
            continue
    _complete_satisfied_pending_close_commands()


def _complete_satisfied_pending_close_commands() -> None:
    for path in sorted(INBOX_DIR.glob("*.json")):
        command = _load_command_file(path)
        if _discard_recovered_command_with_existing_result(path, command):
            continue
        _complete_recovered_satisfied_close_workbench(path, command)


def has_recent_lifecycle_command(*, grace_seconds: float, now: datetime | None = None) -> bool:
    ensure_runtime_manager_dirs()
    current = now or datetime.now(timezone.utc)
    age_limit = max(0.0, float(grace_seconds))
    for directory in (PROCESSING_DIR, INBOX_DIR):
        for path in sorted(directory.glob("*.json")):
            command = _load_command_file(path)
            if str(command.get("type") or "").strip() not in LIFECYCLE_COMMAND_TYPES:
                continue
            for key in ("claimedAt", "startedAt", "requestedAt"):
                parsed = _parse_datetime(str(command.get(key) or ""))
                if parsed is not None and (current - parsed).total_seconds() <= age_limit:
                    return True
            try:
                mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
            except OSError:
                continue
            if (current - mtime).total_seconds() <= age_limit:
                return True
    return False


def claim_next_command() -> tuple[Path, dict[str, Any]] | None:
    ensure_runtime_manager_dirs()
    now = datetime.now(timezone.utc)
    for path in sorted(INBOX_DIR.glob("*.json")):
        pending = _load_command_file(path)
        if pending and _command_is_deferred(pending, now=now):
            continue
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
            clear_lifecycle_interrupt(str(payload.get("commandId") or target.stem).strip() or target.stem)
            claimed_at = datetime.now(timezone.utc)
            payload["claimedAt"] = claimed_at.isoformat()
            claimed_payload = command_event_payload(payload, queue_path=target.name)
            claimed_payload.update(_command_queue_timing_fields(payload, now=claimed_at))
            claimed_payload["queueDepthAfterClaim"] = _queue_file_count(INBOX_DIR)
            _append_queue_event("command_queue.command_claimed", claimed_payload)
            return target, payload
        try:
            target.unlink(missing_ok=True)
        except OSError:
            pass
    return None


def request_active_lifecycle_interrupt_for_close(command: dict[str, Any]) -> dict[str, Any] | None:
    ensure_runtime_manager_dirs()
    command_type = str(command.get("type") or "").strip()
    if command_type not in {"close_workbench", "force_close_workbench"}:
        return None
    manager_pid = load_pid()
    if not _process_is_alive(manager_pid):
        return None
    state = load_state()
    if not isinstance(state, dict) or not _state_belongs_to_current_manager(state, manager_pid):
        return None
    active = state.get("command") if isinstance(state.get("command"), dict) else {}
    active_command_id = str(active.get("activeCommandId") or "").strip()
    active_type = str(active.get("activeType") or "").strip()
    if not active_command_id or active_type not in ACTIVE_LIFECYCLE_INTERRUPT_TYPES:
        return None
    interrupt = {
        "interruptedCommandId": active_command_id,
        "interruptedType": active_type,
        "closeCommandId": str(command.get("commandId") or "").strip(),
        "closeCommandType": command_type,
        "requestedBy": str(command.get("requestedBy") or "unknown").strip() or "unknown",
        "requestedAt": datetime.now(timezone.utc).isoformat(),
        "stateVersion": int(state.get("stateVersion") or 0),
        "operation": "force_close" if command_type == "force_close_workbench" else "close",
    }
    try:
        _atomic_write_json(INTERRUPTS_DIR / f"{active_command_id}.json", interrupt)
    except OSError as exc:
        _append_queue_event(
            "command_queue.active_lifecycle_interrupt_failed",
            {
                "commandId": str(command.get("commandId") or ""),
                "type": command_type,
                "activeCommandId": active_command_id,
                "activeType": active_type,
                "errorType": type(exc).__name__,
                "message": str(exc),
            },
        )
        return None
    _append_queue_event(
        "command_queue.active_lifecycle_interrupt_requested",
        {
            "commandId": str(command.get("commandId") or ""),
            "type": command_type,
            "activeCommandId": active_command_id,
            "activeType": active_type,
            "operation": interrupt["operation"],
            "stateVersion": interrupt["stateVersion"],
        },
    )
    return interrupt


def lifecycle_interrupt_requested(command_id: str) -> dict[str, Any] | None:
    normalized_id = str(command_id or "").strip()
    if not _safe_command_id(normalized_id):
        return None
    payload = _load_command_file(INTERRUPTS_DIR / f"{normalized_id}.json")
    if not payload:
        return None
    if str(payload.get("interruptedCommandId") or "").strip() != normalized_id:
        return None
    return payload


def clear_lifecycle_interrupt(command_id: str) -> None:
    normalized_id = str(command_id or "").strip()
    if not _safe_command_id(normalized_id):
        return
    try:
        (INTERRUPTS_DIR / f"{normalized_id}.json").unlink(missing_ok=True)
    except OSError:
        pass


def defer_processing_command_for_active_work(
    path: Path,
    command: dict[str, Any],
    *,
    active_work_runs: list[dict[str, Any]],
    delay_seconds: float = DEFERRED_COMMAND_POLL_SECONDS,
) -> None:
    ensure_runtime_manager_dirs()
    command_id = str(command.get("commandId") or path.stem).strip() or path.stem
    args = command.get("args") if isinstance(command.get("args"), dict) else {}
    now = datetime.now(timezone.utc)
    attempt_count = int(args.get("activeWorkDeferCount") or 0) + 1
    args.update(
        {
            "deferUntil": datetime.fromtimestamp(now.timestamp() + max(1.0, float(delay_seconds)), tz=timezone.utc).isoformat(),
            "activeWorkDeferCount": attempt_count,
            "lastActiveWorkCount": len(active_work_runs),
            "lastActiveWorkRuns": active_work_runs[:8],
        }
    )
    command["args"] = args
    command["commandId"] = command_id
    target = INBOX_DIR / f"{command_id}.json"
    _atomic_write_json(target, command)
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass
    _append_queue_event(
        "command_queue.command_deferred_active_work",
        {
            "commandId": command_id,
            "type": str(command.get("type") or ""),
            "requestedBy": str(command.get("requestedBy") or ""),
            **_command_queue_timing_fields(command, now=now),
            "deferUntil": str(args.get("deferUntil") or ""),
            "activeWorkCount": len(active_work_runs),
            "activeWorkRuns": active_work_runs[:8],
            "attemptCount": attempt_count,
            "deferDelaySeconds": max(1.0, float(delay_seconds)),
            "queuePath": target.name,
            "queueDepthAfterDefer": _queue_file_count(INBOX_DIR),
        },
    )


def cancel_lifecycle_command(
    *,
    command_id: str = "",
    operation: str = "",
    requested_by: str = "unknown",
) -> dict[str, Any]:
    ensure_runtime_manager_dirs()
    normalized_id = str(command_id or "").strip()
    normalized_operation = str(operation or "").strip().lower()
    allowed_types = LIFECYCLE_CANCEL_TYPES.get(normalized_operation, set())
    if not normalized_id:
        return _lifecycle_cancel_response(
            cancelled=False,
            status="invalid_request",
            command_id="",
            operation=normalized_operation,
            message="Lifecycle cancel requires a commandId.",
        )
    if not _safe_command_id(normalized_id):
        return _lifecycle_cancel_response(
            cancelled=False,
            status="invalid_request",
            command_id="",
            operation=normalized_operation,
            message="Lifecycle cancel commandId is invalid.",
        )
    if not allowed_types:
        return _lifecycle_cancel_response(
            cancelled=False,
            status="invalid_request",
            command_id=normalized_id,
            operation=normalized_operation,
            message="Lifecycle cancel operation is invalid.",
        )

    inbox_path = INBOX_DIR / f"{normalized_id}.json"
    cancel_claim_path = RESULTS_DIR / f".{normalized_id}.cancel"
    try:
        os.replace(inbox_path, cancel_claim_path)
    except OSError:
        cancel_claim_path = None
    if cancel_claim_path is not None:
        command = _load_command_file(cancel_claim_path)
        command["commandId"] = str(command.get("commandId") or normalized_id).strip() or normalized_id
        command_type = str(command.get("type") or "").strip()
        if allowed_types and command_type not in allowed_types:
            try:
                os.replace(cancel_claim_path, inbox_path)
            except OSError:
                pass
            return _lifecycle_cancel_response(
                cancelled=False,
                status="not_found",
                command_id=normalized_id,
                operation=normalized_operation,
                message="Lifecycle command did not match the requested operation.",
            )
        state = load_state()
        state_version = int(state.get("stateVersion") or 0) if isinstance(state, dict) else 0
        result = {
            "commandId": normalized_id,
            "accepted": True,
            "completed": True,
            "ok": False,
            "cancelled": True,
            "message": "Lifecycle command was cancelled before execution.",
            "errorType": "LifecycleCommandCancelled",
            "stateVersion": state_version,
        }
        complete_command(cancel_claim_path, result)
        _append_queue_event(
            "command_queue.lifecycle_command_cancelled",
            {
                "commandId": normalized_id,
                "type": command_type,
                "operation": normalized_operation,
                "requestedBy": str(requested_by or "unknown"),
                "queuePath": inbox_path.name,
                "stateVersion": state_version,
            },
        )
        return _lifecycle_cancel_response(
            cancelled=True,
            status="cancelled",
            command_id=normalized_id,
            operation=normalized_operation,
            message="Lifecycle command was cancelled before execution.",
            state_version=state_version,
        )

    processing_path = PROCESSING_DIR / f"{normalized_id}.json"
    if processing_path.exists():
        command = _load_command_file(processing_path)
        command_type = str(command.get("type") or "").strip()
        if allowed_types and command_type not in allowed_types:
            return _lifecycle_cancel_response(
                cancelled=False,
                status="not_found",
                command_id=normalized_id,
                operation=normalized_operation,
                message="Lifecycle command did not match the requested operation.",
            )
        _append_queue_event(
            "command_queue.lifecycle_command_cancel_active_skipped",
            {
                "commandId": normalized_id,
                "type": command_type,
                "operation": normalized_operation,
                "requestedBy": str(requested_by or "unknown"),
                "queuePath": processing_path.name,
            },
        )
        return _lifecycle_cancel_response(
            cancelled=False,
            status="already_active",
            command_id=normalized_id,
            operation=normalized_operation,
            message="Lifecycle command is already running and cannot be cancelled safely.",
        )

    return _lifecycle_cancel_response(
        cancelled=False,
        status="not_found",
        command_id=normalized_id,
        operation=normalized_operation,
        message="Lifecycle command is no longer pending.",
    )


def _should_defer_open_during_shutdown(command: dict[str, Any]) -> bool:
    return str(command.get("type") or "").strip() == "open_workbench"


def _load_command_file(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _discard_recovered_command_with_existing_result(path: Path, command: dict[str, Any]) -> bool:
    command_id = str(command.get("commandId") or path.stem).strip() or path.stem
    result_path = RESULTS_DIR / f"{command_id}.json"
    if not result_path.exists():
        return False
    try:
        payload = json.loads(result_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if not isinstance(payload, dict):
        return False
    if payload.get("completed") is not True:
        return False
    result_command_id = str(payload.get("commandId") or command_id).strip() or command_id
    if result_command_id != command_id:
        return False
    try:
        path.unlink(missing_ok=True)
    except OSError:
        return False
    _append_queue_event(
        "command_queue.recovered_processing_result_preserved",
        {
            "commandId": command_id,
            "type": str(command.get("type") or ""),
            "requestedBy": str(command.get("requestedBy") or ""),
            "requestedAt": str(command.get("requestedAt") or ""),
            "queuePath": path.name,
            "resultPath": result_path.name,
            "resultCompleted": bool(payload.get("completed")),
            "resultOk": bool(payload.get("ok")),
        },
    )
    return True


def _lifecycle_cancel_response(
    *,
    cancelled: bool,
    status: str,
    command_id: str,
    operation: str,
    message: str,
    state_version: int | None = None,
) -> dict[str, Any]:
    response: dict[str, Any] = {
        "cancelled": cancelled,
        "status": status,
        "commandId": command_id,
        "operation": operation,
        "message": message,
    }
    if state_version is not None:
        response["stateVersion"] = state_version
    return response


def _safe_command_id(command_id: str) -> bool:
    return bool(command_id) and all(char.isalnum() or char in {"_", "-"} for char in command_id)


def _complete_recovered_satisfied_close_workbench(path: Path, command: dict[str, Any]) -> bool:
    if not _is_recoverable_close_workbench(command):
        return False
    state = load_state()
    recovery_source = "state"
    if not _workbench_is_already_closed(state):
        if not _live_observation_says_workbench_closed():
            return False
        recovery_source = "live_observation"
    command_id = str(command.get("commandId") or path.stem).strip() or path.stem
    result = {
        "commandId": command_id,
        "accepted": True,
        "completed": True,
        "ok": True,
        "message": "Recovered stale close command was already satisfied.",
        "stateVersion": int(state.get("stateVersion") or 0) if isinstance(state, dict) else 0,
        "staleRecoveredCommand": True,
        "recoverySource": recovery_source,
        "stopDaemon": False,
    }
    complete_command(path, result)
    _append_queue_event(
        "command_queue.recovered_stale_close_completed",
        {
            "commandId": command_id,
            "type": str(command.get("type") or ""),
            "requestedBy": str(command.get("requestedBy") or ""),
            "requestedAt": str(command.get("requestedAt") or ""),
            "queuePath": path.name,
            "reason": "workbench_already_closed",
            "recoverySource": recovery_source,
        },
    )
    return True


def _is_recoverable_close_workbench(command: dict[str, Any]) -> bool:
    return str(command.get("type") or "").strip() in {"close_workbench", "force_close_workbench"}


def _workbench_is_already_closed(state: Any) -> bool:
    if not isinstance(state, dict):
        return False
    workbench = state.get("workbench") if isinstance(state.get("workbench"), dict) else {}
    desired = str(workbench.get("desiredState") or "").strip()
    observed = str(workbench.get("observedState") or "").strip()
    phase = str(workbench.get("phase") or "").strip()
    return desired == "closed" and observed == "closed" and phase in {"", "steady", "closing"}


def _live_observation_says_workbench_closed() -> bool:
    try:
        from . import workbench_controller

        observation = workbench_controller.observe_workbench(recover_browser_window_for_backend_observed=False)
    except TypeError as exc:
        if "recover_browser_window_for_backend_observed" not in str(exc):
            _append_queue_event(
                "command_queue.recovered_stale_close_observation_failed",
                {"errorType": type(exc).__name__, "message": truncate_event_text(str(exc))},
            )
            return False
        try:
            from . import workbench_controller

            observation = workbench_controller.observe_workbench()
        except Exception as fallback_exc:
            _append_queue_event(
                "command_queue.recovered_stale_close_observation_failed",
                {"errorType": type(fallback_exc).__name__, "message": truncate_event_text(str(fallback_exc))},
            )
            return False
    except Exception as exc:
        _append_queue_event(
            "command_queue.recovered_stale_close_observation_failed",
            {"errorType": type(exc).__name__, "message": truncate_event_text(str(exc))},
        )
        return False
    if not isinstance(observation, dict):
        return False
    return bool(
        str(observation.get("observedState") or "").strip() == "closed"
        and not observation.get("backendAlive")
        and not observation.get("backendObserved")
        and not observation.get("backendPortListening")
        and not observation.get("browserWindowAlive")
    )


def complete_command(path: Path, result: dict[str, Any]) -> None:
    command_id = str(result.get("commandId") or path.stem).strip() or path.stem
    completed_at = datetime.now(timezone.utc)
    result_path = RESULTS_DIR / f"{command_id}.json"
    command_payload = _load_command_file(path)
    _atomic_write_json(result_path, result)
    clear_lifecycle_interrupt(command_id)
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass
    event_payload = {
        "commandId": command_id,
        "type": str(result.get("type") or command_payload.get("type") or ""),
        "requestedBy": str(result.get("requestedBy") or command_payload.get("requestedBy") or ""),
        "resultPath": result_path.name,
        "ok": bool(result.get("ok")),
        "completed": bool(result.get("completed")),
        "message": truncate_event_text(str(result.get("message") or "")),
        "errorType": str(result.get("errorType") or ""),
        "stopDaemon": bool(result.get("stopDaemon")),
        "queueDepthAfterResult": _queue_file_count(INBOX_DIR),
    }
    for key in ("requestedAt", "claimedAt", "startedAt", "queuedMs", "runMs"):
        if key in result:
            event_payload[key] = result[key]
    total_ms = _elapsed_ms_since(result.get("requestedAt"), now=completed_at)
    if total_ms is not None:
        event_payload["totalMs"] = total_ms
    _append_queue_event("command_queue.command_result_written", event_payload)


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


def _supersede_pending_open_commands_for_close(command: dict[str, Any]) -> list[dict[str, Any]]:
    command_type = str(command.get("type") or "").strip()
    if command_type not in {"close_workbench", "force_close_workbench"}:
        return []
    pending_types = {"open_workbench", "restart_workbench"}
    if command_type == "force_close_workbench":
        pending_types.add("close_workbench")
    error_type = "SupersededByForceCloseWorkbench" if command_type == "force_close_workbench" else "SupersededByCloseWorkbench"
    superseded: list[dict[str, Any]] = []
    state = load_state()
    state_version = int(state.get("stateVersion") or 0) if isinstance(state, dict) else 0
    for path in sorted(INBOX_DIR.glob("*.json")):
        payload = _load_command_file(path)
        pending_type = str(payload.get("type") or "").strip()
        if pending_type not in pending_types:
            continue
        command_id = str(payload.get("commandId") or path.stem).strip() or path.stem
        payload["commandId"] = command_id
        result = {
            "commandId": command_id,
            "accepted": True,
            "completed": True,
            "ok": False,
            "message": f"Command superseded by a {command_type} request.",
            "errorType": error_type,
            "supersededByCommandId": str(command.get("commandId") or ""),
            "stateVersion": state_version,
        }
        try:
            complete_command(path, result)
        except OSError as exc:
            superseded.append(
                {
                    "commandId": command_id,
                    "type": pending_type,
                    "status": "failed",
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
            continue
        superseded.append({"commandId": command_id, "type": pending_type, "status": "superseded"})
    if superseded:
        event_type = (
            "command_queue.pending_lifecycle_superseded_by_force_close"
            if command_type == "force_close_workbench"
            else "command_queue.pending_open_superseded_by_close"
        )
        _append_queue_event(
            event_type,
            {
                "commandId": str(command.get("commandId") or ""),
                "count": len(superseded),
                "commands": superseded,
            },
        )
    return superseded


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


def _joinable_lifecycle_command_id(command: dict[str, Any]) -> str:
    command_type = str(command.get("type") or "").strip()
    if command_type == "open_workbench":
        return _joinable_open_command_id(command)
    if command_type == "restart_workbench":
        return _joinable_restart_command_id(command)
    if command_type == "close_workbench":
        return _joinable_close_command_id(command)
    if command_type == "force_close_workbench":
        return _joinable_force_close_command_id(command)
    return ""


def _joinable_open_command_id(command: dict[str, Any]) -> str:
    command_type = str(command.get("type") or "").strip()
    if command_type != "open_workbench":
        return ""
    manager_pid = load_pid()
    if not _process_is_alive(manager_pid):
        return ""
    state = load_state()
    if not isinstance(state, dict) or not _state_belongs_to_current_manager(state, manager_pid):
        return ""
    requested_args = command.get("args") if isinstance(command.get("args"), dict) else {}
    requested_no_browser = bool(requested_args.get("noBrowser"))
    active = state.get("command") if isinstance(state.get("command"), dict) else {}
    active_command_id = str(active.get("activeCommandId") or "").strip()
    if (
        active_command_id
        and str(active.get("activeType") or "").strip() == "open_workbench"
        and _open_requests_are_compatible(existing_no_browser=bool(active.get("noBrowser")), requested_no_browser=requested_no_browser)
    ):
        return active_command_id
    for path in sorted(INBOX_DIR.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        if str(payload.get("type") or "").strip() != "open_workbench":
            continue
        existing_args = payload.get("args") if isinstance(payload.get("args"), dict) else {}
        if not _open_requests_are_compatible(
            existing_no_browser=bool(existing_args.get("noBrowser")),
            requested_no_browser=requested_no_browser,
        ):
            continue
        return str(payload.get("commandId") or path.stem).strip() or path.stem
    return ""


def _joinable_restart_command_id(command: dict[str, Any]) -> str:
    command_type = str(command.get("type") or "").strip()
    if command_type != "restart_workbench":
        return ""
    manager_pid = load_pid()
    if not _process_is_alive(manager_pid):
        return ""
    state = load_state()
    if not isinstance(state, dict) or not _state_belongs_to_current_manager(state, manager_pid):
        return ""
    requested_args = command.get("args") if isinstance(command.get("args"), dict) else {}
    requested_no_browser = bool(requested_args.get("noBrowser"))
    active = state.get("command") if isinstance(state.get("command"), dict) else {}
    active_command_id = str(active.get("activeCommandId") or "").strip()
    if (
        active_command_id
        and str(active.get("activeType") or "").strip() == "restart_workbench"
        and _open_requests_are_compatible(existing_no_browser=bool(active.get("noBrowser")), requested_no_browser=requested_no_browser)
    ):
        return active_command_id
    for path in sorted(INBOX_DIR.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        if str(payload.get("type") or "").strip() != "restart_workbench":
            continue
        existing_args = payload.get("args") if isinstance(payload.get("args"), dict) else {}
        if not _open_requests_are_compatible(
            existing_no_browser=bool(existing_args.get("noBrowser")),
            requested_no_browser=requested_no_browser,
        ):
            continue
        return str(payload.get("commandId") or path.stem).strip() or path.stem
    return ""


def _joinable_close_command_id(command: dict[str, Any]) -> str:
    command_type = str(command.get("type") or "").strip()
    if command_type != "close_workbench":
        return ""
    manager_pid = load_pid()
    if not _process_is_alive(manager_pid):
        return ""
    state = load_state()
    if not isinstance(state, dict) or not _state_belongs_to_current_manager(state, manager_pid):
        return ""
    active = state.get("command") if isinstance(state.get("command"), dict) else {}
    active_command_id = str(active.get("activeCommandId") or "").strip()
    if active_command_id and str(active.get("activeType") or "").strip() == "close_workbench":
        return active_command_id
    for path in sorted(INBOX_DIR.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        if str(payload.get("type") or "").strip() != "close_workbench":
            continue
        return str(payload.get("commandId") or path.stem).strip() or path.stem
    return ""


def _joinable_force_close_command_id(command: dict[str, Any]) -> str:
    command_type = str(command.get("type") or "").strip()
    if command_type != "force_close_workbench":
        return ""
    manager_pid = load_pid()
    if not _process_is_alive(manager_pid):
        return ""
    state = load_state()
    if not isinstance(state, dict) or not _state_belongs_to_current_manager(state, manager_pid):
        return ""
    active = state.get("command") if isinstance(state.get("command"), dict) else {}
    active_command_id = str(active.get("activeCommandId") or "").strip()
    active_type = str(active.get("activeType") or "").strip()
    if active_command_id and active_type in {"close_workbench", "force_close_workbench"}:
        return active_command_id
    for path in sorted(INBOX_DIR.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        if str(payload.get("type") or "").strip() != "force_close_workbench":
            continue
        return str(payload.get("commandId") or path.stem).strip() or path.stem
    return ""


def _open_requests_are_compatible(*, existing_no_browser: bool, requested_no_browser: bool) -> bool:
    if existing_no_browser and not requested_no_browser:
        return False
    return True


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
    event_at = append_runtime_manager_file_event(
        event_type,
        payload,
        events_path=EVENTS_PATH,
        ensure_dirs=ensure_runtime_manager_dirs,
        suppress_io_errors=True,
    )
    record_runtime_manager_scene_event(event_type, payload, phase="queue", occurred_at=event_at)


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


def _complete_deferred_open_command(command: dict[str, Any], *, shutdown_state: dict[str, Any]) -> None:
    args = command.get("args") if isinstance(command.get("args"), dict) else {}
    intent = create_restart_intent(
        "workbench",
        reason=str(args.get("reason") or "reopen_after_close"),
        requested_by=str(command.get("requestedBy") or "unknown"),
        source_command_id=str(command.get("commandId") or ""),
        payload={
            "action": "reopen_after_close",
            "noBrowser": bool(args.get("noBrowser")),
            "stateVersion": int(shutdown_state.get("stateVersion") or 0),
        },
    )
    _append_queue_event(
        "command_queue.open_deferred_until_shutdown_complete",
        {
            "commandId": str(command.get("commandId") or ""),
            "intentId": str(intent.get("intentId") or ""),
            "requestedBy": str(command.get("requestedBy") or ""),
            "stateVersion": int(shutdown_state.get("stateVersion") or 0),
            "managerPid": int(shutdown_state.get("managerPid") or 0),
        },
    )
    result = {
        "commandId": str(command.get("commandId") or "").strip(),
        "accepted": True,
        "completed": True,
        "ok": True,
        "message": "Workbench reopen was queued until shutdown completes.",
        "stateVersion": int(shutdown_state.get("stateVersion") or 0),
        "runtimeManagerStopping": True,
        "deferredUntilShutdownComplete": True,
        "restartIntentId": str(intent.get("intentId") or ""),
    }
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
