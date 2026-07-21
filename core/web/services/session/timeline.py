"""Session message timeline / tool-call / mental-snapshot normalizers.

Claim scope: preflight rejection persistence, persisted tool/feedback
normalization, assistant timeline projection, and mental snapshot builders.

Late-bound facade keeps monkeypatches stable.
"""

from __future__ import annotations

import json
import re
from copy import deepcopy
from pathlib import Path
from typing import Any


def _service():
    from core.web.services import session_service

    return session_service


def _persist_session_preflight_rejection(
    conversation: dict[str, Any],
    *,
    message: str,
    reason: str,
    error_type: str,
    http_status: int,
    source: str,
    requested_leases: list[str] | None = None,
    lease_conflicts: list[dict[str, Any]] | None = None,
    lang: str,
) -> dict[str, Any]:
    s = _service()
    timestamp = s._now_timestamp()
    reason_text = str(reason or "").strip()
    normalized_http_status = s._coerce_nonnegative_int(http_status)
    requested = s.normalize_leases(requested_leases or [])
    conflicts = list(lease_conflicts or [])
    conflict = conflicts[0] if conflicts and isinstance(conflicts[0], dict) else {}
    conflict_run_id = str(conflict.get("runId") or "").strip()
    conflict_leases = s.normalize_leases(conflict.get("leases") or [])
    message_lines = [
        s.text_for(
            lang,
            zh="本轮未调用模型：请求在进入 LLM 前被系统拒绝。",
            en="The model was not called: this request was rejected before the LLM stage.",
        ),
        f"HTTP {normalized_http_status}" if normalized_http_status else "",
        reason_text,
    ]
    if conflict_run_id:
        message_lines.append(f"activeRunId: {conflict_run_id}")
    if conflict_leases:
        message_lines.append(f"leases: {', '.join(conflict_leases)}")
    notice_message = "\n".join(line for line in message_lines if str(line or "").strip())
    turn_error = {
        "message": notice_message,
        "error_type": str(error_type or "preflight_rejected").strip() or "preflight_rejected",
        "reason_code": "preflight_rejected",
        "reason_summary": s.text_for(
            lang,
            zh="请求在进入模型调用前被拒绝",
            en="Request rejected before model call",
        ),
        "reason_detail": reason_text,
        "http_status": normalized_http_status,
        "provider": "",
        "provider_host": "",
        "provider_error_type": "",
        "provider_error_message": "",
        "model": "",
        "recoverable": True,
        "timestamp": timestamp,
        "turn_id": "",
    }
    conversation["runtime_notices"] = s._append_session_runtime_notice(
        conversation.get("runtime_notices") or conversation.get("runtimeNotices") or [],
        {
            "kind": "turn_rejected",
            "level": "warning" if normalized_http_status != 401 else "error",
            "message": notice_message,
            "timestamp": timestamp,
            "source": source,
            "previousStatus": "preflight_rejected",
        },
    )
    conversation["last_cache_composition"] = s._not_called_cache_composition(
        recorded_at=timestamp,
        reason="preflight_rejected",
    )
    conversation["last_turn_status"] = "blocked"
    conversation["last_turn_error"] = turn_error
    conversation["updated_at"] = timestamp
    try:
        s.record_runtime_scene_event(
            "conversation",
            "turn_rejected",
            "conversation.turn.rejected_before_llm",
            level="warning" if normalized_http_status != 401 else "error",
            outcome="rejected",
            message="Conversation turn rejected before any LLM call.",
            fields={
                "sessionId": str(conversation.get("conversation_id") or conversation.get("id") or "").strip(),
                "source": source,
                "httpStatus": normalized_http_status,
                "errorType": str(error_type or "preflight_rejected").strip() or "preflight_rejected",
                "requestedLeases": requested,
                "conflictRunId": conflict_run_id,
                "conflictLeases": conflict_leases,
                "reason": reason_text,
                "userMessageChars": len(str(message or "")),
                "llmCalled": False,
            },
            child_log_path=f"conversations/{s._safe_session_workspace_token(str(conversation.get('conversation_id') or conversation.get('id') or '').strip())}-turnjsonl",
            child_log_payload={
                "event": "turn_rejected_before_llm",
                "timestamp": timestamp,
                "httpStatus": normalized_http_status,
                "errorType": str(error_type or "preflight_rejected").strip() or "preflight_rejected",
                "requestedLeases": requested,
                "conflictRunId": conflict_run_id,
                "conflictLeases": conflict_leases,
                "reason": reason_text,
                "llmCalled": False,
            },
            lifecycle=True,
        )
    except Exception:
        pass
    return turn_error


def _assistant_timeline_target_indices(items: list[Any], *, source_start_index: int = 1) -> dict[str, int]:
    s = _service()
    targets: dict[str, int] = {}
    first_assistant_by_turn: dict[str, int] = {}
    for index, raw in enumerate(list(items or []), start=max(1, int(source_start_index or 1))):
        if not isinstance(raw, dict):
            continue
        if str(raw.get("role") or "").strip().lower() != "assistant":
            continue
        turn_id = s._message_turn_id(raw)
        if not turn_id:
            continue
        first_assistant_by_turn.setdefault(turn_id, index)
        content = s._sanitize_message_content("assistant", raw.get("content") or "")
        if content:
            targets[turn_id] = index
    for turn_id, index in first_assistant_by_turn.items():
        targets.setdefault(turn_id, index)
    return targets


