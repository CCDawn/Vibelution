"""Session live-output write / checkpoint bridge helpers.

Claim scope: set live overlay fields, checkpoint payload I/O wrappers used by
the hot path, and recovered live-output persistence into chat state.

Core store primitives may still live in ``live_output.py``. Late-bound facade
keeps monkeypatches stable.
"""

from __future__ import annotations

import json
import threading
import time
from typing import Any

from pathlib import Path
from core.web.services.session.live_output import SessionLiveOutputState

_UNSET = object()


def _service():
    from core.web.services import session_service

    return session_service


def _session_live_output_checkpoint_path(session_id: str) -> Path:
    s = _service()
    return s._ensure_session_workspace(session_id) / "live_output.json"


def _live_output_checkpoint_payload(state: SessionLiveOutputState) -> dict[str, Any]:
    s = _service()
    session_id = str(getattr(state, "session_id", "") or "").strip()
    turn_id = str(getattr(state, "turn_id", "") or "").strip()
    content = str(getattr(state, "content", "") or "")
    feedback_events = s._normalize_message_feedback_events(getattr(state, "feedback_events", []) or [])
    updated_at = str(getattr(state, "updated_at", "") or "").strip() or s._now_timestamp()
    payload = s.build_live_output_checkpoint_core_payload(
        SessionLiveOutputState(
            session_id=session_id,
            turn_id=turn_id,
            stage=str(getattr(state, "stage", "") or "").strip(),
            thought=str(getattr(state, "thought", "") or ""),
            content=content,
            mental_snapshot=s._normalize_mental_snapshot(getattr(state, "mental_snapshot", None)),
            tool_calls=s._normalize_message_tool_calls(getattr(state, "tool_calls", []) or []),
            feedback_events=feedback_events,
            context_composition=s._normalize_session_context_composition(
                getattr(state, "context_composition", None)
            ),
            llm_payload_trace=s._normalize_session_llm_payload_trace(getattr(state, "llm_payload_trace", None)),
            updated_at=updated_at,
        ),
        updated_at=updated_at,
    )
    # Facade enrichment: timeline/codex projections depend on session_service helpers.
    timeline_items = s._build_message_timeline_items(
        message_id=s._live_assistant_message_id(session_id, turn_id) if session_id else "",
        content=content,
        feedback_events=feedback_events,
        streaming=True,
        include_assistant_text=not any(
            str(event.get("kind") or "").strip() == "assistant_text"
            for event in feedback_events
        ),
    )
    if timeline_items:
        payload["timelineItems"] = timeline_items
    codex_transcript = s._build_codex_transcript_projection(
        message_id=s._live_assistant_message_id(session_id, turn_id) if session_id else "",
        content=content,
        feedback_events=feedback_events,
        tool_calls=payload.get("toolCalls") or [],
        streaming=True,
    )
    if codex_transcript:
        payload["codexTranscript"] = codex_transcript
    return payload


def _write_session_live_output_checkpoint(
    session_id: str,
    state: SessionLiveOutputState,
    *,
    force: bool = False,
) -> None:
    s = _service()
    normalized_session_id = str(session_id or "").strip()
    if not normalized_session_id:
        return
    s._write_session_live_output_checkpoint_core(
        normalized_session_id,
        checkpoint_path=s._session_live_output_checkpoint_path(normalized_session_id),
        build_payload=lambda: s._live_output_checkpoint_payload(state),
        force=force,
        interval_seconds=s._SESSION_LIVE_OUTPUT_CHECKPOINT_INTERVAL_SECONDS,
    )


def _delete_session_live_output_checkpoint(session_id: str) -> None:
    s = _service()
    normalized_session_id = str(session_id or "").strip()
    if not normalized_session_id:
        return
    s._delete_session_live_output_checkpoint_core(
        normalized_session_id,
        checkpoint_path=s._session_live_output_checkpoint_path(normalized_session_id),
    )


