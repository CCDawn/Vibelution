"""Persistent task broker for interactive CLI Agent terminal sessions."""

from __future__ import annotations

import hashlib
import json
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import cli_agent_protocols as protocols
from . import cli_agent_service


PROJECT_ROOT = cli_agent_service.PROJECT_ROOT
TASK_STATE_DIR = PROJECT_ROOT / ".runtime" / "cli_agents" / "tasks"
MAX_TASK_OUTPUT_CHARS = 180_000
WATCH_INTERVAL_SECONDS = 1.0

ACTIVE_STATUSES = {"queued", "sent", "running"}
TERMINAL_CLOSED_STATUSES = {"closed", "stopped", "exited", "stale"}

_TASK_LOCK = threading.RLock()
_WATCHER_STARTED = False


def submit_cli_agent_task(
    *,
    terminal_session: dict[str, Any],
    task: str,
    timeout_seconds: int,
    output_limit: int,
    source: str = "tool_call",
) -> dict[str, Any]:
    """Send one logical task to a persistent terminal, respecting adapter+cwd task locks."""

    normalized_task = str(task or "").strip()
    terminal_session_id = str(terminal_session.get("terminalSessionId") or "").strip()
    adapter_id = cli_agent_service._normalize_id(terminal_session.get("adapterId") or terminal_session.get("agentType") or "")
    if not terminal_session_id:
        return _error_result("MISSING_TERMINAL_SESSION", "CLI Agent terminal session id is missing.", adapter_id=adapter_id)
    if not normalized_task:
        return _error_result("MISSING_TASK", "cli_agent_run_tool requires a non-empty task.", adapter_id=adapter_id)

    _ensure_watcher_started()
    timeout = cli_agent_service._clamp_int(timeout_seconds, cli_agent_service.DEFAULT_TIMEOUT_SECONDS, 1, cli_agent_service.MAX_TIMEOUT_SECONDS)
    output_chars = cli_agent_service._clamp_int(output_limit, cli_agent_service.DEFAULT_OUTPUT_LIMIT, 1000, cli_agent_service.MAX_OUTPUT_LIMIT)
    now = _now_iso()
    with _TASK_LOCK:
        active = _active_task_for_terminal(terminal_session_id)
        if active:
            return _public_task_result(
                active,
                code="CLI_AGENT_TASK_LOCKED",
                message="同一 CLI Agent 终端已有任务在运行，请等待该任务完成或超时后再发送新任务。",
                terminal_session=terminal_session,
                output_limit=output_chars,
            )

        task_state = _initial_task_state(
            terminal_session=terminal_session,
            task=normalized_task,
            timeout_seconds=timeout,
            output_limit=output_chars,
            source=source,
            created_at=now,
        )
        _write_task_state(task_state)

    payload = protocols.task_input_for_adapter(
        adapter_id,
        normalized_task,
        completion_marker=str(task_state.get("completionMarker") or ""),
    )
    with _TASK_LOCK:
        task_state = _read_task_state(str(task_state.get("taskId") or "")) or task_state
        task_state["sentInput"] = payload
        _write_task_state(task_state)
    try:
        from . import cli_agent_terminal_service

        cli_agent_terminal_service.write_cli_agent_terminal_input(terminal_session_id, payload)
    except Exception as exc:
        with _TASK_LOCK:
            task_state = _read_task_state(str(task_state.get("taskId") or "")) or task_state
            task_state["status"] = "failed"
            task_state["code"] = "CLI_AGENT_TASK_SEND_FAILED"
            task_state["message"] = str(exc)
            task_state["completedAt"] = _now_iso()
            task_state["updatedAt"] = task_state["completedAt"]
            _write_task_state(task_state)
        _finalize_task_result(task_state, reason="send_failed")
        return _public_task_result(task_state, terminal_session=terminal_session, output_limit=output_chars)

    with _TASK_LOCK:
        task_state = _read_task_state(str(task_state.get("taskId") or "")) or task_state
        task_state["status"] = "sent"
        task_state["code"] = "CLI_AGENT_TASK_SENT"
        task_state["sentAt"] = _now_iso()
        task_state["updatedAt"] = task_state["sentAt"]
        _write_task_state(task_state)
    return _public_task_result(task_state, terminal_session=terminal_session, output_limit=output_chars)