def _finish_image_attachment_preflight_turn(
    session_id: str,
    turn_id: str,
    result: dict[str, Any],
    *,
    decision: str,
    reason: str,
    agent_id: str,
    attachments: list[dict[str, Any]],
    leases: list[str] | None,
    raw_user_message: str,
    outcome: str = "completed",
    level: str = "info",
    fields: dict[str, Any] | None = None,
) -> None:
    s = _service()
    s._record_image_attachment_capability_event(
        session_id,
        turn_id=turn_id,
        decision=decision,
        reason=reason,
        outcome=outcome,
        level=level,
        agent_id=agent_id,
        attachments=attachments,
        fields={
            **(fields or {}),
            "resultStatus": str(result.get("status") or "").strip(),
            "assistantTextLength": len(str(result.get("summary") or result.get("raw_output") or "")),
        },
    )
    s._persist_session_turn_result(session_id, result, turn_id=turn_id)
    s._persist_chat_turn_work_run(
        session_id=session_id,
        turn_id=turn_id,
        status=s._chat_turn_result_status(str(result.get("status") or "completed"), result, stop_requested=False),
        agent_id=agent_id,
        leases=leases,
        user_message=raw_user_message,
        summary=str(result.get("summary") or result.get("raw_output") or "").strip(),
        finished_at=s._now_timestamp(),
    )
    s._set_session_running(session_id, False, turn_id=turn_id)
    s._clear_session_turn_control(session_id, turn_id=turn_id)
    s._publish_session_detail_snapshot(session_id)


def _record_session_turn_tool_calls(
    session_id: str,
    turn_id: str,
    tool_calls: list[dict[str, Any]],
) -> None:
    s = _service()
    for index, tool_call in enumerate(tool_calls or []):
        if not isinstance(tool_call, dict):
            continue
        s._record_session_turn_subpackage_event(
            session_id,
            turn_id,
            "tool_calljsonl",
            {
                "index": index,
                "toolCallId": str(
                    tool_call.get("id")
                    or tool_call.get("toolCallId")
                    or tool_call.get("tool_call_id")
                    or ""
                ).strip(),
                "name": str(tool_call.get("name") or "").strip(),
                "status": str(tool_call.get("status") or "").strip(),
                "summary": s.trim_lines(tool_call.get("summary") or "", max_lines=3),
                "owner": str(tool_call.get("owner") or tool_call.get("agent") or "main").strip(),
                "trace_path": str(tool_call.get("tracePath") or tool_call.get("trace_path") or "").strip(),
            },
            phase="turn_tool_call",
            event_code="conversation.turn.tool_call",
            outcome=str(tool_call.get("status") or "observed").strip() or "observed",
            message=f"Conversation turn tool call: {tool_call.get('name') or 'tool'}.",
        )


def _normalize_tool_call_status(value: Any, *, default: str = "done") -> str:
    s = _service()
    status = str(value or "").strip().lower()
    if status in {
        "running",
        "pending",
        "queued",
        "thinking",
        "tooling",
        "answering",
        "done",
        "success",
        "succeeded",
        "completed",
        "finished",
        "ready",
        "degraded",
        "recovered",
        "observed",
        "failed",
        "error",
        "blocked",
        "cancelled",
        "no_result",
        "submitted",
        "in_progress",
        "timeout",
        "timed_out",
    }:
        if status in {"success", "succeeded", "completed", "finished", "ready", "observed"}:
            return "done"
        if status == "error":
            return "failed"
        if status in {"timeout", "timed_out"}:
            return "timeout"
        return status
    return default


def _looks_like_tool_call_failure_summary(value: Any) -> bool:
    s = _service()
    text = str(value or "").strip()
    if not text:
        return False
    return bool(
        re.search(
            r"(?i)(^\s*\[(?:超时|timeout|failed|error)\]|执行超时|timed\s+out|timeout(?:\s+expired)?|tool\s+failed|工具执行失败|调用失败|traceback|exception\b)",
            text,
        )
    )


def _tool_call_name(raw: Any) -> str:
    s = _service()
    if isinstance(raw, dict):
        function_block = raw.get("function") or {}
        if not isinstance(function_block, dict):
            function_block = {}
        return str(
            raw.get("name")
            or raw.get("tool_name")
            or function_block.get("name")
            or ""
        ).strip()
    return str(raw or "").strip()


