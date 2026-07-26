"""Session turn stop / interrupt control helpers.

Claim scope: request_stop_session_turn, interrupted snapshot persistence, and
related paused/stopped turn result builders.

Agent purge/archive/child/inbox/cli lifecycle lives in ``agent_sessions.py``.
Late-bound facade keeps monkeypatches stable.
"""

from __future__ import annotations

from typing import Any


def _service():
    from core.web.services import session_service

    return session_service


def request_stop_session_turn(session_id: str, *, expected_turn_id: str = "") -> dict:
    """Interrupt the active web chat turn after optional identity validation.

    Interactive HTTP callers always provide ``expected_turn_id``. Trusted
    internal shutdown paths may omit it to retain explicit stop-current
    behavior.
    """
    s = _service()

    lang = s.get_web_language()
    conversation_id = str(session_id or "").strip()
    if not conversation_id:
        raise s.SessionNotFoundError(s.text_for(lang, zh="未找到当前会话。", en="Session not found."))

    detail = s.get_session_detail(conversation_id)
    if detail is None:
        raise s.SessionNotFoundError(s.text_for(lang, zh="未找到当前会话。", en="Session not found."))

    if not s._is_session_running(conversation_id):
        return detail

    controller = s._get_session_turn_control(conversation_id)
    controller_was_restored = controller is None
    if controller_was_restored:
        controller = s._restore_missing_session_turn_control(conversation_id)
        s._set_session_running(conversation_id, True, turn_id=controller.turn_id)
    normalized_expected_turn_id = str(expected_turn_id or "").strip()
    if normalized_expected_turn_id and normalized_expected_turn_id != controller.turn_id:
        raise s.SessionBusyError(
            s.text_for(
                lang,
                zh="停止请求对应的轮次已不是当前运行轮次，请刷新后重试。",
                en="The requested turn is no longer the active turn. Refresh and try again.",
            )
        )

    controller.request_stop(
        s.text_for(
            lang,
            zh="操作者请求停止当前轮。",
            en="The operator requested this turn to stop.",
        )
    )
    stop_snapshot = controller.snapshot()
    queued_turn_cancelled = s._cancel_queued_session_turn(
        conversation_id,
        str(stop_snapshot.get("turnId") or controller.turn_id),
    )
    s._record_chat_next_state_signal(
        session_id=conversation_id,
        turn_id=str(stop_snapshot.get("turnId") or controller.turn_id),
        source="user",
        kind="user_stops",
        polarity="negative",
        mode="directive",
        related_event_code="conversation.user_stop_requested",
        summary=s.text_for(
            lang,
            zh="用户请求停止当前对话轮次。",
            en="The user requested the current chat turn to stop.",
        ),
        metadata={
            "stopReason": stop_snapshot.get("stopReason") or "",
            "stopRequestedAt": stop_snapshot.get("stopRequestedAt") or "",
        },
    )
    if queued_turn_cancelled or controller_was_restored:
        s._persist_session_interrupted_snapshot(
            conversation_id,
            stop_snapshot,
            lang=lang,
        )
        s._set_session_running(conversation_id, False, turn_id=controller.turn_id)
        controller.mark_released_to_user()
    s._publish_session_detail_snapshot(conversation_id)
    return s.get_session_detail(conversation_id) or detail


