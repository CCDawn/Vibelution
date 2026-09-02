"""Session turn diagnostics: errors, work-runs, review candidates, reconcile hooks.

Claim scope: turn error recording/messages, chat-turn work-run persistence,
kernel traces, stale ledger reconcile, session reference resolution, and
post-turn SC stage reconcile bridge.

Late-bound facade keeps monkeypatches stable.
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.web.services.session.timebase import parse_timestamp_utc


def _service():
    from core.web.services import session_service

    return session_service


def _reconcile_stale_session_ledger(session_id: str, *, active_turn_id: str = "", reason: str = "process_restarted") -> None:
    s = _service()
    normalized_session_id = str(session_id or "").strip()
    if not normalized_session_id:
        return
    if s._is_session_running(normalized_session_id):
        return
    recovered_from_checkpoint_only = False
    event_turn_id = ""
    try:
        events = s._load_session_conversation_events_cached(normalized_session_id)
        checkpoint = s._load_session_live_output_checkpoint(normalized_session_id)
        turn_id = s.latest_open_turn_id(events)
        checkpoint_turn_id = str(getattr(checkpoint, "turn_id", "") or "").strip() if checkpoint is not None else ""
        checkpoint_payload = s._live_output_checkpoint_payload(checkpoint) if checkpoint is not None else {}
        checkpoint_has_assistant_payload = s._live_output_checkpoint_has_assistant_payload(checkpoint_payload)
        if not turn_id and checkpoint_turn_id and s._session_events_have_terminal_turn(events, checkpoint_turn_id):
            s._discard_session_live_output_state(normalized_session_id, turn_id=checkpoint_turn_id)
            return
        if not turn_id and checkpoint_turn_id and not checkpoint_has_assistant_payload:
            return
        if not turn_id and checkpoint_turn_id:
            turn_id = checkpoint_turn_id
            recovered_from_checkpoint_only = True
        if not turn_id:
            s._discard_session_live_output_state(normalized_session_id)
            return
        if active_turn_id and turn_id == str(active_turn_id or "").strip():
            return
        # Detail hydration can run in a process that does not own the worker.
        # The exact persisted chat-turn WorkRun is the cross-process authority;
        # a single global activeRunId cannot represent concurrent sessions.
        if s._active_chat_turn_work_run_for_session(normalized_session_id, turn_id=turn_id) is not None:
            return
        if checkpoint is not None and (not checkpoint.turn_id or checkpoint.turn_id == turn_id):
            payload = checkpoint_payload
            if checkpoint_has_assistant_payload:
                s._persist_recovered_live_output_to_chat_state(normalized_session_id, turn_id, checkpoint)
                s._append_session_reasoning_item_if_needed(
                    normalized_session_id,
                    turn_id,
                    str(payload.get("thought") or ""),
                    source="recover_live_output_checkpoint",
                )
                s._append_missing_canonical_result_items(
                    normalized_session_id,
                    turn_id,
                    {"toolCalls": list(payload.get("toolCalls") or [])},
                )
                s._append_session_conversation_event(
                    normalized_session_id,
                    turn_id,
                    s.EVENT_ASSISTANT_MESSAGE,
                    status="interrupted",
                    payload={
                        "content": str(payload.get("content") or ""),
                        "thought": str(payload.get("thought") or ""),
                        "toolCalls": list(payload.get("toolCalls") or []),
                        "feedbackEvents": list(payload.get("feedbackEvents") or []),
                        "metadata": {
                            "interrupted": True,
                            "recoveredFromLiveOutputCheckpoint": True,
                        },
                    },
                    source="recover_live_output_checkpoint",
                )
        event = s._append_stale_turn_interruption_if_session_inactive(
            normalized_session_id,
            turn_id,
            reason=reason,
        )
        if event is None:
            return
        event_turn_id = str(event.turn_id or turn_id)
        s._invalidate_session_conversation_events_cache(normalized_session_id)
        s._discard_session_live_output_state(normalized_session_id, turn_id=turn_id)
    except Exception:
        return
    try:
        s.record_runtime_scene_event(
            "conversation",
            "conversation_ledger",
            "conversation.ledger.reconciled_interrupted",
            level="warning",
            outcome="interrupted",
            message="Reconciled an open chat ledger turn as interrupted.",
            fields={
                "sessionId": normalized_session_id,
                "turnId": event_turn_id,
                "reason": reason,
                "recoveredFromCheckpointOnly": recovered_from_checkpoint_only,
            },
            lifecycle=True,
        )
    except Exception:
        return


# Mirror projection's ephemeral tool-event bubble kinds; completion must not treat
# these compatibility shells as turn-scoped assistant prose.
_COMPLETION_SNAPSHOT_INTERMEDIATE_TOOL_EVENT_KINDS = frozenset(
    {
        "tool_result",
        "tool_call_started",
        "cli_task_result",
        "cli_task_sent",
        "cli_session_lifecycle",
    }
)


def _completion_snapshot_rejects_intermediate_tool_event_assistant(
    message: dict[str, Any] | None,
) -> bool:
    """True when the selected assistant row is only a tool-journal compatibility shell."""

    if not isinstance(message, dict):
        return False
    metadata = message.get("metadata") if isinstance(message.get("metadata"), dict) else {}
    kind = str(metadata.get("kind") or "").strip().lower()
    return kind in _COMPLETION_SNAPSHOT_INTERMEDIATE_TOOL_EVENT_KINDS


def get_session_turn_completion_snapshot(session_id: str, turn_id: str = "") -> dict[str, Any]:
    """Return a turn-scoped completion snapshot for external harness pollers."""
    s = _service()

    normalized_session_id = str(session_id or "").strip()
    normalized_turn_id = str(turn_id or "").strip()
    if not normalized_session_id:
        return {
            "sessionId": "",
            "turnId": normalized_turn_id,
            "terminal": False,
            "terminalStatus": "",
            "completionSource": "missing_session_id",
            "completionRecovered": False,
            "assistantText": "",
            "lastTurnStatus": "",
            "messageCount": 0,
            "isRunning": False,
            "activeTurnId": "",
            "turnCurrent": False,
        }

    with s._RUNNING_SESSIONS_LOCK:
        is_running = normalized_session_id in s._RUNNING_SESSION_IDS
        active_turn_id = str(s._SESSION_ACTIVE_TURN_IDS.get(normalized_session_id) or "").strip()
    turn_current = bool(is_running and (not normalized_turn_id or active_turn_id == normalized_turn_id))

    with s._CHAT_STATE_LOCK:
        try:
            s.reconcile_stale_chat_turn_work_runs()
        except Exception:
            pass
        conversation = s.load_session_chat_state(s.PROJECT_ROOT, normalized_session_id)
        if conversation is not None and s._repair_stale_running_conversation(conversation):
            s.save_session_chat_state(s.PROJECT_ROOT, normalized_session_id, conversation)
        if conversation is None:
            return {
                "sessionId": normalized_session_id,
                "turnId": normalized_turn_id,
                "terminal": False,
                "terminalStatus": "",
                "completionSource": "missing_conversation",
                "completionRecovered": False,
                "assistantText": "",
                "lastTurnStatus": "",
                "messageCount": 0,
                "isRunning": is_running,
                "activeTurnId": active_turn_id,
                "turnCurrent": turn_current,
            }
        try:
            from core.chat.turn_journal import (
                read_model_invocation_receipts_from_events,
            )

            model_invocation_receipts = read_model_invocation_receipts_from_events(
                s._load_session_conversation_events_cached(normalized_session_id),
                turn_id=normalized_turn_id,
            )
        except Exception:
            # Receipt audit readback must never break ordinary chat diagnostics.
            model_invocation_receipts = []
        last_turn_status = str(conversation.get("last_turn_status") or conversation.get("lastTurnStatus") or "").strip().lower()
        terminal_problem_code = str(
            conversation.get("last_turn_terminal_problem_code")
            or conversation.get("lastTurnTerminalProblemCode")
            or conversation.get("terminalProblemCode")
            or ""
        ).strip()[:128]
        terminal_reason = str(
            conversation.get("last_turn_terminal_reason")
            or conversation.get("lastTurnTerminalReason")
            or conversation.get("terminalReason")
            or ""
        ).strip()[:256]
        messages = s._session_ledger_visible_messages(session_id)

    assistant_message = s._find_turn_scoped_assistant_message(messages, normalized_turn_id)
    if _completion_snapshot_rejects_intermediate_tool_event_assistant(assistant_message):
        assistant_message = None
    assistant_text = str((assistant_message or {}).get("content") or "").strip()
    if not assistant_text and assistant_message:
        from core.web.services.session.session_ops import _turn_items_visible_text

        assistant_text = _turn_items_visible_text(assistant_message).strip()
    assistant_turn_id = s._message_turn_id(assistant_message)
    marker_present = s._supervised_completion_marker_present(assistant_text)
    terminal_statuses = {
        "ready",
        "completed",
        "done",
        "success",
        "failed",
        "failed_provider",
        "failed_runtime",
        "paused_limit",
        "stopped",
        "stopped_by_user",
        "cancelled",
        "needs_continue",
        "superseded",
    }
    terminal = False
    terminal_status = ""
    completion_source = "running"
    completion_recovered = False
    # "ready" is the session's idle marker and is ALSO written by stop handling
    # and stale restart repair (`_repair_stale_running_conversation`) when a
    # turn was killed mid-flight.  A turn-scoped poller must therefore only
    # accept "ready" as terminal when the conversation anchors its last real
    # settlement (`last_turn_terminal_turn_id`) to the requested turn.  All
    # other statuses keep their explicit terminal meaning.
    terminal_anchor_turn_id = str(
        conversation.get("last_turn_terminal_turn_id") or ""
    ).strip()
    ready_trusted = last_turn_status != "ready" or (
        normalized_turn_id
        and terminal_anchor_turn_id
        and terminal_anchor_turn_id == normalized_turn_id
    )
    if last_turn_status in terminal_statuses and ready_trusted:
        terminal = True
        terminal_status = last_turn_status
        completion_source = "last_turn_status"
    elif marker_present and assistant_text and not turn_current:
        terminal = True
        terminal_status = "ready"
        completion_source = "assistant_marker"
        completion_recovered = True
    snapshot = {
        "sessionId": normalized_session_id,
        "turnId": normalized_turn_id,
        "terminal": terminal,
        "terminalStatus": terminal_status,
        "completionSource": completion_source,
        "completionRecovered": completion_recovered,
        "assistantText": assistant_text,
        "assistantMessageFound": assistant_message is not None,
        "assistantTurnId": assistant_turn_id,
        "lastTurnStatus": last_turn_status,
        "messageCount": len(messages),
        "isRunning": is_running,
        "activeTurnId": active_turn_id,
        "turnCurrent": turn_current,
    }
    assistant_metadata = (
        assistant_message.get("metadata")
        if isinstance(assistant_message, dict)
        and isinstance(assistant_message.get("metadata"), dict)
        else {}
    )
    continuation_pause_reason = str(
        assistant_metadata.get("continuation_pause_reason") or ""
    ).strip()
    if continuation_pause_reason:
        snapshot["continuationPauseReason"] = continuation_pause_reason
    try:
        continuation_no_progress_count = max(
            0,
            int(assistant_metadata.get("continuation_no_progress_count") or 0),
        )
    except (TypeError, ValueError):
        continuation_no_progress_count = 0
    if continuation_no_progress_count:
        snapshot["continuationNoProgressCount"] = continuation_no_progress_count
    if "continuation_progress_advanced" in assistant_metadata:
        snapshot["continuationProgressAdvanced"] = bool(
            assistant_metadata.get("continuation_progress_advanced")
        )
    if terminal_problem_code:
        snapshot["terminalProblemCode"] = terminal_problem_code
    if terminal_reason:
        snapshot["terminalReason"] = terminal_reason
    if model_invocation_receipts:
        snapshot["modelInvocationReceipts"] = deepcopy(model_invocation_receipts)
        snapshot["modelInvocationReceipt"] = deepcopy(model_invocation_receipts[-1])
    return snapshot


def create_chat_review_candidate_from_session(session_id: str) -> dict:
    """Create a pending supervised review candidate from a persisted chat session."""
    s = _service()

    lang = s.get_web_language()
    conversation_id = str(session_id or "").strip()
    if not conversation_id:
        raise s.SessionValidationError(s.text_for(lang, zh="会话 ID 不能为空。", en="Session id is required."))

    _, conversations = s._load_conversations()
    conversation = next(
        (item for item in conversations if str(item.get("id") or "").strip() == conversation_id),
        None,
    )
    if conversation is None:
        raise s.SessionNotFoundError(s.text_for(lang, zh="未找到当前会话。", en="Session not found."))

    stop_requested = s._is_session_stop_requested(conversation_id)
    if s._is_session_running(conversation_id) or stop_requested:
        s._record_session_chat_review_candidate_event(
            "blocked",
            session_id=conversation_id,
            outcome="busy",
            level="warning",
            fields={"stopRequested": bool(stop_requested)},
        )
        raise s.SessionBusyError(
            s.text_for(
                lang,
                zh="当前会话仍在运行或停止中，结束后再添加到监督评审队列。",
                en="This session is still running or stopping. Add it to review after the turn closes.",
            )
        )

    messages = s._session_ledger_visible_messages(conversation_id)
    turns = s._build_chat_turn_records_from_messages(messages)
    if len(turns) < 1:
        s._record_session_chat_review_candidate_event(
            "blocked",
            session_id=conversation_id,
            outcome="no_complete_turn",
            level="warning",
            fields={"messageCount": len(messages), "turnCount": len(turns)},
        )
        raise s.SessionValidationError(
            s.text_for(
                lang,
                zh="这个会话还没有完整的用户-助手轮次，不能加入监督评审队列。",
                en="This session does not have a complete user-assistant turn yet.",
            )
        )

    service = s.ChatDatasetCaptureService(project_root=s.PROJECT_ROOT)
    try:
        candidate = service.capture_candidate(
            mode="chat",
            session_id=conversation_id,
            source_log_path=s._resolve_chat_source_log_path(),
            turns=turns,
            require_auto_capture=False,
            apply_quality_filters=False,
            min_turns=1,
            max_turns=len(turns),
        )
    except Exception as exc:
        s._record_session_chat_review_candidate_event(
            "failed",
            session_id=conversation_id,
            outcome="failed",
            level="error",
            fields={
                "messageCount": len(messages),
                "turnCount": len(turns),
                "errorType": exc.__class__.__name__,
            },
        )
        raise

    if candidate is None:
        capture_enabled = bool(getattr(service.config.evolution.chat_dataset, "enabled", False))
        s._record_session_chat_review_candidate_event(
            "blocked",
            session_id=conversation_id,
            outcome="duplicate" if capture_enabled else "capture_disabled",
            level="warning",
            fields={"messageCount": len(messages), "turnCount": len(turns)},
        )
        if not capture_enabled:
            raise s.SessionValidationError(
                s.text_for(
                    lang,
                    zh="当前配置未启用 chat 数据采集，不能加入监督评审队列。",
                    en="Chat dataset capture is disabled in the current configuration.",
                )
            )
        raise s.SessionChatReviewCandidateExistsError(
            s.text_for(
                lang,
                zh="这段会话快照已经生成过监督评审样本，刷新评审工作区即可查看当前状态。",
                en="This session snapshot already has a supervised review sample. Refresh the review workspace to see its current state.",
            )
        )

    s._record_session_chat_review_candidate_event(
        "created",
        session_id=conversation_id,
        outcome="created",
        fields={
            "candidateId": candidate.candidate_id,
            "turnCount": candidate.turn_count,
            "qualitySignals": candidate.quality_signals,
            "rawExcerptPath": candidate.raw_excerpt_path,
        },
    )
    return {
        "candidateId": candidate.candidate_id,
        "status": "pending",
        "sessionId": candidate.session_id,
        "topicSummary": candidate.topic_summary,
        "turnCount": candidate.turn_count,
        "qualitySignals": candidate.quality_signals,
        "rawExcerptPath": candidate.raw_excerpt_path,
        "summary": s.text_for(
            lang,
            zh="已加入监督进化会话评审队列，等待人工判定正例、负例或丢弃。",
            en="Added to the supervised chat review queue for human review.",
        ),
    }


_LAST_SUBMIT_KERNEL_TRACE_FUTURE = None


def _enqueue_direct_session_submit_kernel_trace(
    conversation: dict[str, Any],
    *,
    agent: dict[str, Any] | None,
    turn_id: str,
    message: str,
    source: str,
):
    """Run Kernel submit audit off the accept path (traceOnly).

    Returns a Future when scheduled on the cycle executor (tests may .result()).
    """

    global _LAST_SUBMIT_KERNEL_TRACE_FUTURE
    s = _service()
    conversation_copy = dict(conversation or {}) if isinstance(conversation, dict) else {}
    agent_copy = dict(agent or {}) if isinstance(agent, dict) else {}
    turn_id_value = str(turn_id or "").strip()
    message_value = str(message or "")
    source_value = str(source or "").strip()

    def _run() -> dict[str, Any]:
        return _create_direct_session_submit_kernel_trace(
            conversation_copy,
            agent=agent_copy,
            turn_id=turn_id_value,
            message=message_value,
            source=source_value,
        )

    executor = getattr(s, "_SESSION_CYCLE_PROJECTION_EXECUTOR", None)
    submit = getattr(executor, "submit", None)
    if callable(submit):
        future = submit(_run)
        _LAST_SUBMIT_KERNEL_TRACE_FUTURE = future
        return future
    # Fallback: still never raise into the submit accept path.
    try:
        result = _run()
    except Exception:
        result = {}
    _LAST_SUBMIT_KERNEL_TRACE_FUTURE = None
    return result


def _await_last_submit_kernel_trace(timeout: float = 5.0) -> dict[str, Any] | None:
    """Test helper: wait for the most recently enqueued submit kernel trace."""

    future = _LAST_SUBMIT_KERNEL_TRACE_FUTURE
    if future is None:
        return None
    result = getattr(future, "result", None)
    if not callable(result):
        return future if isinstance(future, dict) else None
    try:
        return result(timeout=timeout)
    except TypeError:
        return result()


def _create_direct_session_submit_kernel_trace(
    conversation: dict[str, Any],
    *,
    agent: dict[str, Any] | None,
    turn_id: str,
    message: str,
    source: str,
) -> dict[str, Any]:
    s = _service()
    normalized_source = str(source or "").strip() or "raw"
    if normalized_source in {"agent_inbox", "hot_restart_resume", "supervised_evolution"}:
        return {}
    if not isinstance(conversation, dict) or not isinstance(agent, dict):
        return {}
    session_id = str(conversation.get("id") or conversation.get("conversation_id") or "").strip()
    normalized_turn_id = str(turn_id or "").strip()
    agent_id = str(conversation.get("agent_id") or conversation.get("agentId") or agent.get("agentId") or "").strip()
    if not session_id or not normalized_turn_id or not agent_id:
        return {}
    if str(agent.get("agentId") or "").strip() != agent_id:
        return {}
    # directSessionId may be missing on minimal snapshots used by deferred enqueue;
    # only enforce when present.
    direct_session_id = str(agent.get("directSessionId") or "").strip()
    if direct_session_id and direct_session_id != session_id:
        return {}

    content = str(message or "").strip()
    if not content:
        content = f"Direct session turn {normalized_turn_id}"
    content_hash = hashlib.sha256(content.encode("utf-8", errors="replace")).hexdigest()[:16]
    event_payload = {
        "eventId": f"session-submit-{session_id}-{normalized_turn_id}",
        "sender": {"type": "user", "id": "session_submit"},
        "recipientAgentIds": [agent_id],
        "semanticType": "agent.session_submit",
        "payload": {
            "goal": f"Direct session turn {normalized_turn_id}",
            "sessionId": session_id,
            "turnId": normalized_turn_id,
            "messageSource": normalized_source,
            "contentLength": len(content),
            "contentHash": content_hash,
        },
        "correlationId": f"session:{session_id}",
        "idempotencyKey": f"session-submit:{session_id}:{normalized_turn_id}",
        "wakeTarget": False,
        "traceOnly": True,
        "metadata": {
            "sourceSurface": "session_submit",
            "sourceSessionId": session_id,
            "sourceMessageId": normalized_turn_id,
            "projectionRef": {"kind": "session_turn", "id": normalized_turn_id},
            "adapterVersion": "session-submit-kernel-bridge-v1",
            "source": normalized_source,
            "targetAgentId": agent_id,
            "agentId": agent_id,
            "messageContentHash": content_hash,
            "messageContentLength": len(content),
        },
    }
    try:
        from core.agent_kernel import service as agent_kernel_service

        if getattr(agent_kernel_service, "s.PROJECT_ROOT", s.PROJECT_ROOT) != Path(__file__).resolve().parents[3]:
            agent_kernel_service.PROJECT_ROOT = Path(__file__).resolve().parents[3]
        result = agent_kernel_service.handle_kernel_event(event_payload)
    except Exception as exc:
        trace = {
            "source": "agent_kernel",
            "traceOnly": True,
            "status": "failed",
            "sourceSurface": "session_submit",
            "errorType": type(exc).__name__,
            "reason": s.trim_lines(str(exc), max_lines=2),
        }
        s._record_direct_session_submit_kernel_trace_event(
            conversation,
            trace,
            turn_id=normalized_turn_id,
            agent_id=agent_id,
            source=normalized_source,
            level="warning",
            outcome="failed",
        )
        return trace

    event = result.get("event") if isinstance(result.get("event"), dict) else {}
    task = result.get("task") if isinstance(result.get("task"), dict) else {}
    execution = result.get("execution") if isinstance(result.get("execution"), dict) else {}
    outcome_payload = result.get("outcome") if isinstance(result.get("outcome"), dict) else {}
    trace = {
        "source": "agent_kernel",
        "sourceSurface": "session_submit",
        "traceOnly": True,
        "status": "recorded",
        "eventId": str(event.get("eventId") or "").strip(),
        "taskId": str(task.get("taskId") or "").strip(),
        "workRunId": str(execution.get("workRunId") or "").strip(),
        "outcomeId": str(outcome_payload.get("outcomeId") or "").strip(),
        "outcomeStatus": str(outcome_payload.get("status") or task.get("status") or "").strip(),
        "reused": bool(result.get("reused")),
    }
    s._record_direct_session_submit_kernel_trace_event(
        conversation,
        trace,
        turn_id=normalized_turn_id,
        agent_id=agent_id,
        source=normalized_source,
        outcome=trace["outcomeStatus"] or "succeeded",
    )
    return trace


def _record_direct_session_submit_kernel_trace_event(
    conversation: dict[str, Any],
    kernel_trace: dict[str, Any],
    *,
    turn_id: str,
    agent_id: str,
    source: str,
    level: str = "info",
    outcome: str = "observed",
) -> None:
    s = _service()
    try:
        s.record_runtime_scene_event(
            "conversation",
            "kernel",
            (
                "session.submit.kernel_trace_recorded"
                if str(kernel_trace.get("status") or "").strip() == "recorded"
                else "session.submit.kernel_trace_failed"
            ),
            message="Direct Agent session submit Kernel trace.",
            level=level,
            outcome=outcome,
            fields={
                "sessionId": str(conversation.get("id") or conversation.get("conversation_id") or "").strip(),
                "turnId": str(turn_id or "").strip(),
                "agentId": str(agent_id or "").strip(),
                "source": str(source or "").strip(),
                "kernelTraceOnly": bool(kernel_trace.get("traceOnly", True)),
                "kernelTraceStatus": str(kernel_trace.get("status") or "").strip(),
                "kernelEventId": str(kernel_trace.get("eventId") or "").strip(),
                "kernelTaskId": str(kernel_trace.get("taskId") or "").strip(),
                "kernelWorkRunId": str(kernel_trace.get("workRunId") or "").strip(),
                "kernelOutcomeId": str(kernel_trace.get("outcomeId") or "").strip(),
                "kernelOutcomeStatus": str(kernel_trace.get("outcomeStatus") or "").strip(),
                "reused": bool(kernel_trace.get("reused")),
                "errorType": str(kernel_trace.get("errorType") or "").strip(),
                "reason": str(kernel_trace.get("reason") or "").strip(),
            },
            lifecycle=True,
        )
    except Exception:
        return


def _active_chat_turn_work_run_id_for_session(session_id: str) -> str:
    s = _service()
    active = s._WORK_RUN_STORE.load_active_snapshot("chat_turn")
    if not isinstance(active, dict):
        return ""
    active_session_id = str(active.get("sessionId") or "").strip()
    if active_session_id and active_session_id != session_id:
        return ""
    return str(active.get("runId") or "").strip()


def _release_stale_chat_turn_work_run(*, session_id: str, finished_at: str, summary: str) -> None:
    """Clear a persisted active chat_turn when its in-memory worker is gone."""
    s = _service()

    active = s._WORK_RUN_STORE.load_active_snapshot("chat_turn")
    if not isinstance(active, dict):
        return
    active_session_id = str(active.get("sessionId") or "").strip()
    if active_session_id and active_session_id != session_id:
        return
    run_id = str(active.get("runId") or "").strip()
    if not run_id:
        return
    status = str(active.get("status") or active.get("currentPhase") or "").strip().lower()
    if status not in {"queued", "running", "stopping", "paused"}:
        return
    s._persist_chat_turn_work_run(
        session_id=session_id,
        turn_id=run_id,
        status="stopped",
        summary=summary,
        finished_at=finished_at,
        updated_at=finished_at,
    )
    try:
        s.record_runtime_scene_event(
            "conversation",
            "turn_recovery",
            "conversation.turn_recovered",
            level="warning",
            outcome="stopped",
            message=summary or "Stale chat turn recovered.",
            fields={
                "sessionId": session_id,
                "turnId": run_id,
                "previousStatus": status,
            },
            lifecycle=True,
        )
    except Exception:
        return


# C1: tool-timeout hang and absolute stale running work-run settlement.
_CHAT_TURN_TOOL_TIMEOUT_HANG_SECONDS = 180.0
_CHAT_TURN_ABSOLUTE_STALE_SECONDS = 30.0 * 60.0
# A worker_gone verdict (in-memory running registration absent/mismatched) must
# not settle a *young* snapshot: the running set is process-local and volatile
# (restart, stop-request cooperative window, submit cleanup paths), while the
# persisted work-run snapshot is the cross-process authority.  Give any
# registration-visibility gap a bounded recovery window before killing the run.
_CHAT_TURN_WORKER_GONE_GRACE_SECONDS = 120.0


def _parse_work_run_timestamp(value: Any) -> datetime | None:
    # Naive timestamps come from the legacy _now_timestamp() local-time writer;
    # parse_timestamp_utc treats them as machine-local and converts to UTC.
    return parse_timestamp_utc(value)


def _chat_turn_last_tool_error_timed_out(payload: dict[str, Any]) -> bool:
    last_tool_error = payload.get("lastToolError") if isinstance(payload.get("lastToolError"), dict) else {}
    if not last_tool_error:
        return False
    if bool(last_tool_error.get("timedOut") or last_tool_error.get("timed_out")):
        return True
    failure_class = str(last_tool_error.get("failureClass") or last_tool_error.get("failure_class") or "").strip().lower()
    if failure_class in {"timeout", "timed_out", "tool_timeout"}:
        return True
    summary = str(last_tool_error.get("summary") or last_tool_error.get("errorPreview") or "").lower()
    return "timeout" in summary or "超时" in summary


def _chat_turn_work_run_hang_reason(
    payload: dict[str, Any],
    *,
    now: datetime,
    worker_owns_turn: bool,
) -> str:
    """Return a non-empty reason code when a chat_turn work-run should be force-settled."""
    status = str(payload.get("status") or payload.get("currentPhase") or "").strip().lower()
    if status not in {"queued", "running", "stopping", "paused"}:
        return ""
    if str(payload.get("finishedAt") or payload.get("endedAt") or "").strip():
        return ""

    updated = _parse_work_run_timestamp(payload.get("updatedAt") or payload.get("startedAt") or "")
    started = _parse_work_run_timestamp(payload.get("startedAt") or payload.get("updatedAt") or "")
    tool_error = payload.get("lastToolError") if isinstance(payload.get("lastToolError"), dict) else {}
    tool_error_at = _parse_work_run_timestamp(tool_error.get("updatedAt") if tool_error else "")

    # Worker gone: disk still says running → settle only after the grace
    # window.  A missing in-process registration alone does not prove the
    # worker is gone (process-local visibility gap, stop-request cooperative
    # window, restart recovery); a young snapshot gets the benefit of the
    # doubt exactly like `_stale_running_live_owner_reason` does for the
    # stale-running repair path.
    if not worker_owns_turn:
        anchor = updated or started
        if anchor is not None and (now - anchor).total_seconds() < _CHAT_TURN_WORKER_GONE_GRACE_SECONDS:
            return ""
        return "worker_gone"

    # Worker still claims the turn but tool timeout hang left no progress.
    if _chat_turn_last_tool_error_timed_out(payload) and tool_error_at is not None:
        if (now - tool_error_at).total_seconds() >= _CHAT_TURN_TOOL_TIMEOUT_HANG_SECONDS:
            return "tool_timeout_hang"

    # Absolute ceiling for any running chat_turn (defensive).
    anchor = updated or started
    if anchor is not None and (now - anchor).total_seconds() >= _CHAT_TURN_ABSOLUTE_STALE_SECONDS:
        return "absolute_stale"

    return ""


def _revive_registration_from_turn_control(payload: dict[str, Any], *, run_id: str, session_id: str) -> bool:
    """Re-arm a lost running registration when the live turn control still owns the run.

    The running set / active-turn map is process-local and volatile, while the
    SessionTurnControl is created at submit and cleared only at terminal.  When
    the control still holds this run and no stop was requested, the worker is
    provably alive: restore the registration the reconcile depends on instead of
    settling a live turn (self-healing visibility gap, e.g. after an
    unconditional `_set_session_running(False)` cleanup path or a restart race).
    Returns True when the registration was revived and the run must not settle.
    """

    s = _service()
    try:
        control = s._get_session_turn_control(session_id)
    except Exception:
        return False
    if control is None:
        return False
    if str(getattr(control, "turn_id", "") or "").strip() != run_id:
        return False
    if bool(getattr(control, "stop_requested", False)):
        return False
    status = str(payload.get("status") or payload.get("currentPhase") or "").strip().lower()
    if status != "running":
        return False
    leases = payload.get("leases") if isinstance(payload.get("leases"), list) else []
    s._set_session_running(session_id, True, turn_id=run_id, leases=[str(item) for item in leases] or None)
    try:
        s.record_runtime_scene_event(
            "conversation",
            "turn_recovery",
            "conversation.stale_run_registration_revived",
            level="warning",
            outcome="revived",
            message="Restored a lost running registration for a live chat turn.",
            fields={
                "sessionId": session_id,
                "turnId": run_id,
            },
            lifecycle=True,
        )
    except Exception:
        pass
    return True


def _settle_stale_chat_turn_work_run(
    payload: dict[str, Any],
    *,
    reason: str,
    now: datetime | None = None,
) -> dict[str, Any] | None:
    """Force a stuck chat_turn to a terminal work-run status and clear session running flags."""
    s = _service()
    run_id = str(payload.get("runId") or payload.get("roundId") or payload.get("id") or "").strip()
    session_id = str(payload.get("sessionId") or "").strip()
    if not run_id or not session_id:
        return None
    finished_at = (now or datetime.now(timezone.utc)).isoformat()
    previous_status = str(payload.get("status") or payload.get("currentPhase") or "running").strip().lower()
    if reason == "tool_timeout_hang":
        status = "failed_runtime"
        summary = s.text_for(
            s.get_web_language(),
            zh="工具超时后长时间无进展，本轮已自动收口为失败，可继续发送消息。",
            en="This turn was auto-closed after a tool timeout with no further progress. You can continue the session.",
        )
    elif reason == "absolute_stale":
        status = "failed_runtime"
        summary = s.text_for(
            s.get_web_language(),
            zh="本轮运行时间过长且无收口，已自动标记失败以便继续对话。",
            en="This turn ran too long without closing and was auto-marked failed so chat can continue.",
        )
    else:
        status = "stopped"
        summary = s.text_for(
            s.get_web_language(),
            zh="会话 worker 已结束，已清除残留运行态。",
            en="Session worker finished; cleared residual running state.",
        )
    prior_summary = str(payload.get("summary") or "").strip()
    if prior_summary and prior_summary not in summary:
        summary = f"{prior_summary} [{summary}]"

    s._persist_chat_turn_work_run(
        session_id=session_id,
        turn_id=run_id,
        status=status,
        summary=summary,
        finished_at=finished_at,
        updated_at=finished_at,
        error_type="StaleChatTurnSettled",
        error=reason,
    )
    try:
        s._set_session_running(session_id, False, turn_id=run_id)
        s._clear_session_turn_control(session_id, turn_id=run_id)
    except Exception:
        pass
    try:
        with s._CHAT_STATE_LOCK:
            conversation = s.load_session_chat_state(s.PROJECT_ROOT, session_id)
            if conversation is not None:
                conversation["last_turn_status"] = status
                conversation["updated_at"] = finished_at
                conversation["runtime_notices"] = s._append_session_runtime_notice(
                    conversation.get("runtime_notices") or conversation.get("runtimeNotices") or [],
                    {
                        "kind": "turn_recovered",
                        "level": "warning",
                        "message": summary,
                        "timestamp": finished_at,
                        "source": "conversation.turn_recovered",
                        "turnId": run_id,
                        "previousStatus": previous_status,
                        "reason": reason,
                    },
                )
                s.save_session_chat_state(s.PROJECT_ROOT, session_id, conversation)
    except Exception:
        pass
    try:
        s._publish_session_detail_snapshot(session_id)
    except Exception:
        pass
    try:
        s.record_runtime_scene_event(
            "conversation",
            "turn_recovery",
            "conversation.turn_recovered",
            level="warning",
            outcome=status,
            message=summary,
            fields={
                "sessionId": session_id,
                "turnId": run_id,
                "previousStatus": previous_status,
                "reason": reason,
            },
            lifecycle=True,
        )
    except Exception:
        pass
    return {
        "runId": run_id,
        "sessionId": session_id,
        "status": status,
        "reason": reason,
    }


_RECONCILE_STALE_CHAT_TURN_LOCK = threading.Lock()
_RECONCILE_STALE_CHAT_TURN_DEPTH = 0


def reconcile_stale_chat_turn_work_runs(*, now: datetime | None = None) -> list[dict[str, Any]]:
    """Settle chat_turn work-runs left running after worker death or tool-timeout hang (C1)."""
    global _RECONCILE_STALE_CHAT_TURN_DEPTH
    # Prevent re-entry from publish/detail projection triggered by settlement.
    with _RECONCILE_STALE_CHAT_TURN_LOCK:
        if _RECONCILE_STALE_CHAT_TURN_DEPTH > 0:
            return []
        _RECONCILE_STALE_CHAT_TURN_DEPTH += 1
    try:
        s = _service()
        clock = now or datetime.now(timezone.utc)
        settled: list[dict[str, Any]] = []
        seen_run_ids: set[str] = set()

        candidates: list[dict[str, Any]] = []
        active = s._WORK_RUN_STORE.load_active_snapshot("chat_turn")
        if isinstance(active, dict):
            candidates.append(active)
        try:
            # Bound scan: active + recent index only (avoid loading hundreds of historical runs).
            for snapshot in s._WORK_RUN_STORE.list_snapshots("chat_turn", limit=40):
                if not isinstance(snapshot, dict):
                    continue
                status = str(snapshot.get("status") or snapshot.get("currentPhase") or "").strip().lower()
                if status not in {"queued", "running", "stopping", "paused"}:
                    continue
                if str(snapshot.get("finishedAt") or snapshot.get("endedAt") or "").strip():
                    continue
                candidates.append(snapshot)
        except Exception:
            pass

        with s._RUNNING_SESSIONS_LOCK:
            running_session_ids = set(s._RUNNING_SESSION_IDS)
            active_turn_ids = dict(s._SESSION_ACTIVE_TURN_IDS)
        try:
            # Queued turns are held by the scheduler, not the running set; a
            # queued snapshot still owned by the queue must not be settled.
            queued_scheduler_turns = s._SESSION_TURN_SCHEDULER.queued_session_turn_ids()
        except Exception:
            queued_scheduler_turns = set()

        for payload in candidates:
            run_id = str(payload.get("runId") or payload.get("roundId") or payload.get("id") or "").strip()
            session_id = str(payload.get("sessionId") or "").strip()
            if not run_id or run_id in seen_run_ids:
                continue
            seen_run_ids.add(run_id)
            worker_owns_turn = (
                bool(session_id)
                and session_id in running_session_ids
                and str(active_turn_ids.get(session_id) or "").strip() == run_id
            ) or (bool(session_id) and (session_id, run_id) in queued_scheduler_turns)
            if not worker_owns_turn and _revive_registration_from_turn_control(
                payload,
                run_id=run_id,
                session_id=session_id,
            ):
                # Live turn control still owns the run: the registration gap was
                # a visibility problem, not a dead worker.  Healed above.
                continue
            reason = _chat_turn_work_run_hang_reason(
                payload,
                now=clock,
                worker_owns_turn=worker_owns_turn,
            )
            if not reason:
                continue
            result = _settle_stale_chat_turn_work_run(payload, reason=reason, now=clock)
            if result:
                settled.append(result)
        return settled
    finally:
        with _RECONCILE_STALE_CHAT_TURN_LOCK:
            _RECONCILE_STALE_CHAT_TURN_DEPTH = max(0, _RECONCILE_STALE_CHAT_TURN_DEPTH - 1)


def _complete_turn_error_visible_content(content: Any, metadata: dict[str, Any]) -> str:
    s = _service()
    visible = str(content or "").strip()
    reason_summary = str(metadata.get("reasonSummary") or metadata.get("reason_summary") or "").strip()
    reason_detail = str(metadata.get("reasonDetail") or metadata.get("reason_detail") or "").strip()
    http_status = s._coerce_nonnegative_int(metadata.get("httpStatus") or metadata.get("http_status"))
    provider_error_type = str(metadata.get("providerErrorType") or metadata.get("provider_error_type") or "").strip()
    provider_error_message = str(metadata.get("providerErrorMessage") or metadata.get("provider_error_message") or "").strip()
    if reason_summary:
        visible = visible.replace("原因：provider 返回了错误。", f"原因：{reason_summary}。")
        visible = visible.replace("Reason: the provider returned an error.", f"Reason: {reason_summary}.")
    if reason_summary and reason_summary not in visible:
        visible = f"{visible} 原因：{reason_summary}。".strip()
    if s._provider_error_detail_safe_for_chat(reason_detail) and reason_detail not in visible:
        visible = f"{visible} 具体报错：{reason_detail}。".strip()
    diagnostics: list[str] = []
    if http_status > 0:
        diagnostics.append(f"HTTP {http_status}")
    if provider_error_type:
        diagnostics.append(provider_error_type)
    if (
        s._provider_error_detail_safe_for_chat(provider_error_message)
        and provider_error_message not in visible
    ):
        diagnostics.append(provider_error_message)
    if diagnostics:
        diagnostic_line = " / ".join(diagnostics)
        if diagnostic_line not in visible:
            visible = f"{visible} 上游诊断：{diagnostic_line}。".strip()
    return visible


def _provider_error_detail_safe_for_chat(reason_detail: Any) -> bool:
    s = _service()
    detail = str(reason_detail or "").strip()
    if not detail:
        return False
    lower = detail.lower()
    if any(marker in lower for marker in ("reasoning_content", "authorization", "bearer ", "api_key", "apikey", "token", "secret")):
        return False
    if "sk-" in lower:
        return False
    return len(detail) <= 180


def _normalize_session_references(value: Any) -> list[dict[str, Any]]:
    s = _service()
    references: list[dict[str, Any]] = []
    for raw in list(value or []):
        if not isinstance(raw, dict):
            continue
        session_id = str(raw.get("sessionId") or raw.get("session_id") or "").strip()
        if not session_id:
            continue
        reference_id = str(raw.get("referenceId") or raw.get("reference_id") or f"session:{session_id}").strip()
        item = {
            "referenceId": reference_id,
            "kind": "session",
            "sessionId": session_id,
            "title": s.trim_lines(raw.get("title") or session_id, max_lines=1),
            "agentId": str(raw.get("agentId") or raw.get("agent_id") or "").strip(),
            "agentCode": str(raw.get("agentCode") or raw.get("agent_code") or "").strip(),
            "agentDisplayName": s.trim_lines(raw.get("agentDisplayName") or raw.get("agent_display_name") or "", max_lines=1),
            "summary": s.trim_lines(raw.get("summary") or "", max_lines=2),
            "createdAt": str(raw.get("createdAt") or raw.get("created_at") or "").strip(),
        }
        if not any(existing.get("referenceId") == item["referenceId"] for existing in references):
            references.append(item)
    return references[:6]


def _resolve_session_references(
    current_session_id: str,
    references: Any,
    *,
    conversations: list[dict[str, Any]],
    lang: str,
) -> list[dict[str, Any]]:
    s = _service()
    normalized = s._normalize_session_references(references)
    if not normalized:
        return []
    by_id = {
        str(item.get("id") or item.get("conversation_id") or "").strip(): item
        for item in list(conversations or [])
        if isinstance(item, dict) and str(item.get("id") or item.get("conversation_id") or "").strip()
    }
    resolved: list[dict[str, Any]] = []
    for reference in normalized:
        target_id = str(reference.get("sessionId") or "").strip()
        target = by_id.get(target_id)
        if target is None:
            raise s.SessionValidationError(
                s.text_for(
                    lang,
                    zh=f"会话引用无效：找不到目标会话 {target_id}。",
                    en=f"Invalid session reference: target session {target_id} was not found.",
                )
            )
        s._ensure_conversation_agent_metadata(target)
        agent_id = str(target.get("agent_id") or target.get("agentId") or reference.get("agentId") or "").strip()
        agent = s.get_agent(agent_id) if agent_id else None
        if agent_id and agent is None:
            raise s.SessionValidationError(
                s.text_for(
                    lang,
                    zh=f"会话引用无效：目标会话 {target_id} 绑定的 Agent {agent_id} 不存在。",
                    en=f"Invalid session reference: target session {target_id} references missing Agent {agent_id}.",
                )
            )
        if isinstance(agent, dict) and str(agent.get("status") or "").strip() == "archived":
            raise s.SessionValidationError(
                s.text_for(
                    lang,
                    zh=f"会话引用无效：目标会话 {target_id} 的 Agent 已归档。",
                    en=f"Invalid session reference: target session {target_id} belongs to an archived Agent.",
                )
            )
        title = s.trim_lines(reference.get("title") or target.get("title") or target_id, max_lines=1)
        summary = s.trim_lines(
            reference.get("summary")
            or s._latest_message_summary(
                s._normalize_messages(
                    target_id,
                    s._ledger_visible_messages_for_session(target_id),
                )
            ),
            max_lines=2,
        )
        resolved.append(
            {
                **reference,
                "referenceId": str(reference.get("referenceId") or f"session:{target_id}").strip(),
                "sessionId": target_id,
                "title": title,
                "agentId": agent_id,
                "agentCode": str(target.get("agent_code") or target.get("agentCode") or reference.get("agentCode") or "").strip(),
                "agentDisplayName": s.trim_lines(
                    target.get("agent_display_name")
                    or target.get("agentDisplayName")
                    or (agent or {}).get("name")
                    or reference.get("agentDisplayName")
                    or "",
                    max_lines=1,
                ),
                "summary": summary,
                "currentSession": target_id == str(current_session_id or "").strip(),
                "permissions": {
                    "query": True,
                    "sendMessage": False,
                    "sendRequiresExplicitUserIntent": True,
                },
            }
        )
    return resolved


def _active_chat_turn_work_run_for_session(
    session_id: str,
    *,
    turn_id: str = "",
) -> dict[str, Any] | None:
    s = _service()
    normalized_session_id = str(session_id or "").strip()
    normalized_turn_id = str(turn_id or "").strip()
    if not normalized_session_id:
        return None
    with s._RUNNING_SESSIONS_LOCK:
        active_turn_id = str(s._SESSION_ACTIVE_TURN_IDS.get(normalized_session_id) or "").strip()
    candidates: list[dict[str, Any]] = []
    if normalized_turn_id:
        snapshot = s._WORK_RUN_STORE.load_snapshot("chat_turn", normalized_turn_id)
        if isinstance(snapshot, dict):
            candidates.append(snapshot)
    if active_turn_id:
        snapshot = s._WORK_RUN_STORE.load_snapshot("chat_turn", active_turn_id)
        if isinstance(snapshot, dict):
            candidates.append(snapshot)
    active = s._WORK_RUN_STORE.load_active_snapshot("chat_turn")
    if isinstance(active, dict):
        candidates.append(active)
    try:
        candidates.extend(s._WORK_RUN_STORE.list_snapshots("chat_turn", limit=40))
    except (OSError, ValueError):
        pass
    seen_run_ids: set[str] = set()
    for snapshot in candidates:
        if not isinstance(snapshot, dict):
            continue
        run_id = str(snapshot.get("runId") or snapshot.get("roundId") or snapshot.get("id") or "").strip()
        if not run_id or run_id in seen_run_ids:
            continue
        seen_run_ids.add(run_id)
        if str(snapshot.get("sessionId") or "").strip() != normalized_session_id:
            continue
        if normalized_turn_id and run_id != normalized_turn_id:
            continue
        status = str(snapshot.get("status") or snapshot.get("currentPhase") or "").strip().lower()
        finished_at = str(snapshot.get("finishedAt") or snapshot.get("endedAt") or "").strip()
        if status in {"queued", "running", "stopping", "paused"} and not finished_at:
            return dict(snapshot)
    return None


def list_active_session_work_runs(*, reconcile: bool = True) -> list[dict[str, Any]]:
    """Return active web chat turns as lightweight WorkRun lease snapshots."""
    s = _service()
    if reconcile:
        try:
            reconcile_stale_chat_turn_work_runs()
        except Exception:
            pass

    with s._RUNNING_SESSIONS_LOCK:
        session_ids = sorted(s._RUNNING_SESSION_IDS)
        active_turn_ids = dict(s._SESSION_ACTIVE_TURN_IDS)
        active_leases = {key: list(value) for key, value in s._SESSION_ACTIVE_TURN_LEASES.items()}
    try:
        queued_scheduler_turns = s._SESSION_TURN_SCHEDULER.queued_session_turn_ids()
    except Exception:
        queued_scheduler_turns = set()
    active_statuses = s._active_session_work_run_statuses(session_ids)
    items: list[dict[str, Any]] = []
    for session_id in session_ids:
        run_id = active_turn_ids.get(session_id) or f"chat-turn-{session_id}"
        # Submit marks the session running before the scheduler admits it; a
        # turn still held in a scheduler queue must stay visibly "queued"
        # instead of being projected as running.
        status = (
            "queued"
            if (session_id, run_id) in queued_scheduler_turns
            else active_statuses.get(session_id) or "running"
        )
        item: dict[str, Any] = {
            "runId": run_id,
            "runKind": "chat_turn",
            "sessionId": session_id,
            "status": status,
            "currentPhase": status,
            "leases": active_leases.get(session_id) or ["readonly_chat"],
        }
        snapshot = s._WORK_RUN_STORE.load_snapshot("chat_turn", run_id) or {}
        user_message = str(snapshot.get("userMessage") or "").strip()
        summary = str(snapshot.get("summary") or "").strip()
        if user_message:
            item["userMessage"] = user_message
        if summary:
            item["summary"] = summary
        last_tool_error = snapshot.get("lastToolError")
        if isinstance(last_tool_error, dict) and last_tool_error:
            item["lastToolError"] = last_tool_error
        items.append(item)

    # Turns may also sit in persisted work-run snapshots without holding a
    # running-set entry (their submit-time `running` marker was demoted by
    # `_mark_session_turn_queued`); project those as queued too so runtime
    # summary consumers never lose a waiting turn.
    covered_session_ids = {str(item.get("sessionId") or "") for item in items}
    seen_run_ids = {str(item.get("runId") or "") for item in items}
    try:
        recent_snapshots = s._WORK_RUN_STORE.list_snapshots("chat_turn", limit=40)
    except Exception:
        recent_snapshots = []
    for queued_snapshot in recent_snapshots:
        if not isinstance(queued_snapshot, dict):
            continue
        if str(queued_snapshot.get("status") or queued_snapshot.get("currentPhase") or "").strip().lower() != "queued":
            continue
        if str(queued_snapshot.get("finishedAt") or queued_snapshot.get("endedAt") or "").strip():
            continue
        run_id = str(queued_snapshot.get("runId") or "").strip()
        session_id = str(queued_snapshot.get("sessionId") or "").strip()
        if not run_id or not session_id or run_id in seen_run_ids or session_id in covered_session_ids:
            continue
        item = {
            "runId": run_id,
            "runKind": "chat_turn",
            "sessionId": session_id,
            "status": "queued",
            "currentPhase": "queued",
            "leases": list(queued_snapshot.get("leases") or ["readonly_chat"]),
        }
        user_message = str(queued_snapshot.get("userMessage") or "").strip()
        summary = str(queued_snapshot.get("summary") or "").strip()
        if user_message:
            item["userMessage"] = user_message
        if summary:
            item["summary"] = summary
        last_tool_error = queued_snapshot.get("lastToolError")
        if isinstance(last_tool_error, dict) and last_tool_error:
            item["lastToolError"] = last_tool_error
        items.append(item)
    return items


def _active_session_work_run_statuses(session_ids: list[str]) -> dict[str, str]:
    """Map live session ids to a work-run status without touching chat_state.

    Runtime summary polls this on the hot path while submit/select hold
    ``_CHAT_STATE_LOCK``. The in-memory running set already selected
    ``session_ids``; queued/stopping can stay ``running`` for lease/UI dots.
    """
    return {
        session_id: "running"
        for session_id in session_ids
        if str(session_id or "").strip()
    }


def load_chat_turn_work_run_summary() -> dict[str, Any]:
    s = _service()
    try:
        reconcile_stale_chat_turn_work_runs()
    except Exception:
        pass
    active_items = list_active_session_work_runs(reconcile=False)
    active = s._WORK_RUN_STORE.load_active_snapshot("chat_turn")
    if not active and active_items:
        active = active_items[0]
    return {
        "active": active,
        "activeItems": active_items,
        "latest": s._WORK_RUN_STORE.load_latest_snapshot("chat_turn"),
    }


def _persist_chat_turn_work_run(
    *,
    session_id: str,
    turn_id: str,
    status: str,
    agent_id: str = "",
    leases: list[str] | None = None,
    user_message: str = "",
    summary: str = "",
    error_type: str = "",
    error: str = "",
    started_at: str = "",
    updated_at: str = "",
    finished_at: str = "",
    last_tool_error: dict[str, Any] | None = None,
) -> None:
    s = _service()
    normalized_turn_id = str(turn_id or "").strip()
    if not normalized_turn_id:
        return
    now = s._now_timestamp()
    previous = s._WORK_RUN_STORE.load_snapshot("chat_turn", normalized_turn_id) or {}
    started = str(started_at or previous.get("startedAt") or now).strip()
    finished = str(finished_at or previous.get("finishedAt") or "").strip()
    normalized_status = str(status or previous.get("status") or "running").strip().lower() or "running"
    if normalized_status in {"running", "stopping"}:
        active_run_id = normalized_turn_id
    elif normalized_status == "queued":
        active_run_id = s._replacement_active_chat_turn_id(exclude_turn_id=normalized_turn_id) or normalized_turn_id
    else:
        active_run_id = s._replacement_active_chat_turn_id(exclude_turn_id=normalized_turn_id)
    payload = {
        **previous,
        "runId": normalized_turn_id,
        "runKind": "chat_turn",
        "track": "dialogue",
        "sessionId": str(session_id or previous.get("sessionId") or "").strip(),
        "agentId": str(agent_id or previous.get("agentId") or "").strip(),
        "status": normalized_status,
        "currentPhase": normalized_status,
        "leases": list(leases or previous.get("leases") or ["readonly_chat"]),
        "userMessage": str(user_message or previous.get("userMessage") or "").strip(),
        "summary": str(summary or previous.get("summary") or "").strip(),
        "errorType": str(error_type or previous.get("errorType") or "").strip(),
        "error": str(error or previous.get("error") or "").strip(),
        "startedAt": started,
        "updatedAt": str(updated_at or now).strip(),
        "finishedAt": finished
        if normalized_status
        in {
            "completed",
            "failed",
            "failed_provider",
            "failed_runtime",
            "stopped",
            "cancelled",
            "paused_limit",
            "needs_continue",
            "stopped_by_user",
            "superseded",
        }
        else "",
    }
    if isinstance(last_tool_error, dict) and last_tool_error:
        timed_out = bool(last_tool_error.get("timedOut") or last_tool_error.get("timed_out"))
        failure_class = str(last_tool_error.get("failureClass") or last_tool_error.get("failure_class") or "").strip()
        if not timed_out and failure_class.lower() in {"timeout", "timed_out", "tool_timeout"}:
            timed_out = True
        payload["lastToolError"] = {
            "toolName": s.trim_lines(str(last_tool_error.get("toolName") or ""), max_lines=1),
            "summary": s.trim_lines(str(last_tool_error.get("summary") or ""), max_lines=2),
            "errorPreview": s.trim_lines(str(last_tool_error.get("errorPreview") or ""), max_lines=2),
            "relatedEventCode": s.trim_lines(str(last_tool_error.get("relatedEventCode") or ""), max_lines=1),
            "timedOut": timed_out,
            "failureClass": s.trim_lines(failure_class or ("timeout" if timed_out else ""), max_lines=1),
            "updatedAt": str(last_tool_error.get("updatedAt") or now).strip(),
        }
    s._WORK_RUN_STORE.persist_snapshot("chat_turn", payload, active_run_id=active_run_id)


def _reconcile_source_collection_stage_task_after_turn(
    metadata: dict[str, str],
    *,
    session_id: str,
    turn_id: str,
    final_status: str,
    llm_usage: dict[str, Any] | None = None,
) -> None:
    s = _service()
    if not isinstance(metadata, dict) or not metadata:
        return
    team_id = str(metadata.get("teamId") or "").strip()
    task_id = str(metadata.get("taskId") or "").strip()
    if not team_id or not task_id:
        return
    try:
        from core.web.services import team_workflow_orchestration_service

        result = team_workflow_orchestration_service.reconcile_source_collection_stage_session_task_after_turn(
            team_id,
            task_id,
            run_id=str(metadata.get("runId") or "").strip(),
            session_id=session_id,
            turn_id=turn_id,
            final_status=final_status,
            llm_usage=llm_usage,
            reason=f"session_turn_{final_status or 'completed'}",
        )
    except Exception as exc:  # pragma: no cover - defensive, session persistence must not fail here
        s._record_session_turn_lifecycle_event(
            session_id,
            "source_collection_stage_task_reconcile_failed",
            turn_id=turn_id,
            level="warning",
            outcome="failed",
            fields={
                "teamId": team_id,
                "taskId": task_id,
                "runId": str(metadata.get("runId") or "").strip(),
                "finalStatus": str(final_status or "").strip(),
                "errorType": type(exc).__name__,
                "error": s.trim_lines(str(exc), max_lines=2),
            },
        )
        return
    if not isinstance(result, dict) or not bool(result.get("changed")):
        return
    s._record_session_turn_lifecycle_event(
        session_id,
        "source_collection_stage_task_reconciled",
        turn_id=turn_id,
        outcome=str(result.get("taskStatus") or "reconciled").strip() or "reconciled",
        fields={
            "teamId": team_id,
            "runId": str(result.get("runId") or metadata.get("runId") or "").strip(),
            "taskId": task_id,
            "stageId": str(metadata.get("stageId") or "").strip(),
            "agentId": str(metadata.get("agentId") or "").strip(),
            "agentRole": str(metadata.get("agentRole") or "").strip(),
            "finalStatus": str(final_status or "").strip(),
            "previousTaskStatus": str(result.get("previousTaskStatus") or "").strip(),
            "taskStatus": str(result.get("taskStatus") or "").strip(),
            "completionGatePassed": bool(result.get("completionGatePassed")),
            "taskChecklistComplete": bool(result.get("taskChecklistComplete")),
            "artifactComplete": bool(result.get("artifactComplete")),
        },
    )


def _make_local_runtime_turn_error(
    raw_error: Any,
    *,
    lang: str,
    error_type: str,
    reason_code: str,
    reason_summary: str,
    reason_detail: str = "",
    turn_id: str = "",
    model: str = "",
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    s = _service()
    normalized_reason_summary = s.trim_lines(reason_summary, max_lines=2)
    normalized_reason_detail = s.trim_lines(reason_detail or raw_error, max_lines=4)
    message = s.text_for(
        lang,
        zh="运行提示：本轮没有进入模型调用，因为本地 Agent 模型槽位无法解析。",
        en="Runtime notice: this turn did not reach the model call because the local Agent model slot could not be resolved.",
    )
    if normalized_reason_summary:
        message = f"{message} 原因：{normalized_reason_summary}。" if lang == "zh" else f"{message} Reason: {normalized_reason_summary}."
    payload: dict[str, Any] = {
        "message": message,
        "error_type": str(error_type or "runtime_error").strip() or "runtime_error",
        "reason_code": str(reason_code or "").strip(),
        "reason_summary": normalized_reason_summary,
        "reason_detail": normalized_reason_detail,
        "http_status": 0,
        "provider": "",
        "provider_host": "",
        "provider_error_type": "",
        "provider_error_message": "",
        "model": str(model or "").strip(),
        "recoverable": False,
        "timestamp": s._now_timestamp(),
        "turn_id": str(turn_id or "").strip(),
    }
    if extra:
        payload["extra"] = {str(key): value for key, value in extra.items() if str(key or "").strip()}
    return payload


def _record_session_turn_error(
    session_id: str,
    turn_error: dict[str, Any],
    *,
    raw_error: str = "",
    status: str = "failed",
    active_task: dict[str, Any] | None = None,
) -> None:
    s = _service()
    timestamp = str(turn_error.get("timestamp") or s._now_timestamp()).strip()
    error_type = str(turn_error.get("error_type") or turn_error.get("errorType") or "runtime_error").strip()
    message = {
        "role": "system",
        "content": str(turn_error.get("message") or "").strip(),
        "timestamp": timestamp,
        "error_type": error_type,
        "turn_id": str(turn_error.get("turn_id") or turn_error.get("turnId") or "").strip(),
    }
    s._append_session_workspace_log(
        session_id,
        message,
        event="turn_error",
        status=status,
        active_task=active_task,
    )
    try:
        s.record_runtime_scene_event(
            "conversation",
            "turn_error",
            "conversation.turn_error",
            level="error",
            outcome=status,
            message=str(turn_error.get("message") or "Conversation turn failed."),
            fields={
                "sessionId": str(session_id or "").strip(),
                "turnId": str(turn_error.get("turn_id") or turn_error.get("turnId") or "").strip(),
                "errorType": error_type,
                "reasonCode": str(turn_error.get("reason_code") or turn_error.get("reasonCode") or "").strip(),
                "reasonSummary": str(turn_error.get("reason_summary") or turn_error.get("reasonSummary") or "").strip(),
                "reasonDetail": str(turn_error.get("reason_detail") or turn_error.get("reasonDetail") or "").strip(),
                "httpStatus": s._coerce_nonnegative_int(turn_error.get("http_status") or turn_error.get("httpStatus")) or None,
                "provider": str(turn_error.get("provider") or "").strip(),
                "providerHost": str(turn_error.get("provider_host") or turn_error.get("providerHost") or "").strip(),
                "providerErrorType": str(turn_error.get("provider_error_type") or turn_error.get("providerErrorType") or "").strip(),
                "providerErrorMessage": str(turn_error.get("provider_error_message") or turn_error.get("providerErrorMessage") or "").strip(),
                "model": str(turn_error.get("model") or "").strip(),
                "chainStage": str(turn_error.get("chain_stage") or turn_error.get("chainStage") or "").strip(),
                "eventCode": str(turn_error.get("event_code") or turn_error.get("eventCode") or "").strip(),
                "traceId": str(turn_error.get("trace_id") or turn_error.get("traceId") or "").strip(),
                "protocol": str(turn_error.get("protocol") or "").strip(),
                "recoverable": bool(turn_error.get("recoverable", True)),
                "rawErrorPreview": s.trim_lines(raw_error, max_lines=2),
            },
            child_log_path=f"conversations/{s._safe_session_workspace_token(session_id)}-errors.jsonl",
            child_log_payload={
                "session_id": str(session_id or "").strip(),
                "turn_id": str(turn_error.get("turn_id") or turn_error.get("turnId") or "").strip(),
                "status": status,
                "error_type": error_type,
                "message": str(turn_error.get("message") or "").strip(),
                "reason_code": str(turn_error.get("reason_code") or turn_error.get("reasonCode") or "").strip(),
                "reason_summary": str(turn_error.get("reason_summary") or turn_error.get("reasonSummary") or "").strip(),
                "reason_detail": str(turn_error.get("reason_detail") or turn_error.get("reasonDetail") or "").strip(),
                "http_status": s._coerce_nonnegative_int(turn_error.get("http_status") or turn_error.get("httpStatus")) or 0,
                "provider": str(turn_error.get("provider") or "").strip(),
                "provider_host": str(turn_error.get("provider_host") or turn_error.get("providerHost") or "").strip(),
                "provider_error_type": str(turn_error.get("provider_error_type") or turn_error.get("providerErrorType") or "").strip(),
                "provider_error_message": str(turn_error.get("provider_error_message") or turn_error.get("providerErrorMessage") or "").strip(),
                "model": str(turn_error.get("model") or "").strip(),
                "chain_stage": str(turn_error.get("chain_stage") or turn_error.get("chainStage") or "").strip(),
                "event_code": str(turn_error.get("event_code") or turn_error.get("eventCode") or "").strip(),
                "trace_id": str(turn_error.get("trace_id") or turn_error.get("traceId") or "").strip(),
                "protocol": str(turn_error.get("protocol") or "").strip(),
                "recoverable": bool(turn_error.get("recoverable", True)),
            },
        )
    except Exception as exc:
        s._debug_logger.warning(
            f"runtime scene turn error log skipped: {type(exc).__name__}: {exc}",
            tag="LOGS",
        )


def _record_session_turn_circuit_breaker_event(
    session_id: str,
    result: Any,
    *,
    turn_id: str = "",
    turn_index: int,
) -> None:
    s = _service()
    if not isinstance(result, dict):
        return
    llm_failure = result.get("llm_failure") if isinstance(result.get("llm_failure"), dict) else {}
    raw_error = s._provider_failure_raw_error(result)
    error_type = s._failure_error_type(raw_error)
    try:
        s.record_runtime_scene_event(
            "conversation",
            "turn_circuit_breaker",
            "conversation.turn_circuit_breaker",
            level="error",
            outcome="failed",
            message="Chat turn stopped after provider failure budget was exhausted.",
            fields={
                "sessionId": str(session_id or "").strip(),
                "errorType": error_type,
                "llmFailureCategory": str(llm_failure.get("category") or "").strip(),
                "retryable": bool(llm_failure.get("retryable", True)),
                "attempts": s._coerce_nonnegative_int(llm_failure.get("attempts") or 0),
                "maxAttempts": s._coerce_nonnegative_int(llm_failure.get("max_attempts") or 0),
                "consecutiveFailures": s._coerce_nonnegative_int(llm_failure.get("consecutive_failures") or 0),
                "continuationTurn": max(0, int(turn_index or 0)),
                "stopReason": s.trim_lines(llm_failure.get("stop_reason") or "", max_lines=2),
                "rawErrorPreview": s.trim_lines(raw_error, max_lines=2),
            },
            child_log_path=f"conversations/{s._safe_session_workspace_token(session_id)}-circuit-breaker.jsonl",
            child_log_payload={
                "session_id": str(session_id or "").strip(),
                "error_type": error_type,
                "llm_failure": dict(llm_failure),
                "continuation_turn": max(0, int(turn_index or 0)),
                "raw_error": s.trim_lines(raw_error, max_lines=6),
            },
            lifecycle=True,
        )
    except Exception as exc:
        s._debug_logger.warning(
            f"runtime scene circuit breaker log skipped: {type(exc).__name__}: {exc}",
            tag="LOGS",
        )
    s._record_provider_failure_signal(
        session_id=session_id,
        turn_id=str(turn_id or "").strip(),
        error_type=error_type,
        raw_error=raw_error,
        related_event_code="conversation.turn_circuit_breaker",
        metadata={
            "continuationTurn": max(0, int(turn_index or 0)),
        },
    )


def _append_session_workspace_log(
    session_id: str,
    message: dict[str, Any],
    *,
    event: str,
    status: str,
    active_task: dict[str, Any] | None = None,
) -> None:
    s = _service()
    try:
        workspace = s._ensure_session_workspace(session_id)
        logs_dir = workspace / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        role = str(message.get("role") or "").strip().lower() or "message"
        record = {
            "timestamp": str(message.get("timestamp") or s._now_timestamp()).strip(),
            "session_id": str(session_id or "").strip(),
            "event": str(event or "message").strip() or "message",
            "status": str(status or "").strip(),
            "role": role,
            "content": s._sanitize_message_content(role, message.get("content") or ""),
            "thought": s._sanitize_thought_text(message.get("thought") or ""),
            "mental_snapshot": s._normalize_mental_snapshot(message.get("mental_snapshot") or message.get("mentalSnapshot")),
            "attachments": s._safe_attachment_log_summary(
                message.get("attachments") or message.get("imageAttachments") or []
            ),
            "tool_calls": s._normalize_persisted_tool_calls(
                message.get("tool_calls") or message.get("toolCalls") or []
            ),
            "feedback_events": s._normalize_persisted_feedback_events(
                message.get("feedback_events") or message.get("feedbackEvents") or []
            ),
            "active_task": active_task if isinstance(active_task, dict) else {},
        }
        with (logs_dir / "conversation.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
        content = str(record["content"] or "").strip()
        thought = str(record["thought"] or "").strip()
        tool_names = ", ".join(
            str(item.get("name") or "").strip()
            for item in list(record["tool_calls"] or [])
            if isinstance(item, dict) and str(item.get("name") or "").strip()
        )
        md_lines = [
            f"## {record['timestamp']} {role}",
            "",
            f"- event: {record['event']}",
            f"- status: {record['status'] or 'observed'}",
        ]
        if tool_names:
            md_lines.append(f"- tools: {tool_names}")
        if record["feedback_events"]:
            md_lines.append(f"- feedback events: {len(record['feedback_events'])}")
        md_lines.extend(["", content or "(empty)", ""])
        if thought:
            md_lines.extend(["```thought", thought, "```", ""])
        with (logs_dir / "conversation.md").open("a", encoding="utf-8") as handle:
            handle.write("\n".join(md_lines) + "\n")
    except Exception as exc:
        s._debug_logger.warning(
            f"session workspace log skipped: {type(exc).__name__}: {exc}",
            tag="CHAT",
        )


def _normalize_session_turn_error(value: Any) -> dict[str, Any] | None:
    s = _service()
    if not isinstance(value, dict):
        return None
    message = s.trim_lines(value.get("message") or value.get("summary") or "", max_lines=4)
    if not message:
        return None
    http_status = s._coerce_nonnegative_int(value.get("httpStatus") or value.get("http_status"))
    return {
        "message": message,
        "errorType": str(value.get("errorType") or value.get("error_type") or "runtime_error").strip() or "runtime_error",
        "reasonCode": str(value.get("reasonCode") or value.get("reason_code") or "").strip(),
        "reasonSummary": str(value.get("reasonSummary") or value.get("reason_summary") or "").strip(),
        "reasonDetail": str(value.get("reasonDetail") or value.get("reason_detail") or "").strip(),
        "httpStatus": http_status if http_status > 0 else None,
        "provider": str(value.get("provider") or "").strip(),
        "providerHost": str(value.get("providerHost") or value.get("provider_host") or "").strip(),
        "providerErrorType": str(value.get("providerErrorType") or value.get("provider_error_type") or "").strip(),
        "providerErrorMessage": str(value.get("providerErrorMessage") or value.get("provider_error_message") or "").strip(),
        "model": str(value.get("model") or "").strip(),
        "chainStage": str(value.get("chainStage") or value.get("chain_stage") or "").strip(),
        "eventCode": str(value.get("eventCode") or value.get("event_code") or "").strip(),
        "traceId": str(value.get("traceId") or value.get("trace_id") or "").strip(),
        "protocol": str(value.get("protocol") or "").strip(),
        "recoverable": bool(value.get("recoverable", True)),
        "timestamp": str(value.get("timestamp") or value.get("createdAt") or value.get("created_at") or "").strip(),
        "turnId": str(value.get("turnId") or value.get("turn_id") or "").strip(),
    }


def _make_session_turn_error(
    raw_error: Any,
    *,
    lang: str,
    error_type: str = "",
    turn_id: str = "",
    llm_failure: dict[str, Any] | None = None,
    llm_payload_trace: dict[str, Any] | None = None,
) -> dict[str, Any]:
    s = _service()
    normalized_error_type = str(error_type or s._failure_error_type(str(raw_error or ""))).strip() or "runtime_error"
    provider_reason = s._provider_error_user_reason(raw_error, lang=lang)
    provider_diagnostics = s._provider_error_diagnostics(raw_error, llm_failure=llm_failure)
    structured_failure = dict(llm_failure or {})
    payload_trace = dict(llm_payload_trace or {})
    # A terse raw_error (e.g. a bare "provider_protocol_error" code) yields no
    # concrete reason; fall back to parsing the llm_failure message which usually
    # carries the provider detail.
    llm_failure_message = str(structured_failure.get("message") or "").strip()
    if (
        llm_failure_message
        and (
            not provider_reason.get("code")
            or str(provider_reason.get("code") or "").strip() in {"", "provider_error"}
        )
    ):
        fallback_reason = s._provider_error_user_reason(llm_failure_message, lang=lang)
        if fallback_reason.get("code"):
            provider_reason = fallback_reason

    def _failure_text(snake_key: str, camel_key: str, *, max_lines: int = 2) -> str:
        value = structured_failure.get(snake_key, structured_failure.get(camel_key, ""))
        return s.trim_lines(value, max_lines=max_lines)

    if normalized_error_type == "provider_upstream_error" and provider_reason.get("code") in {"", "provider_error"}:
        provider_reason = {
            **provider_reason,
            "code": "upstream_unavailable",
            "summary": s.text_for(
                lang,
                zh="provider 上游服务不可用或网关失败",
                en="provider upstream service is unavailable or failed at the gateway",
            ),
        }
    reason_code = _failure_text("reason_code", "reasonCode") or str(provider_reason.get("code") or "").strip()
    reason_summary = _failure_text("reason_summary", "reasonSummary") or str(
        provider_reason.get("summary") or ""
    ).strip()
    reason_detail = _failure_text("reason_detail", "reasonDetail", max_lines=4) or str(
        provider_reason.get("detail") or ""
    ).strip()
    chain_stage = _failure_text("chain_stage", "chainStage")
    event_code = _failure_text("event_code", "eventCode")
    trace_id = _failure_text("trace_id", "traceId") or str(payload_trace.get("traceId") or "").strip()
    protocol = _failure_text("protocol", "protocol") or str(
        payload_trace.get("selectedProtocol") or payload_trace.get("transport") or ""
    ).strip()
    structured_message = _failure_text("message", "message", max_lines=4)
    default_recoverable = normalized_error_type.startswith("provider_") or normalized_error_type in {
        "server_error",
        "network_error",
    }
    return {
        # User-visible failure text (raw_error already human-readable, e.g. an
        # image-route failure) wins over the internal llm_failure diagnostic so
        # the operator sees the actual problem first; llm_failure details stay
        # in reason_summary/reason_detail/chainStage diagnostics fields.
        # An empty raw_error yields no user-visible text, so the structured
        # llm_failure message still surfaces.
        "message": (
            s._user_visible_failure_summary(raw_error, lang=lang, provider_reason=provider_reason)
            if str(raw_error or "").strip()
            else ""
        )
        or structured_message,
        "error_type": normalized_error_type,
        "reason_code": reason_code,
        "reason_summary": reason_summary,
        "reason_detail": reason_detail,
        "chain_stage": chain_stage,
        "event_code": event_code,
        "trace_id": trace_id,
        "protocol": protocol,
        "http_status": provider_diagnostics.get("http_status") or 0,
        "provider": provider_diagnostics.get("provider") or "",
        "provider_host": provider_diagnostics.get("provider_host") or "",
        "provider_error_type": provider_diagnostics.get("provider_error_type") or "",
        "provider_error_message": provider_diagnostics.get("provider_error_message") or "",
        "model": provider_diagnostics.get("model") or "",
        "recoverable": bool(structured_failure.get("retryable", default_recoverable)),
        "timestamp": s._now_timestamp(),
        "turn_id": str(turn_id or "").strip(),
    }


def _session_turn_error_to_api(value: Any) -> dict[str, Any] | None:
    s = _service()
    normalized = s._normalize_session_turn_error(value)
    if normalized is None:
        return None
    if not normalized["timestamp"]:
        normalized["timestamp"] = s._now_timestamp()
    return normalized


def _make_turn_error_chat_message(
    turn_error: dict[str, Any],
    *,
    error_type: str,
    turn_id: str,
    provider_failure: bool,
) -> dict[str, Any]:
    s = _service()
    timestamp = str(turn_error.get("timestamp") or s._now_timestamp()).strip()
    reason_summary = str(turn_error.get("reason_summary") or turn_error.get("reasonSummary") or "").strip()
    reason_detail = str(turn_error.get("reason_detail") or turn_error.get("reasonDetail") or "").strip()
    visible_message = str(turn_error.get("message") or "").strip()
    if reason_summary and reason_summary not in visible_message:
        visible_message = f"{visible_message} 原因：{reason_summary}。".strip()
    message = s._make_chat_message(
        "assistant",
        visible_message,
        metadata={
            "kind": "turn_error",
            "errorType": str(error_type or "").strip(),
            "turnId": str(turn_id or "").strip(),
            "recoverable": bool(turn_error.get("recoverable")),
            "providerFailure": bool(provider_failure),
            "reasonCode": str(turn_error.get("reason_code") or turn_error.get("reasonCode") or "").strip(),
            "reasonSummary": reason_summary,
            "reasonDetail": reason_detail,
            "httpStatus": s._coerce_nonnegative_int(turn_error.get("http_status") or turn_error.get("httpStatus")) or None,
            "provider": str(turn_error.get("provider") or "").strip(),
            "providerHost": str(turn_error.get("provider_host") or turn_error.get("providerHost") or "").strip(),
            "providerErrorType": str(turn_error.get("provider_error_type") or turn_error.get("providerErrorType") or "").strip(),
            "providerErrorMessage": str(turn_error.get("provider_error_message") or turn_error.get("providerErrorMessage") or "").strip(),
            "model": str(turn_error.get("model") or "").strip(),
            "chainStage": str(turn_error.get("chain_stage") or turn_error.get("chainStage") or "").strip(),
            "eventCode": str(turn_error.get("event_code") or turn_error.get("eventCode") or "").strip(),
            "traceId": str(turn_error.get("trace_id") or turn_error.get("traceId") or "").strip(),
            "protocol": str(turn_error.get("protocol") or "").strip(),
        },
    )
    message["timestamp"] = timestamp
    return message


def _looks_like_provider_error_text(text: Any) -> bool:
    s = _service()
    value = str(text or "").strip()
    if not value:
        return False
    return bool(s._PROVIDER_ERROR_PATTERN.search(value))


def _provider_error_user_reason(raw_error: Any, *, lang: str | None = None) -> dict[str, str]:
    s = _service()
    language = lang or s.get_web_language()
    value = str(raw_error or "").strip()
    lower = value.lower()
    detail = s._provider_error_reason_detail(value)

    def reason(code: str, zh: str, en: str) -> dict[str, str]:
        return {"code": code, "summary": s.text_for(language, zh=zh, en=en), "detail": detail}

    if "api key" in lower and ("额度" in value or "限额" in value or "用完" in value or "quota" in lower or "rate_limit" in lower):
        return reason("quota_exhausted", "API Key 额度或当日限额已用完", "API key quota or daily limit is exhausted")
    if (
        "prompt_cache_unsupported" in lower
        or "不支持显式 prompt cache" in value
        or "模型配置声明不支持 prompt cache" in value
    ):
        return reason(
            "prompt_cache_unsupported",
            "当前模型配置声明不支持 prompt cache",
            "the current model configuration declares prompt cache unsupported",
        )
    if "rate limit" in lower or "rate_limit" in lower or "429" in lower:
        return reason("rate_limited", "provider 正在限流", "provider is rate limiting requests")
    if "temperature" in lower and ("deprecated" in lower or "not supported" in lower or "unsupported" in lower):
        return reason("deprecated_sampling_parameter", "模型不接受当前采样参数，例如 temperature", "model rejected a sampling parameter such as temperature")
    if "top_p" in lower or "top_k" in lower:
        return reason("deprecated_sampling_parameter", "模型不接受当前采样参数，例如 top_p/top_k", "model rejected a sampling parameter such as top_p/top_k")
    if "context_length" in lower or "context length" in lower or "maximum context" in lower or "too many tokens" in lower:
        return reason("context_limit", "输入上下文超过模型限制", "input context exceeded the model limit")
    if "auth" in lower or "unauthorized" in lower or "forbidden" in lower or "401" in lower or "403" in lower:
        return reason("auth_failed", "provider 认证失败，请检查 API Key 或权限", "provider authentication failed; check the API key or permissions")
    if (
        "upstream_error" in lower
        or "upstream request failed" in lower
        or "badgateway" in lower
        or "bad gateway" in lower
        or "serviceunavailable" in lower
        or "service unavailable" in lower
    ):
        return reason("upstream_unavailable", "provider 上游服务不可用或网关失败", "provider upstream service is unavailable or failed at the gateway")
    if "provider_protocol_error" in lower or "payload_protocol_error" in lower:
        return reason(
            "provider_protocol_error",
            "模型返回了违反协议的响应（例如重复的工具调用 id）",
            "the model returned a protocol-violating response (for example a duplicated tool call id)",
        )
    if "timeout" in lower:
        return reason("timeout", "provider 响应超时", "provider response timed out")
    if s._looks_like_provider_error_text(value):
        return reason("provider_error", "provider 返回了协议或服务错误", "provider returned a protocol or service error")
    return {"code": "", "summary": "", "detail": detail}


def _provider_error_reason_detail(raw_error: Any) -> str:
    s = _service()
    value = str(raw_error or "").strip()
    if not value:
        return ""
    candidates: list[str] = []
    json_start = value.find("{")
    json_end = value.rfind("}")
    json_blobs = [value[json_start:json_end + 1]] if json_start >= 0 and json_end > json_start else []
    json_blobs.extend(re.findall(r"(?s)(\{.*?\})", value))
    for json_blob in json_blobs:
        try:
            parsed = json.loads(json_blob)
        except Exception:
            continue
        message = s._extract_provider_error_message_from_json(parsed)
        if message:
            candidates.append(message)
    for pattern in (
        r"(?is)['\"]error['\"]\s*:\s*\{[^{}]*['\"]message['\"]\s*:\s*['\"]([^'\"]+)['\"]",
        r"(?is)['\"]message['\"]\s*:\s*['\"]([^'\"]+)['\"]",
        r"(?is)\berror\s*:\s*\{[^{}]*\bmessage\s*:\s*['\"]([^'\"]+)['\"]",
        r"(?is)\bmessage\s*[:=]\s*['\"]([^'\"]+)['\"]",
        r"(?is)(?:invalid_request_error|rate_limit_error|authentication_error|permission_error|context_length_exceeded)\s*:\s*(.+)$",
        r"(?is)(?:AnthropicException|OpenAIException|BadGatewayError)\s*-\s*(.+)$",
    ):
        match = re.search(pattern, value)
        if match:
            candidates.append(match.group(1))
    for candidate in candidates:
        detail = s._sanitize_provider_error_detail(candidate)
        if detail:
            return detail
    if len(value) <= 220 and not any(secret in value.lower() for secret in ("authorization", "bearer ", "sk-")):
        return s._sanitize_provider_error_detail(value)
    return ""


def _provider_error_diagnostics(raw_error: Any, *, llm_failure: dict[str, Any] | None = None) -> dict[str, Any]:
    s = _service()
    value = str(raw_error or "").strip()
    llm_failure = llm_failure if isinstance(llm_failure, dict) else {}
    diagnostics: dict[str, Any] = {
        "http_status": s._coerce_nonnegative_int(
            llm_failure.get("http_status")
            or llm_failure.get("httpStatus")
            or llm_failure.get("status_code")
            or llm_failure.get("statusCode")
        ),
        "provider": str(llm_failure.get("provider") or "").strip(),
        "provider_host": s._host_from_provider_url(llm_failure.get("api_base") or llm_failure.get("base_url") or llm_failure.get("baseUrl")),
        "provider_error_type": str(llm_failure.get("provider_error_type") or llm_failure.get("providerErrorType") or "").strip(),
        "provider_error_message": str(
            llm_failure.get("provider_error_message")
            or llm_failure.get("providerErrorMessage")
            or ""
        ).strip(),
        "model": str(llm_failure.get("model") or "").strip(),
    }
    for parsed in s._iter_provider_error_json(value):
        if not diagnostics["provider_error_message"]:
            diagnostics["provider_error_message"] = s._extract_provider_error_message_from_json(parsed)
        if not diagnostics["provider_error_type"]:
            diagnostics["provider_error_type"] = s._extract_provider_error_type_from_json(parsed)
        if not diagnostics["http_status"]:
            diagnostics["http_status"] = s._extract_provider_http_status_from_json(parsed)
    if not diagnostics["provider_error_message"]:
        diagnostics["provider_error_message"] = s._provider_error_reason_detail(value)
    if not diagnostics["provider_error_type"]:
        type_match = re.search(
            r"(?i)\b(?:litellm\.)?([A-Za-z][A-Za-z0-9_]*(?:Error|Exception))\b",
            value,
        )
        diagnostics["provider_error_type"] = type_match.group(1) if type_match else ""
    if not diagnostics["http_status"]:
        diagnostics["http_status"] = s._infer_provider_http_status(value)
    if not diagnostics["provider_host"]:
        host_match = re.search(r"(?i)\bbaseUrlHost['\"]?\s*[:=]\s*['\"]?([A-Za-z0-9_.-]+)", value)
        diagnostics["provider_host"] = host_match.group(1) if host_match else ""
    diagnostics["provider_error_message"] = s._sanitize_provider_error_detail(diagnostics["provider_error_message"])
    diagnostics["provider_error_type"] = s._sanitize_provider_error_type(diagnostics["provider_error_type"])
    if diagnostics["http_status"] <= 0:
        diagnostics["http_status"] = 0
    return diagnostics


def _iter_provider_error_json(value: str) -> list[Any]:
    s = _service()
    text = str(value or "").strip()
    if not text:
        return []
    blobs: list[str] = []
    json_start = text.find("{")
    json_end = text.rfind("}")
    if json_start >= 0 and json_end > json_start:
        blobs.append(text[json_start:json_end + 1])
    blobs.extend(re.findall(r"(?s)(\{.*?\})", text))
    parsed_items: list[Any] = []
    seen: set[str] = set()
    for blob in blobs:
        candidate = blob.strip()
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        try:
            parsed_items.append(json.loads(candidate))
            continue
        except Exception:
            pass
        try:
            parsed_items.append(json.loads(candidate.encode("utf-8").decode("unicode_escape")))
        except Exception:
            continue
    return parsed_items


def _extract_provider_error_type_from_json(value: Any) -> str:
    s = _service()
    if isinstance(value, dict):
        error = value.get("error")
        if isinstance(error, dict):
            error_type = str(error.get("type") or error.get("code") or "").strip()
            if error_type:
                return error_type
        error_type = str(value.get("type") or value.get("code") or "").strip()
        if error_type and error_type != "error":
            return error_type
        for nested in value.values():
            error_type = s._extract_provider_error_type_from_json(nested)
            if error_type:
                return error_type
    if isinstance(value, list):
        for item in value:
            error_type = s._extract_provider_error_type_from_json(item)
            if error_type:
                return error_type
    return ""


def _sanitize_provider_error_type(value: Any) -> str:
    s = _service()
    error_type = str(value or "").strip()
    if not error_type:
        return ""
    error_type = re.sub(r"[^A-Za-z0-9_.:-]", "", error_type)
    return error_type[:96]


def _extract_provider_error_message_from_json(value: Any) -> str:
    s = _service()
    if isinstance(value, dict):
        error = value.get("error")
        if isinstance(error, dict):
            message = str(error.get("message") or "").strip()
            if message:
                return message
        message = str(value.get("message") or "").strip()
        if message:
            return message
        for nested in value.values():
            message = s._extract_provider_error_message_from_json(nested)
            if message:
                return message
    if isinstance(value, list):
        for item in value:
            message = s._extract_provider_error_message_from_json(item)
            if message:
                return message
    return ""


def _sanitize_provider_error_detail(value: Any) -> str:
    s = _service()
    detail = s.trim_lines(value, max_lines=3)
    if not detail:
        return ""
    detail = re.sub(r"sk-[A-Za-z0-9_-]{8,}", "sk-***", detail)
    detail = re.sub(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+", "Bearer ***", detail)
    detail = re.sub(
        r"(?i)\b(api[_-]?key|token|secret|authorization)(\s*[:=]\s*)([^\s,;]+)",
        lambda match: f"{match.group(1)}{match.group(2)}***",
        detail,
    )
    if len(detail) > 320:
        detail = f"{detail[:317].rstrip()}..."
    return detail


def _user_visible_failure_summary(
    raw_error: Any,
    *,
    lang: str | None = None,
    exc: Exception | None = None,
    provider_reason: dict[str, str] | None = None,
) -> str:
    s = _service()
    language = lang or s.get_web_language()
    text = str(raw_error or "").strip()
    if (
        "prompt_cache_unsupported" in text.lower()
        or "不支持显式 prompt cache" in text
        or "模型配置声明不支持 prompt cache" in text
    ):
        reason_summary = str((provider_reason or {}).get("summary") or "").strip()
        reason_line = s.text_for(
            language,
            zh=f"原因：{reason_summary}。" if reason_summary else "原因：当前模型配置声明不支持 prompt cache。",
            en=f"Reason: {reason_summary}." if reason_summary else "Reason: the current model configuration declares prompt cache unsupported.",
        )
        return s.text_for(
            language,
            zh=f"模型配置不满足本轮 prompt cache 要求，本轮已停止。{reason_line}请把当前模型的 prompt_cache.mode 配置为 automatic 或 explicit_cache_control，或关闭缓存强制要求。",
            en=f"The model configuration does not satisfy this turn's prompt-cache requirement, so the turn was stopped. {reason_line} Set this model's prompt_cache.mode to automatic or explicit_cache_control, or disable the cache requirement.",
        )
    if s._looks_like_provider_error_text(text):
        reason_summary = str((provider_reason or {}).get("summary") or "").strip()
        reason_detail = str((provider_reason or {}).get("detail") or "").strip()
        visible_reason_detail = reason_detail if s._provider_error_detail_safe_for_chat(reason_detail) else ""
        reason_line = s.text_for(
            language,
            zh=f"原因：{reason_summary}。" if reason_summary else "原因：provider 返回了错误。",
            en=f"Reason: {reason_summary}." if reason_summary else "Reason: the provider returned an error.",
        )
        detail_line = s.text_for(
            language,
            zh=f"具体报错：{visible_reason_detail}。" if visible_reason_detail else "",
            en=f"Provider detail: {visible_reason_detail}." if visible_reason_detail else "",
        )
        # Headline follows the single authoritative failure classification so a
        # payload-protocol error that also carries upstream markers still reads
        # as an upstream failure (classification precedence stays in one place).
        if s._failure_error_type(text) == "provider_protocol_error":
            return s.text_for(
                language,
                zh=f"模型返回了无法处理的协议级响应，本轮已停止。{reason_line}{detail_line}完整错误已写入运行日志；可以稍后直接重试或发送“继续”。",
                en=f'The model returned a protocol-invalid response, so this turn was stopped. {reason_line}{detail_line} The full error was written to runtime logs; retry later or send "continue".',
            )
        return s.text_for(
            language,
            zh=f"模型服务上游暂时失败，本轮没有完成。{reason_line}{detail_line}完整 provider 错误已写入运行日志；可以稍后直接重试或发送“继续”。",
            en=f'The model provider failed upstream, so this turn did not complete. {reason_line}{detail_line} The full provider error was written to runtime logs; retry later or send "continue".',
        )
    reason = s.trim_lines(text, max_lines=2)
    summary = s.text_for(
        language,
        zh="网页工作台这一轮执行失败，请检查配置或稍后重试。",
        en="This web workbench turn failed. Check configuration and try again.",
    )
    if reason:
        return f"{summary}\n{reason}"
    if exc is not None:
        return f"{summary}\n{type(exc).__name__}"
    return summary


def _touch_chat_turn_work_run(
    *,
    session_id: str,
    turn_id: str,
    stage: str,
    summary: str = "",
    last_tool_error: dict[str, Any] | None = None,
) -> None:
    s = _service()
    normalized_turn_id = str(turn_id or "").strip()
    if not normalized_turn_id:
        return
    previous = s._WORK_RUN_STORE.load_snapshot("chat_turn", normalized_turn_id)
    if not isinstance(previous, dict):
        return
    status = str(previous.get("status") or previous.get("currentPhase") or "running").strip().lower() or "running"
    if status not in {"queued", "running", "stopping", "paused"}:
        return
    s._persist_chat_turn_work_run(
        session_id=session_id,
        turn_id=normalized_turn_id,
        status=status,
        summary=summary or str(previous.get("summary") or "").strip(),
        updated_at=s._now_timestamp(),
        last_tool_error=last_tool_error,
    )


def _record_session_chat_review_candidate_event(
    phase: str,
    *,
    session_id: str,
    outcome: str,
    level: str = "info",
    fields: dict[str, Any] | None = None,
) -> None:
    s = _service()
    try:
        s.record_runtime_scene_event(
            "chat_review",
            f"session_candidate_{phase}",
            f"chat_review.session_candidate.{phase}",
            level=level,
            outcome=outcome,
            message="Session chat review candidate event.",
            fields={
                "sessionId": str(session_id or "").strip(),
                "source": "manual_session_action",
                **(fields or {}),
            },
            child_log_path=f"conversations/{s._safe_session_workspace_token(session_id)}-chat-review.jsonl",
            child_log_payload={
                "session_id": str(session_id or "").strip(),
                "phase": phase,
                "outcome": outcome,
                **(fields or {}),
            },
        )
    except Exception:
        return