def _discard_session_live_output_state(session_id: str, *, turn_id: str = "") -> None:
    s = _service()
    normalized_session_id = str(session_id or "").strip()
    if not normalized_session_id:
        return
    s._discard_session_live_output_state_core(
        normalized_session_id,
        turn_id=turn_id,
        checkpoint_path=s._session_live_output_checkpoint_path(normalized_session_id),
    )


def _load_session_live_output_checkpoint(session_id: str) -> "SessionLiveOutputState | None":
    s = _service()
    normalized_session_id = str(session_id or "").strip()
    if not normalized_session_id:
        return None
    payload = s._load_session_live_output_checkpoint_payload(
        s._session_live_output_checkpoint_path(normalized_session_id)
    )
    if payload is None:
        return None
    return s._state_from_checkpoint_payload(
        normalized_session_id,
        payload,
        sanitize_thought=s._sanitize_thought_text,
        sanitize_content=lambda value: s._sanitize_message_content("assistant", value),
        normalize_mental_snapshot=s._normalize_mental_snapshot,
        normalize_tool_calls=s._normalize_message_tool_calls,
        normalize_feedback_events=s._normalize_message_feedback_events,
        normalize_context_composition=s._normalize_session_context_composition,
        normalize_llm_payload_trace=s._normalize_session_llm_payload_trace,
    )


def _persist_recovered_live_output_to_chat_state(
    session_id: str,
    turn_id: str,
    state: SessionLiveOutputState,
) -> None:
    s = _service()
    payload = s._live_output_checkpoint_payload(state)
    content = s._sanitize_message_content("assistant", payload.get("content") or "")
    thought = s._sanitize_thought_text(payload.get("thought") or "")
    tool_calls = s._normalize_message_tool_calls(payload.get("toolCalls") or [])
    feedback_events = s._normalize_message_feedback_events(payload.get("feedbackEvents") or [])
    mental_snapshot = s._normalize_mental_snapshot(payload.get("mentalSnapshot"))
    if not content and not thought and not tool_calls and not feedback_events and mental_snapshot is None:
        return
    normalized_turn_id = str(turn_id or "").strip()
    with s._CHAT_STATE_LOCK:
        chat_payload = s.load_chat_state(s.PROJECT_ROOT)
        conversation = s._find_conversation_entry(chat_payload, session_id)
        if conversation is None:
            return
        if s._find_turn_scoped_assistant_message(s._session_ledger_visible_messages(session_id), normalized_turn_id) is not None:
            return
        assistant_entry = s._make_chat_message(
            "assistant",
            content,
            tool_calls,
            thought=thought,
            feedback_events=feedback_events,
            mental_snapshot=mental_snapshot,
            metadata={"turnId": normalized_turn_id},
        )
        if tool_calls:
            assistant_entry["toolCalls"] = tool_calls
        if feedback_events:
            assistant_entry["feedbackEvents"] = feedback_events
        conversation.pop("messages", None)
        conversation["last_turn_status"] = "ready"
        conversation["updated_at"] = assistant_entry["timestamp"]
        chat_payload["updated_at"] = assistant_entry["timestamp"]
        s.save_chat_state(s.PROJECT_ROOT, chat_payload)