def ingest_terminal_output(terminal_session: dict[str, Any], chunk: str) -> None:
    """Feed output chunks from a terminal runtime into the active task parser."""

    terminal_session_id = str(terminal_session.get("terminalSessionId") or "").strip()
    if not terminal_session_id or not str(chunk or ""):
        return
    finalized: dict[str, Any] | None = None
    with _TASK_LOCK:
        task_state = _active_task_for_terminal(terminal_session_id)
        if not task_state:
            return
        adapter_id = str(task_state.get("adapterId") or terminal_session.get("adapterId") or "").strip()
        task_state["status"] = "running"
        task_state["updatedAt"] = _now_iso()
        task_state["lastOutputAt"] = task_state["updatedAt"]
        task_state["output"] = _bounded_output(str(task_state.get("output") or "") + str(chunk or ""))
        _capture_terminal_screen(task_state, terminal_session)
        segments = protocols.split_semantic_segments(adapter_id, _task_parse_text(task_state))
        task_state["segments"] = segments[-50:]
        detected = protocols.detect_task_status(
            adapter_id,
            task_state["output"],
            completion_marker=str(task_state.get("completionMarker") or ""),
        )
        if detected:
            _complete_task_state(
                task_state,
                status=detected,
                code="CLI_AGENT_TASK_FAILED" if detected == "failed" else "CLI_AGENT_TASK_COMPLETED",
                reason="protocol_pattern",
            )
            finalized = dict(task_state)
        _write_task_state(task_state)
    if finalized:
        _finalize_task_result(finalized, reason="protocol_pattern")


def mark_terminal_closed(terminal_session: dict[str, Any], *, status: str = "exited") -> None:
    """Fail any active task attached to a terminal that closed before task completion."""

    terminal_session_id = str(terminal_session.get("terminalSessionId") or "").strip()
    if not terminal_session_id:
        return
    finalized: dict[str, Any] | None = None
    with _TASK_LOCK:
        task_state = _active_task_for_terminal(terminal_session_id)
        if not task_state:
            return
        _complete_task_state(
            task_state,
            status="failed",
            code="CLI_AGENT_TERMINAL_CLOSED",
            reason=str(status or "exited"),
        )
        _write_task_state(task_state)
        finalized = dict(task_state)
    _finalize_task_result(finalized, reason=str(status or "terminal_closed"))


def active_cli_agent_task_for_terminal(terminal_session_id: str) -> dict[str, Any]:
    with _TASK_LOCK:
        return _active_task_for_terminal(terminal_session_id)


def task_state_path(task_id: str) -> Path:
    return TASK_STATE_DIR / f"{_safe_filename(task_id)}.json"


def _ensure_watcher_started() -> None:
    global _WATCHER_STARTED
    with _TASK_LOCK:
        if _WATCHER_STARTED:
            return
        _WATCHER_STARTED = True
    thread = threading.Thread(target=_watch_active_tasks, name="cli-agent-task-watchdog", daemon=True)
    thread.start()


def _watch_active_tasks() -> None:
    while True:
        finalized: list[dict[str, Any]] = []
        with _TASK_LOCK:
            now = time.time()
            for task_state in _iter_task_states():
                if str(task_state.get("status") or "").strip().lower() not in ACTIVE_STATUSES:
                    continue
                status = _task_timeout_or_idle_status(task_state, now=now)
                if not status:
                    continue
                if status == "timeout":
                    _complete_task_state(
                        task_state,
                        status="timeout",
                        code="CLI_AGENT_TASK_TIMEOUT",
                        reason="timeout",
                    )
                else:
                    _complete_task_state(
                        task_state,
                        status="completed",
                        code="CLI_AGENT_TASK_COMPLETED",
                        reason="idle_completion",
                    )
                _write_task_state(task_state)
                finalized.append(dict(task_state))
        for task_state in finalized:
            _finalize_task_result(task_state, reason=str(task_state.get("completionReason") or "watchdog"))
        time.sleep(WATCH_INTERVAL_SECONDS)