def _normalize_persisted_tool_calls(value: Any) -> list[dict[str, Any]]:
    s = _service()
    tool_calls: list[dict[str, Any]] = []
    for item in list(value or []):
        name = s._tool_call_name(item)
        if not name:
            continue
        status = s._normalize_tool_call_status(
            item.get("status") if isinstance(item, dict) else "",
            default="done",
        )
        entry: dict[str, Any] = {
            "name": name,
            "status": status,
        }
        if isinstance(item, dict):
            call_id = str(
                item.get("callId")
                or item.get("toolCallId")
                or item.get("tool_call_id")
                or item.get("id")
                or ""
            ).strip()
            if call_id:
                entry["callId"] = call_id
            summary = s.trim_lines(
                item.get("summary")
                or item.get("result_preview")
                or item.get("resultPreview")
                or item.get("error")
                or "",
                max_lines=2,
            )
            if summary:
                entry["summary"] = summary
            failure_hint = summary or item.get("error") or ""
            if s._looks_like_tool_call_failure_summary(failure_hint):
                entry["status"] = "timeout" if re.search(r"(?i)(超时|timed\s+out|timeout)", str(failure_hint or "")) else "failed"
            arguments = s._safe_tool_argument_details(
                item.get("arguments") if isinstance(item.get("arguments"), dict) else item.get("args")
            )
            if arguments:
                entry["arguments"] = arguments
            result_preview = s._trim_tool_detail_text(
                item.get("resultPreview") or item.get("result_preview") or item.get("result"),
                max_chars=1200,
                max_lines=10,
            )
            if result_preview:
                entry["resultPreview"] = result_preview
            terminal_facts = s._sandbox_terminal_result_facts(
                item.get("result") or item.get("resultPreview") or item.get("result_preview")
            ) or s._sandbox_terminal_result_facts(item)
            if terminal_facts:
                entry.update(terminal_facts)
                if terminal_facts.get("formattedOutput"):
                    entry["resultPreview"] = str(terminal_facts["formattedOutput"])
            result_type = str(item.get("resultType") or item.get("result_type") or "").strip()
            if result_type:
                entry["resultType"] = result_type
            result_length = s._coerce_tool_number(item.get("resultLength") or item.get("result_length"))
            if result_length is not None:
                entry["resultLength"] = result_length
            error = s._trim_tool_detail_text(item.get("error"), max_chars=1200, max_lines=10)
            if error:
                entry["error"] = error
            duration_ms = s._coerce_tool_number(item.get("durationMs") or item.get("duration_ms"))
            if duration_ms is not None:
                entry["durationMs"] = duration_ms
            duration_seconds = s._coerce_tool_number(item.get("durationSeconds") or item.get("duration_seconds") or item.get("elapsedSeconds"))
            if duration_seconds is not None:
                entry["durationSeconds"] = duration_seconds
            timeout_seconds = s._coerce_tool_number(item.get("timeoutSeconds") or item.get("timeout_seconds"))
            if timeout_seconds is not None:
                entry["timeoutSeconds"] = timeout_seconds
            trace_path = str(item.get("tracePath") or item.get("trace_path") or "").strip()
            if trace_path:
                entry["tracePath"] = trace_path
            s._copy_tool_result_fact_fields(item, entry)
            if entry.get("semanticStatus"):
                entry["status"] = s._normalize_tool_call_status(entry.get("semanticStatus"), default=entry["status"])
        tool_calls.append(entry)
    return tool_calls


def _normalize_message_tool_calls(value: Any) -> list[dict[str, Any]]:
    s = _service()
    tool_calls: list[dict[str, Any]] = []
    for item in s._normalize_persisted_tool_calls(value):
        entry = {
            "name": str(item.get("name") or "").strip(),
            "status": s._normalize_tool_call_status(item.get("status"), default="done"),
        }
        summary = s.trim_lines(item.get("summary") or "", max_lines=2)
        if summary:
            entry["summary"] = summary
        for key in (
            "callId",
            "arguments",
            "resultPreview",
            "resultType",
            "resultLength",
            "error",
            "durationMs",
            "durationSeconds",
            "timeoutSeconds",
            "transportStatus",
            "semanticStatus",
            "failureClass",
            "exitCode",
            "timedOut",
            "resultKind",
            "truncated",
            "originalLength",
            "tracePath",
            "terminalSessionId",
            "terminalStatus",
            "sessionOpen",
            "formattedOutput",
        ):
            if key in item:
                entry[key] = item[key]
        if entry["name"]:
            tool_calls.append(entry)
    return tool_calls


def _normalize_feedback_event_kind(value: Any) -> str:
    s = _service()
    kind = str(value or "").strip().lower()
    if kind in {"thought", "mental", "tool", "status", "assistant_text"}:
        return kind
    return ""