def _build_live_output_message(session_id: str) -> dict[str, Any] | None:
    s = _service()
    with s._SESSION_LIVE_OUTPUTS_LOCK:
        state = s._SESSION_LIVE_OUTPUTS.get(session_id)
        if state is None:
            return None
        turn_id = s._live_assistant_overlay_turn_id(session_id, state.turn_id)
        stage = str(state.stage or "").strip()
        thought = str(state.thought or "").strip()
        content = str(state.content or "").strip()
        mental_snapshot = s._normalize_mental_snapshot(state.mental_snapshot)
        tool_calls = s._normalize_message_tool_calls(state.tool_calls)
        feedback_events = s._normalize_message_feedback_events(state.feedback_events)
        timestamp = str(state.updated_at or "").strip() or s._now_timestamp()
    if not thought and not content and mental_snapshot is None and not tool_calls and not feedback_events:
        return None
    message: dict[str, Any] = {
        "id": s._live_assistant_message_id(session_id, turn_id),
        "role": "assistant",
        "content": content,
        "timestamp": timestamp,
        "streaming": True,
        "metadata": {
            "kind": "session_live_overlay",
            "turnId": turn_id,
            "ledgerSeq": s._session_ledger_sequence(session_id),
        },
    }
    if stage:
        message["streamStage"] = stage
    if thought:
        message["thought"] = thought
    if mental_snapshot is not None:
        message["mentalSnapshot"] = mental_snapshot
    if tool_calls:
        message["toolCalls"] = tool_calls
    if feedback_events:
        message["feedbackEvents"] = feedback_events
    timeline_items = s._build_message_timeline_items(
        message_id=message["id"],
        content=content,
        feedback_events=feedback_events,
        streaming=True,
        include_assistant_text=not any(
            str(event.get("kind") or "").strip() == "assistant_text"
            for event in feedback_events
        ),
    )
    if timeline_items:
        message["timelineItems"] = timeline_items
    codex_transcript = s._build_codex_transcript_projection(
        message_id=message["id"],
        content=content,
        feedback_events=feedback_events,
        tool_calls=tool_calls,
        streaming=True,
    )
    if codex_transcript:
        message["codexTranscript"] = codex_transcript
    return message


