"""Session turn stop / interrupt control helpers.

Claim scope: request_stop_session_turn, interrupted snapshot persistence, and
related paused/stopped turn result builders.

Agent purge/archive/child/inbox/cli lifecycle lives in ``agent_sessions.py``.
Late-bound facade keeps monkeypatches stable.
"""

from __future__ import annotations

import threading
from contextlib import contextmanager
from typing import Any


_RUNTIME_STOP_REASONS = frozenset({"electron_user_restart", "electron_user_close", "runtime_shutdown"})

#: Public read-only view of the runtime stop reasons. Lifecycle-stop recovery
#: sweeps (knowledge sideflow dead-turn gate) import this to recognize turns
#: killed by a workbench restart/close — those are machine-recoverable, while
#: an operator stop writes the ``user_stops`` chat signal instead (the two
#: paths are mutually exclusive). Do not mutate; it backs ``_RUNTIME_STOP_REASONS``.
RUNTIME_STOP_REASONS = _RUNTIME_STOP_REASONS

# 收割窗口上下文：进程级模块状态（非线程本地、非 contextvars）。user_close
# 的并行收割在新线程里执行各 owner 停止器，域内组件（资料搜集等）可能在任意
# 线程对会话回合发起无 stop_reason 的停止请求；只有模块级状态才能让整条收割
# 链路共享同一个窗口。栈结构支持嵌套（内层退出恢复外层值）。
_RUNTIME_STOP_REASON_LOCK = threading.Lock()
_ACTIVE_RUNTIME_STOP_REASONS: list[str] = []


def active_runtime_stop_reason() -> str:
    """当前收割窗口注入的运行时停止原因；空串表示没有活跃收割上下文。"""
    with _RUNTIME_STOP_REASON_LOCK:
        return _ACTIVE_RUNTIME_STOP_REASONS[-1] if _ACTIVE_RUNTIME_STOP_REASONS else ""


def _push_runtime_stop_reason(reason: str) -> None:
    with _RUNTIME_STOP_REASON_LOCK:
        _ACTIVE_RUNTIME_STOP_REASONS.append(str(reason or "").strip())


def _pop_runtime_stop_reason() -> None:
    with _RUNTIME_STOP_REASON_LOCK:
        if _ACTIVE_RUNTIME_STOP_REASONS:
            _ACTIVE_RUNTIME_STOP_REASONS.pop()


@contextmanager
def runtime_stop_reason_context(reason: str):
    """收割窗口上下文：窗口内无显式 stop_reason 的停止请求继承收割原因。

    退休收割（重启/关闭）触发的进程内停止请求可能不带 stop_reason，若按
    操作者默认文案处理，被杀回合会被永久误标为用户停止（写 ``user_stops``
    信号），证据门随对其 fail-closed。收割是进程级状态：进入窗口后，任何
    无显式原因的停止都继承这里的机器可识别原因，走 ``runtime_stop_requested``
    生命周期事件路径。Nesting-safe：内层退出恢复外层值。
    """
    normalized = str(reason or "").strip()
    _push_runtime_stop_reason(normalized)
    try:
        yield normalized
    finally:
        _pop_runtime_stop_reason()


def _stopped_turn_message(reason: str, *, lang: str, queued: bool = False) -> str:
    s = _service()
    if reason == "electron_user_restart":
        return s.text_for(
            lang,
            zh="本轮因工作台重启中断，尚未开始执行。" if queued else "本轮因工作台重启中断。",
            en="This turn was interrupted by a workbench restart before it started." if queued else "This turn was interrupted by a workbench restart.",
        )
    if reason in {"electron_user_close", "runtime_shutdown"}:
        return s.text_for(
            lang,
            zh="本轮因工作台关闭中断，尚未开始执行。" if queued else "本轮因工作台关闭中断。",
            en="This turn was interrupted by workbench shutdown before it started." if queued else "This turn was interrupted by workbench shutdown.",
        )
    return s.text_for(
        lang,
        zh="本轮已按请求停止，尚未开始执行。" if queued else "本轮已按请求停止。",
        en="This turn was stopped before it started." if queued else "This turn was stopped as requested.",
    )


def _service():
    from core.web.services import session_service

    return session_service