def _normalize_persisted_feedback_events(value: Any) -> list[dict[str, Any]]:
    s = _service()
    events: list[dict[str, Any]] = []
    for index, item in enumerate(list(value or []), start=1):
        if not isinstance(item, dict):
            continue
        kind = s._normalize_feedback_event_kind(item.get("kind"))
        if not kind:
            continue
        sequence = s._coerce_nonnegative_int(item.get("sequence"))
        if sequence <= 0:
            sequence = index
        status = s._normalize_tool_call_status(item.get("status"), default="done")
        entry: dict[str, Any] = {
            "sequence": sequence,
            "kind": kind,
            "status": status,
        }
        timestamp = str(item.get("timestamp") or item.get("createdAt") or item.get("created_at") or "").strip()
        if timestamp:
            entry["timestamp"] = timestamp
        name = str(item.get("name") or item.get("label") or "").strip()
        if name:
            entry["name"] = name
        call_id = str(item.get("callId") or item.get("toolCallId") or item.get("tool_call_id") or "").strip()
        if call_id:
            entry["callId"] = call_id
        summary = s.trim_lines(
            item.get("summary")
            or item.get("resultPreview")
            or item.get("result_preview")
            or item.get("error")
            or "",
            max_lines=2,
        )
        if summary:
            entry["summary"] = summary
        if kind == "assistant_text":
            content = s._sanitize_message_content("assistant", item.get("text") or item.get("content") or summary)
            if content:
                entry["content"] = content
        arguments = s._safe_tool_argument_details(
            item.get("arguments") if isinstance(item.get("arguments"), dict) else item.get("args")
        )
        if arguments:
            entry["arguments"] = arguments
        result_preview = s._trim_tool_detail_text(
            item.get("resultPreview") or item.get("result_preview") or item.get("result"),
            max_chars=1800 if kind == "thought" else 1200,
            max_lines=18 if kind == "thought" else 10,
        )
        if result_preview:
            entry["resultPreview"] = result_preview
        terminal_facts = s._sandbox_terminal_result_facts(
            item.get("result") or item.get("resultPreview") or item.get("result_preview")
        ) or s._sandbox_terminal_result_facts(item)
        if terminal_facts:
            entry.update(terminal_facts)
            if terminal_facts.get("formattedOutput"):
                entry["resultPreview"] = str(terminal_facts["formattedOutput"])
        result_type = str(item.get("resultType") or item.get("result_type") or "").strip()
        if result_type:
            entry["resultType"] = result_type
        result_length = s._coerce_tool_number(item.get("resultLength") or item.get("result_length"))
        if result_length is not None:
            entry["resultLength"] = result_length
        error = s._trim_tool_detail_text(item.get("error"), max_chars=1200, max_lines=10)
        if error:
            entry["error"] = error
        duration_ms = s._coerce_tool_number(item.get("durationMs") or item.get("duration_ms"))
        if duration_ms is not None:
            entry["durationMs"] = duration_ms
        duration_seconds = s._coerce_tool_number(item.get("durationSeconds") or item.get("duration_seconds") or item.get("elapsedSeconds"))
        if duration_seconds is not None:
            entry["durationSeconds"] = duration_seconds
        timeout_seconds = s._coerce_tool_number(item.get("timeoutSeconds") or item.get("timeout_seconds"))
        if timeout_seconds is not None:
            entry["timeoutSeconds"] = timeout_seconds
        trace_path = str(item.get("tracePath") or item.get("trace_path") or "").strip()
        if trace_path:
            entry["tracePath"] = trace_path
        s._copy_tool_result_fact_fields(item, entry)
        if entry.get("semanticStatus"):
            entry["status"] = s._normalize_tool_call_status(entry.get("semanticStatus"), default=entry["status"])
        related_sequence = s._coerce_nonnegative_int(item.get("relatedThoughtSequence") or item.get("related_thought_sequence"))
        if related_sequence > 0:
            entry["relatedThoughtSequence"] = related_sequence
        events.append(entry)
    events.sort(key=lambda event: s._coerce_nonnegative_int(event.get("sequence")))
    return events[-120:]


def _normalize_message_feedback_events(value: Any) -> list[dict[str, Any]]:
    s = _service()
    events: list[dict[str, Any]] = []
    for item in s._normalize_persisted_feedback_events(value):
        entry = {
            "sequence": s._coerce_nonnegative_int(item.get("sequence")),
            "kind": str(item.get("kind") or "").strip(),
            "status": s._normalize_tool_call_status(item.get("status"), default="done"),
        }
        for key in (
            "timestamp",
            "callId",
            "name",
            "summary",
            "arguments",
            "resultPreview",
            "resultType",
            "resultLength",
            "error",
            "durationMs",
            "durationSeconds",
            "timeoutSeconds",
            "transportStatus",
            "semanticStatus",
            "failureClass",
            "exitCode",
            "timedOut",
            "resultKind",
            "truncated",
            "originalLength",
            "tracePath",
            "relatedThoughtSequence",
            "terminalSessionId",
            "terminalStatus",
            "sessionOpen",
            "formattedOutput",
            "content",
            "text",
        ):
            if key in item:
                entry[key] = item[key]
        if entry["sequence"] > 0 and entry["kind"]:
            events.append(entry)
    return events