def _task_timeout_or_idle_status(task_state: dict[str, Any], *, now: float) -> str:
    created_epoch = _parse_iso_epoch(str(task_state.get("createdAt") or ""))
    last_output_epoch = _parse_iso_epoch(str(task_state.get("lastOutputAt") or task_state.get("sentAt") or task_state.get("createdAt") or ""))
    timeout_seconds = cli_agent_service._clamp_int(
        task_state.get("timeoutSeconds"),
        cli_agent_service.DEFAULT_TIMEOUT_SECONDS,
        1,
        cli_agent_service.MAX_TIMEOUT_SECONDS,
    )
    if created_epoch is not None and now - created_epoch >= timeout_seconds:
        return "timeout"
    adapter_id = str(task_state.get("adapterId") or "").strip()
    protocol = protocols.protocol_for_adapter(adapter_id)
    if not str(task_state.get("output") or "").strip():
        return ""
    if protocol.marker_completion_required and not protocol.allow_idle_completion_with_marker:
        return ""
    if protocol.marker_completion_required and not _task_has_non_echo_output(task_state):
        return ""
    if created_epoch is not None and now - created_epoch < protocol.min_completion_seconds:
        return ""
    if last_output_epoch is not None and now - last_output_epoch >= protocol.idle_completion_seconds:
        return "completed"
    return ""


def _initial_task_state(
    *,
    terminal_session: dict[str, Any],
    task: str,
    timeout_seconds: int,
    output_limit: int,
    source: str,
    created_at: str,
) -> dict[str, Any]:
    adapter_id = cli_agent_service._normalize_id(terminal_session.get("adapterId") or terminal_session.get("agentType") or "")
    terminal_session_id = str(terminal_session.get("terminalSessionId") or "").strip()
    task_id = _stable_task_id(terminal_session_id=terminal_session_id, task=task, created_at=created_at)
    protocol = protocols.protocol_for_adapter(adapter_id)
    completion_marker = protocols.completion_marker_for_task(task_id) if protocol.marker_completion_required else ""
    return {
        "schemaVersion": 1,
        "taskId": task_id,
        "status": "queued",
        "code": "CLI_AGENT_TASK_QUEUED",
        "source": str(source or "tool_call").strip() or "tool_call",
        "adapterId": adapter_id,
        "label": str(terminal_session.get("label") or adapter_id or "CLI Agent").strip(),
        "terminalSessionId": terminal_session_id,
        "cliRunId": str(terminal_session.get("cliRunId") or "").strip(),
        "lockKey": str(terminal_session.get("lockKey") or "").strip(),
        "sourceSessionId": str(terminal_session.get("sourceSessionId") or "").strip(),
        "sourceMessageId": str(terminal_session.get("sourceMessageId") or "").strip(),
        "sourceRunId": str(terminal_session.get("sourceRunId") or "").strip(),
        "cliSessionId": str(terminal_session.get("cliSessionId") or "").strip(),
        "cwd": str(terminal_session.get("cwd") or "").strip(),
        "mode": str(terminal_session.get("mode") or "readonly").strip() or "readonly",
        "task": task,
        "taskHash": cli_agent_service._task_hash(task),
        "taskPreview": cli_agent_service._clip(task, 500),
        "completionMarker": completion_marker,
        "screenTextBaseline": str(terminal_session.get("screenText") or "").strip(),
        "screenText": "",
        "screenTextDelta": "",
        "timeoutSeconds": timeout_seconds,
        "outputLimit": output_limit,
        "output": "",
        "segments": [],
        "createdAt": created_at,
        "updatedAt": created_at,
    }