def _set_session_live_output(
    session_id: str,
    *,
    turn_id: str = "",
    stage: Any = _UNSET,
    thought: Any = _UNSET,
    content: Any = _UNSET,
    mental_snapshot: Any = _UNSET,
    tool_calls: Any = _UNSET,
    feedback_events: Any = _UNSET,
    context_composition: Any = _UNSET,
    llm_payload_trace: Any = _UNSET,
) -> None:
    s = _service()
    requested_turn_id = str(turn_id or "").strip()
    assistant_delta_state: SessionLiveOutputState | None = None
    checkpoint_snapshot: SessionLiveOutputState | None = None
    delete_checkpoint = False
    feedback_events_changed = feedback_events is not _UNSET
    # Live progress, assistant text, and tool updates already have a bounded
    # assistant_delta projection. Rebuilding the full session detail for each
    # of those updates blocks the Agent worker before the next LLM invocation.
    # Keep full snapshots for diagnostic structures that must immediately
    # reshape the visible session.  LLM payload trace is already available
    # from the in-memory live state and is persisted in the bounded checkpoint;
    # hydrating a full session detail here blocks the Agent worker before each
    # provider request.  Terminal persistence and reconnect paths still publish
    # the authoritative detail snapshot.
    publish_full_snapshot = mental_snapshot is not _UNSET
    with s._RUNNING_SESSIONS_LOCK:
        current_turn_id = s._SESSION_ACTIVE_TURN_IDS.get(session_id, "")
    if requested_turn_id and current_turn_id and requested_turn_id != current_turn_id:
        return
    output_turn_id = requested_turn_id or current_turn_id
    with s._SESSION_LIVE_OUTPUTS_LOCK:
        state = s._SESSION_LIVE_OUTPUTS.get(session_id)
        if state is None:
            state = SessionLiveOutputState(session_id=session_id, turn_id=output_turn_id)
            s._SESSION_LIVE_OUTPUTS[session_id] = state
        elif output_turn_id and state.turn_id and state.turn_id != output_turn_id:
            state = SessionLiveOutputState(session_id=session_id, turn_id=output_turn_id)
            s._SESSION_LIVE_OUTPUTS[session_id] = state
        elif output_turn_id and not state.turn_id:
            state.turn_id = output_turn_id
        previous_thought = state.thought
        previous_content = state.content
        if stage is not _UNSET:
            state.stage = str(stage or "").strip()
        if thought is not _UNSET:
            state.thought = s._sanitize_thought_text(thought)
        if content is not _UNSET:
            state.content = s._sanitize_message_content("assistant", content)
        thought_delta = ""
        content_delta = ""
        replace_thought = False
        replace_content = False
        if thought is not _UNSET:
            thought_delta, replace_thought = s._live_output_delta(previous_thought, state.thought)
        if content is not _UNSET:
            content_delta, replace_content = s._live_output_delta(previous_content, state.content)
        if mental_snapshot is not _UNSET:
            state.mental_snapshot = s._normalize_mental_snapshot(mental_snapshot)
        if tool_calls is not _UNSET:
            state.tool_calls = s._normalize_message_tool_calls(tool_calls)
        if feedback_events is not _UNSET:
            state.feedback_events = s._normalize_message_feedback_events(feedback_events)
        if context_composition is not _UNSET:
            state.context_composition = s._normalize_session_context_composition(context_composition)
        if llm_payload_trace is not _UNSET:
            state.llm_payload_trace = s._normalize_session_llm_payload_trace(llm_payload_trace)
        state.updated_at = s._now_timestamp()
        if (
            not state.thought
            and not state.content
            and state.mental_snapshot is None
            and not state.tool_calls
            and not state.feedback_events
            and state.context_composition is None
            and state.llm_payload_trace is None
        ):
            if content is not _UNSET or thought is not _UNSET or feedback_events is not _UNSET:
                assistant_delta_state = SessionLiveOutputState(
                    session_id=state.session_id,
                    turn_id=state.turn_id,
                    stage=state.stage,
                    thought=state.thought,
                    content=state.content,
                    thought_delta=thought_delta,
                    content_delta=content_delta,
                    replace_thought=replace_thought,
                    replace_content=replace_content,
                    feedback_events=list(state.feedback_events or []),
                    updated_at=state.updated_at,
                )
            s._SESSION_LIVE_OUTPUTS.pop(session_id, None)
            delete_checkpoint = True
        elif content is not _UNSET or thought is not _UNSET or feedback_events is not _UNSET or tool_calls is not _UNSET:
            assistant_delta_state = SessionLiveOutputState(
                session_id=state.session_id,
                turn_id=state.turn_id,
                stage=state.stage,
                thought=state.thought,
                content=state.content,
                thought_delta=thought_delta,
                content_delta=content_delta,
                replace_thought=replace_thought,
                replace_content=replace_content,
                tool_calls=list(state.tool_calls or []),
                feedback_events=list(state.feedback_events or []),
                updated_at=state.updated_at,
            )
        if state.turn_id and (
            content is not _UNSET
            or thought is not _UNSET
            or tool_calls is not _UNSET
            or feedback_events is not _UNSET
            or mental_snapshot is not _UNSET
            or llm_payload_trace is not _UNSET
        ):
            checkpoint_snapshot = SessionLiveOutputState(
                session_id=state.session_id,
                turn_id=state.turn_id,
                stage=state.stage,
                thought=state.thought,
                content=state.content,
                mental_snapshot=dict(state.mental_snapshot or {}) if isinstance(state.mental_snapshot, dict) else None,
                tool_calls=list(state.tool_calls or []),
                feedback_events=list(state.feedback_events or []),
                context_composition=dict(state.context_composition or {}) if isinstance(state.context_composition, dict) else None,
                llm_payload_trace=dict(state.llm_payload_trace or {}) if isinstance(state.llm_payload_trace, dict) else None,
                updated_at=state.updated_at,
            )
    if delete_checkpoint:
        s._delete_session_live_output_checkpoint(session_id)
    elif checkpoint_snapshot is not None:
        s._write_session_live_output_checkpoint(session_id, checkpoint_snapshot)
    if assistant_delta_state is not None:
        s._publish_session_assistant_delta(
            session_id,
            assistant_delta_state,
            include_feedback_events=feedback_events_changed,
        )
    if publish_full_snapshot:
        s._publish_session_detail_snapshot(session_id)


