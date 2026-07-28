"""Session runtime-scene / lifecycle event logging helpers.

Claim scope: record session list/query/prewarm, turn lifecycle, skill,
message edit, delete, guidance, and related runtime-scene conversation events.

Late-bound facade keeps monkeypatches stable.
"""

from __future__ import annotations

import re
from typing import Any, Mapping


def _service():
    from core.web.services import session_service

    return session_service


def _record_session_cycle_message(
    session_id: str,
    message: dict[str, Any],
    *,
    event: str,
    status: str,
    active_task: dict[str, Any] | None = None,
) -> None:
    s = _service()
    s._append_session_workspace_log(
        session_id,
        message,
        event=event,
        status=status,
        active_task=active_task,
    )
    try:
        role = str(message.get("role") or "").strip() or "message"
        content = s._sanitize_message_content(role, message.get("content") or "")
        s.record_runtime_scene_conversation_event(
            session_id,
            role,
            content,
            message=message,
            event=event,
            status=status,
            tool_calls=s._normalize_message_tool_calls(
                message.get("tool_calls") or message.get("toolCalls") or []
            ),
            active_task=active_task,
        )
    except Exception as exc:
        s._debug_logger.warning(
            f"runtime scene conversation log skipped: {type(exc).__name__}: {exc}",
            tag="LOGS",
        )


def _record_session_delete_event(
    phase: str,
    *,
    session_id: str,
    outcome: str,
    level: str = "info",
    fields: dict[str, Any] | None = None,
) -> None:
    s = _service()
    normalized_session_id = str(session_id or "").strip()
    normalized_phase = re.sub(r"[^a-zA-Z0-9_.-]+", "_", str(phase or "event").strip()).strip("._-") or "event"
    try:
        s.record_runtime_scene_event(
            "conversation",
            f"session_delete_{normalized_phase}",
            f"session.delete.{normalized_phase}",
            level=level,
            outcome=outcome,
            message="Session delete lifecycle event.",
            fields={
                "sessionId": normalized_session_id,
                "source": "manual_session_action",
                **(fields or {}),
            },
            child_log_path=f"conversations/{s._safe_session_workspace_token(normalized_session_id)}-delete.jsonl",
            child_log_payload={
                "session_id": normalized_session_id,
                "phase": normalized_phase,
                "outcome": outcome,
                **(fields or {}),
            },
            lifecycle=True,
        )
    except Exception:
        return


def _record_session_execution_registry_event(
    session_id: str,
    turn_id: str,
    entry_type: str,
    status: str,
    *,
    owner: str = "main",
    details: dict[str, Any] | None = None,
) -> None:
    s = _service()
    s._record_session_turn_subpackage_event(
        session_id,
        turn_id,
        "execution_registry.jsonl",
        {
            "entry_type": str(entry_type or "runtime").strip(),
            "owner": str(owner or "main").strip(),
            "status": str(status or "").strip(),
            "details": details if isinstance(details, dict) else {},
        },
        phase=f"turn_execution_{entry_type or 'runtime'}",
        event_code="conversation.turn.execution_registry",
        outcome=status or "observed",
        message=f"Conversation turn execution registry: {entry_type or 'runtime'}.",
    )


def _record_session_guidance_event(
    session_id: str,
    *,
    mode: str,
    turn_id: str = "",
    signal_id: str = "",
    guidance_length: int = 0,
    running: bool = False,
) -> None:
    s = _service()
    try:
        s.record_runtime_scene_event(
            "conversation",
            "guidance",
            "conversation.guidance.submitted",
            level="warning" if mode == "interrupt" else "info",
            outcome=mode or "safe",
            message="User guidance submitted for the chat turn.",
            fields={
                "sessionId": str(session_id or "").strip(),
                "turnId": str(turn_id or "").strip(),
                "signalId": str(signal_id or "").strip(),
                "guidanceMode": str(mode or "").strip(),
                "guidanceLength": max(0, int(guidance_length or 0)),
                "sessionRunning": bool(running),
            },
            child_log_path="conversations/chat-guidance.jsonl",
            child_log_payload={
                "sessionId": str(session_id or "").strip(),
                "turnId": str(turn_id or "").strip(),
                "signalId": str(signal_id or "").strip(),
                "guidanceMode": str(mode or "").strip(),
                "guidanceLength": max(0, int(guidance_length or 0)),
                "sessionRunning": bool(running),
                "createdAt": s._now_timestamp(),
            },
            lifecycle=True,
        )
    except Exception as exc:
        s._debug_logger.warning(f"session guidance event skipped: {type(exc).__name__}: {exc}", tag="CHAT")