def _complete_task_state(task_state: dict[str, Any], *, status: str, code: str, reason: str) -> None:
    now = _now_iso()
    task_state["status"] = status
    task_state["code"] = code
    task_state["completionReason"] = reason
    task_state["completedAt"] = now
    task_state["updatedAt"] = now
    adapter_id = str(task_state.get("adapterId") or "").strip()
    segments = protocols.tail_semantic_segments(adapter_id, _task_parse_text(task_state))
    task_state["resultSegments"] = segments
    task_state["resultSummary"] = protocols.summarize_segments(segments)


def _finalize_task_result(task_state: dict[str, Any], *, reason: str) -> None:
    session_id = str(task_state.get("sourceSessionId") or "").strip()
    cli_agent_service._record_event(
        "cli_agent.task.result_ready",
        outcome=str(task_state.get("status") or "completed").strip() or "completed",
        fields={
            "taskId": str(task_state.get("taskId") or ""),
            "terminalSessionId": str(task_state.get("terminalSessionId") or ""),
            "adapterId": str(task_state.get("adapterId") or ""),
            "completionReason": str(task_state.get("completionReason") or reason or ""),
            "resultSegmentCount": len(list(task_state.get("resultSegments") or [])),
        },
    )
    if not session_id:
        return
    try:
        from . import session_service

        session_service.append_cli_agent_task_result_event(
            session_id,
            task_result=_public_task_result(task_state, output_limit=int(task_state.get("outputLimit") or cli_agent_service.DEFAULT_OUTPUT_LIMIT)),
            wake_agent=True,
            wake_reason=reason,
        )
    except Exception as exc:
        cli_agent_service._record_event(
            "cli_agent.task.result_delivery_failed",
            outcome="failed",
            fields={
                "taskId": str(task_state.get("taskId") or ""),
                "terminalSessionId": str(task_state.get("terminalSessionId") or ""),
                "adapterId": str(task_state.get("adapterId") or ""),
                "errorType": type(exc).__name__,
            },
        )


