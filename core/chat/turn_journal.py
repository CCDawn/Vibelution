"""Durable append-only journal for web chat turns."""

from __future__ import annotations

import json
import re
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable
from uuid import uuid4

from core.infrastructure import developer_sandbox

from .model_messages import normalize_model_messages


SCHEMA_VERSION = 2

EVENT_TURN_STARTED = "turn_started"
EVENT_USER_MESSAGE = "user_message"
EVENT_TURN_CONTEXT = "turn_context"
EVENT_ASSISTANT_PARTIAL = "assistant_partial"
EVENT_ASSISTANT_DELTA_COMMITTED = "assistant_delta_committed"
EVENT_ASSISTANT_MESSAGE = "assistant_message"
EVENT_TOOL_CALL_STARTED = "tool_call_started"
EVENT_TOOL_RESULT = "tool_result"
EVENT_CLI_TASK_SENT = "cli_task_sent"
EVENT_CLI_TASK_RESULT = "cli_task_result"
EVENT_CLI_SESSION_LIFECYCLE = "cli_session_lifecycle"
EVENT_TURN_COMPLETED = "turn_completed"
EVENT_TURN_FAILED = "turn_failed"
EVENT_TURN_INTERRUPTED = "turn_interrupted"
EVENT_COMPACTION_CHECKPOINT = "compaction_checkpoint"

TERMINAL_EVENTS = {
    EVENT_TURN_COMPLETED,
    EVENT_TURN_FAILED,
    EVENT_TURN_INTERRUPTED,
}

MODEL_VISIBLE_EVENT_TYPES = {
    EVENT_USER_MESSAGE,
    EVENT_ASSISTANT_PARTIAL,
    EVENT_ASSISTANT_DELTA_COMMITTED,
    EVENT_ASSISTANT_MESSAGE,
    EVENT_TOOL_CALL_STARTED,
    EVENT_TOOL_RESULT,
    EVENT_CLI_TASK_SENT,
    EVENT_CLI_TASK_RESULT,
    EVENT_CLI_SESSION_LIFECYCLE,
    EVENT_TURN_INTERRUPTED,
    EVENT_COMPACTION_CHECKPOINT,
}

VOLATILE_MODEL_EVENT_TYPES = {
    EVENT_ASSISTANT_PARTIAL,
    EVENT_ASSISTANT_DELTA_COMMITTED,
}

AUDIT_ONLY_EVENT_TYPES = {
    EVENT_TURN_STARTED,
    EVENT_TURN_CONTEXT,
    EVENT_TURN_COMPLETED,
    EVENT_TURN_FAILED,
}

TURN_INTERRUPTED_MARKER = (
    "<turn_interrupted>\n"
    "上一轮在完成前中断。已产生的助手内容、工具结果和 CLI 结果已经保留在上文；"
    "继续时应基于这些内容衔接，不要重复已经完成的工具调用。\n"
    "</turn_interrupted>"
)

_SAFE_SESSION_CHARS = re.compile(r"[^A-Za-z0-9_.-]+")
_SEQUENCE_CACHE_LOCK = threading.Lock()
_SEQUENCE_CACHE: dict[str, tuple[int, int, int]] = {}