def _record_session_list_loaded_event(
    *,
    session_count: int,
    conversation_count: int,
    agent_count: int,
    elapsed_ms: int,
    cache_hit: bool = False,
    cache_age_ms: int = 0,
    cache_ttl_ms: int = 0,
    waited_for_inflight: bool = False,
) -> None:
    s = _service()
    cache_expired = bool(cache_hit and cache_ttl_ms > 0 and cache_age_ms > cache_ttl_ms)
    try:
        s.record_runtime_scene_event(
            "conversation",
            "session_list",
            "session.list.loaded",
            level="info",
            outcome="observed",
            message="Session list loaded through read-only lightweight indexes.",
            fields={
                "sessionCount": int(session_count),
                "conversationCount": int(conversation_count),
                "agentCount": int(agent_count),
                "elapsedMs": int(elapsed_ms),
                "readOnly": True,
                "hydrateAgent": False,
                "repair": False,
                "cacheHit": bool(cache_hit),
                "cacheAgeMs": max(0, int(cache_age_ms)),
                "cacheTtlMs": max(0, int(cache_ttl_ms)),
                "cacheExpired": cache_expired,
                "servedStaleMatchingSignature": cache_expired,
                "waitedForInflight": bool(waited_for_inflight),
            },
            lifecycle=False,
        )
    except Exception:
        return


def _record_session_list_prewarm_event(
    *,
    status: str,
    reason: str,
    elapsed_ms: int,
    session_count: int = 0,
    error_type: str = "",
    error_message: str = "",
) -> None:
    s = _service()
    normalized_status = str(status or "").strip().lower() or "observed"
    try:
        message = (
            "Session list cache prewarm failed before the first user request."
            if normalized_status == "failed"
            else "Session list cache prewarm completed outside the user request path."
        )
        s.record_runtime_scene_event(
            "conversation",
            "session_list",
            "session.list.prewarm",
            level="warning" if normalized_status == "failed" else "info",
            outcome=normalized_status,
            message=message,
            fields={
                "status": normalized_status,
                "reason": s.trim_lines(reason, max_lines=1) or "startup",
                "elapsedMs": max(0, int(elapsed_ms)),
                "sessionCount": max(0, int(session_count)),
                "readOnly": True,
                "hydrateAgent": False,
                "cacheWarmup": True,
                "errorType": str(error_type or "").strip(),
                "errorMessage": s.trim_lines(error_message, max_lines=2),
            },
            lifecycle=False,
        )
    except Exception:
        return


def _record_session_list_query_event(
    *,
    result_count: int,
    matched_count: int,
    total_count: int,
    limit: int,
    cursor: int,
    elapsed_ms: int,
    has_query: bool,
    has_agent_filter: bool,
    has_kind_filter: bool,
    has_state_filter: bool,
    sort: str,
) -> None:
    s = _service()
    try:
        s.record_runtime_scene_event(
            "conversation",
            "session_list",
            "session.list.query",
            level="info",
            outcome="observed",
            message="Session list query served a paginated lightweight index page.",
            fields={
                "resultCount": int(result_count),
                "matchedCount": int(matched_count),
                "totalCount": int(total_count),
                "limit": int(limit),
                "cursor": int(cursor),
                "elapsedMs": int(elapsed_ms),
                "hasQuery": bool(has_query),
                "hasAgentFilter": bool(has_agent_filter),
                "hasKindFilter": bool(has_kind_filter),
                "hasStateFilter": bool(has_state_filter),
                "sort": str(sort or "").strip(),
                "readOnly": True,
                "hydrateAgent": False,
            },
            lifecycle=False,
        )
    except Exception:
        return