def _public_task_result(
    task_state: dict[str, Any],
    *,
    code: str = "",
    message: str = "",
    terminal_session: dict[str, Any] | None = None,
    output_limit: int | None = None,
) -> dict[str, Any]:
    terminal = dict(terminal_session or {}) if isinstance(terminal_session, dict) else {}
    limit = int(output_limit or task_state.get("outputLimit") or cli_agent_service.DEFAULT_OUTPUT_LIMIT)
    adapter_id = str(task_state.get("adapterId") or terminal.get("adapterId") or "").strip()
    segments = list(task_state.get("resultSegments") or task_state.get("segments") or [])
    parse_text = _task_parse_text(task_state)
    if not task_state.get("resultSegments"):
        segments = protocols.tail_semantic_segments(adapter_id, parse_text, limit=protocols.protocol_for_adapter(adapter_id).max_tail_segments)
    stdout_preview = protocols.summarize_segments(segments) or protocols.remove_protocol_markers(protocols.strip_terminal_controls(parse_text))
    result_source = _task_result_source(task_state)
    public_status = _semantic_task_status(str(task_state.get("status") or "").strip(), code or str(task_state.get("code") or "").strip())
    result = {
        "status": public_status,
        "semanticStatus": public_status,
        "internalStatus": str(task_state.get("status") or "").strip() or "unknown",
        "code": code or str(task_state.get("code") or "").strip() or "CLI_AGENT_TASK",
        "message": message or str(task_state.get("message") or "").strip(),
        "taskId": str(task_state.get("taskId") or "").strip(),
        "agentType": adapter_id,
        "adapterId": adapter_id,
        "label": str(task_state.get("label") or terminal.get("label") or adapter_id or "CLI Agent").strip(),
        "mode": str(task_state.get("mode") or terminal.get("mode") or "readonly").strip() or "readonly",
        "cwd": str(task_state.get("cwd") or terminal.get("cwd") or "").strip(),
        "taskHash": str(task_state.get("taskHash") or "").strip(),
        "taskPreview": str(task_state.get("taskPreview") or "").strip(),
        "timeoutSeconds": task_state.get("timeoutSeconds"),
        "terminalSessionId": str(task_state.get("terminalSessionId") or terminal.get("terminalSessionId") or "").strip(),
        "cliRunId": str(task_state.get("cliRunId") or terminal.get("cliRunId") or "").strip(),
        "lockKey": str(task_state.get("lockKey") or terminal.get("lockKey") or "").strip(),
        "cliSessionId": str(task_state.get("cliSessionId") or terminal.get("cliSessionId") or "").strip(),
        "sourceSessionId": str(task_state.get("sourceSessionId") or terminal.get("sourceSessionId") or "").strip(),
        "sourceMessageId": str(task_state.get("sourceMessageId") or terminal.get("sourceMessageId") or "").strip(),
        "sourceRunId": str(task_state.get("sourceRunId") or terminal.get("sourceRunId") or "").strip(),
        "createdAt": str(task_state.get("createdAt") or "").strip(),
        "sentAt": str(task_state.get("sentAt") or "").strip(),
        "completedAt": str(task_state.get("completedAt") or "").strip(),
        "completionReason": str(task_state.get("completionReason") or "").strip(),
        "terminalAlive": bool(terminal.get("alive")),
        "terminalStatus": str(terminal.get("status") or "").strip(),
        "terminalReuse": bool(terminal.get("reusedActiveLock")),
        "resultSegments": segments,
        "resultSource": result_source,
        "parserConfidence": _parser_confidence(task_state, result_source),
        "stdoutPreview": cli_agent_service._clip(stdout_preview, limit),
        "stderrPreview": "",
        "exitCode": None,
        "timedOut": str(task_state.get("status") or "").strip().lower() == "timeout",
        "logPath": _relative_to_project(task_state_path(str(task_state.get("taskId") or ""))),
    }
    return result


def _capture_terminal_screen(task_state: dict[str, Any], terminal_session: dict[str, Any]) -> None:
    screen_text = str(terminal_session.get("screenText") or "").strip()
    if not screen_text:
        return
    baseline = str(task_state.get("screenTextBaseline") or "").strip()
    delta = _screen_delta_text(screen_text, baseline)
    task_state["screenText"] = screen_text
    task_state["screenTextDelta"] = delta
    task_state["screenQuality"] = str(terminal_session.get("screenQuality") or "").strip()


def _task_parse_text(task_state: dict[str, Any]) -> str:
    for key in ("output", "screenTextDelta", "screenText"):
        raw_value = str(task_state.get(key) or "")
        value = protocols.remove_protocol_markers(protocols.strip_terminal_controls(raw_value)).strip()
        if value:
            return raw_value
    return ""


def _task_result_source(task_state: dict[str, Any]) -> str:
    if protocols.remove_protocol_markers(protocols.strip_terminal_controls(str(task_state.get("output") or ""))).strip():
        return "terminal_output"
    if str(task_state.get("screenTextDelta") or "").strip():
        return "screen_delta"
    if str(task_state.get("screenText") or "").strip():
        return "screen_buffer"
    return "terminal_output"


def _task_has_non_echo_output(task_state: dict[str, Any]) -> bool:
    output = _normalize_echo_comparison_text(str(task_state.get("output") or ""))
    if not output:
        return False
    sent_input = _normalize_echo_comparison_text(str(task_state.get("sentInput") or ""))
    if sent_input and (output == sent_input or output in sent_input):
        return False
    task = _normalize_echo_comparison_text(str(task_state.get("task") or ""))
    if task and output == task:
        return False
    return True


def _normalize_echo_comparison_text(text: str) -> str:
    cleaned = protocols.remove_protocol_markers(protocols.strip_terminal_controls(str(text or "")))
    return " ".join(cleaned.split()).strip()