def _assistant_timeline_events_by_turn(conversation_id: str) -> dict[str, list[dict[str, Any]]]:
    s = _service()
    normalized_session_id = str(conversation_id or "").strip()
    if not normalized_session_id:
        return {}
    events_by_turn: dict[str, list[dict[str, Any]]] = {}
    tool_event_keys: dict[str, dict[str, int]] = {}
    journal_events = list(s._load_session_conversation_events_cached(normalized_session_id))
    canonical_commentary_turn_ids: set[str] = set()
    for event in journal_events:
        if str(getattr(event, "event_type", "") or "").strip() != "assistant_item_committed":
            continue
        payload = dict(getattr(event, "payload", {}) or {})
        item_payload = dict(payload.get("item") or {})
        item_kind = str(payload.get("kind") or item_payload.get("kind") or "").strip().lower()
        item_text = s._sanitize_message_content(
            "assistant",
            payload.get("text") or item_payload.get("text") or "",
        )
        turn_id = str(getattr(event, "turn_id", "") or "").strip()
        if turn_id and item_kind == "commentary" and item_text:
            canonical_commentary_turn_ids.add(turn_id)
    for event in journal_events:
        turn_id = str(getattr(event, "turn_id", "") or "").strip()
        if not turn_id:
            continue
        event_type = str(getattr(event, "event_type", "") or "").strip()
        payload = dict(getattr(event, "payload", {}) or {})
        if event_type == "assistant_item_committed":
            item_payload = dict(payload.get("item") or {})
            item_kind = str(payload.get("kind") or item_payload.get("kind") or "").strip().lower()
            content = s._sanitize_message_content(
                "assistant",
                payload.get("text") or item_payload.get("text") or "",
            )
            sequence = s._coerce_nonnegative_int(getattr(event, "sequence", 0))
            if item_kind not in {"commentary", "reasoning"} or sequence <= 0 or not content:
                continue
            events_by_turn.setdefault(turn_id, []).append(
                {
                    "sequence": sequence,
                    "kind": "assistant_text" if item_kind == "commentary" else "thought",
                    "status": s._normalize_tool_call_status(getattr(event, "status", ""), default="done"),
                    "content": content,
                    "source": "assistant_item_committed",
                }
            )
            continue
        if event_type == s.EVENT_ASSISTANT_DELTA_COMMITTED:
            if turn_id in canonical_commentary_turn_ids:
                continue
            sequence = s._coerce_nonnegative_int(payload.get("feedbackSequence") or payload.get("feedback_sequence"))
            if sequence <= 0 and s._is_assistant_timeline_segment_event(event):
                sequence = s._coerce_nonnegative_int(getattr(event, "sequence", 0))
            content = s._sanitize_message_content("assistant", payload.get("content") or "")
            if sequence <= 0 or not content:
                continue
            events_by_turn.setdefault(turn_id, []).append(
                {
                    "sequence": sequence,
                    "kind": "assistant_text",
                    "status": s._normalize_tool_call_status(getattr(event, "status", ""), default="done"),
                    "content": content,
                }
            )
            continue
        if event_type not in {s.EVENT_TOOL_CALL_STARTED, s.EVENT_TOOL_RESULT, s.EVENT_CLI_TASK_SENT, s.EVENT_CLI_TASK_RESULT}:
            continue
        tool_event = s._feedback_event_from_conversation_tool_event(event)
        if tool_event:
            if turn_id in canonical_commentary_turn_ids:
                tool_event["sequence"] = s._coerce_nonnegative_int(getattr(event, "sequence", 0))
            items = events_by_turn.setdefault(turn_id, [])
            tool_key = s._conversation_tool_timeline_key(event)
            previous_index = tool_event_keys.setdefault(turn_id, {}).get(tool_key) if tool_key else None
            if previous_index is not None and 0 <= previous_index < len(items):
                items[previous_index] = tool_event
            else:
                if tool_key:
                    tool_event_keys.setdefault(turn_id, {})[tool_key] = len(items)
                items.append(tool_event)
    return {
        turn_id: sorted(items, key=lambda item: s._coerce_nonnegative_int(item.get("sequence")))
        for turn_id, items in events_by_turn.items()
        if any(str(item.get("kind") or "") in {"assistant_text", "thought"} for item in items)
    }


def _is_assistant_timeline_segment_event(event: Any) -> bool:
    s = _service()
    projection_kind = str(getattr(event, "projection_kind", "") or "").strip()
    source = str(getattr(event, "source", "") or "").strip()
    return projection_kind == "assistant_timeline_segment" or source == "session_ui_capture"


def _conversation_tool_timeline_key(event: Any) -> str:
    s = _service()
    payload = dict(getattr(event, "payload", {}) or {})
    tool_call = dict(payload.get("toolCall") or payload.get("tool_call") or payload)
    tool_id = str(
        getattr(event, "tool_call_id", "")
        or tool_call.get("id")
        or tool_call.get("toolCallId")
        or tool_call.get("tool_call_id")
        or tool_call.get("taskId")
        or ""
    ).strip()
    if tool_id:
        return f"id:{tool_id}"
    sequence = s._coerce_nonnegative_int(tool_call.get("feedbackSequence") or tool_call.get("feedback_sequence"))
    if sequence > 0:
        return f"sequence:{sequence}"
    return ""