def _append_session_live_feedback_event(session_id: str, event: dict[str, Any], *, turn_id: str = "") -> list[dict[str, Any]]:
    s = _service()
    requested_turn_id = str(turn_id or "").strip()
    with s._RUNNING_SESSIONS_LOCK:
        current_turn_id = s._SESSION_ACTIVE_TURN_IDS.get(session_id, "")
    if requested_turn_id and current_turn_id and requested_turn_id != current_turn_id:
        return []
    output_turn_id = requested_turn_id or current_turn_id
    with s._SESSION_LIVE_OUTPUTS_LOCK:
        state = s._SESSION_LIVE_OUTPUTS.get(session_id)
        if state is None:
            state = SessionLiveOutputState(session_id=session_id, turn_id=output_turn_id)
            s._SESSION_LIVE_OUTPUTS[session_id] = state
        elif output_turn_id and state.turn_id and state.turn_id != output_turn_id:
            state = SessionLiveOutputState(session_id=session_id, turn_id=output_turn_id)
            s._SESSION_LIVE_OUTPUTS[session_id] = state
        elif output_turn_id and not state.turn_id:
            state.turn_id = output_turn_id
        sequence = max((s._coerce_nonnegative_int(item.get("sequence")) for item in state.feedback_events), default=0) + 1
        entry = {
            "sequence": sequence,
            "timestamp": s._now_timestamp(),
            **event,
        }
        duplicate_index = -1
        if str(entry.get("kind") or "").strip() == "status":
            name = str(entry.get("name") or "").strip()
            state.feedback_events = s._close_previous_running_status_events(state.feedback_events, name)
            for index, existing in enumerate(state.feedback_events):
                if existing.get("kind") == "status" and str(existing.get("name") or "").strip() == name:
                    duplicate_index = index
                    break
        if duplicate_index >= 0:
            previous = dict(state.feedback_events[duplicate_index])
            state.feedback_events[duplicate_index] = {
                **previous,
                **entry,
                "sequence": previous.get("sequence") or entry["sequence"],
            }
        else:
            state.feedback_events.append(entry)
        state.feedback_events = s._normalize_message_feedback_events(state.feedback_events)[-120:]
        state.updated_at = s._now_timestamp()
        return list(state.feedback_events)


def _set_session_llm_payload_trace_live_output(
    session_id: str,
    trace: Any,
    *,
    turn_id: str = "",
) -> None:
    s = _service()
    s._set_session_live_output(session_id, turn_id=turn_id, llm_payload_trace=trace)


def _set_session_turn_progress_live_output(session_id: str, stage: str, *, turn_id: str = "") -> None:
    s = _service()
    language = s.get_web_language()
    stage_key = str(stage or "").strip().lower()
    labels = {
        "context_prepare": s.text_for(
            language,
            zh="正在准备对话上下文...\n正在读取当前会话、绑定 Agent、工具权限和可恢复的上轮现场。",
            en="Preparing the conversation context...\nReading the current session, bound Agent, tool policy, and any resumable turn state.",
        ),
        "queued": s.text_for(
            language,
            zh="当前会话或 Agent 并发槽暂满，本轮已进入队列...\n会在同会话任务结束或 Agent 释放并发槽后继续执行。",
            en="This session or Agent concurrency slot is busy. This turn is queued...\nIt will continue when the session finishes or the Agent releases a concurrency slot.",
        ),
        "agent_prepare": s.text_for(
            language,
            zh="正在唤起对话 agent...\n正在绑定 Agent 实例、私有工作区、记忆根和工具工作区。",
            en="Preparing the conversation agent...\nBinding the Agent instance, private workspace, memory root, and tool workspace.",
        ),
        "history_restore": s.text_for(
            language,
            zh="正在恢复上一轮对话记忆...\n会把可继续的任务现场接回本轮上下文。",
            en="Restoring the previous conversation memory...\nReattaching resumable task state to this turn context.",
        ),
        "model_request": s.text_for(
            language,
            zh="正在请求模型，等待首个响应片段...\n上下文已组装完成，正在进入 LLM 调用。",
            en="Requesting the model and waiting for the first response chunk...\nThe context is assembled and the LLM call is starting.",
        ),
        "model_thinking": s.text_for(
            language,
            zh="正在思考中，等待模型输出...\n模型请求已发出，服务端可能正在推理，正文会在生成后显示。",
            en="Thinking and waiting for model output...\nThe model request has been sent; server-side reasoning may be running and visible text will appear after generation.",
        ),
        "followup_prepare": s.text_for(
            language,
            zh="正在准备继续推进下一步...\n会沿用上一轮 active task 继续收口。",
            en="Preparing the next continuation step...\nContinuing from the previous active task.",
        ),
    }
    content = labels.get(
        stage_key,
        s.text_for(
            language,
            zh="正在等待模型响应...\n当前阶段还没有更细的前端状态说明。",
            en="Waiting for the model response...\nNo more detailed frontend progress is available for this stage yet.",
        ),
    )
    feedback_events = s._append_session_live_feedback_event(
        session_id,
        {
            "kind": "status",
            "status": "running",
            "name": stage_key or "waiting",
            "summary": s.trim_lines(content, max_lines=2),
            "resultPreview": content,
        },
        turn_id=turn_id,
    )
    capture = s._active_session_turn_capture(session_id, turn_id)
    if capture is not None:
        capture.note_status_event(stage_key or "waiting", content, status="running", name=stage_key or "waiting")
        feedback_events = list(capture.feedback_events)
    s._set_session_live_output(
        session_id,
        turn_id=turn_id,
        stage=stage_key,
        feedback_events=feedback_events,
    )
    # Cosmetic progress is already checkpointed by the live-output channel.  Keep
    # durable WorkRun writes for retry/failure/tool-error and terminal transitions.
    s._record_session_turn_lifecycle_event(
        session_id,
        f"ui_progress_{stage_key or 'waiting'}",
        turn_id=turn_id,
        outcome="running",
        fields={
            "progressStage": stage_key,
            "messageLength": len(content),
        },
    )