def _record_session_catalog_shadow_query_event(
    *,
    comparison: Any,
    limit: int,
    cursor: int,
    has_query: bool,
    has_agent_filter: bool,
    has_kind_filter: bool,
    has_state_filter: bool,
    sort: str,
) -> None:
    """Record bounded shadow evidence without session content or identifiers."""

    s = _service()
    status = str(getattr(comparison, "status", "") or "degraded").strip() or "degraded"
    mismatch_kinds = [
        str(item or "").strip()[:80]
        for item in tuple(getattr(comparison, "mismatch_kinds", ()) or ())[:8]
        if str(item or "").strip()
    ]
    try:
        legacy_count = max(0, int(getattr(comparison, "legacy_count", 0) or 0))
    except (TypeError, ValueError):
        legacy_count = 0
    try:
        candidate_count = max(0, int(getattr(comparison, "candidate_count", 0) or 0))
    except (TypeError, ValueError):
        candidate_count = 0
    try:
        s.record_runtime_scene_event(
            "session_catalog",
            "shadow_query",
            "session_catalog.shadow_query",
            level="info" if status == "match" else "warning",
            outcome=status,
            message="Session catalog shadow query comparison completed.",
            fields={
                "status": status,
                "mismatchKinds": mismatch_kinds,
                "legacyCount": legacy_count,
                "candidateCount": candidate_count,
                "errorType": str(getattr(comparison, "error_type", "") or "").strip()[:120],
                "limit": max(0, int(limit or 0)),
                "cursor": max(0, int(cursor or 0)),
                "hasQuery": bool(has_query),
                "hasAgentFilter": bool(has_agent_filter),
                "hasKindFilter": bool(has_kind_filter),
                "hasStateFilter": bool(has_state_filter),
                "sort": str(sort or "").strip()[:80],
            },
            lifecycle=False,
        )
    except Exception:
        return


def _record_session_message_edit_resubmit_event(
    session_id: str,
    *,
    target_message_id: str,
    turn_id: str,
    truncated_count: int,
    original_content: str,
    edited_content: str,
) -> None:
    s = _service()
    try:
        s.record_runtime_scene_event(
            "conversation",
            "message_edit_resubmit",
            "conversation.message_edited_resubmitted",
            level="info",
            outcome="accepted",
            message="Latest user message edited and resubmitted.",
            fields={
                "sessionId": str(session_id or "").strip(),
                "messageId": str(target_message_id or "").strip(),
                "turnId": str(turn_id or "").strip(),
                "truncatedMessageCount": max(0, int(truncated_count or 0)),
                "originalPreview": s.trim_lines(original_content, max_lines=2),
                "editedPreview": s.trim_lines(edited_content, max_lines=2),
            },
            child_log_path=f"conversations/{s._safe_session_workspace_token(session_id)}-edits.jsonl",
            child_log_payload={
                "session_id": str(session_id or "").strip(),
                "message_id": str(target_message_id or "").strip(),
                "turn_id": str(turn_id or "").strip(),
                "truncated_message_count": max(0, int(truncated_count or 0)),
                "original_preview": s.trim_lines(original_content, max_lines=2),
                "edited_preview": s.trim_lines(edited_content, max_lines=2),
            },
        )
    except Exception as exc:
        s._debug_logger.warning(
            f"runtime scene message edit log skipped: {type(exc).__name__}: {exc}",
            tag="LOGS",
        )