def _feedback_event_from_conversation_tool_event(event: Any) -> dict[str, Any]:
    s = _service()
    payload = dict(getattr(event, "payload", {}) or {})
    tool_call = dict(payload.get("toolCall") or payload.get("tool_call") or payload)
    name = str(tool_call.get("name") or tool_call.get("toolName") or tool_call.get("tool_name") or "").strip()
    if not name:
        return {}
    sequence = s._coerce_nonnegative_int(tool_call.get("feedbackSequence") or tool_call.get("feedback_sequence"))
    if sequence <= 0:
        sequence = s._coerce_nonnegative_int(getattr(event, "sequence", 0))
    entry: dict[str, Any] = {
        "sequence": sequence,
        "kind": "tool",
        "status": s._normalize_tool_call_status(tool_call.get("status") or getattr(event, "status", ""), default="running"),
        "name": name,
    }
    summary = s.trim_lines(
        tool_call.get("summary")
        or tool_call.get("resultPreview")
        or tool_call.get("result_preview")
        or tool_call.get("error")
        or "",
        max_lines=2,
    )
    if summary:
        entry["summary"] = summary
    arguments = s._safe_tool_argument_details(
        tool_call.get("arguments") if isinstance(tool_call.get("arguments"), dict) else tool_call.get("args")
    )
    if arguments:
        entry["arguments"] = arguments
    result_preview = s._trim_tool_detail_text(
        tool_call.get("resultPreview") or tool_call.get("result_preview") or tool_call.get("result"),
        max_chars=1200,
        max_lines=10,
    )
    if result_preview:
        entry["resultPreview"] = result_preview
    terminal_facts = s._sandbox_terminal_result_facts(
        tool_call.get("result") or tool_call.get("resultPreview") or tool_call.get("result_preview")
    ) or s._sandbox_terminal_result_facts(tool_call)
    if terminal_facts:
        entry.update(terminal_facts)
        if terminal_facts.get("formattedOutput"):
            entry["resultPreview"] = str(terminal_facts["formattedOutput"])
    error = s._trim_tool_detail_text(tool_call.get("error"), max_chars=1200, max_lines=10)
    if error:
        entry["error"] = error
    for source_key, target_key in (
        ("durationMs", "durationMs"),
        ("duration_ms", "durationMs"),
        ("durationSeconds", "durationSeconds"),
        ("duration_seconds", "durationSeconds"),
        ("timeoutSeconds", "timeoutSeconds"),
        ("timeout_seconds", "timeoutSeconds"),
    ):
        if source_key in tool_call and target_key not in entry:
            value = s._coerce_tool_number(tool_call.get(source_key))
            if value is not None:
                entry[target_key] = value
    s._copy_tool_result_fact_fields(tool_call, entry)
    if entry.get("semanticStatus"):
        entry["status"] = s._normalize_tool_call_status(entry.get("semanticStatus"), default=entry["status"])
    return entry


def _filter_redundant_assistant_timeline_events(
    events: list[dict[str, Any]],
    content: Any,
) -> list[dict[str, Any]]:
    s = _service()
    content_key = s._assistant_projection_text_key(content)
    if not content_key:
        return events
    filtered: list[dict[str, Any]] = []
    for event in events:
        if str(event.get("kind") or "").strip() == "assistant_text":
            text = s._sanitize_message_content("assistant", event.get("text") or event.get("content") or "")
            text_key = s._assistant_projection_text_key(text)
            if text_key and text_key in content_key:
                continue
        filtered.append(event)
    return filtered


def _extract_chat_feedback_events(result: Any, *, final_status: str = "") -> list[dict[str, Any]]:
    s = _service()
    if not isinstance(result, dict):
        return []
    events = s._normalize_persisted_feedback_events(result.get("feedback_events") or result.get("feedbackEvents") or [])
    if not events:
        return []
    status_key = str(final_status or "").strip().lower()
    if not status_key or status_key in {"running", "queued"}:
        return events
    finalized: list[dict[str, Any]] = []
    latest_unfinished_index = -1
    failure_statuses = {"failed", "failed_runtime", "failed_provider", "timeout", "error"}
    should_fail_latest_unfinished = status_key in failure_statuses
    if should_fail_latest_unfinished:
        for index, item in enumerate(events):
            if str(item.get("status") or "").strip().lower() in {"running", "pending"}:
                latest_unfinished_index = index
    for index, item in enumerate(events):
        entry = dict(item)
        if str(entry.get("status") or "").strip().lower() in {"running", "pending"}:
            entry["status"] = (
                "done"
                if not should_fail_latest_unfinished or index < latest_unfinished_index
                else "failed"
            )
        finalized.append(entry)
    return finalized


def _normalize_mental_snapshot(value: Any) -> dict[str, Any] | None:
    s = _service()
    if not isinstance(value, dict):
        return None
    raw_metrics = value.get("metrics")
    metrics = dict(raw_metrics) if isinstance(raw_metrics, dict) else {}
    history_tail: list[dict[str, Any]] = []
    if isinstance(value.get("historyTail"), list):
        history_source = value.get("historyTail")
    elif isinstance(value.get("history_tail"), list):
        history_source = value.get("history_tail")
    else:
        history_source = []
    for item in list(history_source or [])[-5:]:
        if isinstance(item, dict):
            history_tail.append({
                "cognitiveState": str(item.get("cognitiveState") or item.get("state") or item.get("cognitive_state") or "").strip(),
                "confidence": s._coerce_confidence(item.get("confidence")),
                "timestamp": str(item.get("timestamp") or item.get("updatedAt") or item.get("updated_at") or "").strip(),
            })
    snapshot = {
        "mood": str(value.get("mood") or "").strip(),
        "feeling": str(value.get("feeling") or "").strip(),
        "whisper": str(value.get("whisper") or "").strip(),
        "summary": str(value.get("summary") or "").strip(),
        "cognitiveState": str(value.get("cognitiveState") or value.get("cognitive_state") or "").strip(),
        "confidence": s._coerce_confidence(value.get("confidence")),
        "sampleSize": s._coerce_nonnegative_int(value.get("sampleSize") or value.get("sample_size") or 0),
        "interventionCount": s._coerce_nonnegative_int(
            value.get("interventionCount") or value.get("intervention_count") or 0
        ),
        "updatedAt": str(value.get("updatedAt") or value.get("updated_at") or "").strip(),
        "source": str(value.get("source") or "").strip(),
        "intervention": s.trim_lines(value.get("intervention") or "", max_lines=8),
        "metrics": metrics,
        "historyTail": history_tail,
    }
    if not snapshot["summary"]:
        snapshot["summary"] = snapshot["feeling"] or snapshot["whisper"]
    return snapshot


