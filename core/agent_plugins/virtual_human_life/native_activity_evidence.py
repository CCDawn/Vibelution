"""Read-only native tool receipts; model descriptions are never receipts.

Only explicit, successful tool results for the activity's declared tools can
support execution. This proves those calls ran, not every claim in a summary.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import datetime
from typing import Any

from core.chat.turn_journal import EVENT_TOOL_RESULT

MAX_REQUIRED_TOOLS = 32
MAX_RESULT_JSON_CHARS = 64_000
_SUCCESS = frozenset({"ok", "success", "succeeded", "completed"})
_TERMINAL_SUCCESS = _SUCCESS | {"done", "finished", "ready"}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _identifier(value: Any) -> str:
    text = _text(value)
    return text if len(text) <= 256 else ""


def _tool_name(value: Any) -> str:
    text = _text(value)
    return text.lower() if text and len(text) <= 64 else ""


def _timestamp(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(_text(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def _field(event: Any, name: str) -> Any:
    return getattr(event, name, None)


def _status(value: Any) -> str:
    return _text(value).lower().replace("-", "_")


def _explicit_success(tool: dict[str, Any], event_status: Any) -> bool:
    """Do not reuse native display's degraded/observed -> done coercion."""
    if _status(event_status) not in _TERMINAL_SUCCESS:
        return False
    tool_status = _status(tool.get("status"))
    if tool_status and tool_status not in _TERMINAL_SUCCESS:
        return False
    raw_result = tool.get("result")
    if raw_result is None or raw_result == "":
        return False
    result = raw_result if isinstance(raw_result, dict) else {}
    if isinstance(raw_result, str):
        if len(raw_result) > MAX_RESULT_JSON_CHARS:
            return False
        try:
            decoded = json.loads(raw_result)
        except (ValueError, TypeError):
            decoded = None
        if isinstance(decoded, dict):
            result = decoded

    # Every supplied semantic/failure field must agree with success. Native
    # terminal process results may say completed even when exitCode is nonzero.
    for facts in (tool, result):
        if facts.get("error") or facts.get("isError"):
            return False
        for key in ("ok", "success"):
            if key in facts and facts[key] is not True:
                return False
        for key in ("timedOut", "timed_out"):
            if facts.get(key) not in (None, False, 0, "", "false", "False"):
                return False
        for key in ("exitCode", "exit_code", "returncode", "return_code"):
            if (
                key in facts
                and facts[key] not in (None, "")
                and (isinstance(facts[key], bool) or facts[key] not in (0, "0"))
            ):
                return False
        for key in ("failureClass", "failure_class"):
            if _text(facts.get(key)):
                return False
        for key in (
            "semanticStatus",
            "semantic_status",
            "outcomeStatus",
            "outcome_status",
        ):
            if _status(facts.get(key)) and _status(facts[key]) not in _SUCCESS:
                return False
    result_status = _status(result.get("status"))
    if result_status and result_status not in _SUCCESS:
        return False
    transport = _status(tool.get("transportStatus") or tool.get("transport_status"))
    if transport and transport not in {
        "returned",
        "success",
        "succeeded",
        "completed",
        "done",
        "ok",
    }:
        return False
    result_kind = _status(tool.get("resultKind") or tool.get("result_kind"))
    if result_kind in {"unknown", "no_result", "error", "failure"}:
        return False
    # Native semanticStatus defaults to succeeded for arbitrary text results.
    # Only the tool's structured success protocol proves a business result;
    # done/semantic metadata alone cannot elevate an opaque result.
    return bool(
        result.get("ok") is True
        or result.get("success") is True
        or result_status in _SUCCESS
    )


def native_activity_evidence(
    request: dict[str, Any], events: Iterable[Any]
) -> dict[str, Any] | None:
    """Select bounded references from a trusted native Journal snapshot."""
    session_id, turn_id = (
        _identifier(request.get("sessionId")),
        _identifier(request.get("turnId")),
    )
    execution_turn_id = _identifier(request.get("executionTurnId"))
    started_at = _timestamp(request.get("startedAt"))
    if (
        not session_id
        or not turn_id
        or started_at is None
        or (request.get("executionTurnId") and execution_turn_id != turn_id)
    ):
        return None
    names = request.get("requiredToolNames")
    if (
        not isinstance(names, (list, tuple))
        or not names
        or len(names) > MAX_REQUIRED_TOOLS
    ):
        return None
    required = list(dict.fromkeys(_tool_name(name) for name in names))
    if any(not name or name.startswith("virtual_human_") for name in required):
        return None
    required_set = set(required)
    excluded_calls = request.get("excludedToolCallIds", [])
    excluded_events = request.get("excludedReceiptEventIds", [])
    if any(
        not isinstance(values, (list, tuple))
        or len(values) > 512
        or any(not isinstance(value, str) or not _identifier(value) for value in values)
        for values in (excluded_calls, excluded_events)
    ):
        return None
    excluded_calls = set(excluded_calls)
    excluded_events = set(excluded_events)
    # The last result for a call wins: a failed correction cannot be hidden by
    # an older successful receipt carrying the same toolCallId.
    latest: dict[str, tuple[Any, dict[str, Any]]] = {}
    for event in events:
        occurred_at = _timestamp(_field(event, "timestamp"))
        if (
            _text(_field(event, "event_type")) != EVENT_TOOL_RESULT
            or _text(_field(event, "session_id")) != session_id
            or _text(_field(event, "turn_id")) != turn_id
            or occurred_at is None
            or occurred_at < started_at
        ):
            continue
        payload = _field(event, "payload")
        tool = payload.get("toolCall") if isinstance(payload, dict) else None
        if (
            not isinstance(tool, dict)
            or _tool_name(tool.get("name")) not in required_set
        ):
            continue
        call_id = _identifier(_field(event, "tool_call_id"))
        payload_call_id = _identifier(tool.get("callId"))
        if not call_id or (payload_call_id and payload_call_id != call_id):
            continue
        if (
            call_id in excluded_calls
            or _identifier(_field(event, "event_id")) in excluded_events
        ):
            continue
        latest[call_id] = (event, tool)
    selected: dict[str, tuple[str, str]] = {}
    for call_id, (event, tool) in latest.items():
        name = _tool_name(tool.get("name"))
        event_id = _identifier(_field(event, "event_id"))
        if event_id and _explicit_success(tool, _field(event, "status")):
            selected.setdefault(name, (call_id, event_id))
    if any(name not in selected for name in required):
        return None
    return {
        "kind": "native_tool_execution",
        "sessionId": session_id,
        "turnId": turn_id,
        "toolCallIds": [selected[name][0] for name in required],
        "toolNames": required,
        "receiptEventIds": [selected[name][1] for name in required],
    }


def select_episode_history(
    events: Iterable[dict[str, Any]], *, limit: int, episode_ids: Iterable[str] | None
) -> list[dict[str, Any]]:
    """Filter before the bound so older plugin-owned sources remain visible."""
    bounded = max(1, min(500, int(limit or 500)))
    wanted = (
        None
        if episode_ids is None
        else {_text(item) for item in episode_ids if _text(item)}
    )
    selected = []
    for event in events:
        if isinstance(event, dict) and (
            wanted is None or _text(event.get("episodeId")) in wanted
        ):
            selected.append(dict(event))
            if len(selected) >= bounded:
                break
    return selected