@dataclass(frozen=True)
class TurnJournalEvent:
    schema_version: int
    event_id: str
    session_id: str
    turn_id: str
    sequence: int
    event_type: str
    status: str
    timestamp: str
    source: str
    payload: dict[str, Any]
    parent_event_id: str = ""
    visible_in_model: bool = True
    projection_kind: str = ""
    provider_role: str = ""
    tool_call_id: str = ""
    correlation_id: str = ""
    source_kind: str = ""

    @classmethod
    def from_dict(cls, value: Any) -> "TurnJournalEvent | None":
        if not isinstance(value, dict):
            return None
        event_type = str(value.get("eventType") or value.get("event_type") or "").strip()
        if not event_type:
            return None
        payload = value.get("payload")
        if not isinstance(payload, dict):
            payload = {}
        return cls(
            schema_version=_coerce_positive_int(value.get("schemaVersion") or value.get("schema_version"), SCHEMA_VERSION),
            event_id=str(value.get("eventId") or value.get("event_id") or uuid4()).strip(),
            session_id=str(value.get("sessionId") or value.get("session_id") or "").strip(),
            turn_id=str(value.get("turnId") or value.get("turn_id") or "").strip(),
            sequence=_coerce_positive_int(value.get("sequence"), 0),
            event_type=event_type,
            status=str(value.get("status") or "").strip(),
            timestamp=str(value.get("timestamp") or "").strip(),
            source=str(value.get("source") or "").strip(),
            payload=dict(payload),
            parent_event_id=str(value.get("parentEventId") or value.get("parent_event_id") or "").strip(),
            visible_in_model=_coerce_bool(value.get("visibleInModel", value.get("visible_in_model", True)), True),
            projection_kind=str(value.get("projectionKind") or value.get("projection_kind") or "").strip(),
            provider_role=str(value.get("providerRole") or value.get("provider_role") or "").strip(),
            tool_call_id=str(value.get("toolCallId") or value.get("tool_call_id") or "").strip(),
            correlation_id=str(value.get("correlationId") or value.get("correlation_id") or "").strip(),
            source_kind=str(value.get("sourceKind") or value.get("source_kind") or "").strip(),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": self.schema_version,
            "eventId": self.event_id,
            "sessionId": self.session_id,
            "turnId": self.turn_id,
            "sequence": self.sequence,
            "eventType": self.event_type,
            "status": self.status,
            "timestamp": self.timestamp,
            "source": self.source,
            "payload": dict(self.payload),
            "parentEventId": self.parent_event_id,
            "visibleInModel": self.visible_in_model,
            "projectionKind": self.projection_kind,
            "providerRole": self.provider_role,
            "toolCallId": self.tool_call_id,
            "correlationId": self.correlation_id,
            "sourceKind": self.source_kind,
        }


def turn_journal_path(project_root: Path, session_id: str) -> Path:
    token = _safe_session_workspace_token(session_id)
    return developer_sandbox.sandboxed_workspace_path(
        Path(project_root),
        "sessions",
        token,
        "turn_journal.jsonl",
    )


def append_turn_event(
    project_root: Path,
    session_id: str,
    turn_id: str,
    event_type: str,
    *,
    status: str = "",
    payload: dict[str, Any] | None = None,
    source: str = "",
    timestamp: str = "",
    parent_event_id: str = "",
    visible_in_model: bool = True,
    projection_kind: str = "",
    provider_role: str = "",
    tool_call_id: str = "",
    correlation_id: str = "",
    source_kind: str = "",
) -> TurnJournalEvent:
    path = turn_journal_path(project_root, session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with _SEQUENCE_CACHE_LOCK:
        sequence = _next_sequence(path)
        event = TurnJournalEvent(
            schema_version=SCHEMA_VERSION,
            event_id=f"{_safe_event_token(turn_id or session_id)}-{sequence:06d}-{uuid4().hex[:8]}",
            session_id=str(session_id or "").strip(),
            turn_id=str(turn_id or "").strip(),
            sequence=sequence,
            event_type=str(event_type or "").strip(),
            status=str(status or "").strip(),
            timestamp=str(timestamp or "").strip() or _now_timestamp(),
            source=str(source or "").strip(),
            payload=dict(payload or {}),
            parent_event_id=str(parent_event_id or "").strip(),
            visible_in_model=bool(visible_in_model),
            projection_kind=str(projection_kind or "").strip(),
            provider_role=str(provider_role or "").strip(),
            tool_call_id=str(tool_call_id or "").strip(),
            correlation_id=str(correlation_id or "").strip(),
            source_kind=str(source_kind or "").strip(),
        )
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event.to_dict(), ensure_ascii=False, separators=(",", ":")))
            handle.write("\n")
        _remember_sequence(path, sequence)
    return event