def _is_mental_model_enabled_for_turn(override: bool | None = None) -> bool:
    s = _service()
    return s.resolve_feature_decision(
        "mental_model",
        config=s.get_config(),
        requested=override,
    ).effective_enabled


def _has_meaningful_mental_snapshot(snapshot: dict[str, Any] | None) -> bool:
    s = _service()
    if not isinstance(snapshot, dict):
        return False
    return any(
        str(snapshot.get(key) or "").strip()
        for key in ("mood", "feeling", "whisper", "cognitiveState")
    )


def _live_mental_snapshot(state_info: dict[str, Any], lang: str) -> dict[str, Any] | None:
    s = _service()
    mood = str((state_info or {}).get("mood") or "").strip()
    feeling = str((state_info or {}).get("feeling") or "").strip()
    whisper = str((state_info or {}).get("whisper") or "").strip()
    if not any((mood, feeling, whisper)):
        return None
    return {
        "mood": mood,
        "feeling": feeling,
        "whisper": whisper,
        "summary": feeling or whisper or s.text_for(
            lang,
            zh="当前心智层已给出最近一次状态。",
            en="The mental layer has produced a recent state.",
        ),
        "cognitiveState": "",
        "confidence": 0.0,
        "sampleSize": 0,
        "interventionCount": 0,
        "updatedAt": s._now_timestamp(),
        "source": "state",
    }


def _build_turn_mental_snapshot(
    result: Any,
    lang: str,
    *,
    mental_model_enabled: bool | None = None,
    session_workspace: str | Path | None = None,
    session_id: str = "",
    turn_id: str = "",
) -> dict[str, Any] | None:
    s = _service()
    if not s._is_mental_model_enabled_for_turn(mental_model_enabled):
        return None
    state_snapshot = None
    explicit = None
    if isinstance(result, dict):
        explicit = s._normalize_mental_snapshot(result.get("mental_snapshot") or result.get("mentalSnapshot"))
        if s._has_meaningful_mental_snapshot(explicit):
            s._record_mental_snapshot_selection(
                session_id=session_id,
                turn_id=turn_id,
                chosen_source="explicit",
                explicit=explicit,
                state_snapshot=None,
                runtime_snapshot=None,
                diagnosis_snapshot=None,
            )
            return explicit
        state_snapshot = s._live_mental_snapshot(result.get("state_info") or result.get("stateInfo") or {}, lang)
    else:
        state_snapshot = None

    runtime_snapshot = None
    try:
        from .runtime_service import _mental_state_summary

        runtime_snapshot = s._normalize_mental_snapshot(_mental_state_summary(lang))
    except Exception:
        runtime_snapshot = None

    diagnosis_snapshot = s._diagnosis_mental_snapshot(lang, session_workspace=session_workspace)

    if s._has_meaningful_mental_snapshot(state_snapshot):
        chosen = s._merge_diagnosis_mental_snapshot(state_snapshot, diagnosis_snapshot)
        s._record_mental_snapshot_selection(
            session_id=session_id,
            turn_id=turn_id,
            chosen_source="state",
            explicit=explicit,
            state_snapshot=state_snapshot,
            runtime_snapshot=runtime_snapshot,
            diagnosis_snapshot=diagnosis_snapshot,
        )
        return chosen
    if s._has_meaningful_mental_snapshot(runtime_snapshot):
        chosen = s._merge_diagnosis_mental_snapshot(runtime_snapshot, diagnosis_snapshot)
        s._record_mental_snapshot_selection(
            session_id=session_id,
            turn_id=turn_id,
            chosen_source="runtime",
            explicit=explicit,
            state_snapshot=state_snapshot,
            runtime_snapshot=runtime_snapshot,
            diagnosis_snapshot=diagnosis_snapshot,
        )
        return chosen
    if s._has_meaningful_mental_snapshot(diagnosis_snapshot):
        s._record_mental_snapshot_selection(
            session_id=session_id,
            turn_id=turn_id,
            chosen_source="diagnosis",
            explicit=explicit,
            state_snapshot=state_snapshot,
            runtime_snapshot=runtime_snapshot,
            diagnosis_snapshot=diagnosis_snapshot,
        )
        return diagnosis_snapshot
    s._record_mental_snapshot_selection(
        session_id=session_id,
        turn_id=turn_id,
        chosen_source="none",
        explicit=explicit,
        state_snapshot=state_snapshot,
        runtime_snapshot=runtime_snapshot,
        diagnosis_snapshot=diagnosis_snapshot,
    )
    return None