def _persist_session_interrupted_snapshot(
    session_id: str,
    stop_snapshot: dict[str, Any],
    *,
    lang: str,
) -> None:
    s = _service()
    reason = str(stop_snapshot.get("stopReason") or "").strip()
    turn_id = str(stop_snapshot.get("turnId") or "").strip()
    live_state = s._snapshot_session_live_output(session_id)
    live_content = s._sanitize_message_content("assistant", getattr(live_state, "content", "") if live_state else "")
    live_thought = s._sanitize_thought_text(getattr(live_state, "thought", "") if live_state else "")
    live_tools = s._normalize_message_tool_calls(getattr(live_state, "tool_calls", []) if live_state else [])
    live_feedback_events = s._normalize_message_feedback_events(getattr(live_state, "feedback_events", []) if live_state else [])
    live_feedback_events = s._extract_chat_feedback_events({"feedback_events": live_feedback_events}, final_status="stopped")
    live_mental = s._normalize_mental_snapshot(getattr(live_state, "mental_snapshot", None) if live_state else None)
    live_stage = str(getattr(live_state, "stage", "") if live_state else "").strip().lower()
    stop_text = s.text_for(
        lang,
        zh="本轮已按请求停止。可发送“继续”恢复这次未完成的任务。",
        en='This turn was stopped as requested. Send "continue" to resume the unfinished task.',
    )
    assistant_text = f"{live_content}\n\n{stop_text}".strip() if live_content else stop_text
    queued_before_worker = (
        live_stage == "queued"
        and not live_thought
        and not live_tools
        and live_mental is None
    )

    with s._CHAT_STATE_LOCK:
        payload = s.load_chat_state(s.PROJECT_ROOT)
        conversation = s._find_conversation_entry(payload, session_id)
        if conversation is None:
            return
        messages = s._session_ledger_visible_messages(session_id)
        if s._latest_assistant_message_is_stop(messages):
            conversation["last_turn_status"] = "ready"
            payload["updated_at"] = conversation.get("updated_at") or s._now_timestamp()
            s.save_chat_state(s.PROJECT_ROOT, payload)
            s._clear_session_live_output(session_id)
            return
        if queued_before_worker:
            stopped_at = str(stop_snapshot.get("stopRequestedAt") or "").strip() or s._now_timestamp()
            notice_message = s.text_for(
                lang,
                zh="本轮已按请求停止，尚未开始执行。",
                en="This turn was stopped before it started.",
            )
            conversation["runtime_notices"] = s._append_session_runtime_notice(
                conversation.get("runtime_notices") or conversation.get("runtimeNotices") or [],
                {
                    "kind": "turn_stopped",
                    "level": "info",
                    "message": notice_message,
                    "timestamp": stopped_at,
                    "source": "conversation.turn_stopped_before_start",
                    "turnId": turn_id,
                    "previousStatus": "queued",
                },
            )
            conversation["last_turn_status"] = "ready"
            conversation["updated_at"] = stopped_at
            payload["updated_at"] = stopped_at
            s.save_chat_state(s.PROJECT_ROOT, payload)
            s._persist_chat_turn_work_run(
                session_id=session_id,
                turn_id=turn_id,
                status="stopped",
                summary=notice_message,
                finished_at=stopped_at,
                updated_at=stopped_at,
            )
            s._clear_session_live_output(session_id)
            s._record_session_turn_lifecycle_event(
                session_id,
                "queued_stop_not_persisted",
                turn_id=turn_id,
                outcome="stopped",
                fields={
                    "reason": "queued_before_worker_start",
                    "messageCount": len(messages),
                },
            )
            s._append_session_conversation_event(
                session_id,
                turn_id,
                s.EVENT_TURN_INTERRUPTED,
                status="stopped",
                payload={
                    "reason": reason or "queued_before_worker_start",
                    "marker": s.TURN_INTERRUPTED_MARKER,
                    "summary": notice_message,
                },
                source="persist_interrupted_snapshot",
            )
            return
        existing_active_task = s._normalize_session_active_task(
            conversation.get("active_task") or conversation.get("activeTask")
        )
        stopped_result = {
            "status": "stopped",
            "summary": assistant_text,
            "raw_output": assistant_text,
            "thought": live_thought,
            "stop_requested": True,
            "stop_reason": reason,
            "outcome": "progress",
            "recommended_next_action": s.text_for(
                lang,
                zh="发送“继续”以恢复停止前的现场。",
                en='Send "continue" to resume from the stopped point.',
            ),
            "tool_call_count": len(live_tools),
            "tool_trace": live_tools,
            "feedback_events": live_feedback_events,
        }
        assistant_entry = s._make_chat_message(
            "assistant",
            assistant_text,
            live_tools,
            thought=live_thought,
            feedback_events=live_feedback_events,
            mental_snapshot=live_mental,
            metadata={"turnId": turn_id},
        )
        if live_tools:
            assistant_entry["toolCalls"] = live_tools
        if live_feedback_events:
            assistant_entry["feedbackEvents"] = live_feedback_events
        next_active_task = s._build_session_active_task(
            session_id,
            stopped_result,
            [*messages, assistant_entry],
            existing_task=existing_active_task,
        )
        s._set_or_clear_session_active_task(conversation, next_active_task)
        conversation.pop("messages", None)
        conversation["last_turn_status"] = "ready"
        conversation["updated_at"] = assistant_entry["timestamp"]
        payload["updated_at"] = assistant_entry["timestamp"]
        s.save_chat_state(s.PROJECT_ROOT, payload)
        s._persist_chat_turn_work_run(
            session_id=session_id,
            turn_id=turn_id,
            status="stopped",
            summary=assistant_text,
            finished_at=assistant_entry["timestamp"],
            updated_at=assistant_entry["timestamp"],
        )
    s._clear_session_live_output(session_id)
    s._record_session_cycle_message(
        session_id,
        assistant_entry,
        event="assistant_interrupted",
        status="stopped",
        active_task=next_active_task,
    )
    s._append_session_conversation_event(
        session_id,
        turn_id,
        s.EVENT_ASSISTANT_MESSAGE,
        status="stopped",
        payload={
            "content": assistant_text,
            "thought": live_thought,
            "toolCalls": live_tools,
            "feedbackEvents": live_feedback_events,
        },
        source="persist_interrupted_snapshot",
    )
    s._append_session_conversation_event(
        session_id,
        turn_id,
        s.EVENT_TURN_INTERRUPTED,
        status="stopped",
        payload={
            "reason": reason or "user_stop",
            "marker": s.TURN_INTERRUPTED_MARKER,
            "summary": assistant_text,
        },
        source="persist_interrupted_snapshot",
    )