def load_turn_events(project_root: Path, session_id: str) -> list[TurnJournalEvent]:
    path = turn_journal_path(project_root, session_id)
    if not path.exists():
        return []
    events: list[TurnJournalEvent] = []
    try:
        with path.open(encoding="utf-8") as handle:
            lines = handle
            for line in lines:
                raw = line.strip()
                if not raw:
                    continue
                try:
                    parsed = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                event = TurnJournalEvent.from_dict(parsed)
                if event is not None:
                    events.append(event)
    except OSError:
        return []
    events.sort(key=lambda item: (item.sequence, item.timestamp, item.event_id))
    return events


def latest_open_turn_id(events: Iterable[TurnJournalEvent]) -> str:
    event_list = list(events or [])
    terminal_turn_ids = {
        event.turn_id
        for event in event_list
        if event.turn_id and event.event_type in TERMINAL_EVENTS
    }
    for event in reversed(event_list):
        if event.turn_id and event.event_type == EVENT_TURN_STARTED and event.turn_id not in terminal_turn_ids:
            return event.turn_id
    return ""


def event_projection_category(event_type: str) -> str:
    normalized = str(event_type or "").strip()
    if normalized in VOLATILE_MODEL_EVENT_TYPES:
        return "volatile_model"
    if normalized in MODEL_VISIBLE_EVENT_TYPES:
        return "model"
    if normalized in AUDIT_ONLY_EVENT_TYPES:
        return "audit"
    return "unknown"


def event_has_model_projection(event: TurnJournalEvent | str) -> bool:
    if isinstance(event, TurnJournalEvent):
        if not event.visible_in_model:
            return False
        event_type = event.event_type
    else:
        event_type = str(event or "").strip()
    return event_projection_category(event_type) in {"model", "volatile_model"}


def append_interrupted_if_open(
    project_root: Path,
    session_id: str,
    *,
    active_turn_id: str = "",
    reason: str = "process_restarted",
    source: str = "turn_journal_reconcile",
) -> TurnJournalEvent | None:
    events = load_turn_events(project_root, session_id)
    turn_id = latest_open_turn_id(events)
    if not turn_id:
        return None
    if active_turn_id and turn_id == active_turn_id:
        return None
    return append_turn_event(
        project_root,
        session_id,
        turn_id,
        EVENT_TURN_INTERRUPTED,
        status="interrupted",
        payload={
            "reason": str(reason or "process_restarted").strip() or "process_restarted",
            "marker": TURN_INTERRUPTED_MARKER,
        },
        source=source,
    )