def _set_session_llm_status_live_output(
    session_id: str,
    status: str,
    *,
    turn_id: str = "",
    fields: dict[str, Any] | None = None,
) -> None:
    s = _service()
    language = s.get_web_language()
    status_key = str(status or "").strip().lower()
    data = fields if isinstance(fields, dict) else {}
    attempt = s._coerce_nonnegative_int(data.get("attempt"))
    max_attempts = s._coerce_nonnegative_int(data.get("max_attempts") or data.get("maxAttempts"))
    category = str(data.get("category") or data.get("reason") or "").strip()
    close_code = s._coerce_nonnegative_int(data.get("closeCode") or data.get("close_code"))
    close_reason = s.trim_lines(str(data.get("closeReason") or data.get("close_reason") or "").strip(), max_lines=1)
    fallback_transport = str(data.get("fallbackTransport") or data.get("fallback_transport") or "").strip()
    transport_detail = close_reason or (f"WebSocket {close_code}" if close_code else "")
    feedback_status = "running"
    feedback_name = status_key or "status"
    feedback_error = ""
    failure_class = ""

    if status_key == "retrying":
        attempt_line = (
            s.text_for(language, zh=f"第 {attempt}/{max_attempts} 次", en=f"attempt {attempt}/{max_attempts}")
            if attempt and max_attempts
            else s.text_for(language, zh="正在重试", en="retrying")
        )
        reason_line = category or s.text_for(language, zh="上游连接暂时不稳定", en="temporary upstream connection issue")
        content = s.text_for(
            language,
            zh=f"模型连接正在重试...\n{attempt_line}；原因：{reason_line}。本轮仍在继续，请不要重复提交。",
            en=f"Retrying the model connection...\n{attempt_line}; reason: {reason_line}. This turn is still running.",
        )
        stage = "model_retry"
    elif status_key == "transport_degraded":
        content = s.text_for(
            language,
            zh="模型连接中断，正在恢复。",
            en="The model connection was interrupted and is recovering.",
        )
        stage = "model_transport"
        feedback_status = "degraded"
        feedback_name = "model_transport"
        feedback_error = transport_detail or category
        failure_class = category or "provider_transport_unavailable"
    elif status_key == "transport_fallback":
        target = fallback_transport.upper() if fallback_transport else "HTTP"
        content = s.text_for(
            language,
            zh=f"WebSocket 暂时不可用，正在切换到 {target}。",
            en=f"WebSocket is temporarily unavailable; switching to {target}.",
        )
        stage = "model_transport"
        feedback_status = "degraded"
        feedback_name = "model_transport"
        feedback_error = transport_detail or category
        failure_class = category or "provider_transport_unavailable"
    elif status_key == "transport_recovered":
        target = fallback_transport.upper() if fallback_transport else "HTTP"
        content = s.text_for(
            language,
            zh=f"连接已恢复。\n已从 WebSocket 切换到 {target}。",
            en=f"Connection recovered.\nSwitched from WebSocket to {target}.",
        )
        stage = "model_transport"
        feedback_status = "recovered"
        feedback_name = "model_transport"
    elif status_key == "failed":
        reason_line = category or s.text_for(language, zh="模型调用失败", en="model call failed")
        hint_line = (
            s.text_for(language, zh="\n请检查网络连接或代理端口是否可用。", en="\nCheck the network connection or proxy port.")
            if category == "network_error"
            else ""
        )
        content = s.text_for(
            language,
            zh=f"模型请求失败。\n原因：{reason_line}。{hint_line}",
            en=f"The model request failed.\nReason: {reason_line}.{hint_line}",
        )
        stage = "model_failed"
        feedback_status = "failed"
    else:
        return

    feedback_event = {
        "kind": "status",
        "status": feedback_status if status_key != "failed" else "failed",
        "name": feedback_name,
        "summary": s.trim_lines(content, max_lines=2),
        "resultPreview": content,
        "error": feedback_error,
        "failureClass": failure_class,
        "transportStatus": status_key if status_key.startswith("transport_") else "",
    }
    feedback_events = s._append_session_live_feedback_event(
        session_id,
        feedback_event,
        turn_id=turn_id,
    )
    capture = s._active_session_turn_capture(session_id, turn_id)
    if capture is not None:
        capture.note_status_event(
            status_key or stage,
            content,
            status="failed" if status_key == "failed" else "running",
            name=feedback_name,
        )
        for existing in capture.feedback_events:
            if existing.get("kind") == "status" and str(existing.get("name") or "").strip() == feedback_name:
                existing.update(feedback_event)
                break
        feedback_events = list(capture.feedback_events)
    live_output_fields: dict[str, Any] = {
        "turn_id": turn_id,
        "stage": stage,
        "feedback_events": feedback_events,
    }
    if not status_key.startswith("transport_"):
        live_output_fields["content"] = content
    s._set_session_live_output(session_id, **live_output_fields)
    s._touch_chat_turn_work_run(session_id=session_id, turn_id=turn_id, stage=stage, summary=s.trim_lines(content, max_lines=1))
    s._record_session_turn_lifecycle_event(
        session_id,
        f"llm_status_{status_key}",
        turn_id=turn_id,
        outcome="running" if status_key != "failed" else "failed",
        fields={
            "llmStatus": status_key,
            "attempt": attempt,
            "maxAttempts": max_attempts,
            "category": s.trim_lines(category, max_lines=1),
            "closeCode": close_code,
            "closeReason": close_reason,
            "fallbackTransport": fallback_transport,
            "messageLength": len(content),
        },
    )


def _set_session_model_thinking_live_output(session_id: str, *, turn_id: str = "", thought_chars: int = 0) -> None:
    s = _service()
    live_state = s._snapshot_session_live_output(session_id)
    if live_state is not None and str(live_state.stage or "").strip() == "model_thinking":
        return
    s._set_session_turn_progress_live_output(session_id, "model_thinking", turn_id=turn_id)
    event_status = "reasoning" if max(0, int(thought_chars or 0)) > 0 else "server_thinking"
    s._record_session_turn_lifecycle_event(
        session_id,
        "llm_status_reasoning" if event_status == "reasoning" else "llm_status_server_thinking",
        turn_id=turn_id,
        outcome="running",
        fields={
            "llmStatus": event_status,
            "thoughtChars": max(0, int(thought_chars or 0)),
        },
    )