def _record_session_message_edit_resubmit_rejected_event(
    session_id: str,
    *,
    target_message_id: str,
    reason: str,
    latest_message_id: str = "",
    target_preview: str = "",
) -> None:
    s = _service()
    try:
        s.record_runtime_scene_event(
            "conversation",
            "message_edit_resubmit_rejected",
            "conversation.message_edit_resubmit_rejected",
            level="warning",
            outcome="rejected",
            message="Rejected a message edit because only the latest user message can be edited and resent.",
            fields={
                "sessionId": str(session_id or "").strip(),
                "messageId": str(target_message_id or "").strip(),
                "latestMessageId": str(latest_message_id or "").strip(),
                "reason": str(reason or "").strip(),
                "targetPreview": s.trim_lines(target_preview, max_lines=2),
            },
            child_log_path=f"conversations/{s._safe_session_workspace_token(session_id)}-edits.jsonl",
            child_log_payload={
                "session_id": str(session_id or "").strip(),
                "message_id": str(target_message_id or "").strip(),
                "latest_message_id": str(latest_message_id or "").strip(),
                "reason": str(reason or "").strip(),
                "target_preview": s.trim_lines(target_preview, max_lines=2),
            },
        )
    except Exception as exc:
        s._debug_logger.warning(
            f"runtime scene rejected edit log skipped: {type(exc).__name__}: {exc}",
            tag="LOGS",
        )


def _record_session_message_encoding_rejected(message: str) -> None:
    s = _service()
    try:
        s.record_runtime_scene_event(
            "conversation",
            "message_validation",
            "conversation.message_encoding_rejected",
            level="warning",
            outcome="rejected",
            message="Rejected a user message that appears to contain replacement characters from upstream encoding loss.",
            fields={
                "length": len(str(message or "")),
                "questionMarkCount": str(message or "").count("?"),
            },
            lifecycle=True,
        )
    except Exception:
        return


def _record_session_skill_command_event(
    session_id: str,
    *,
    turn_id: str = "",
    invocation: Any = None,
    outcome: str = "routed",
) -> None:
    s = _service()
    if not isinstance(invocation, dict):
        return
    fields = {
        "sessionId": str(session_id or "").strip(),
        "turnId": str(turn_id or "").strip(),
        "command": str(invocation.get("command") or "").strip(),
        "skillName": str(invocation.get("skillName") or "").strip(),
        "skillPath": str(invocation.get("skillPath") or "").strip(),
        "skillHash": str(invocation.get("skillHash") or "").strip(),
        "skillContentLength": int(invocation.get("skillContentLength") or 0),
        "argsLength": len(str(invocation.get("args") or "")),
    }
    child_payload = {
        "session_id": fields["sessionId"],
        "turn_id": fields["turnId"],
        "command": fields["command"],
        "skill_name": fields["skillName"],
        "skill_hash": fields["skillHash"],
        "skill_content_length": fields["skillContentLength"],
        "args_length": fields["argsLength"],
        "outcome": str(outcome or "routed"),
    }
    try:
        s.record_runtime_scene_event(
            "conversation",
            "skill_command",
            "conversation.skill_command.routed",
            level="info",
            outcome=outcome,
            message="Chat slash skill command routed.",
            fields=fields,
            child_log_path=f"conversations/{s._safe_session_workspace_token(session_id)}-skill-commands.jsonl",
            child_log_payload=child_payload,
            lifecycle=True,
        )
    except Exception as exc:
        s._debug_logger.warning(
            f"runtime scene skill command log skipped: {type(exc).__name__}: {exc}",
            tag="LOGS",
        )


def _record_session_turn_accepted_event(
    context: dict[str, Any],
    submit_timing_fields: dict[str, Any],
) -> None:
    s = _service()
    session_id = str(context.get("session_id") or "").strip()
    turn_id = str(context.get("turn_id") or "").strip()
    fields = dict(submit_timing_fields or {})
    submit_started_at = context.get("submit_started_at_monotonic")
    if submit_started_at is not None:
        fields["submitTotalMs"] = s._elapsed_ms_between(submit_started_at)
    s._record_session_turn_lifecycle_event(
        session_id,
        "accepted",
        turn_id=turn_id,
        outcome="accepted",
        fields={
            "agentId": str(context.get("agent_id") or context.get("agentId") or "").strip(),
            "clientSubmissionId": str(context.get("client_submission_id") or "").strip(),
            **fields,
        },
    )