def model_visible_messages_from_events(events: Iterable[TurnJournalEvent]) -> list[dict[str, Any]]:
    event_list = list(events or [])
    messages: list[dict[str, Any]] = []
    latest_partial_by_turn: dict[str, dict[str, Any]] = {}
    final_turn_ids: set[str] = set()
    terminal_turn_ids: set[str] = set()
    resolved_tool_keys = {
        key
        for event in event_list
        if event.visible_in_model and event.event_type in {EVENT_TOOL_RESULT, EVENT_CLI_TASK_RESULT}
        for key in [_event_tool_correlation_key(event)]
        if key
    }

    for event in event_list:
        if not event.visible_in_model:
            continue
        if not event_has_model_projection(event) and event.event_type not in TERMINAL_EVENTS:
            continue
        turn_id = str(event.turn_id or "").strip()
        payload = dict(event.payload or {})
        if event.event_type == EVENT_USER_MESSAGE:
            content = str(payload.get("content") or "").strip()
            if content or payload.get("attachments"):
                messages.append(
                    {
                        "role": "user",
                        "content": content,
                        "attachments": list(payload.get("attachments") or []),
                        "metadata": {
                            "kind": "journal_user_message",
                            "turnId": turn_id,
                            "eventId": event.event_id,
                        },
                    }
                )
        elif event.event_type in {EVENT_ASSISTANT_PARTIAL, EVENT_ASSISTANT_DELTA_COMMITTED}:
            partial = _assistant_message_from_payload(
                payload,
                kind="journal_assistant_partial",
                turn_id=turn_id,
                event_id=event.event_id,
                interrupted=False,
            )
            if _message_has_visible_payload(partial):
                latest_partial_by_turn[turn_id] = partial
        elif event.event_type == EVENT_ASSISTANT_MESSAGE:
            message = _assistant_message_from_payload(
                payload,
                kind="journal_assistant_message",
                turn_id=turn_id,
                event_id=event.event_id,
                interrupted=False,
            )
            if _message_has_visible_payload(message):
                messages.append(message)
                final_turn_ids.add(turn_id)
        elif event.event_type == EVENT_COMPACTION_CHECKPOINT:
            checkpoint_message = _checkpoint_message_from_event(event)
            if _message_has_visible_payload(checkpoint_message):
                messages.append(checkpoint_message)
        elif event.event_type == EVENT_TOOL_CALL_STARTED:
            if _event_tool_correlation_key(event) in resolved_tool_keys:
                continue
            tool_message = _tool_message_from_event(event)
            if _message_has_visible_payload(tool_message):
                messages.append(tool_message)
        elif event.event_type in {EVENT_TOOL_RESULT, EVENT_CLI_TASK_SENT, EVENT_CLI_TASK_RESULT}:
            tool_message = _tool_message_from_event(event)
            if _message_has_visible_payload(tool_message):
                messages.append(tool_message)
        elif event.event_type == EVENT_CLI_SESSION_LIFECYCLE:
            lifecycle_message = _lifecycle_message_from_event(event)
            if _message_has_visible_payload(lifecycle_message):
                messages.append(lifecycle_message)
        elif event.event_type in TERMINAL_EVENTS:
            terminal_turn_ids.add(turn_id)
            if event.event_type == EVENT_TURN_INTERRUPTED:
                partial = latest_partial_by_turn.get(turn_id)
                if partial is not None and turn_id not in final_turn_ids:
                    partial = dict(partial)
                    metadata = dict(partial.get("metadata") or {})
                    metadata["interrupted"] = True
                    partial["metadata"] = metadata
                    messages.append(partial)
                messages.append(
                    {
                        "role": "system",
                        "content": str(payload.get("marker") or TURN_INTERRUPTED_MARKER),
                        "metadata": {
                            "kind": "turn_interrupted",
                            "turnId": turn_id,
                            "eventId": event.event_id,
                            "reason": str(payload.get("reason") or "").strip(),
                        },
                    }
                )

    for turn_id, partial in latest_partial_by_turn.items():
        if turn_id and turn_id not in final_turn_ids and turn_id not in terminal_turn_ids:
            partial = dict(partial)
            metadata = dict(partial.get("metadata") or {})
            metadata["interrupted"] = True
            partial["metadata"] = metadata
            messages.append(partial)
            messages.append(
                {
                    "role": "system",
                    "content": TURN_INTERRUPTED_MARKER,
                    "metadata": {
                        "kind": "turn_interrupted",
                        "turnId": turn_id,
                        "reason": "open_turn_replay",
                    },
                }
            )
    return _dedupe_adjacent_messages(messages)
def model_messages_from_events(events: Iterable[TurnJournalEvent]) -> list[dict[str, Any]]:
    """Replay journal events into canonical LLM-facing messages.

    The legacy visible replay keeps UI-era ``toolCalls`` bundles. This model
    replay splits assistant tool calls from tool results so provider payloads
    have a single, protocol-valid source.
    """

    return normalize_model_messages(model_visible_messages_from_events(events))


