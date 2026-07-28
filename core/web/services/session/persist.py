"""Session turn result persistence (final journal + chat state + work-run).

Claim scope: persist successful/failed/interrupted turn outcomes after the
worker finishes. Do not put submit validation, schedule policy, or SSE
transport here.

Bodies late-bind ``session_service`` so facade monkeypatches remain effective.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


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
        events = s.load_conversation_events(s.PROJECT_ROOT, session_id)
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
    with s._CHAT_STATE_LOCK:
        payload = s.load_chat_state(s.PROJECT_ROOT)
        conversation = s._find_conversation_entry(payload, session_id)
        if conversation is None:
            return
        if turn_id and not s._is_session_turn_current(session_id, turn_id):
            return
        messages = s._session_ledger_visible_messages(session_id)
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
            conversation["last_turn_status"] = "failed"
            conversation["last_turn_error"] = turn_error
            conversation["updated_at"] = timestamp
            payload["updated_at"] = timestamp
            s.save_chat_state(s.PROJECT_ROOT, payload)
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
            s._append_session_conversation_event(
                session_id,
                turn_id,
                s.EVENT_ASSISTANT_MESSAGE,
                status="failed_provider",
                payload={
                    "content": str(error_entry.get("content") or ""),
                    "thought": str(error_entry.get("thought") or ""),
                    "toolCalls": s._normalize_message_tool_calls(error_entry.get("tool_calls") or error_entry.get("toolCalls") or []),
                    "feedbackEvents": s._normalize_message_feedback_events(error_entry.get("feedback_events") or error_entry.get("feedbackEvents") or []),
                    "metadata": error_entry.get("metadata") if isinstance(error_entry.get("metadata"), dict) else {},
                },
                source="persist_session_turn_result",
            )
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
        assistant_entry["metadata"] = {**assistant_metadata, "turnId": turn_id}
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
            else ("needs_continue" if final_status == "needs_continue" else ("paused_limit" if final_status == "paused_limit" else "ready"))
        )
        conversation["updated_at"] = assistant_entry["timestamp"]
        payload["updated_at"] = assistant_entry["timestamp"]
        s.save_chat_state(s.PROJECT_ROOT, payload)
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
                "resumeAllowed": final_status in {"stopped_by_user", "paused_limit", "needs_continue"},
                "toolCallCount": len(tool_calls),
                "feedbackEventCount": feedback_event_count,
                "hasMentalSnapshot": bool(assistant_entry.get("mental_snapshot")),
                "phantomImageSuccess": phantom_image_success,
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
        canonical_turn_items = s.conversation_turn_items_from_events(
            s.load_conversation_events(s.PROJECT_ROOT, session_id),
            turn_id=turn_id,
        )
        has_canonical_final = any(
            item.get("kind") == "assistant_message"
            and item.get("channel") == "answer"
            and item.get("phase") == "final_answer"
            and str(item.get("text") or "").strip()
            for item in canonical_turn_items
        )
        if not has_canonical_final:
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
        terminal_event = s.EVENT_TURN_FAILED if final_status in {"failed_provider", "failed_runtime", "failed"} else (
            s.EVENT_TURN_INTERRUPTED if stop_requested or final_status in {"stopped", "stopped_by_user"} else s.EVENT_TURN_COMPLETED
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
            },
            source="persist_session_turn_result",
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
    with s._CHAT_STATE_LOCK:
        payload = s.load_chat_state(s.PROJECT_ROOT)
        conversation = s._find_conversation_entry(payload, session_id)
        if conversation is None:
            return
        if turn_id and not s._is_session_turn_current(session_id, turn_id):
            return
        conversation.pop("messages", None)
        conversation["last_turn_status"] = normalized_status
        conversation["last_turn_error"] = turn_error
        conversation["updated_at"] = timestamp
        payload["updated_at"] = timestamp
        s.save_chat_state(s.PROJECT_ROOT, payload)
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
    s._append_session_conversation_event(
        session_id,
        turn_id,
        s.EVENT_ASSISTANT_MESSAGE,
        status=normalized_status,
        payload={
            "content": str(error_entry.get("content") or ""),
            "thought": str(error_entry.get("thought") or ""),
            "toolCalls": s._normalize_message_tool_calls(error_entry.get("tool_calls") or error_entry.get("toolCalls") or []),
            "feedbackEvents": s._normalize_message_feedback_events(error_entry.get("feedback_events") or error_entry.get("feedbackEvents") or []),
            "metadata": error_entry.get("metadata") if isinstance(error_entry.get("metadata"), dict) else {},
        },
        source="persist_session_turn_runtime_error",
    )
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
    turn_id = str(context.get("turn_id") or "")
    work_run_summary = s.text_for(
        lang,
        zh="网页工作台这一轮执行失败，完整错误已写入运行日志。",
        en="This web workbench turn failed. The full error was written to runtime logs.",
    )

    with s._CHAT_STATE_LOCK:
        payload = s.load_chat_state(s.PROJECT_ROOT)
        conversation = s._find_conversation_entry(payload, session_id)
        if conversation is None:
            return
        messages = s._session_ledger_visible_messages(session_id)
        if s._looks_like_provider_error_text(raw_error):
            turn_error = s._make_session_turn_error(
                raw_error,
                lang=lang,
                error_type=error_type,
                turn_id=turn_id,
                llm_payload_trace=s._current_session_live_llm_payload_trace(session_id),
            )
            error_entry = s._make_provider_failure_chat_message(
                turn_error,
                error_type=error_type,
                turn_id=turn_id,
            )
            timestamp = str(error_entry.get("timestamp") or s._now_timestamp()).strip()
            conversation.pop("messages", None)
            conversation["last_turn_status"] = "failed"
            conversation["last_turn_error"] = turn_error
            conversation["updated_at"] = timestamp
            payload["updated_at"] = timestamp
            s.save_chat_state(s.PROJECT_ROOT, payload)
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
            s._append_session_conversation_event(
                session_id,
                turn_id,
                s.EVENT_ASSISTANT_MESSAGE,
                status="failed_provider",
                payload={
                    "content": str(error_entry.get("content") or ""),
                    "thought": str(error_entry.get("thought") or ""),
                    "toolCalls": s._normalize_message_tool_calls(error_entry.get("tool_calls") or error_entry.get("toolCalls") or []),
                    "feedbackEvents": s._normalize_message_feedback_events(error_entry.get("feedback_events") or error_entry.get("feedbackEvents") or []),
                    "metadata": error_entry.get("metadata") if isinstance(error_entry.get("metadata"), dict) else {},
                },
                source="persist_session_turn_failure",
            )
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
                source="persist_session_turn_failure",
            )
            return
        turn_error = s._make_session_turn_error(
            raw_error,
            lang=lang,
            error_type=error_type,
            turn_id=turn_id,
            llm_payload_trace=s._current_session_live_llm_payload_trace(session_id),
        )
        error_entry = s._make_turn_error_chat_message(
            turn_error,
            error_type=error_type,
            turn_id=turn_id,
            provider_failure=False,
        )
        timestamp = str(error_entry.get("timestamp") or s._now_timestamp()).strip()
        conversation.pop("messages", None)
        conversation["last_turn_error"] = turn_error
        conversation["last_turn_status"] = "failed"
        conversation["updated_at"] = timestamp
        payload["updated_at"] = timestamp
        s.save_chat_state(s.PROJECT_ROOT, payload)
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
    s._record_session_cycle_message(
        session_id,
        error_entry,
        event="assistant_turn_error",
        status="failed",
    )
    s._append_session_conversation_event(
        session_id,
        turn_id,
        s.EVENT_ASSISTANT_MESSAGE,
        status="failed_runtime",
        payload={
            "content": str(error_entry.get("content") or ""),
            "thought": str(error_entry.get("thought") or ""),
            "toolCalls": s._normalize_message_tool_calls(error_entry.get("tool_calls") or error_entry.get("toolCalls") or []),
            "feedbackEvents": s._normalize_message_feedback_events(error_entry.get("feedback_events") or error_entry.get("feedbackEvents") or []),
            "metadata": error_entry.get("metadata") if isinstance(error_entry.get("metadata"), dict) else {},
        },
        source="persist_session_turn_failure",
    )
    s._append_session_conversation_event(
        session_id,
        turn_id,
        s.EVENT_TURN_FAILED,
        status="failed_runtime",
        payload={
            "errorType": error_type,
            "message": str(turn_error.get("message") or ""),
            "rawError": raw_error,
        },
        source="persist_session_turn_failure",
    )