def _semantic_task_status(status: str, code: str) -> str:
    normalized = str(status or "").strip().lower()
    normalized_code = str(code or "").strip()
    if normalized_code == "CLI_AGENT_TASK_LOCKED":
        return "task_locked"
    if normalized in {"queued", "sent"}:
        return "task_sent"
    if normalized in {"completed", "failed", "timeout", "running", "error"}:
        return normalized
    return normalized or "unknown"


def _parser_confidence(task_state: dict[str, Any], result_source: str) -> str:
    reason = str(task_state.get("completionReason") or "").strip()
    if reason == "protocol_pattern":
        return "high"
    if result_source == "terminal_output":
        return "medium"
    if result_source.startswith("screen"):
        return "low"
    return "medium"


def _screen_delta_text(current: str, baseline: str) -> str:
    current_text = str(current or "").strip()
    baseline_text = str(baseline or "").strip()
    if not current_text or not baseline_text:
        return current_text
    if current_text.startswith(baseline_text):
        return current_text[len(baseline_text):].strip()
    current_lines = current_text.splitlines()
    baseline_lines = baseline_text.splitlines()
    index = 0
    max_common = min(len(current_lines), len(baseline_lines))
    while index < max_common and current_lines[index].strip() == baseline_lines[index].strip():
        index += 1
    delta = "\n".join(current_lines[index:]).strip()
    return delta or current_text


def _active_task_for_terminal(terminal_session_id: str) -> dict[str, Any]:
    normalized = str(terminal_session_id or "").strip()
    if not normalized:
        return {}
    candidates = [
        task
        for task in _iter_task_states()
        if str(task.get("terminalSessionId") or "").strip() == normalized
        and str(task.get("status") or "").strip().lower() in ACTIVE_STATUSES
    ]
    if not candidates:
        return {}
    candidates.sort(
        key=lambda item: _parse_iso_epoch(str(item.get("updatedAt") or item.get("createdAt") or "")) or 0.0,
        reverse=True,
    )
    return dict(candidates[0])


def _iter_task_states() -> list[dict[str, Any]]:
    if not TASK_STATE_DIR.exists():
        return []
    result: list[dict[str, Any]] = []
    for path in TASK_STATE_DIR.glob("*.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(payload, dict):
            result.append(payload)
    return result


def _read_task_state(task_id: str) -> dict[str, Any]:
    path = task_state_path(task_id)
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_task_state(task_state: dict[str, Any]) -> None:
    task_id = str(task_state.get("taskId") or "").strip()
    if not task_id:
        return
    path = task_state_path(task_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(task_state, ensure_ascii=False, indent=2), encoding="utf-8")


def _bounded_output(text: str) -> str:
    value = str(text or "")
    if len(value) <= MAX_TASK_OUTPUT_CHARS:
        return value
    return value[-MAX_TASK_OUTPUT_CHARS:]


def _stable_task_id(*, terminal_session_id: str, task: str, created_at: str) -> str:
    basis = "\n".join([str(terminal_session_id or ""), cli_agent_service._task_hash(task), str(created_at or ""), uuid.uuid4().hex[:8]])
    return f"cli-task-{hashlib.sha256(basis.encode('utf-8', errors='replace')).hexdigest()[:16]}"


def _error_result(code: str, message: str, *, adapter_id: str = "") -> dict[str, Any]:
    return {
        "status": "error",
        "semanticStatus": "error",
        "internalStatus": "error",
        "code": code,
        "message": message,
        "agentType": adapter_id,
        "adapterId": adapter_id,
    }


def _parse_iso_epoch(value: str) -> float | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_filename(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "_" for ch in str(value or ""))[:120] or "task"


def _relative_to_project(path: Path) -> str:
    try:
        return path.resolve().relative_to(Path(PROJECT_ROOT).resolve()).as_posix()
    except ValueError:
        return str(path)