def _record_session_turn_lifecycle_event(
    session_id: str,
    phase: str,
    *,
    turn_id: str = "",
    level: str = "info",
    outcome: str = "observed",
    fields: dict[str, Any] | None = None,
) -> None:
    s = _service()
    normalized_session_id = str(session_id or "").strip()
    normalized_phase = re.sub(r"[^a-zA-Z0-9_.-]+", "_", str(phase or "event").strip()).strip("._-") or "event"
    normalized_turn_id = str(turn_id or "").strip()
    event_fields = {
        "sessionId": normalized_session_id,
        "turnId": normalized_turn_id,
        **(fields or {}),
    }
    child_payload = {
        "session_id": normalized_session_id,
        "turn_id": normalized_turn_id,
        "phase": normalized_phase,
        "outcome": str(outcome or "").strip() or "observed",
        **(fields or {}),
    }
    try:
        s.record_runtime_scene_event(
            "conversation",
            f"turn_{normalized_phase}",
            f"conversation.turn.{normalized_phase}",
            level=level,
            outcome=outcome,
            message=f"Conversation turn {normalized_phase.replace('_', ' ')}.",
            fields=event_fields,
            child_log_path=f"conversations/{s._safe_session_workspace_token(normalized_session_id)}-turns.jsonl",
            child_log_payload=child_payload,
            lifecycle=True,
        )
    except Exception as exc:
        s._debug_logger.warning(
            f"runtime scene turn lifecycle log skipped: {type(exc).__name__}: {exc}",
            tag="LOGS",
        )


def _record_session_turn_result_log(
    session_id: str,
    turn_id: str,
    *,
    status: str,
    summary: str,
    recovery_pointer: dict[str, Any] | None = None,
) -> None:
    s = _service()
    s._record_session_turn_subpackage_event(
        session_id,
        turn_id,
        "turn_result.jsonl",
        {
            "status": str(status or "").strip(),
            "summary": s.trim_lines(summary or "", max_lines=6),
            "recovery_pointer": recovery_pointer if isinstance(recovery_pointer, dict) else {},
        },
        phase="turn_result",
        event_code="conversation.turn.result",
        outcome=status or "observed",
        message="Conversation turn result persisted.",
    )


def _record_session_turn_scheduled_event(context: dict[str, Any]) -> None:
    s = _service()
    session_id = str(context.get("session_id") or "").strip()
    turn_id = str(context.get("turn_id") or "").strip()
    submit_timing_fields = dict(context.get("submit_timing_fields") or {})
    submit_started_at = context.get("submit_started_at_monotonic")
    if submit_started_at is not None:
        submit_timing_fields["submitElapsedBeforeScheduleLogMs"] = s._elapsed_ms_between(submit_started_at)
    s._record_session_turn_lifecycle_event(
        session_id,
        "scheduled",
        turn_id=turn_id,
        outcome="queued",
        fields={
            "agentId": str(context.get("agent_id") or context.get("agentId") or "").strip(),
            "historyMessageCount": len(list(context.get("history_messages") or [])),
            "mentalModelEnabled": s._normalize_optional_bool(context.get("mental_model_enabled")),
            "userMessageLength": len(str(context.get("user_message") or "")),
            "userMessageSource": str(context.get("user_message_source") or "").strip(),
            "clientSubmissionId": str(context.get("client_submission_id") or "").strip(),
            "attachmentCount": len(s._normalize_message_attachments(context.get("attachments") or [])),
            **submit_timing_fields,
        },
    )


def _record_session_turn_started_event(
    session_id: str,
    *,
    turn_id: str,
    leases: list[str] | None = None,
    user_message: str = "",
    raw_user_message: str = "",
    user_message_source: str = "",
    attachments: list[dict[str, Any]] | None = None,
) -> None:
    s = _service()
    attachment_summary = s._safe_attachment_log_summary(attachments or [])
    try:
        s.record_runtime_scene_event(
            "conversation",
            "turn",
            "conversation.turn.started",
            message="Web chat turn started.",
            level="info",
            outcome="running",
            fields={
                "sessionId": str(session_id or "").strip(),
                "turnId": str(turn_id or "").strip(),
                "leaseCount": len(list(leases or [])),
                "userMessageChars": len(str(user_message or "")),
                "rawUserMessageChars": len(str(raw_user_message or "")),
                "userMessageSource": str(user_message_source or "").strip(),
                "attachmentCount": len(attachment_summary),
                "attachments": attachment_summary,
            },
            lifecycle=True,
        )
    except Exception as exc:
        s._debug_logger.warning(
            f"runtime scene chat turn start log skipped: {type(exc).__name__}: {exc}",
            tag="LOGS",
        )


