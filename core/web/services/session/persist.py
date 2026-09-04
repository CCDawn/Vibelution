"""Session turn result persistence (final journal + chat state + work-run).

Claim scope: persist successful/failed/interrupted turn outcomes after the
worker finishes. Do not put submit validation, schedule policy, or SSE
transport here.

Bodies late-bind ``session_service`` so facade monkeypatches remain effective.
"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from core.web.services.session.turn_failure_classification import classify_turn_failure


_CHALLENGE_DEADLINE_PROBLEM_CODE = "challenge_logical_task_deadline_exhausted"


def _apply_turn_failure_problem_code(conversation: dict[str, Any], problem_code: str) -> None:
    """Anchor (or clear) the terminal problem code for a classified failure.

    Budget-family failures keep the established ``context_budget_exhausted``
    code so downstream loop detection sees them; every other failure keeps the
    historical "no problem code from this path" behavior.
    """

    normalized = str(problem_code or "").strip()
    if normalized:
        conversation["last_turn_terminal_problem_code"] = normalized
        return
    conversation.pop("last_turn_terminal_problem_code", None)
    conversation.pop("lastTurnTerminalProblemCode", None)


def _service():
    """Late-bound facade module (avoids import cycles at package import time)."""

    from core.web.services import session_service

    return session_service


def _ensure_session_turn_terminal_fallback(
    session_id: str,
    turn_id: str,
    *,
    stop_reason: str = "",
) -> None:
    """Converge an accepted turn after result/failure persistence itself fails."""

    s = _service()
    normalized_turn_id = str(turn_id or "").strip()
    if not normalized_turn_id:
        return
    terminal_types = {s.EVENT_TURN_COMPLETED, s.EVENT_TURN_FAILED, s.EVENT_TURN_INTERRUPTED}
    terminal_event = None
    journal_loaded = False
    try:
        events = s._load_session_conversation_events_cached(session_id)
        journal_loaded = True
        terminal_event = next(
            (
                event
                for event in reversed(events)
                if str(event.turn_id or "").strip() == normalized_turn_id
                and event.event_type in terminal_types
            ),
            None,
        )
    except Exception:
        pass
    try:
        # This helper is always called from the turn's finally block.  A normal
        # result has already written a terminal ledger event and its work-run
        # summary, so treating that completed turn as a persistence fallback
        # would overwrite the correct completed summary with a false failure.
        if terminal_event is not None:
            return
        stopped = bool(str(stop_reason or "").strip())
        terminal_status = "stopped" if stopped else "failed_runtime"
        if journal_loaded:
            s._append_session_conversation_event(
                session_id,
                normalized_turn_id,
                s.EVENT_TURN_INTERRUPTED if stopped else s.EVENT_TURN_FAILED,
                status=terminal_status,
                payload={
                    "reason": str(stop_reason or "").strip() or "turn_persistence_failed",
                    "errorType": "turn_persistence_failed" if not stopped else "",
                },
                source="session_turn_terminal_fallback",
            )
        finished_at = s._now_timestamp()
        work_run_status = "stopped" if terminal_status in {"stopped", "interrupted", "cancelled"} else (
            "completed" if terminal_status == "completed" else "failed"
        )
        try:
            s._persist_chat_turn_work_run(
                session_id=session_id,
                turn_id=normalized_turn_id,
                status=work_run_status,
                summary=str(stop_reason or "").strip() or "Turn persistence failed; terminal fallback applied.",
                error_type="" if work_run_status != "failed" else "turn_persistence_failed",
                finished_at=finished_at,
                updated_at=finished_at,
            )
        except Exception:
            pass
    except Exception:
        pass
    finally:
        try:
            s._clear_session_live_output(session_id, turn_id=normalized_turn_id)
        except Exception:
            pass


def _append_missing_canonical_result_items(
    session_id: str,
    turn_id: str,
    assistant_entry: dict[str, Any],
) -> None:
    """Commit result-only UI facts into the same canonical turn item journal.

    Some Agent adapters return a mental snapshot or a compact tool trace only
    with the terminal result.  The protocol outcome already committed the
    answer/reasoning items, so keeping these facts solely on the retired
    assistant envelope would make them disappear from the v3 projection.
    """

    s = _service()
    normalized_session_id = str(session_id or "").strip()
    normalized_turn_id = str(turn_id or "").strip()
    if not normalized_session_id or not normalized_turn_id:
        return
    mental_snapshot = s._normalize_mental_snapshot(
        assistant_entry.get("mental_snapshot") or assistant_entry.get("mentalSnapshot")
    )
    tool_calls = s._normalize_message_tool_calls(
        assistant_entry.get("tool_calls") or assistant_entry.get("toolCalls") or []
    )
    if mental_snapshot is None and not tool_calls:
        return

    existing = s.conversation_turn_items_from_events(
        s._load_session_conversation_events_cached(normalized_session_id),
        turn_id=normalized_turn_id,
    )
    base_id = s._session_turn_item_base_id(normalized_session_id, normalized_turn_id)
    has_mental_snapshot = any(
        str(item.get("code") or "").strip() == "mental_snapshot"
        or (
            str(item.get("kind") or item.get("type") or "").strip().lower() == "status"
            and isinstance(item.get("metadata"), dict)
            and isinstance(item["metadata"].get("mentalSnapshot"), dict)
        )
        for item in existing
        if isinstance(item, dict)
    )
    if mental_snapshot is not None and not has_mental_snapshot:
        mental_text = s._sanitize_message_content(
            "assistant",
            mental_snapshot.get("summary")
            or mental_snapshot.get("feeling")
            or mental_snapshot.get("whisper")
            or mental_snapshot.get("mood")
            or "Mental state updated.",
        )
        s._append_session_conversation_event(
            normalized_session_id,
            normalized_turn_id,
            s.EVENT_ASSISTANT_ITEM_COMMITTED,
            status="completed",
            payload={
                "schemaVersion": 2,
                "sessionId": normalized_session_id,
                "turnId": normalized_turn_id,
                "invocationId": "",
                "iteration": 0,
                "itemId": f"{base_id}-mental",
                "revision": 0,
                "sequence": 0,
                "kind": "status",
                "channel": "status",
                "phase": "mental_snapshot",
                "status": "completed",
                "protocol": "session_result",
                "provisional": False,
                "terminal": True,
                "text": mental_text,
                "code": "mental_snapshot",
                "metadata": {"mentalSnapshot": mental_snapshot},
            },
            source="persist_session_turn_result",
            visible_in_model=False,
            projection_kind="session_turn_item_v2",
            source_kind="session_mental_snapshot",
        )

    existing_call_ids: set[str] = set()
    existing_legacy_tool_counts: dict[str, int] = {}
    for item in existing:
        if not isinstance(item, dict):
            continue
        if str(item.get("kind") or item.get("type") or "").strip().lower() != "tool_call":
            continue
        name = str(item.get("toolName") or "").strip()
        metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
        existing_call_id = str(
            item.get("callId")
            or item.get("toolCallId")
            or metadata.get("callId")
            or metadata.get("toolCallId")
            or ""
        ).strip()
        if existing_call_id:
            existing_call_ids.add(existing_call_id)
        elif name:
            existing_legacy_tool_counts[name] = existing_legacy_tool_counts.get(name, 0) + 1
    seen_legacy_tool_counts: dict[str, int] = {}
    for index, tool_call in enumerate(tool_calls, start=1):
        name = str(tool_call.get("name") or tool_call.get("toolName") or "tool").strip() or "tool"
        source_call_id = str(
            tool_call.get("callId")
            or tool_call.get("toolCallId")
            or tool_call.get("id")
        ).strip()
        if source_call_id:
            if source_call_id in existing_call_ids:
                continue
            call_id = source_call_id
        else:
            seen_legacy_tool_counts[name] = seen_legacy_tool_counts.get(name, 0) + 1
            if existing_legacy_tool_counts.get(name, 0) >= seen_legacy_tool_counts[name]:
                continue
            call_id = f"{base_id}-tool-{index}"
        status = str(tool_call.get("status") or "completed").strip().lower() or "completed"
        text = s._sanitize_message_content(
            "assistant",
            tool_call.get("resultPreview")
            or tool_call.get("result_preview")
            or tool_call.get("summary")
            or tool_call.get("result")
            or tool_call.get("error")
            or "",
        )
        s._append_session_conversation_event(
            normalized_session_id,
            normalized_turn_id,
            s.EVENT_ASSISTANT_ITEM_COMMITTED,
            status=status,
            payload={
                "schemaVersion": 2,
                "sessionId": normalized_session_id,
                "turnId": normalized_turn_id,
                "invocationId": "",
                "iteration": 0,
                "itemId": f"{base_id}-tool-{index}",
                "revision": 0,
                "sequence": index,
                "kind": "tool_call",
                "channel": "tool",
                "phase": "tool",
                "status": status,
                "protocol": "session_result",
                "provisional": False,
                "terminal": status not in {"pending", "queued", "running", "in_progress"},
                "text": text,
                "callId": call_id,
                "toolName": name,
            },
            source="persist_session_turn_result",
            visible_in_model=False,
            projection_kind="session_turn_item_v2",
            tool_call_id=call_id,
            correlation_id=call_id,
            source_kind="session_tool_result",
        )
    s._invalidate_session_conversation_events_cache(normalized_session_id)


def _latest_client_submission_id(messages: list[dict[str, Any]], turn_id: str) -> str:
    normalized_turn_id = str(turn_id or "").strip().removeprefix("live:")
    if not normalized_turn_id:
        return ""
    for message in reversed(messages):
        if not isinstance(message, dict) or str(message.get("role") or "").strip() != "user":
            continue
        metadata = message.get("metadata") if isinstance(message.get("metadata"), dict) else {}
        message_turn_id = str(metadata.get("turnId") or metadata.get("turn_id") or "").strip().removeprefix("live:")
        if message_turn_id != normalized_turn_id:
            continue
        return str(metadata.get("clientSubmissionId") or metadata.get("client_submission_id") or "").strip()
    return ""


def _commit_session_turn_runtime_state(
    session_id: str,
    conversation: dict[str, Any],
    *,
    previous_conversation: dict[str, Any],
    turn_id: str = "",
) -> bool:
    """Persist turn-owned row changes without clobbering concurrent metadata."""

    s = _service()
    with s._CHAT_STATE_LOCK:
        if turn_id and not s._is_session_turn_current(session_id, turn_id):
            return False
        current = s.load_session_chat_state(s.PROJECT_ROOT, session_id)
        if current is None:
            return False
        merged = dict(current)
        for key in previous_conversation.keys() - conversation.keys():
            merged.pop(key, None)
        for key, value in conversation.items():
            if key not in previous_conversation or previous_conversation[key] != value:
                merged[key] = value
        s.save_session_chat_state(s.PROJECT_ROOT, session_id, merged)
        return True


def _persist_session_turn_result(
    session_id: str,
    result: Any,
    *,
    mental_model_enabled: bool | None = None,
    session_workspace: str | Path | None = None,
    active_task_hint: Any = None,
    user_message_source: str = "",
    turn_id: str = "",
) -> None:
    s = _service()
    lang = s.get_web_language()
    capture_messages: list[dict[str, Any]] | None = None
    agent_inbox_reply: dict[str, Any] | None = None
    source_collection_stage_task_metadata: dict[str, str] = {}
    runtime_stop_requested = s._is_session_stop_requested(session_id)
    if turn_id and not s._is_session_turn_current(session_id, turn_id):
        return
    messages = s._session_ledger_visible_messages(session_id)
    conversation = s.load_session_chat_state(s.PROJECT_ROOT, session_id)
    if conversation is None:
        return
    previous_conversation = deepcopy(conversation)
    if s._latest_assistant_message_is_stop(messages):
        s._persist_chat_turn_work_run(
            session_id=session_id,
            turn_id=turn_id,
            status="stopped",
            summary=s.text_for(lang, zh="本轮已按请求停止。", en="This turn was stopped as requested."),
            finished_at=s._now_timestamp(),
        )
        return
    result_status = str(result.get("status") or "").strip().lower() if isinstance(result, dict) else ""
    prompt_assembly = s._public_prompt_assembly_manifest(
        result.get("prompt_assembly") if isinstance(result, dict) else None
    )
    if prompt_assembly:
        conversation["last_prompt_assembly"] = prompt_assembly
    source_collection_stage_task_metadata = s._source_collection_stage_task_turn_metadata(messages, turn_id)
    result_stop_requested = bool(result.get("stop_requested")) if isinstance(result, dict) else False
    stop_requested = result_stop_requested and runtime_stop_requested
    stop_reason = (
        str(
            result.get("stop_reason")
            or result.get("stopReason")
            or ""
        ).strip().lower()
        if isinstance(result, dict)
        else ""
    )
    challenge_deadline_cancelled = (
        result_stop_requested
        and stop_reason == _CHALLENGE_DEADLINE_PROBLEM_CODE
    )
    if s._is_provider_failed_result(result):
        raw_error = s._provider_failure_raw_error(result)
        error_type = s._failure_error_type(raw_error)
        turn_error = s._make_session_turn_error(
            raw_error,
            lang=lang,
            error_type=error_type,
            turn_id=turn_id,
            llm_failure=result.get("llm_failure") if isinstance(result.get("llm_failure"), dict) else None,
            llm_payload_trace=s._current_session_live_llm_payload_trace(session_id),
        )
        failure_message = str(turn_error.get("message") or "").strip()
        context_composition = s._normalize_session_context_composition(
            result.get("context_composition") if isinstance(result, dict) else None
        )
        cache_composition = s._build_session_cache_composition(turn_id, None)
        partial_reply = s._provider_failure_partial_visible_reply(result, failure_message)
        partial_entry: dict[str, Any] | None = None
        if partial_reply:
            partial_entry = s._make_chat_message(
                "assistant",
                partial_reply,
                s._extract_chat_tool_calls(result),
                thought=s._extract_chat_thought(result, partial_reply),
                feedback_events=s._extract_chat_feedback_events(result, final_status="failed"),
                mental_snapshot=s._build_turn_mental_snapshot(
                    result,
                    lang,
                    mental_model_enabled=mental_model_enabled,
                    session_workspace=session_workspace or s._ensure_session_workspace(session_id),
                    session_id=session_id,
                    turn_id=turn_id,
                ),
            )
            if isinstance(result, dict):
                partial_entry["toolCalls"] = s._normalize_message_tool_calls(s._extract_chat_tool_calls(result))
        error_entry = s._make_provider_failure_chat_message(
            turn_error,
            error_type=error_type,
            turn_id=turn_id,
        )
        timestamp = str(error_entry.get("timestamp") or s._now_timestamp()).strip()
        stored_active_task = s._normalize_session_active_task(
            conversation.get("active_task") or conversation.get("activeTask")
        )
        hint_active_task = s._normalize_session_active_task(active_task_hint)
        existing_active_task = s._select_existing_active_task_for_update(
            stored_active_task,
            hint_active_task,
            messages,
        )
        next_active_task = s._build_session_active_task(
            session_id,
            result,
            messages,
            existing_task=existing_active_task,
            user_message_source=user_message_source,
        )
        s._set_or_clear_session_active_task(conversation, next_active_task)
        conversation.pop("messages", None)
        if context_composition is not None:
            conversation["last_context_composition"] = context_composition
        conversation["last_cache_composition"] = cache_composition
        last_llm_payload_trace = s._current_session_live_llm_payload_trace(session_id)
        if last_llm_payload_trace is not None:
            conversation["last_llm_payload_trace"] = last_llm_payload_trace
        conversation.pop("last_turn_terminal_problem_code", None)
        conversation.pop("lastTurnTerminalProblemCode", None)
        conversation["last_turn_status"] = "failed"
        conversation["last_turn_terminal_reason"] = s._terminal_reason_for_turn(
            "failed_provider",
            result=result if isinstance(result, dict) else None,
            stop_requested=False,
        )
        conversation["last_turn_error"] = turn_error
        conversation["updated_at"] = timestamp
        if not _commit_session_turn_runtime_state(
            session_id,
            conversation,
            previous_conversation=previous_conversation,
            turn_id=turn_id,
        ):
            return
        s._clear_session_live_output(session_id, turn_id=turn_id)
        s._persist_chat_turn_work_run(
            session_id=session_id,
            turn_id=turn_id,
            status="failed",
            summary=str(turn_error.get("message") or ""),
            error_type=error_type,
            error=raw_error,
            finished_at=timestamp,
            updated_at=timestamp,
        )
        if partial_entry:
            s._record_session_turn_visible_message(
                session_id,
                turn_id,
                partial_entry,
                event="assistant_partial_result",
                status="failed_provider",
            )
            s._record_session_cycle_message(
                session_id,
                partial_entry,
                event="assistant_partial_result",
                status="failed_provider",
                active_task=next_active_task,
            )
        s._record_session_turn_visible_message(
            session_id,
            turn_id,
            error_entry,
            event="assistant_turn_error",
            status="failed_provider",
        )
        s._record_session_cycle_message(
            session_id,
            error_entry,
            event="assistant_turn_error",
            status="failed_provider",
            active_task=next_active_task,
        )
        s._record_session_turn_result_log(
            session_id,
            turn_id,
            status="failed_provider",
            summary=str(turn_error.get("message") or ""),
            recovery_pointer={"resumeAllowed": True, "source": "provider_failure"},
        )
        s._record_session_turn_lifecycle_event(
            session_id,
            "result_persisted",
            turn_id=turn_id,
            level="error",
            outcome="failed",
            fields={
                "resultStatus": "failed",
                "errorType": error_type,
                "providerFailure": error_type != "prompt_cache_unsupported",
                "visibleErrorMessagePersisted": True,
                "partialReplyPersisted": bool(partial_entry),
                "messageCount": len(messages) + (1 if partial_entry else 0) + 1,
            },
        )
        s._record_session_turn_error(
            session_id,
            turn_error,
            raw_error=raw_error,
            status="failed",
            active_task=next_active_task,
        )
        s._record_provider_failure_signal(
            session_id=session_id,
            turn_id=turn_id,
            error_type=error_type,
            raw_error=raw_error,
            related_event_code="conversation.turn_error",
        )
        if partial_entry:
            s._append_session_conversation_event(
                session_id,
                turn_id,
                s.EVENT_ASSISTANT_MESSAGE,
                status="failed_provider",
                payload={
                    "content": str(partial_entry.get("content") or ""),
                    "thought": str(partial_entry.get("thought") or ""),
                    "toolCalls": s._normalize_message_tool_calls(partial_entry.get("tool_calls") or partial_entry.get("toolCalls") or []),
                    "feedbackEvents": s._normalize_message_feedback_events(partial_entry.get("feedback_events") or partial_entry.get("feedbackEvents") or []),
                },
                source="persist_session_turn_result",
            )
        # Non-tool failures (provider/runtime errors) are deliberately NOT written
        # to the conversation journal: error text is runtime noise, not dialogue,
        # and persisting it polluted model history (see history-filtering contract
        # in core/chat/turn_journal.py). The error stays visible via
        # conversation["last_turn_error"] (session detail turnError surface).
        s._append_session_conversation_event(
            session_id,
            turn_id,
            s.EVENT_TURN_FAILED,
            status="failed_provider",
            payload={
                "errorType": error_type,
                "message": str(turn_error.get("message") or ""),
                "rawError": raw_error,
            },
            source="persist_session_turn_result",
        )
        from . import directory_bridge

        directory_bridge.touch_directory_session_safe(
            session_id,
            status="failed",
            last_preview=str(turn_error.get("message") or ""),
        )
        return
    assistant_text = (
        s.text_for(
            lang,
            zh="本轮已按请求停止。",
            en="This turn was stopped as requested.",
        )
        if stop_requested
        else s._format_visible_reply(result)
    )
    assistant_text = s._ensure_assistant_visible_text(assistant_text, result=result, lang=lang)
    phantom_image_success = s._is_phantom_image_generation_success(
        assistant_text,
        result,
        messages,
    )
    if phantom_image_success:
        assistant_text = s.text_for(
            lang,
            zh="这轮没有实际生成新的图片：系统没有捕获到图片生成工具调用产生的图片结果。请重新发送生成请求。",
            en="No new image was actually generated in this turn: no image-generation artifact was captured. Please send the generation request again.",
        )
        if isinstance(result, dict):
            result = {
                **result,
                "status": "failed_runtime",
                "summary": assistant_text,
                "raw_output": assistant_text,
                "error": assistant_text,
                "outcome": "failed",
            }
            result_status = "failed_runtime"
    llm_usage = s._normalize_turn_llm_usage(result.get("llm_usage") if isinstance(result, dict) else None)
    if llm_usage is not None:
        llm_usage["recordedAt"] = llm_usage.get("recordedAt") or s._now_timestamp()
        metadata = result.get("metadata") if isinstance(result.get("metadata"), dict) else {}
        llm_usage["promptCacheScope"] = (
            llm_usage.get("promptCacheScope")
            or metadata.get("promptCacheScope")
            or metadata.get("prompt_cache_scope")
            or "chat_session"
        )
        llm_usage["promptCachePartition"] = (
            llm_usage.get("promptCachePartition")
            or metadata.get("promptCachePartition")
            or metadata.get("prompt_cache_partition")
            or ""
        )
        llm_usage["llmModelId"] = (
            llm_usage.get("llmModelId")
            or metadata.get("llmModelId")
            or metadata.get("llm_model_id")
            or ""
        )
    context_composition = s._normalize_session_context_composition(
        result.get("context_composition") if isinstance(result, dict) else None
    )
    cache_composition = s._build_session_cache_composition(turn_id, llm_usage)
    final_status = s._chat_turn_result_status(result_status, result, stop_requested=stop_requested)
    # Challenge logical-deadline cancellation is an adapter-owned terminal
    # outcome, not an operator stop.  Keep ordinary stop semantics unchanged,
    # but never project this bounded deadline outcome through ``ready``.
    if challenge_deadline_cancelled:
        final_status = "cancelled"
    feedback_events_for_result = s._extract_chat_feedback_events(result, final_status=final_status)
    runtime_failed = final_status in {"failed_runtime", "failed"} and not stop_requested
    if runtime_failed:
        error_type = s._failure_error_type(assistant_text)
        turn_error = s._make_session_turn_error(
            assistant_text,
            lang=lang,
            error_type=error_type,
            turn_id=turn_id,
            llm_failure=result.get("llm_failure") if isinstance(result.get("llm_failure"), dict) else None,
            llm_payload_trace=s._current_session_live_llm_payload_trace(session_id),
        )
        assistant_entry = s._make_turn_error_chat_message(
            turn_error,
            error_type=error_type,
            turn_id=turn_id,
            provider_failure=False,
        )
        assistant_entry["tool_calls"] = s._normalize_message_tool_calls(s._extract_chat_tool_calls(result))
        thought = s._extract_chat_thought(result, assistant_text)
        if thought:
            assistant_entry["thought"] = thought
        mental_snapshot = s._build_turn_mental_snapshot(
            result,
            lang,
            mental_model_enabled=mental_model_enabled,
            session_workspace=session_workspace or s._ensure_session_workspace(session_id),
            session_id=session_id,
            turn_id=turn_id,
        )
        if mental_snapshot is not None:
            assistant_entry["mental_snapshot"] = mental_snapshot
        normalized_feedback_events = s._normalize_message_feedback_events(feedback_events_for_result)
        if normalized_feedback_events:
            assistant_entry["feedback_events"] = normalized_feedback_events
        if llm_usage is not None:
            assistant_entry["metadata"] = {
                **(assistant_entry.get("metadata") if isinstance(assistant_entry.get("metadata"), dict) else {}),
                "llmUsage": llm_usage,
            }
    else:
        error_type = ""
        turn_error = None
        assistant_entry = s._make_chat_message(
            "assistant",
            assistant_text,
            s._extract_chat_tool_calls(result),
            thought=s._extract_chat_thought(result, assistant_text),
            feedback_events=feedback_events_for_result,
            mental_snapshot=s._build_turn_mental_snapshot(
                result,
                lang,
                mental_model_enabled=mental_model_enabled,
                session_workspace=session_workspace or s._ensure_session_workspace(session_id),
                session_id=session_id,
                turn_id=turn_id,
            ),
            metadata={"llmUsage": llm_usage} if llm_usage is not None else None,
        )
    assistant_metadata = assistant_entry.get("metadata") if isinstance(assistant_entry.get("metadata"), dict) else {}
    client_submission_id = _latest_client_submission_id(messages, turn_id)
    assistant_entry["metadata"] = {
        **assistant_metadata,
        "turnId": turn_id,
        **({"clientSubmissionId": client_submission_id} if client_submission_id else {}),
    }
    visible_assistant_text = str(assistant_entry.get("content") or assistant_text or "").strip()
    turn_llm_usage = llm_usage if llm_usage is not None else s._missing_llm_usage(
        recorded_at=str(assistant_entry.get("timestamp") or "").strip(),
    )
    if isinstance(result, dict):
        assistant_entry["toolCalls"] = s._normalize_message_tool_calls(s._extract_chat_tool_calls(result))
        feedback_events = s._normalize_message_feedback_events(feedback_events_for_result)
        if feedback_events:
            assistant_entry["feedbackEvents"] = feedback_events
    conversation.pop("messages", None)
    stored_active_task = s._normalize_session_active_task(
        conversation.get("active_task") or conversation.get("activeTask")
    )
    hint_active_task = s._normalize_session_active_task(active_task_hint)
    existing_active_task = s._select_existing_active_task_for_update(
        stored_active_task,
        hint_active_task,
        messages,
    )
    task_result = result
    if not isinstance(task_result, dict):
        task_result = {
            "status": result_status or "completed",
            "summary": assistant_text,
            "raw_output": assistant_text,
            "outcome": "done" if result_status == "completed" and not stop_requested else (result_status or ""),
        }
    next_active_task = s._build_session_active_task(
        session_id,
        task_result,
        messages,
        existing_task=existing_active_task,
        user_message_source=user_message_source,
    )
    s._set_or_clear_session_active_task(conversation, next_active_task)
    if context_composition is not None:
        conversation["last_context_composition"] = context_composition
    conversation["last_cache_composition"] = cache_composition
    last_llm_payload_trace = s._current_session_live_llm_payload_trace(session_id)
    if last_llm_payload_trace is not None:
        conversation["last_llm_payload_trace"] = last_llm_payload_trace
    if runtime_failed and turn_error is not None:
        conversation["last_turn_error"] = turn_error
    else:
        conversation.pop("last_turn_error", None)
        conversation.pop("lastTurnError", None)
    conversation["last_turn_status"] = (
        "failed"
        if final_status in {"failed_provider", "failed_runtime", "failed"}
        else (
            "cancelled"
            if challenge_deadline_cancelled
            else (
                "needs_continue"
                if final_status == "needs_continue"
                else ("paused_limit" if final_status == "paused_limit" else "ready")
            )
        )
    )
    if challenge_deadline_cancelled:
        conversation["last_turn_terminal_problem_code"] = _CHALLENGE_DEADLINE_PROBLEM_CODE
        conversation["last_turn_terminal_reason"] = _CHALLENGE_DEADLINE_PROBLEM_CODE
    else:
        conversation.pop("last_turn_terminal_problem_code", None)
        conversation.pop("lastTurnTerminalProblemCode", None)
    # Terminal anchor: "ready" is also written by stop handling and stale
    # restart repair, so the completion snapshot can only trust "ready" as a
    # terminal verdict when it is anchored to THIS turn's real settlement.
    normalized_turn_id = str(turn_id or "").strip()
    if normalized_turn_id:
        conversation["last_turn_terminal_turn_id"] = normalized_turn_id
    else:
        conversation.pop("last_turn_terminal_turn_id", None)
    if not challenge_deadline_cancelled:
        conversation["last_turn_terminal_reason"] = s._terminal_reason_for_turn(
            final_status,
            result=result if isinstance(result, dict) else None,
            stop_requested=stop_requested,
        )
    conversation["updated_at"] = assistant_entry["timestamp"]
    if not _commit_session_turn_runtime_state(
        session_id,
        conversation,
        previous_conversation=previous_conversation,
        turn_id=turn_id,
    ):
        return
    s._clear_session_live_output(session_id, turn_id=turn_id)
    tool_calls = s._normalize_message_tool_calls(s._extract_chat_tool_calls(result))
    feedback_event_count = len(s._normalize_message_feedback_events(feedback_events_for_result))
    if final_status == "completed":
        capture_messages = [*messages, assistant_entry]
        agent_inbox_reply = s._build_agent_inbox_turn_reply(
            messages,
            assistant_text=assistant_text,
            tool_calls=tool_calls,
            source_session_id=session_id,
            source_turn_id=turn_id,
        )
    cycle_active_task = next_active_task
    s._persist_chat_turn_work_run(
        session_id=session_id,
        turn_id=turn_id,
        status=final_status,
        summary=visible_assistant_text,
        error_type=error_type if runtime_failed else "",
        error=visible_assistant_text if runtime_failed else "",
        finished_at=assistant_entry["timestamp"],
        updated_at=assistant_entry["timestamp"],
    )
    s._record_session_turn_visible_message(
        session_id,
        turn_id,
        assistant_entry,
        event="assistant_turn_error" if runtime_failed else "assistant_result",
        status=final_status,
    )
    s._record_session_turn_tool_calls(session_id, turn_id, tool_calls)
    if assistant_entry.get("thought"):
        s._record_session_turn_trace_event(
            session_id,
            turn_id,
            "thought",
            {"chars": len(str(assistant_entry.get("thought") or ""))},
            status=final_status,
            summary="Assistant thought trace captured.",
        )
    s._record_session_llm_usage_event(session_id, turn_id, llm_usage)
    if assistant_entry.get("mental_snapshot"):
        s._record_session_turn_trace_event(
            session_id,
            turn_id,
            "mental",
            assistant_entry.get("mental_snapshot") if isinstance(assistant_entry.get("mental_snapshot"), dict) else {},
            status=final_status,
            summary="Mental model trace captured.",
        )
    if tool_calls:
        s._record_session_execution_registry_event(
            session_id,
            turn_id,
            "tool_calls",
            final_status,
            details={"toolCallCount": len(tool_calls)},
        )
    s._record_session_turn_result_log(
        session_id,
        turn_id,
        status=final_status,
        summary=visible_assistant_text,
        recovery_pointer={
            # Runtime failures (e.g. main-loop TimeoutExpired) should stay recoverable
            # via “继续”, same as paused/needs_continue turns.
            "resumeAllowed": final_status
            in {
                "stopped_by_user",
                "paused_limit",
                "needs_continue",
                "failed_runtime",
                "failed",
            },
            "toolCallCount": len(tool_calls),
            "feedbackEventCount": feedback_event_count,
            "hasMentalSnapshot": bool(assistant_entry.get("mental_snapshot")),
            "phantomImageSuccess": phantom_image_success,
            "source": "runtime_failure" if runtime_failed else "turn_result",
        },
    )
    s._record_session_turn_lifecycle_event(
        session_id,
        "result_persisted",
        turn_id=turn_id,
        outcome=final_status,
        fields={
            "resultStatus": result_status or "completed",
            "finalStatus": final_status,
            "errorType": error_type,
            "providerFailure": False,
            "visibleErrorMessagePersisted": bool(runtime_failed),
            "activeTaskStatus": str((cycle_active_task or {}).get("status") or "").strip(),
            "activeTaskOutcome": str(((cycle_active_task or {}).get("metadata") or {}).get("outcome") or "").strip(),
            "activeTaskChangedFileCount": len(list((cycle_active_task or {}).get("changed_files") or [])),
            "messageCount": len(messages) + 1,
            "assistantTextLength": len(visible_assistant_text),
            "toolCallCount": len(s._extract_chat_tool_calls(result)),
            "feedbackEventCount": feedback_event_count,
            "hasThought": bool(assistant_entry.get("thought")),
            "hasMentalSnapshot": bool(assistant_entry.get("mental_snapshot")),
            "phantomImageSuccess": phantom_image_success,
        },
    )
    if runtime_failed and turn_error is not None:
        s._record_session_turn_error(
            session_id,
            turn_error,
            raw_error=assistant_text,
            status=final_status,
            active_task=cycle_active_task,
        )
    if phantom_image_success:
        s._record_session_turn_lifecycle_event(
            session_id,
            "phantom_image_success_blocked",
            turn_id=turn_id,
            level="warning",
            outcome="failed_runtime",
            fields={
                "assistantTextLength": len(assistant_text),
                "toolCallCount": len(tool_calls),
                "hasImageArtifactEvidence": False,
            },
        )
    # Ensure reasoning is durable even when wire only committed final_answer.
    thought_for_journal = str(assistant_entry.get("thought") or "").strip()
    if thought_for_journal:
        s._append_session_reasoning_item_if_needed(
            session_id,
            turn_id,
            thought_for_journal,
            source="persist_session_turn_result",
            done=True,
        )
    _append_missing_canonical_result_items(session_id, turn_id, assistant_entry)
    canonical_turn_items = s.conversation_turn_items_from_events(
        s._load_session_conversation_events_cached(session_id),
        turn_id=turn_id,
    )
    has_canonical_final = any(
        item.get("kind") == "assistant_message"
        and item.get("channel") == "answer"
        and item.get("phase") == "final_answer"
        and str(item.get("text") or "").strip()
        for item in canonical_turn_items
    )
    if not has_canonical_final and not runtime_failed:
        s._append_session_conversation_event(
            session_id,
            turn_id,
            s.EVENT_ASSISTANT_MESSAGE,
            status=final_status,
            payload={
                "content": visible_assistant_text,
                "thought": str(assistant_entry.get("thought") or ""),
                "toolCalls": s._normalize_message_tool_calls(assistant_entry.get("tool_calls") or assistant_entry.get("toolCalls") or []),
                "feedbackEvents": s._normalize_message_feedback_events(assistant_entry.get("feedback_events") or assistant_entry.get("feedbackEvents") or []),
                "llmUsage": turn_llm_usage,
                "mentalSnapshot": s._normalize_mental_snapshot(assistant_entry.get("mental_snapshot")),
                "metadata": assistant_entry.get("metadata") if isinstance(assistant_entry.get("metadata"), dict) else {},
            },
            source="persist_session_turn_result",
        )
    # runtime_failed turns persist no error assistant message to the journal
    # (see "Non-tool failures" note above): the error stays visible through
    # conversation["last_turn_error"] only.
    terminal_event = s.EVENT_TURN_FAILED if final_status in {"failed_provider", "failed_runtime", "failed"} else (
        s.EVENT_TURN_INTERRUPTED
        if challenge_deadline_cancelled or stop_requested or final_status in {"stopped", "stopped_by_user"}
        else s.EVENT_TURN_COMPLETED
    )
    s._append_session_conversation_event(
        session_id,
        turn_id,
        terminal_event,
        status=final_status,
        payload={
            "resultStatus": result_status or "completed",
            "finalStatus": final_status,
            "marker": s.TURN_INTERRUPTED_MARKER if terminal_event == s.EVENT_TURN_INTERRUPTED else "",
            "errorType": error_type if runtime_failed else "",
            "summary": visible_assistant_text,
            "llmUsage": turn_llm_usage,
        },
        source="persist_session_turn_result",
    )
    from . import directory_bridge

    directory_bridge.touch_directory_session_safe(
        session_id,
        status=(
            "failed"
            if final_status in {"failed_provider", "failed_runtime", "failed"}
            else ("stopped" if challenge_deadline_cancelled else "ready")
        ),
        last_preview=visible_assistant_text,
    )
    s._reconcile_source_collection_stage_task_after_turn(
        source_collection_stage_task_metadata,
        session_id=session_id,
        turn_id=turn_id,
        final_status=final_status,
        llm_usage=turn_llm_usage,
    )
    s._record_session_cycle_message(
        session_id,
        assistant_entry,
        event="assistant_turn_error" if runtime_failed else "assistant_result",
        status=final_status,
        active_task=cycle_active_task,
    )
    if agent_inbox_reply:
        s._deliver_agent_inbox_turn_reply(agent_inbox_reply)
    if capture_messages:
        s._capture_session_chat_candidate(session_id, capture_messages)

def _persist_session_turn_runtime_error(
    session_id: str,
    turn_error: dict[str, Any],
    *,
    raw_error: str,
    turn_id: str = "",
    status: str = "failed_runtime",
    work_run_summary: str = "",
) -> None:
    s = _service()
    timestamp = str(turn_error.get("timestamp") or s._now_timestamp()).strip()
    error_entry = s._make_local_runtime_error_chat_message(turn_error, turn_id=turn_id)
    message = str(error_entry.get("content") or turn_error.get("message") or "").strip()
    normalized_status = str(status or "failed_runtime").strip() or "failed_runtime"
    normalized_error_type = str(turn_error.get("error_type") or turn_error.get("errorType") or "runtime_error").strip()
    conversation = s.load_session_chat_state(s.PROJECT_ROOT, session_id)
    if conversation is None:
        return
    previous_conversation = deepcopy(conversation)
    if turn_id and not s._is_session_turn_current(session_id, turn_id):
        return
    conversation.pop("messages", None)
    conversation.pop("last_turn_terminal_problem_code", None)
    conversation.pop("lastTurnTerminalProblemCode", None)
    conversation["last_turn_status"] = normalized_status
    conversation["last_turn_terminal_reason"] = s._terminal_reason_for_turn(normalized_status)
    conversation["last_turn_error"] = turn_error
    conversation["updated_at"] = timestamp
    if not _commit_session_turn_runtime_state(
        session_id,
        conversation,
        previous_conversation=previous_conversation,
        turn_id=turn_id,
    ):
        return
    from . import directory_bridge

    directory_bridge.touch_directory_session_safe(
        session_id,
        status="failed",
        last_preview=message,
    )
    s._clear_session_live_output(session_id, turn_id=turn_id)
    s._persist_chat_turn_work_run(
        session_id=session_id,
        turn_id=turn_id,
        status=normalized_status,
        summary=work_run_summary or message,
        error_type=normalized_error_type,
        error=raw_error,
        finished_at=timestamp,
        updated_at=timestamp,
    )
    s._record_session_turn_result_log(
        session_id,
        turn_id,
        status=normalized_status,
        summary=message,
        recovery_pointer={"resumeAllowed": False, "source": "local_runtime_error"},
    )
    s._record_session_turn_visible_message(
        session_id,
        turn_id,
        error_entry,
        event="assistant_turn_error",
        status=normalized_status,
    )
    s._record_session_cycle_message(
        session_id,
        error_entry,
        event="assistant_turn_error",
        status=normalized_status,
    )
    s._record_session_turn_lifecycle_event(
        session_id,
        "runtime_error_persisted",
        turn_id=turn_id,
        level="error",
        outcome=normalized_status,
        fields={
            "errorType": normalized_error_type,
            "reasonCode": str(turn_error.get("reason_code") or turn_error.get("reasonCode") or "").strip(),
            "model": str(turn_error.get("model") or "").strip(),
            "visibleTurnErrorMessagePersisted": True,
            "normalAssistantReplyPersisted": False,
        },
    )
    s._record_session_turn_error(
        session_id,
        turn_error,
        raw_error=raw_error,
        status=normalized_status,
    )
    # No error assistant message is appended to the journal for runtime failures
    # (see "Non-tool failures" note above); conversation["last_turn_error"] carries
    # the visible error instead.
    s._append_session_conversation_event(
        session_id,
        turn_id,
        s.EVENT_TURN_FAILED,
        status=normalized_status,
        payload={
            "errorType": normalized_error_type,
            "message": message,
            "rawError": raw_error,
            "chainStage": str(turn_error.get("chain_stage") or turn_error.get("chainStage") or "").strip(),
            "eventCode": str(turn_error.get("event_code") or turn_error.get("eventCode") or "").strip(),
            "traceId": str(turn_error.get("trace_id") or turn_error.get("traceId") or "").strip(),
            "protocol": str(turn_error.get("protocol") or "").strip(),
        },
        source="persist_session_turn_runtime_error",
    )

def _persist_session_turn_failure(session_id: str, context: dict[str, Any], exc: Exception) -> None:
    s = _service()
    lang = s.get_web_language()
    raw_error = str(exc or "").strip()
    error_type = s._failure_error_type(raw_error, exc=exc)
    # Terminal-state decision comes from the centralized classifier (category +
    # three-value disposition), not the provider-text regex. Only the existing
    # failed/failed_provider values (plus additive diagnosis fields) are
    # written, so journal projection / UI / diagnosis consumers stay compatible.
    classification = classify_turn_failure(raw_error, exc=exc)

    def _attach_failure_classification(turn_error: dict[str, Any]) -> dict[str, Any]:
        turn_error["failure_category"] = classification.category
        turn_error["failure_disposition"] = classification.disposition
        return turn_error

    turn_id = str(context.get("turn_id") or "")
    work_run_summary = s.text_for(
        lang,
        zh="网页工作台这一轮执行失败，完整错误已写入运行日志。",
        en="This web workbench turn failed. The full error was written to runtime logs.",
    )

    messages = s._session_ledger_visible_messages(session_id)
    conversation = s.load_session_chat_state(s.PROJECT_ROOT, session_id)
    if conversation is None:
        return
    previous_conversation = deepcopy(conversation)
    if classification.provider_family:
        turn_error = _attach_failure_classification(
            s._make_session_turn_error(
                raw_error,
                lang=lang,
                error_type=error_type,
                turn_id=turn_id,
                llm_payload_trace=s._current_session_live_llm_payload_trace(session_id),
            )
        )
        error_entry = s._make_provider_failure_chat_message(
            turn_error,
            error_type=error_type,
            turn_id=turn_id,
        )
        timestamp = str(error_entry.get("timestamp") or s._now_timestamp()).strip()
        conversation.pop("messages", None)
        _apply_turn_failure_problem_code(conversation, classification.problem_code)
        conversation["last_turn_status"] = "failed"
        conversation["last_turn_terminal_reason"] = s._terminal_reason_for_turn("failed_provider")
        conversation["last_turn_error"] = turn_error
        conversation["updated_at"] = timestamp
        if not _commit_session_turn_runtime_state(
            session_id,
            conversation,
            previous_conversation=previous_conversation,
            turn_id=turn_id,
        ):
            return
        s._clear_session_live_output(session_id, turn_id=turn_id)
        s._persist_chat_turn_work_run(
            session_id=session_id,
            turn_id=turn_id,
            status="failed",
            summary=work_run_summary,
            error_type=error_type,
            error=raw_error,
            finished_at=timestamp,
            updated_at=timestamp,
        )
        s._record_session_turn_result_log(
            session_id,
            turn_id,
            status="failed_provider",
            summary=work_run_summary,
            recovery_pointer={"resumeAllowed": True, "source": "provider_failure"},
        )
        s._record_session_turn_visible_message(
            session_id,
            turn_id,
            error_entry,
            event="assistant_turn_error",
            status="failed_provider",
        )
        s._record_session_cycle_message(
            session_id,
            error_entry,
            event="assistant_turn_error",
            status="failed_provider",
        )
        s._record_session_turn_lifecycle_event(
            session_id,
            "failure_persisted",
            turn_id=turn_id,
            level="error",
            outcome="failed",
            fields={
                "errorType": error_type,
                "providerFailure": True,
                "failureCategory": classification.category,
                "failureDisposition": classification.disposition,
                "visibleErrorMessagePersisted": True,
                "messageCount": len(messages) + 1,
            },
        )
        s._record_session_turn_error(
            session_id,
            turn_error,
            raw_error=raw_error,
            status="failed",
        )
        s._record_provider_failure_signal(
            session_id=session_id,
            turn_id=turn_id,
            error_type=error_type,
            raw_error=raw_error,
            related_event_code="conversation.turn_error",
        )
        # Provider-failure error messages stay out of the journal
        # (see "Non-tool failures" note above); last_turn_error carries the
        # visible error for the session detail turnError surface.
        s._append_session_conversation_event(
            session_id,
            turn_id,
            s.EVENT_TURN_FAILED,
            status="failed_provider",
            payload={
                "errorType": error_type,
                "message": str(turn_error.get("message") or ""),
                "rawError": raw_error,
                "failureCategory": classification.category,
                "failureDisposition": classification.disposition,
                **(
                    {"problemCode": classification.problem_code}
                    if classification.problem_code
                    else {}
                ),
            },
            source="persist_session_turn_failure",
        )
        from . import directory_bridge

        directory_bridge.touch_directory_session_safe(
            session_id,
            status="failed",
            last_preview=str(turn_error.get("message") or work_run_summary or ""),
        )
        return
    turn_error = _attach_failure_classification(
        s._make_session_turn_error(
            raw_error,
            lang=lang,
            error_type=error_type,
            turn_id=turn_id,
            llm_payload_trace=s._current_session_live_llm_payload_trace(session_id),
        )
    )
    error_entry = s._make_turn_error_chat_message(
        turn_error,
        error_type=error_type,
        turn_id=turn_id,
        provider_failure=False,
    )
    timestamp = str(error_entry.get("timestamp") or s._now_timestamp()).strip()
    conversation.pop("messages", None)
    _apply_turn_failure_problem_code(conversation, classification.problem_code)
    conversation["last_turn_error"] = turn_error
    conversation["last_turn_status"] = "failed"
    conversation["last_turn_terminal_reason"] = s._terminal_reason_for_turn("failed_runtime")
    conversation["updated_at"] = timestamp
    if not _commit_session_turn_runtime_state(
        session_id,
        conversation,
        previous_conversation=previous_conversation,
        turn_id=turn_id,
    ):
        return
    s._clear_session_live_output(session_id, turn_id=turn_id)
    s._persist_chat_turn_work_run(
        session_id=session_id,
        turn_id=turn_id,
        status="failed",
        summary=work_run_summary,
        error_type=error_type,
        error=raw_error,
        finished_at=timestamp,
        updated_at=timestamp,
    )
    s._record_session_turn_visible_message(
        session_id,
        turn_id,
        error_entry,
        event="assistant_turn_error",
        status="failed",
    )
    s._record_session_turn_result_log(
        session_id,
        turn_id,
        status="failed_runtime",
        summary=work_run_summary,
        recovery_pointer={"resumeAllowed": True, "source": "runtime_failure"},
    )
    s._record_session_turn_lifecycle_event(
        session_id,
        "failure_persisted",
        turn_id=turn_id,
        level="error",
        outcome="failed",
        fields={
            "errorType": error_type,
            "providerFailure": False,
            "failureCategory": classification.category,
            "failureDisposition": classification.disposition,
            "visibleErrorMessagePersisted": True,
            "messageCount": len(messages) + 1,
        },
    )
    s._record_session_turn_error(
        session_id,
        turn_error,
        raw_error=raw_error,
        status="failed",
    )
    from . import directory_bridge

    directory_bridge.touch_directory_session_safe(
        session_id,
        status="failed",
        last_preview=str(turn_error.get("message") or work_run_summary or ""),
    )
    s._record_session_cycle_message(
        session_id,
        error_entry,
        event="assistant_turn_error",
        status="failed",
    )
    # Runtime-failure error messages stay out of the journal
    # (see "Non-tool failures" note above); last_turn_error carries the
    # visible error for the session detail turnError surface.
    s._append_session_conversation_event(
        session_id,
        turn_id,
        s.EVENT_TURN_FAILED,
        status="failed_runtime",
        payload={
            "errorType": error_type,
            "message": str(turn_error.get("message") or ""),
            "rawError": raw_error,
            "failureCategory": classification.category,
            "failureDisposition": classification.disposition,
            **(
                {"problemCode": classification.problem_code}
                if classification.problem_code
                else {}
            ),
        },
        source="persist_session_turn_failure",
    )