def _append_stale_turn_interruption_if_session_inactive(
    session_id: str,
    turn_id: str,
    *,
    reason: str,
) -> Any | None:
    """Close a stale ledger turn only while no live turn can become active.

    Session detail hydration may start reconciliation just before a new submit
    marks the same session active.  Serialize the final liveness check with the
    running-session transition so reconciliation can never terminate that new
    turn after observing an older process-local snapshot.
    """
    s = _service()

    normalized_session_id = str(session_id or "").strip()
    normalized_turn_id = str(turn_id or "").strip()
    with s._RUNNING_SESSIONS_LOCK:
        if (
            normalized_session_id in s._RUNNING_SESSION_IDS
            or str(s._SESSION_ACTIVE_TURN_IDS.get(normalized_session_id) or "").strip()
        ):
            return None
        return s.append_conversation_event(
            s.PROJECT_ROOT,
            normalized_session_id,
            normalized_turn_id,
            s.EVENT_TURN_INTERRUPTED,
            status="interrupted",
            payload={
                "reason": str(reason or "process_restarted").strip() or "process_restarted",
                "marker": s.TURN_INTERRUPTED_MARKER,
            },
            source="session_service",
        )


def _build_auto_continue_paused_result(
    result: Any,
    visible_result: dict[str, Any] | None,
    turn_count: int,
    *,
    pause_reason: str = "internal_auto_continue_not_authorized",
    status: str = "needs_continue",
    fallback_visible: str = "",
    internal_auto_continue_blocked: bool = True,
    reached_limit: bool = False,
) -> Any:
    s = _service()
    if not isinstance(result, dict):
        return result
    merged = s._merge_continuation_visible_result(dict(result), visible_result)
    visible = s._visible_reply_summary_candidate(merged) if isinstance(merged, dict) else ""
    if not visible:
        visible = fallback_visible or "本轮还没有形成最终回答，已保留当前执行进度；发送“继续”可衔接上一轮继续。"
    paused = dict(merged)
    metadata = dict(paused.get("metadata") or {}) if isinstance(paused.get("metadata"), dict) else {}
    metadata.update(
        {
            "continuation_turn_count": turn_count,
            "internal_auto_continue_blocked": bool(internal_auto_continue_blocked),
            "continuation_pause_reason": str(pause_reason or "").strip() or "internal_auto_continue_not_authorized",
        }
    )
    if reached_limit:
        metadata["continuation_limit_reached"] = True
    else:
        metadata.pop("continuation_limit_reached", None)
    paused["metadata"] = metadata
    paused["status"] = str(status or "").strip() or "needs_continue"
    paused["outcome"] = "progress"
    paused["task_outcome"] = "progress"
    paused["recommended_next_action"] = paused.get("recommended_next_action") or "继续当前会话目标并汇总已有工具结果。"
    paused["summary"] = visible
    paused["raw_output"] = visible
    return paused


def _build_stopped_turn_result(reason: str) -> dict[str, Any]:
    return {
        "status": "stopped",
        "summary": "",
        "raw_output": "",
        "stop_requested": True,
        "stop_reason": str(reason or "").strip(),
        "tool_call_count": 0,
        "tool_trace": [],
    }