def request_stop_session_turn(
    session_id: str,
    *,
    expected_turn_id: str = "",
    fast_ack: bool = False,
    cascade: bool = True,
    stop_reason: str = "",
) -> dict:
    """Interrupt the active web chat turn after optional identity validation.

    Interactive HTTP callers always provide ``expected_turn_id``. Trusted
    internal shutdown paths may omit it to retain explicit stop-current
    behavior.

    ``stop_reason`` is reserved for trusted internal lifecycle callers. Public
    stop requests keep the existing operator-stop reason and signal.

    Signal the controller before any hydration. With ``fast_ack`` the
    running-turn stop is acknowledged without rebuilding session detail: the
    worker owns the stopped snapshot and publishes it once it observes the
    request (provider abort or the next cooperative checkpoint), so the HTTP
    response no longer scales with transcript size or projection congestion.
    Internal callers keep the hydrated-detail response by default.

    With ``cascade`` (the default) the active descendant task subtree — child
    sessions and background tasks registered under this session in the unified
    runtime task registry — is stopped and sealed so late completions cannot
    wake the settled turn. A session without active descendants behaves
    exactly as before.
    """
    s = _service()

    lang = s.get_web_language()
    conversation_id = str(session_id or "").strip()
    if not conversation_id:
        raise s.SessionNotFoundError(s.text_for(lang, zh="未找到当前会话。", en="Session not found."))

    if not s._is_session_running(conversation_id):
        detail = s.get_session_detail(conversation_id)
        if detail is None:
            raise s.SessionNotFoundError(s.text_for(lang, zh="未找到当前会话。", en="Session not found."))
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

    # 原因解析：显式 stop_reason 永远优先；为空且收割窗口活跃且其值属于
    # 运行时停止原因集合 → 继承收割原因（机器可识别，走 runtime 生命周期
    # 事件路径）；两者皆无 → 维持操作者默认文案与 user_stops 信号现状。
    normalized_stop_reason = str(stop_reason or "").strip()
    if not normalized_stop_reason:
        harvest_reason = active_runtime_stop_reason()
        if harvest_reason in _RUNTIME_STOP_REASONS:
            normalized_stop_reason = harvest_reason
    controller.request_stop(
        normalized_stop_reason or s.text_for(
            lang,
            zh="操作者请求停止当前轮。",
            en="The operator requested this turn to stop.",
        )
    )
    stop_snapshot = controller.snapshot()
    stop_turn_id = str(stop_snapshot.get("turnId") or controller.turn_id)
    effective_reason = str(stop_snapshot.get("stopReason") or "").strip()
    if cascade:
        # Explicit cancel of this turn closes the whole descendant subtree:
        # stop each active descendant task and seal its completion
        # notifications so a late return can never wake the settled turn.
        # Failures inside the cascade never fail the user-facing stop.
        try:
            _cascade_stop_descendant_runtime_tasks(
                conversation_id, turn_id=stop_turn_id,
                stop_reason=effective_reason if effective_reason in _RUNTIME_STOP_REASONS else "",
            )
        except Exception:
            pass
    queued_turn_cancelled = s._cancel_queued_session_turn(
        conversation_id,
        stop_turn_id,
    )
    if effective_reason in _RUNTIME_STOP_REASONS:
        s._record_session_turn_lifecycle_event(
            conversation_id, "runtime_stop_requested", turn_id=stop_turn_id,
            outcome="requested", fields={"source": effective_reason, "stopReason": effective_reason},
        )
    else:
        s._record_chat_next_state_signal(
            session_id=conversation_id,
            turn_id=stop_turn_id,
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
    else:
        if fast_ack:
            # The controller has the stop request; acknowledge before the
            # worker persists and publishes the authoritative stopped snapshot.
            return {
                "id": conversation_id,
                "currentPhase": "stopping",
                "stopRequested": True,
                "stopRequestedAt": str(stop_snapshot.get("stopRequestedAt") or ""),
                "activeTurnId": str(stop_snapshot.get("turnId") or controller.turn_id),
            }
    next_detail = s.get_session_detail(conversation_id)
    if next_detail is not None:
        s._publish_session_detail_snapshot(conversation_id, detail=next_detail)
        return next_detail
    s._publish_session_detail_snapshot(conversation_id)
    return {
        "id": conversation_id,
        "currentPhase": "stopping",
        "stopRequested": True,
        "activeTurnId": str(stop_snapshot.get("turnId") or controller.turn_id),
    }


def _cascade_stop_descendant_runtime_tasks(
    session_id: str, *, turn_id: str, stop_reason: str = "",
) -> list[dict[str, Any]]:
    """Stop and seal the active descendant task subtree of one session.

    The registry owns the ledger: targets are collected breadth-first via
    ``parentSessionId`` (child-session tasks recurse into their own session
    id, cycle-safe, depth-capped). Each target is sealed before it is stopped
    so its own settle-time return notification is already sealed when it
    fires. Child sessions go through the single-session stop primitive with
    ``cascade=False`` — their own subtree is already part of the collected
    list — while other task kinds get a ledger stop intent (no native worker
    cancel API exists for them yet). Every stopped task is annotated with
    ``cascadeStop`` audit fields and the whole manifest is reported to the
    caller for the session lifecycle event.
    """

    from .. import cli_agent_task_kernel, runtime_task_registry as runtime_tasks

    s = _service()
    root_session_id = str(session_id or "").strip()
    normalized_turn_id = str(turn_id or "").strip()
    if not root_session_id:
        return []
    store = runtime_tasks.default_store()
    targets = store.collect_cascade_targets(root_session_id)
    owner_session_depths = {root_session_id: 0}
    for target in targets:
        if target.get("kind") == runtime_tasks.KIND_CHILD_SESSION:
            owner_session_depths[str(target.get("taskId") or "").strip()] = int(target.get("cascadeDepth") or 0) + 1
    report: list[dict[str, Any]] = []
    for target in targets:
        task_id = str(target.get("taskId") or "").strip()
        kind = str(target.get("kind") or "").strip()
        entry: dict[str, Any] = {
            "taskId": task_id,
            "kind": kind,
            "cascadeDepth": target.get("cascadeDepth"),
            "stopResult": "",
            "sealed": False,
            "error": "",
        }
        try:
            store.seal_and_request_stop(
                task_id,
                reason=runtime_tasks.SEAL_REASON_PARENT_TURN_CANCELLED,
                turn_id=normalized_turn_id,
                cascaded_from=root_session_id,
                initiator="user",
            )
            entry["sealed"] = True
            if kind == runtime_tasks.KIND_CHILD_SESSION:
                request_stop_session_turn(task_id, cascade=False, stop_reason=stop_reason)
                entry["stopResult"] = "session_stop_requested"
            else:
                entry["stopResult"] = "stop_intent_recorded"
        except Exception as exc:
            entry["error"] = type(exc).__name__
        report.append(entry)
    report.extend(cli_agent_task_kernel.seal_cli_agent_task_notifications(
        owner_session_depths, turn_id=normalized_turn_id, cascaded_from=root_session_id,
    ))
    if not report:
        return []
    try:
        s._record_session_turn_lifecycle_event(
            root_session_id,
            "descendant_cascade_stop",
            turn_id=normalized_turn_id,
            outcome="requested",
            fields={
                "cascadedFrom": root_session_id,
                "targetCount": len(report),
                "targets": report,
            },
        )
    except Exception:
        pass
    return report


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
    stop_text = _stopped_turn_message(reason, lang=lang) + s.text_for(
        lang,
        zh="可发送“继续”恢复这次未完成的任务。",
        en=' Send "continue" to resume the unfinished task.',
    )
    assistant_text = f"{live_content}\n\n{stop_text}".strip() if live_content else stop_text
    queued_before_worker = (
        live_stage == "queued"
        and not live_thought
        and not live_tools
        and live_mental is None
    )

    with s._CHAT_STATE_LOCK:
        conversation = s.load_session_chat_state(s.PROJECT_ROOT, session_id)
        if conversation is None:
            return
        messages = s._session_ledger_visible_messages(session_id)
        if s._latest_assistant_message_is_stop(messages):
            conversation["last_turn_status"] = "ready"
            conversation["last_turn_terminal_turn_id"] = turn_id
            conversation["last_turn_terminal_reason"] = s._terminal_reason_for_turn(
                "ready",
                stop_requested=True,
            )
            conversation.setdefault("updated_at", s._now_timestamp())
            s.save_session_chat_state(s.PROJECT_ROOT, session_id, conversation)
            s._clear_session_live_output(session_id)
            return
        if queued_before_worker:
            stopped_at = str(stop_snapshot.get("stopRequestedAt") or "").strip() or s._now_timestamp()
            notice_message = _stopped_turn_message(reason, lang=lang, queued=True)
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
            # ``ready`` is the idle phase, not the outcome of this turn. Keep
            # the explicit stop reason so projections and notifications cannot
            # infer a successful completion from the idle phase.
            conversation["last_turn_status"] = "ready"
            conversation["last_turn_terminal_turn_id"] = turn_id
            conversation["last_turn_terminal_reason"] = s._terminal_reason_for_turn(
                "ready",
                stop_requested=True,
            )
            conversation["updated_at"] = stopped_at
            s.save_session_chat_state(s.PROJECT_ROOT, session_id, conversation)
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
        conversation["last_turn_terminal_turn_id"] = turn_id
        conversation["last_turn_terminal_reason"] = s._terminal_reason_for_turn(
            "ready",
            stop_requested=True,
        )
        conversation["updated_at"] = assistant_entry["timestamp"]
        s.save_session_chat_state(s.PROJECT_ROOT, session_id, conversation)
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
    s._append_session_reasoning_item_if_needed(
        session_id,
        turn_id,
        live_thought,
        source="persist_interrupted_snapshot",
    )
    s._append_missing_canonical_result_items(session_id, turn_id, assistant_entry)
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
