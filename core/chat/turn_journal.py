"""Durable append-only journal for web chat turns."""

from __future__ import annotations

import json
import re
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
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
EVENT_ASSISTANT_ITEM_COMMITTED = "assistant_item_committed"
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
EVENT_COMPRESSION_ATTEMPT = "context_compression_attempt"

TERMINAL_EVENTS = {
    EVENT_TURN_COMPLETED,
    EVENT_TURN_FAILED,
    EVENT_TURN_INTERRUPTED,
}

MODEL_VISIBLE_EVENT_TYPES = {
    EVENT_USER_MESSAGE,
    EVENT_ASSISTANT_PARTIAL,
    EVENT_ASSISTANT_DELTA_COMMITTED,
    EVENT_ASSISTANT_ITEM_COMMITTED,
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

POST_TERMINAL_MODEL_EVENT_TYPES = MODEL_VISIBLE_EVENT_TYPES - {EVENT_TURN_INTERRUPTED}

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
    normalized_session_id = str(session_id or "").strip()
    normalized_turn_id = str(turn_id or "").strip()
    normalized_event_type = str(event_type or "").strip()
    with _SEQUENCE_CACHE_LOCK:
        if (
            normalized_event_type in POST_TERMINAL_MODEL_EVENT_TYPES
            and _turn_has_terminal_event(path, normalized_turn_id)
        ):
            raise ValueError(
                f"Cannot append {normalized_event_type} after terminal event for turn {normalized_turn_id}."
            )
        sequence = _next_sequence(path)
        event = TurnJournalEvent(
            schema_version=SCHEMA_VERSION,
            event_id=f"{_safe_event_token(normalized_turn_id or normalized_session_id)}-{sequence:06d}-{uuid4().hex[:8]}",
            session_id=normalized_session_id,
            turn_id=normalized_turn_id,
            sequence=sequence,
            event_type=normalized_event_type,
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


def _turn_has_terminal_event(path: Path, turn_id: str) -> bool:
    normalized_turn_id = str(turn_id or "").strip()
    if not normalized_turn_id or not path.exists():
        return False
    try:
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                raw = line.strip()
                if not raw:
                    continue
                try:
                    parsed = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                event = TurnJournalEvent.from_dict(parsed)
                if (
                    event is not None
                    and event.turn_id == normalized_turn_id
                    and event.event_type in TERMINAL_EVENTS
                ):
                    return True
    except OSError:
        return False
    return False


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


def rewrite_turn_events(project_root: Path, session_id: str, events: Iterable[TurnJournalEvent]) -> None:
    path = turn_journal_path(project_root, session_id)
    event_list = [event for event in list(events or []) if isinstance(event, TurnJournalEvent)]
    with _SEQUENCE_CACHE_LOCK:
        if not event_list:
            try:
                path.unlink()
            except FileNotFoundError:
                pass
            except OSError:
                return
            _SEQUENCE_CACHE.pop(_sequence_cache_key(path), None)
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_name(f"{path.name}.tmp")
        try:
            with tmp_path.open("w", encoding="utf-8") as handle:
                for event in event_list:
                    handle.write(json.dumps(event.to_dict(), ensure_ascii=False, separators=(",", ":")))
                    handle.write("\n")
            tmp_path.replace(path)
            _SEQUENCE_CACHE.pop(_sequence_cache_key(path), None)
        except OSError:
            try:
                tmp_path.unlink()
            except OSError:
                pass


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


def _canonical_item_payload(protocol_event: Any, *, outcome: Any) -> dict[str, Any]:
    diagnostic_summary = dict(getattr(protocol_event, "diagnostic_summary", {}) or {})
    call_id = str(getattr(protocol_event, "call_id", "") or "").strip()
    tool_name = str(getattr(protocol_event, "tool_name", "") or "").strip()
    channel = str(getattr(protocol_event, "channel", "") or "").strip().lower()
    phase = str(getattr(protocol_event, "phase", "") or "").strip().lower()
    if call_id or tool_name:
        kind = "tool_call"
        channel = channel or "commentary"
        phase = phase or "tool_call"
    elif channel == "reasoning":
        kind = "reasoning"
    elif channel == "commentary":
        kind = "commentary"
    else:
        kind = "assistant_message"
        channel = channel or "answer"
        phase = phase or ("final_answer" if str(getattr(outcome, "kind", "")) == "final_answer" else "interim")
    terminal = bool(getattr(protocol_event, "terminal", False)) or (
        str(getattr(outcome, "kind", "")) == "final_answer"
        and channel == "answer"
        and phase == "final_answer"
    )
    return {
        "schemaVersion": 2,
        "sessionId": str(getattr(protocol_event, "session_id", "") or "").strip(),
        "turnId": str(getattr(protocol_event, "turn_id", "") or "").strip(),
        "invocationId": str(getattr(protocol_event, "invocation_id", "") or "").strip(),
        "iteration": max(0, int(getattr(protocol_event, "iteration", 0) or 0)),
        "itemId": str(getattr(protocol_event, "item_id", "") or "").strip(),
        "revision": max(0, int(getattr(protocol_event, "item_revision", 0) or 0)),
        "sequence": max(0, int(getattr(protocol_event, "sequence", 0) or 0)),
        "kind": kind,
        "channel": channel,
        "phase": phase,
        "status": str(getattr(protocol_event, "status", "") or "completed").strip().lower(),
        "protocol": str(diagnostic_summary.get("protocol") or "canonical").strip().lower(),
        "provisional": bool(getattr(protocol_event, "provisional", False)),
        "terminal": terminal,
        "text": str(getattr(protocol_event, "text", "") or ""),
        "callId": call_id,
        "toolName": tool_name,
        "diagnosticSummary": diagnostic_summary,
    }


def append_canonical_turn_outcome(
    project_root: str | Path,
    session_id: str,
    turn_id: str,
    outcome: Any,
) -> list["TurnJournalEvent"]:
    """Commit canonical item identities before their tool lifecycle events."""

    normalized_session_id = str(session_id or "").strip()
    normalized_turn_id = str(turn_id or "").strip()
    identity = getattr(outcome, "identity", None)
    if identity is None or not normalized_session_id or not normalized_turn_id:
        raise ValueError("canonical outcome requires session_id, turn_id, and identity")
    outcome_session_id = str(getattr(identity, "session_id", "") or "").strip()
    outcome_turn_id = str(getattr(identity, "turn_id", "") or "").strip()
    if outcome_session_id != normalized_session_id or (outcome_turn_id and outcome_turn_id != normalized_turn_id):
        raise ValueError("canonical outcome identity does not match journal turn")

    protocol_events = [
        event
        for event in tuple(getattr(outcome, "events", ()) or ())
        if str(getattr(event, "kind", "") or "").strip() == "item_completed"
    ]
    committed_call_ids = {
        str(getattr(event, "call_id", "") or "").strip()
        for event in protocol_events
        if str(getattr(event, "call_id", "") or "").strip()
    }
    for tool_call in tuple(getattr(outcome, "tool_calls", ()) or ()):
        if str(getattr(tool_call, "call_id", "") or "").strip() not in committed_call_ids:
            tool_identity = getattr(tool_call, "identity", identity)
            protocol_events.append(
                SimpleNamespace(
                    session_id=getattr(tool_identity, "session_id", normalized_session_id),
                    turn_id=getattr(tool_identity, "turn_id", normalized_turn_id),
                    invocation_id=getattr(tool_identity, "invocation_id", ""),
                    iteration=getattr(tool_identity, "iteration", 0),
                    item_id=getattr(tool_identity, "item_id", ""),
                    item_revision=getattr(tool_identity, "item_revision", 0),
                    sequence=0,
                    call_id=getattr(tool_call, "call_id", ""),
                    tool_name=getattr(tool_call, "name", ""),
                    channel="commentary",
                    phase="tool_call",
                    status="ready",
                    text="",
                    provisional=False,
                    terminal=False,
                    diagnostic_summary={},
                )
            )
    has_final_item = any(
        str(getattr(event, "channel", "") or "").strip().lower() == "answer"
        and str(getattr(event, "phase", "") or "").strip().lower() == "final_answer"
        for event in protocol_events
    )
    if str(getattr(outcome, "kind", "")) == "final_answer" and not has_final_item:
        protocol_events.append(
            SimpleNamespace(
                session_id=outcome_session_id,
                turn_id=outcome_turn_id or normalized_turn_id,
                invocation_id=str(getattr(identity, "invocation_id", "") or ""),
                iteration=getattr(identity, "iteration", 0),
                item_id=getattr(identity, "item_id", ""),
                item_revision=getattr(identity, "item_revision", 0),
                sequence=0,
                call_id="",
                tool_name="",
                channel="answer",
                phase="final_answer",
                status="completed",
                text=str(getattr(outcome, "final_text", "") or ""),
                provisional=False,
                terminal=True,
                diagnostic_summary={},
            )
        )

    existing_keys = {
        (
            str(event.payload.get("invocationId") or ""),
            int(event.payload.get("iteration") or 0),
            str(event.payload.get("itemId") or ""),
            int(event.payload.get("revision") or 0),
            str(event.payload.get("kind") or ""),
            str(event.payload.get("callId") or ""),
        )
        for event in load_turn_events(project_root, normalized_session_id)
        if event.event_type == EVENT_ASSISTANT_ITEM_COMMITTED and event.turn_id == normalized_turn_id
    }
    committed: list[TurnJournalEvent] = []
    for protocol_event in protocol_events:
        payload = _canonical_item_payload(protocol_event, outcome=outcome)
        key = (
            payload["invocationId"], payload["iteration"], payload["itemId"],
            payload["revision"], payload["kind"], payload["callId"],
        )
        if key in existing_keys:
            continue
        committed.append(
            append_turn_event(
                project_root,
                normalized_session_id,
                normalized_turn_id,
                EVENT_ASSISTANT_ITEM_COMMITTED,
                status=payload["status"],
                payload=payload,
                source="canonical_turn_outcome",
                visible_in_model=(payload["kind"] == "assistant_message" and payload["channel"] == "answer" and payload["phase"] == "final_answer"),
                projection_kind="session_turn_item_v2",
                provider_role="assistant",
                tool_call_id=payload["callId"],
                correlation_id=payload["invocationId"],
                source_kind="canonical_protocol",
            )
        )
        existing_keys.add(key)
    return committed


def session_turn_items_from_events(
    events: Iterable["TurnJournalEvent"],
    *,
    turn_id: str = "",
) -> list[dict[str, Any]]:
    """Project safe, deterministic SessionTurnItem v2 records from canonical commits."""

    normalized_turn_id = str(turn_id or "").strip()
    items: list[dict[str, Any]] = []
    for event in sorted(list(events or []), key=lambda item: (item.sequence, item.event_id)):
        if event.event_type != EVENT_ASSISTANT_ITEM_COMMITTED:
            continue
        if normalized_turn_id and event.turn_id != normalized_turn_id:
            continue
        payload = dict(event.payload or {})
        item = {
            "version": 2,
            "id": f"{payload.get('itemId') or event.event_id}:{int(payload.get('revision') or 0)}",
            "type": str(payload.get("kind") or "assistant_message"),
            "sessionId": str(payload.get("sessionId") or event.session_id),
            "turnId": str(payload.get("turnId") or event.turn_id),
            "invocationId": str(payload.get("invocationId") or ""),
            "iteration": max(0, int(payload.get("iteration") or 0)),
            "itemId": str(payload.get("itemId") or ""),
            "revision": max(0, int(payload.get("revision") or 0)),
            "sequence": max(0, int(event.sequence or 0)),
            "kind": str(payload.get("kind") or "assistant_message"),
            "channel": str(payload.get("channel") or ""),
            "phase": str(payload.get("phase") or ""),
            "status": str(payload.get("status") or event.status),
            "protocol": str(payload.get("protocol") or "canonical"),
            "provisional": bool(payload.get("provisional")),
            "terminal": bool(payload.get("terminal")),
            "text": str(payload.get("text") or ""),
        }
        if str(payload.get("callId") or ""):
            item["callId"] = str(payload.get("callId"))
        if str(payload.get("toolName") or ""):
            item["toolName"] = str(payload.get("toolName"))
        diagnostic_summary = dict(payload.get("diagnosticSummary") or {})
        if diagnostic_summary:
            item["diagnosticSummary"] = diagnostic_summary
        protocol_sequence = max(0, int(payload.get("sequence") or 0))
        if protocol_sequence:
            item["protocolSequence"] = protocol_sequence
        items.append(item)
    return items


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
    canonical_final_turn_ids = {
        event.turn_id
        for event in event_list
        if event.event_type == EVENT_ASSISTANT_ITEM_COMMITTED
        and str(event.payload.get("kind") or "") == "assistant_message"
        and str(event.payload.get("channel") or "") == "answer"
        and str(event.payload.get("phase") or "") == "final_answer"
        and str(event.payload.get("text") or "").strip()
    }

    for event in event_list:
        if not event.visible_in_model and event.event_type != EVENT_COMPRESSION_ATTEMPT:
            continue
        if (
            not event_has_model_projection(event)
            and event.event_type not in TERMINAL_EVENTS
            and event.event_type != EVENT_COMPRESSION_ATTEMPT
        ):
            continue
        turn_id = str(event.turn_id or "").strip()
        payload = dict(event.payload or {})
        if event.event_type == EVENT_ASSISTANT_MESSAGE and turn_id in canonical_final_turn_ids:
            continue
        if event.event_type == EVENT_USER_MESSAGE:
            content = str(payload.get("content") or "").strip()
            attachments = list(payload.get("attachments") or [])
            references = list(payload.get("references") or [])
            if content or attachments or references:
                payload_metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
                message_metadata = {
                    "kind": "journal_user_message",
                    "turnId": turn_id,
                    "eventId": event.event_id,
                }
                if payload_metadata:
                    message_metadata.update(payload_metadata)
                messages.append(
                    {
                        "role": "user",
                        "content": content,
                        "timestamp": event.timestamp,
                        "attachments": attachments,
                        "references": references,
                        "metadata": message_metadata,
                    }
                )
        elif event.event_type == EVENT_ASSISTANT_ITEM_COMMITTED:
            if (
                str(payload.get("kind") or "") == "assistant_message"
                and str(payload.get("channel") or "") == "answer"
                and str(payload.get("phase") or "") == "final_answer"
            ):
                content = str(payload.get("text") or "").strip()
                if content:
                    messages.append(
                        {
                            "role": "assistant",
                            "content": content,
                            "timestamp": event.timestamp,
                            "metadata": {
                                "kind": EVENT_ASSISTANT_ITEM_COMMITTED,
                                "turnId": turn_id,
                                "eventId": event.event_id,
                                "invocationId": str(payload.get("invocationId") or ""),
                                "itemId": str(payload.get("itemId") or ""),
                                "revision": int(payload.get("revision") or 0),
                            },
                        }
                    )
                    final_turn_ids.add(turn_id)
        elif event.event_type in {EVENT_ASSISTANT_PARTIAL, EVENT_ASSISTANT_DELTA_COMMITTED}:
            partial = _assistant_message_from_payload(
                payload,
                kind="journal_assistant_partial",
                turn_id=turn_id,
                event_id=event.event_id,
                timestamp=event.timestamp,
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
                timestamp=event.timestamp,
                interrupted=False,
            )
            if _message_has_visible_payload(message):
                messages.append(message)
                final_turn_ids.add(turn_id)
        elif event.event_type in {EVENT_COMPACTION_CHECKPOINT, EVENT_COMPRESSION_ATTEMPT}:
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
                        "timestamp": event.timestamp,
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
                    "timestamp": str(partial.get("timestamp") or ""),
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

    event_list = list(events or [])
    event_by_id = {event.event_id: event for event in event_list if event.event_id}
    messages: list[dict[str, Any]] = []
    for message in _filter_recoverable_status_messages(model_visible_messages_from_events(event_list)):
        metadata = message.get("metadata") if isinstance(message.get("metadata"), dict) else {}
        if metadata.get("kind") == "context_compression_marker":
            checkpoint_message = _checkpoint_model_message_from_event(
                event_by_id.get(str(metadata.get("eventId") or ""))
            )
            if checkpoint_message:
                messages.append(checkpoint_message)
            continue
        messages.append(message)
    return normalize_model_messages(messages)


def _filter_recoverable_status_messages(messages: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep retry/error status UI out of the semantic model history."""

    first_pass: list[dict[str, Any]] = []
    meaningful_non_user_turn_ids: set[str] = set()
    skipped_recoverable_status = False
    for raw in list(messages or []):
        if not isinstance(raw, dict):
            continue
        message = dict(raw)
        if _is_recoverable_status_message(message):
            skipped_recoverable_status = True
            continue
        first_pass.append(message)
        if _is_meaningful_non_user_message(message):
            turn_id = _message_turn_id(message)
            if turn_id:
                meaningful_non_user_turn_ids.add(turn_id)

    second_pass: list[dict[str, Any]] = []
    for message in first_pass:
        if _is_turn_interrupted_marker_message(message) and _message_turn_id(message) not in meaningful_non_user_turn_ids:
            continue
        second_pass.append(message)

    retained_non_user_turn_ids = {
        _message_turn_id(message)
        for message in second_pass
        if _is_meaningful_non_user_message(message)
    }
    filtered = [
        message
        for message in second_pass
        if not (
            _is_continuation_only_user_message(message)
            and _message_turn_id(message) not in retained_non_user_turn_ids
        )
    ]
    if skipped_recoverable_status:
        return _minimal_provider_failure_recovery_history(filtered)
    return filtered


def _minimal_provider_failure_recovery_history(messages: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    for message in reversed(list(messages or [])):
        if str(message.get("role") or "").strip().lower() != "user":
            continue
        if _is_continuation_only_user_message(message):
            continue
        if str(message.get("content") or "").strip():
            return [message]
    return []


def _message_turn_id(message: dict[str, Any]) -> str:
    metadata = message.get("metadata") if isinstance(message.get("metadata"), dict) else {}
    return str(metadata.get("turnId") or message.get("turnId") or "").strip()


def _message_metadata_kind(message: dict[str, Any]) -> str:
    metadata = message.get("metadata") if isinstance(message.get("metadata"), dict) else {}
    return str(metadata.get("kind") or "").strip()


def _is_recoverable_status_message(message: dict[str, Any]) -> bool:
    role = str(message.get("role") or "").strip().lower()
    if role != "assistant":
        return False
    metadata = message.get("metadata") if isinstance(message.get("metadata"), dict) else {}
    if metadata.get("providerFailure") is True:
        return True
    if str(metadata.get("kind") or "").strip() == "turn_error":
        return True
    if str(metadata.get("errorType") or "").strip().startswith("provider_"):
        return True
    content = str(message.get("content") or "")
    return any(
        marker in content
        for marker in (
            "模型连接正在重试",
            "模型服务上游暂时失败",
            "provider 上游服务不可用",
            "Upstream request failed",
            "server_error:",
        )
    )


def _is_turn_interrupted_marker_message(message: dict[str, Any]) -> bool:
    return _message_metadata_kind(message) == "turn_interrupted"


def _is_meaningful_non_user_message(message: dict[str, Any]) -> bool:
    role = str(message.get("role") or "").strip().lower()
    if role == "user":
        return False
    if _is_turn_interrupted_marker_message(message):
        return False
    if _is_recoverable_status_message(message):
        return False
    return _message_has_visible_payload(message)


def _is_continuation_only_user_message(message: dict[str, Any]) -> bool:
    if str(message.get("role") or "").strip().lower() != "user":
        return False
    content = str(message.get("content") or "").strip().lower()
    return content in {"继续", "继续。", "继续吧", "继续一下", "continue", "go on"}


def _assistant_message_from_payload(
    payload: dict[str, Any],
    *,
    kind: str,
    turn_id: str,
    event_id: str,
    interrupted: bool,
    timestamp: str = "",
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
    if timestamp:
        message["timestamp"] = timestamp
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    if metadata:
        message["metadata"].update(metadata)
    usage = payload.get("llmUsage") or payload.get("llm_usage") or metadata.get("llmUsage") or metadata.get("llm_usage")
    if isinstance(usage, dict):
        message["metadata"]["llmUsage"] = dict(usage)
    mental_snapshot = (
        payload.get("mentalSnapshot")
        or payload.get("mental_snapshot")
        or metadata.get("mentalSnapshot")
        or metadata.get("mental_snapshot")
    )
    if isinstance(mental_snapshot, dict):
        message["mentalSnapshot"] = dict(mental_snapshot)
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
    status = _tool_status_from_event(event, tool_call)
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
        "transportStatus",
        "transport_status",
        "semanticStatus",
        "semantic_status",
        "failureClass",
        "failure_class",
        "exitCode",
        "exit_code",
        "timedOut",
        "timed_out",
        "resultKind",
        "result_kind",
        "truncated",
        "originalLength",
        "original_length",
    ):
        if key in tool_call:
            normalized[key] = tool_call[key]
    if event.event_type == EVENT_TOOL_CALL_STARTED and "result" not in normalized and "error" not in normalized:
        normalized["result"] = "工具调用已开始，但该轮在返回结果前中断。"
        normalized["status"] = "interrupted"
    return {
        "role": "assistant",
        "content": "",
        "timestamp": event.timestamp,
        "toolCalls": [normalized],
        "metadata": {
            "kind": event.event_type,
            "turnId": event.turn_id,
            "eventId": event.event_id,
            "correlationId": str(event.correlation_id or "").strip(),
            "resultKey": str(event.correlation_id or "").strip() if event.event_type == EVENT_CLI_TASK_RESULT else "",
        },
    }


def _tool_status_from_event(event: TurnJournalEvent, tool_call: dict[str, Any]) -> str:
    event_status = str(event.status or "").strip().lower()
    tool_status = str(tool_call.get("status") or "").strip().lower()
    if event.event_type not in {EVENT_TOOL_RESULT, EVENT_CLI_TASK_RESULT}:
        return event_status or tool_status or "running"
    semantic_status = str(tool_call.get("semanticStatus") or tool_call.get("semantic_status") or "").strip().lower()
    transport_status = str(tool_call.get("transportStatus") or tool_call.get("transport_status") or "").strip().lower()
    for candidate in (semantic_status, tool_status, event_status):
        normalized = _normalize_terminal_tool_status(candidate)
        if normalized in {"failed", "timeout", "blocked", "cancelled", "no_result", "interrupted"}:
            return normalized
    timed_out = tool_call.get("timedOut", tool_call.get("timed_out"))
    if timed_out is True or str(timed_out).strip().lower() in {"1", "true", "yes", "y", "on"}:
        return "timeout"
    for candidate in (semantic_status, tool_status, event_status):
        normalized = _normalize_terminal_tool_status(candidate)
        if normalized:
            return normalized
    if transport_status == "returned" and _tool_call_has_result_payload(tool_call):
        return "done"
    if event_status or tool_status:
        return event_status or tool_status
    return "done" if _tool_call_has_result_payload(tool_call) else "running"


def _normalize_terminal_tool_status(status: str) -> str:
    normalized = str(status or "").strip().lower()
    if normalized in {"done", "success", "succeeded", "completed", "finished", "ready", "degraded", "observed"}:
        return "done"
    if normalized in {"failed", "failure", "error"}:
        return "failed"
    if normalized in {"timeout", "timed_out"}:
        return "timeout"
    if normalized in {"blocked", "cancelled", "no_result", "interrupted"}:
        return normalized
    return ""


def _tool_call_has_result_payload(tool_call: dict[str, Any]) -> bool:
    for key in ("summary", "result", "resultPreview", "result_preview", "error"):
        value = tool_call.get(key)
        if value is not None and str(value).strip():
            return True
    return False


def _checkpoint_message_from_event(event: TurnJournalEvent) -> dict[str, Any]:
    payload = dict(event.payload or {})
    metadata = _context_compression_marker_metadata(event, payload)
    if not metadata:
        return {}
    return {
        "role": "assistant",
        "content": "",
        "timestamp": event.timestamp,
        "metadata": metadata,
    }


def _context_compression_marker_metadata(
    event: TurnJournalEvent,
    payload: dict[str, Any],
) -> dict[str, Any]:
    summary = str(payload.get("summary") or payload.get("content") or "").strip()
    summary_written = bool(payload.get("summaryWritten", bool(summary)))
    effective = bool(payload.get("effective", True))
    raw_status = str(payload.get("markerStatus") or event.status or "").strip()
    if raw_status in {"skipped_low_savings", "failed_preserved"}:
        status = raw_status
    elif effective and summary_written:
        status = "applied"
    else:
        status = "skipped_low_savings"
    title_by_status = {
        "applied": "上下文已压缩",
        "skipped_low_savings": "压缩未应用 · 收益不足",
        "failed_preserved": "压缩失败 · 已保留原上下文",
    }
    title = title_by_status.get(status, "压缩未应用 · 收益不足")
    before_tokens = _safe_int(payload.get("beforeTokens"))
    after_tokens = _safe_int(payload.get("afterTokens"))
    saved_tokens = _safe_int(payload.get("savedTokens"))
    if saved_tokens <= 0 and before_tokens > after_tokens:
        saved_tokens = before_tokens - after_tokens
    trigger_source = str(payload.get("triggerSource") or "").strip()
    level = str(payload.get("level") or "").strip()
    detail_parts = [
        level,
        f"节省 {saved_tokens:,} tokens" if saved_tokens > 0 else "",
        _context_compression_trigger_label(trigger_source),
    ]
    metadata = {
        "kind": "context_compression_marker",
        "turnId": event.turn_id,
        "eventId": event.event_id,
        "status": status,
        "title": title,
        "detail": " · ".join(part for part in detail_parts if part),
        "level": level,
        "triggerSource": trigger_source,
        "beforeTokens": before_tokens,
        "afterTokens": after_tokens,
        "savedTokens": max(0, saved_tokens),
        "effectivenessRatio": _safe_float(payload.get("effectivenessRatio")),
        "effectivenessThreshold": _safe_float(payload.get("effectivenessThreshold")),
        "summaryHash": str(payload.get("summaryHash") or "").strip(),
        "summaryAvailable": bool(summary),
        "summaryPreview": summary[:1200],
        "schema": "context_compression_marker.v1",
    }
    if "sourceMessageCount" in payload:
        metadata["sourceMessageCount"] = _safe_int(payload.get("sourceMessageCount"))
    if "coveredEventSeqStart" in payload:
        metadata["coveredEventSeqStart"] = _safe_int(payload.get("coveredEventSeqStart"))
    if "coveredEventSeqEnd" in payload:
        metadata["coveredEventSeqEnd"] = _safe_int(payload.get("coveredEventSeqEnd"))
    error_type = str(payload.get("errorType") or "").strip()
    if error_type:
        metadata["errorType"] = error_type
    return metadata

def _checkpoint_model_message_from_event(event: TurnJournalEvent | None) -> dict[str, Any]:
    if event is None:
        return {}
    payload = dict(event.payload or {})
    summary = str(payload.get("summary") or payload.get("content") or "").strip()
    if not summary:
        return {}
    return {
        "role": "assistant",
        "content": summary,
        "timestamp": event.timestamp,
        "metadata": {
            "kind": EVENT_COMPACTION_CHECKPOINT,
            "turnId": event.turn_id,
            "eventId": event.event_id,
        },
    }


def _context_compression_trigger_label(value: str) -> str:
    normalized = str(value or "").strip().lower()
    labels = {
        "automatic_threshold": "自动阈值",
        "auto": "自动阈值",
        "tool_request": "工具请求",
        "provider_context_length": "上下文长度恢复",
        "context_length_error": "上下文长度恢复",
    }
    return labels.get(normalized, normalized)


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _safe_float(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


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
        "timestamp": event.timestamp,
        "metadata": {
            "kind": EVENT_CLI_SESSION_LIFECYCLE,
            "turnId": event.turn_id,
            "eventId": event.event_id,
            "event": event_name,
            "lifecycleKey": str(lifecycle.get("lifecycleKey") or "").strip(),
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
    metadata = message.get("metadata") if isinstance(message.get("metadata"), dict) else {}
    if metadata.get("kind") == "context_compression_marker":
        return True
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
    "EVENT_ASSISTANT_ITEM_COMMITTED",
    "EVENT_ASSISTANT_PARTIAL",
    "AUDIT_ONLY_EVENT_TYPES",
    "EVENT_CLI_SESSION_LIFECYCLE",
    "EVENT_CLI_TASK_SENT",
    "EVENT_CLI_TASK_RESULT",
    "EVENT_COMPACTION_CHECKPOINT",
    "EVENT_COMPRESSION_ATTEMPT",
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
    "append_canonical_turn_outcome",
    "append_turn_event",
    "event_has_model_projection",
    "event_projection_category",
    "latest_turn_sequence",
    "latest_open_turn_id",
    "load_turn_events",
    "rewrite_turn_events",
    "model_visible_messages_from_events",
    "model_messages_from_events",
    "session_turn_items_from_events",
    "turn_journal_path",
]