def _assistant_message_from_payload(
    payload: dict[str, Any],
    *,
    kind: str,
    turn_id: str,
    event_id: str,
    interrupted: bool,
) -> dict[str, Any]:
    message: dict[str, Any] = {
        "role": "assistant",
        "content": str(payload.get("content") or "").strip(),
        "metadata": {
            "kind": kind,
            "turnId": turn_id,
            "eventId": event_id,
            "interrupted": interrupted,
        },
    }
    thought = str(payload.get("thought") or "").strip()
    if thought:
        message["thought"] = thought
    tool_calls = _normalize_tool_payload(payload.get("toolCalls") or payload.get("tool_calls") or [])
    if tool_calls:
        message["toolCalls"] = tool_calls
    feedback_events = [dict(item) for item in list(payload.get("feedbackEvents") or payload.get("feedback_events") or []) if isinstance(item, dict)]
    if feedback_events:
        message["feedbackEvents"] = feedback_events
    return message


def _tool_message_from_event(event: TurnJournalEvent) -> dict[str, Any]:
    payload = dict(event.payload or {})
    tool_call = dict(payload.get("toolCall") or payload.get("tool_call") or payload)
    if event.event_type in {EVENT_CLI_TASK_SENT, EVENT_CLI_TASK_RESULT} and "name" not in tool_call:
        tool_call["name"] = "cli_agent_run_tool"
    name = str(tool_call.get("name") or tool_call.get("toolName") or tool_call.get("tool_name") or "").strip()
    if not name:
        return {}
    status = str(event.status or tool_call.get("status") or "").strip()
    normalized = {"name": name, "status": status or "running"}
    tool_call_id = _event_tool_call_id(event)
    if tool_call_id:
        normalized["id"] = tool_call_id
        normalized["toolCallId"] = tool_call_id
    for key in (
        "id",
        "tool_call_id",
        "toolCallId",
        "arguments",
        "args",
        "summary",
        "result",
        "resultPreview",
        "result_preview",
        "error",
        "durationMs",
        "duration_ms",
        "timeoutSeconds",
        "timeout_seconds",
        "resultSegments",
        "resultSource",
        "parserConfidence",
        "stdoutPreview",
        "stderrPreview",
        "terminalSessionId",
        "cliRunId",
        "cliSessionId",
        "taskId",
        "completionReason",
    ):
        if key in tool_call:
            normalized[key] = tool_call[key]
    if event.event_type == EVENT_TOOL_CALL_STARTED and "result" not in normalized and "error" not in normalized:
        normalized["result"] = "工具调用已开始，但该轮在返回结果前中断。"
        normalized["status"] = "interrupted"
    return {
        "role": "assistant",
        "content": "",
        "toolCalls": [normalized],
        "metadata": {
            "kind": event.event_type,
            "turnId": event.turn_id,
            "eventId": event.event_id,
        },
    }


def _checkpoint_message_from_event(event: TurnJournalEvent) -> dict[str, Any]:
    payload = dict(event.payload or {})
    summary = str(payload.get("summary") or payload.get("content") or "").strip()
    if not summary:
        return {}
    return {
        "role": "assistant",
        "content": f"历史检查点：\n{summary}",
        "metadata": {
            "kind": EVENT_COMPACTION_CHECKPOINT,
            "turnId": event.turn_id,
            "eventId": event.event_id,
        },
    }


def _lifecycle_message_from_event(event: TurnJournalEvent) -> dict[str, Any]:
    payload = dict(event.payload or {})
    lifecycle = dict(payload.get("lifecycle") or payload)
    event_name = str(lifecycle.get("event") or lifecycle.get("status") or event.status or "").strip().lower()
    if event_name not in {"closed", "failed", "timeout", "resumed", "linked", "session_linked"}:
        return {}
    label = str(lifecycle.get("label") or lifecycle.get("adapterId") or "CLI Agent").strip()
    if event_name in {"linked", "session_linked"}:
        content = f"{label} 已连接 CLI 会话。"
    elif event_name == "resumed":
        content = f"{label} 已恢复 CLI 会话。"
    elif event_name == "timeout":
        content = f"{label} CLI 会话已超时。"
    elif event_name == "failed":
        content = f"{label} CLI 会话失败。"
    else:
        content = f"{label} 已关闭。"
    return {
        "role": "assistant",
        "content": content,
        "metadata": {
            "kind": EVENT_CLI_SESSION_LIFECYCLE,
            "turnId": event.turn_id,
            "eventId": event.event_id,
            "event": event_name,
            "terminalSessionId": str(lifecycle.get("terminalSessionId") or "").strip(),
            "cliRunId": str(lifecycle.get("cliRunId") or "").strip(),
            "adapterId": str(lifecycle.get("adapterId") or "").strip(),
            "cwd": str(lifecycle.get("cwd") or "").strip(),
            "mode": str(lifecycle.get("mode") or "").strip(),
        },
    }