def _merge_diagnosis_mental_snapshot(
    snapshot: dict[str, Any] | None,
    diagnosis_snapshot: dict[str, Any] | None,
) -> dict[str, Any] | None:
    s = _service()
    if not snapshot:
        return None
    merged = dict(snapshot)
    if diagnosis_snapshot:
        for key in ("intervention", "metrics", "historyTail"):
            if diagnosis_snapshot.get(key):
                merged[key] = diagnosis_snapshot[key]
        if not merged.get("cognitiveState"):
            merged["cognitiveState"] = diagnosis_snapshot.get("cognitiveState", "")
        if not merged.get("confidence"):
            merged["confidence"] = diagnosis_snapshot.get("confidence", 0.0)
        if not merged.get("sampleSize"):
            merged["sampleSize"] = diagnosis_snapshot.get("sampleSize", 0)
        if not merged.get("interventionCount"):
            merged["interventionCount"] = diagnosis_snapshot.get("interventionCount", 0)
    return s._normalize_mental_snapshot(merged)


def _record_mental_snapshot_selection(
    *,
    session_id: str,
    turn_id: str,
    chosen_source: str,
    explicit: dict[str, Any] | None,
    state_snapshot: dict[str, Any] | None,
    runtime_snapshot: dict[str, Any] | None,
    diagnosis_snapshot: dict[str, Any] | None,
) -> None:
    s = _service()
    if not session_id and not turn_id:
        return
    try:
        s.record_runtime_scene_event(
            "conversation",
            "mental_snapshot",
            "conversation.mental_snapshot.selected",
            message="Conversation mental snapshot source selected.",
            level="info",
            outcome="selected",
            fields={
                "sessionId": str(session_id or "").strip(),
                "turnId": str(turn_id or "").strip(),
                "chosenSource": str(chosen_source or "").strip() or "none",
                "hasExplicit": s._has_meaningful_mental_snapshot(explicit),
                "hasStateSnapshot": s._has_meaningful_mental_snapshot(state_snapshot),
                "hasRuntimeSnapshot": s._has_meaningful_mental_snapshot(runtime_snapshot),
                "hasDiagnosisSnapshot": s._has_meaningful_mental_snapshot(diagnosis_snapshot),
                "explicitSource": str((explicit or {}).get("source") or "").strip(),
                "stateMood": str((state_snapshot or {}).get("mood") or "").strip(),
                "runtimeMood": str((runtime_snapshot or {}).get("mood") or "").strip(),
                "diagnosisState": str((diagnosis_snapshot or {}).get("cognitiveState") or "").strip(),
            },
            lifecycle=True,
        )
    except Exception:
        return


def _diagnosis_mental_snapshot(lang: str, *, session_workspace: str | Path | None = None) -> dict[str, Any] | None:
    s = _service()
    try:
        from core.infrastructure.mental_model import get_mental_model

        workspace_root = Path(session_workspace).resolve() if session_workspace else (s.PROJECT_ROOT / "workspace")
        mental_model = get_mental_model(workspace_root=str(workspace_root))
        diagnosis = mental_model.diagnose()
        history = []
        try:
            history = mental_model.get_diagnosis_history(limit=5)
        except Exception:
            history = []
    except Exception:
        return None

    metrics = getattr(diagnosis, "metrics", {}) or {}
    cognitive_state = str(getattr(diagnosis, "state", "") or "").strip()
    intervention = s.trim_lines(getattr(diagnosis, "intervention", "") or "", max_lines=8)
    history_tail = [
        {
            "cognitiveState": str(getattr(item, "state", "") or "").strip(),
            "confidence": s._coerce_confidence(getattr(item, "confidence", 0.0)),
            "timestamp": str(getattr(item, "timestamp", "") or "").strip(),
        }
        for item in list(history or [])[-5:]
    ]
    return s._normalize_mental_snapshot({
        "mood": "",
        "feeling": "",
        "whisper": "",
        "summary": s._mental_diagnosis_summary(lang, cognitive_state) if cognitive_state else "",
        "cognitiveState": cognitive_state,
        "confidence": s._coerce_confidence(getattr(diagnosis, "confidence", 0.0)),
        "sampleSize": metrics.get("sample_size") or 0,
        "interventionCount": metrics.get("intervention_count") or 0,
        "updatedAt": str(getattr(diagnosis, "timestamp", "") or "").strip(),
        "source": "diagnosis",
        "intervention": intervention,
        "metrics": metrics,
        "historyTail": history_tail,
    })


def _mental_diagnosis_summary(lang: str, cognitive_state: str) -> str:
    s = _service()
    labels = {
        "normal": s.text_for(lang, zh="心智诊断稳定。", en="Mental diagnosis is stable."),
        "productive": s.text_for(lang, zh="心智诊断显示当前推进顺畅。", en="Mental diagnosis shows productive progress."),
        "looping": s.text_for(lang, zh="心智诊断检测到重复循环。", en="Mental diagnosis detected looping."),
        "thrashing": s.text_for(lang, zh="心智诊断检测到工具或方案失稳。", en="Mental diagnosis detected thrashing."),
        "tunnel_vision": s.text_for(lang, zh="心智诊断检测到隧道视野。", en="Mental diagnosis detected tunnel vision."),
        "disoriented": s.text_for(lang, zh="心智诊断检测到方向分散。", en="Mental diagnosis detected disorientation."),
    }
    return labels.get(str(cognitive_state or "").strip().lower(), str(cognitive_state or "").strip())