def _record_session_turn_subpackage_event(
    session_id: str,
    turn_id: str,
    file_name: str,
    payload: dict[str, Any],
    *,
    phase: str,
    event_code: str,
    level: str = "info",
    outcome: str = "observed",
    message: str = "",
) -> str:
    s = _service()
    path = s._conversation_turn_log_path(session_id, turn_id, file_name)
    fields = {
        "sessionId": str(session_id or "").strip(),
        "turnId": str(turn_id or "").strip(),
        "chatTurnLogPath": path,
    }
    try:
        s.record_runtime_scene_event(
            "conversation",
            phase,
            event_code,
            level=level,
            outcome=outcome,
            message=message or event_code,
            fields=fields,
            child_log_path=path,
            child_log_payload={
                "session_id": str(session_id or "").strip(),
                "turn_id": str(turn_id or "").strip(),
                **(payload or {}),
            },
            lifecycle=True,
        )
    except Exception as exc:
        s._debug_logger.warning(
            f"runtime scene chat turn subpackage log skipped: {type(exc).__name__}: {exc}",
            tag="LOGS",
        )
    return path


def _record_session_turn_trace_event(
    session_id: str,
    turn_id: str,
    kind: str,
    payload: dict[str, Any] | None = None,
    *,
    status: str = "",
    summary: str = "",
) -> None:
    s = _service()
    s._record_session_turn_subpackage_event(
        session_id,
        turn_id,
        "trace_events.jsonl",
        {
            "kind": str(kind or "event").strip(),
            "status": str(status or "").strip(),
            "summary": s.trim_lines(summary or "", max_lines=3),
            "payload": payload if isinstance(payload, dict) else {},
        },
        phase=f"turn_trace_{kind or 'event'}",
        event_code=f"conversation.turn.trace.{re.sub(r'[^a-zA-Z0-9_.-]+', '_', str(kind or 'event')).strip('._-') or 'event'}",
        outcome=status or "observed",
        message=f"Conversation turn trace {kind or 'event'}.",
    )


def _record_session_turn_visible_message(
    session_id: str,
    turn_id: str,
    message: dict[str, Any],
    *,
    event: str,
    status: str,
) -> None:
    s = _service()
    role = str(message.get("role") or "").strip()
    s._record_session_turn_subpackage_event(
        session_id,
        turn_id,
        "visible_messages.jsonl",
        {
            "event": str(event or "message").strip(),
            "status": str(status or "").strip(),
            "role": role,
            "content": s._sanitize_message_content(role, message.get("content") or ""),
            "message": message,
        },
        phase="turn_visible_message",
        event_code="conversation.turn.visible_message",
        outcome=status or "observed",
        message="Conversation turn visible message persisted.",
    )


def _record_session_user_message_filtered_event(
    session_id: str,
    *,
    turn_id: str = "",
    reason: str = "",
    message: str = "",
    source: str = "",
) -> None:
    s = _service()
    try:
        s.record_runtime_scene_event(
            "conversation",
            "message_filtered",
            "conversation.user_message_filtered",
            level="warning",
            outcome="ignored",
            message="Ignored a non-meaningful user message for prompt/task derivation.",
            fields={
                "sessionId": str(session_id or "").strip(),
                "turnId": str(turn_id or "").strip(),
                "reason": str(reason or "").strip(),
                "source": str(source or "").strip(),
                "messageLength": len(str(message or "")),
                "questionMarkCount": str(message or "").count("?"),
            },
            lifecycle=True,
        )
    except Exception:
        return