def _event_tool_call_id(event: TurnJournalEvent) -> str:
    if event.tool_call_id:
        return event.tool_call_id
    payload = dict(event.payload or {})
    tool_call = dict(payload.get("toolCall") or payload.get("tool_call") or payload)
    return str(
        tool_call.get("id")
        or tool_call.get("toolCallId")
        or tool_call.get("tool_call_id")
        or tool_call.get("taskId")
        or ""
    ).strip()


def _event_tool_correlation_key(event: TurnJournalEvent) -> str:
    tool_call_id = _event_tool_call_id(event)
    if tool_call_id:
        return f"id:{tool_call_id}"
    payload = dict(event.payload or {})
    tool_call = dict(payload.get("toolCall") or payload.get("tool_call") or payload)
    name = str(tool_call.get("name") or tool_call.get("toolName") or tool_call.get("tool_name") or "").strip()
    if not name:
        return ""
    return f"turn:{event.turn_id}:{name}"


def _normalize_tool_payload(value: Any) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for item in list(value or []):
        if isinstance(item, dict):
            normalized.append(dict(item))
    return normalized


def _message_has_visible_payload(message: dict[str, Any]) -> bool:
    return bool(
        str(message.get("content") or "").strip()
        or str(message.get("thought") or "").strip()
        or list(message.get("toolCalls") or message.get("tool_calls") or [])
    )


def _dedupe_adjacent_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    previous_key = None
    for message in messages:
        metadata = message.get("metadata") if isinstance(message.get("metadata"), dict) else {}
        key = (
            str(message.get("role") or ""),
            str(message.get("content") or ""),
            str(metadata.get("kind") or ""),
            str(metadata.get("turnId") or ""),
            json.dumps(message.get("toolCalls") or message.get("tool_calls") or [], ensure_ascii=False, sort_keys=True),
        )
        if key == previous_key:
            continue
        deduped.append(message)
        previous_key = key
    return deduped


def _next_sequence(path: Path) -> int:
    return _latest_sequence(path) + 1


def latest_turn_sequence(project_root: Path, session_id: str) -> int:
    path = turn_journal_path(project_root, session_id)
    with _SEQUENCE_CACHE_LOCK:
        return _latest_sequence(path)


def _latest_sequence(path: Path) -> int:
    if not path.exists():
        _SEQUENCE_CACHE.pop(_sequence_cache_key(path), None)
        return 0
    key = _sequence_cache_key(path)
    mtime_ns, size = _sequence_file_signature(path)
    cached = _SEQUENCE_CACHE.get(key)
    if cached is not None and cached[1] == mtime_ns and cached[2] == size:
        return cached[0]
    last_sequence = _latest_sequence_from_tail(path)
    if last_sequence <= 0:
        last_sequence = _latest_sequence_from_scan(path)
    _SEQUENCE_CACHE[key] = (last_sequence, mtime_ns, size)
    return last_sequence


def _latest_sequence_from_tail(path: Path) -> int:
    chunk_size = 8192
    buffer = b""
    try:
        with path.open("rb") as handle:
            handle.seek(0, 2)
            position = handle.tell()
            while position > 0:
                read_size = min(chunk_size, position)
                position -= read_size
                handle.seek(position)
                buffer = handle.read(read_size) + buffer
                lines = buffer.splitlines()
                if not lines:
                    continue
                candidates = lines if position == 0 else lines[1:]
                for raw_line in reversed(candidates):
                    raw = raw_line.strip()
                    if not raw:
                        continue
                    try:
                        parsed = json.loads(raw.decode("utf-8"))
                    except (UnicodeDecodeError, json.JSONDecodeError):
                        continue
                    sequence = _coerce_positive_int(parsed.get("sequence"), 0) if isinstance(parsed, dict) else 0
                    if sequence > 0:
                        return sequence
    except OSError:
        return 0
    return 0


def _latest_sequence_from_scan(path: Path) -> int:
    last_sequence = 0
    try:
        with path.open(encoding="utf-8") as handle:
            lines = handle
            for line in lines:
                try:
                    raw = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(raw, dict):
                    last_sequence = max(last_sequence, _coerce_positive_int(raw.get("sequence"), 0))
    except OSError:
        return 0
    return last_sequence


def _remember_sequence(path: Path, sequence: int) -> None:
    mtime_ns, size = _sequence_file_signature(path)
    _SEQUENCE_CACHE[_sequence_cache_key(path)] = (max(0, int(sequence or 0)), mtime_ns, size)


def _sequence_file_signature(path: Path) -> tuple[int, int]:
    try:
        stat = path.stat()
    except OSError:
        return (-1, -1)
    return (int(stat.st_mtime_ns), int(stat.st_size))


def _sequence_cache_key(path: Path) -> str:
    try:
        return str(path.resolve())
    except OSError:
        return str(path)


def _safe_session_workspace_token(session_id: str) -> str:
    raw = str(session_id or "").strip()
    token = _SAFE_SESSION_CHARS.sub("-", raw).strip("._-") or "session"
    if token != raw or len(token) > 96:
        digest = _short_hash(raw)[:10]
        token = f"{token[:84].rstrip('._-') or 'session'}-{digest}"
    return token


def _safe_event_token(value: str) -> str:
    token = _SAFE_SESSION_CHARS.sub("-", str(value or "").strip()).strip("._-")
    return token[:48] or "turn"


def _short_hash(value: str) -> str:
    import hashlib

    return hashlib.sha256(str(value or "").encode("utf-8", errors="replace")).hexdigest()


def _coerce_positive_int(value: Any, default: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return number if number >= 0 else default


def _coerce_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "no", "n", "off"}:
        return False
    return default


def _now_timestamp() -> str:
    return datetime.now().isoformat(timespec="seconds")


__all__ = [
    "EVENT_ASSISTANT_MESSAGE",
    "EVENT_ASSISTANT_DELTA_COMMITTED",
    "EVENT_ASSISTANT_PARTIAL",
    "AUDIT_ONLY_EVENT_TYPES",
    "EVENT_CLI_SESSION_LIFECYCLE",
    "EVENT_CLI_TASK_SENT",
    "EVENT_CLI_TASK_RESULT",
    "EVENT_COMPACTION_CHECKPOINT",
    "MODEL_VISIBLE_EVENT_TYPES",
    "EVENT_TOOL_CALL_STARTED",
    "EVENT_TOOL_RESULT",
    "VOLATILE_MODEL_EVENT_TYPES",
    "EVENT_TURN_COMPLETED",
    "EVENT_TURN_CONTEXT",
    "EVENT_TURN_FAILED",
    "EVENT_TURN_INTERRUPTED",
    "EVENT_TURN_STARTED",
    "EVENT_USER_MESSAGE",
    "TURN_INTERRUPTED_MARKER",
    "TurnJournalEvent",
    "append_interrupted_if_open",
    "append_turn_event",
    "event_has_model_projection",
    "event_projection_category",
    "latest_turn_sequence",
    "latest_open_turn_id",
    "load_turn_events",
    "model_visible_messages_from_events",
    "model_messages_from_events",
    "turn_journal_path",
]
