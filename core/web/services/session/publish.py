"""Session SSE transport and stream publish helpers.

Claim scope: EventSource stream_session_events, stream initial payload helpers,
session_detail / assistant_delta publish, subscriber queue coalescing.

DTO projection lives in ``projection.py``. Capture batching stays in
``stream_capture.py``. Late-bound facade keeps monkeypatches stable.
"""

from __future__ import annotations

import json
import queue
import threading
import time
from typing import Any, Generator


def _service():
    from core.web.services import session_service

    return session_service


def stream_session_events(
    session_id: str,
    initial_detail: dict[str, Any] | None = None,
    *,
    initial: str = "full",
    initial_state: dict[str, Any] | None = None,
):
    """Yield SSE events for one persisted chat session."""
    s = _service()

    conversation_id = str(session_id or "").strip()
    if not conversation_id:
        raise s.SessionNotFoundError(
            s.text_for(s.get_web_language(), zh="未找到当前会话。", en="Session not found.")
        )
    initial_mode = s.normalize_session_stream_initial_mode(initial, default="full")
    detail: dict[str, Any] | None = None
    state: dict[str, Any] | None = None
    if initial_mode == "full":
        detail = initial_detail or s.get_session_detail(conversation_id)
        if detail is None:
            raise s.SessionNotFoundError(
                s.text_for(s.get_web_language(), zh="未找到当前会话。", en="Session not found.")
            )
    elif initial_mode == "light":
        state = initial_state or s.get_session_stream_initial_state(conversation_id)
        if state is None:
            raise s.SessionNotFoundError(
                s.text_for(s.get_web_language(), zh="未找到当前会话。", en="Session not found.")
            )
    else:
        state = initial_state or s.get_session_stream_initial_state(conversation_id)
        if state is None:
            raise s.SessionNotFoundError(
                s.text_for(s.get_web_language(), zh="未找到当前会话。", en="Session not found.")
            )

    subscriber: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=s._SESSION_STREAM_QUEUE_SIZE)
    s._register_session_stream_subscriber(conversation_id, subscriber)
    try:
        if initial_mode == "full" and detail is not None:
            yield s._encode_sse_event(
                "session_detail",
                {
                    "type": "session_detail",
                    "sessionId": conversation_id,
                    "detail": detail,
                },
            )
        elif initial_mode == "light" and state is not None:
            yield s._encode_sse_event("session_initial", state)
        while True:
            try:
                event = subscriber.get(timeout=s._SESSION_STREAM_HEARTBEAT_SECONDS)
            except queue.Empty:
                yield ": keep-alive\n\n"
                continue
            yield s._encode_sse_event(str(event.get("type") or "message"), event)
    finally:
        s._unregister_session_stream_subscriber(conversation_id, subscriber)


def get_session_stream_initial_state(session_id: str) -> dict | None:
    """Return a lightweight initial SSE payload without hydrating full messages."""
    s = _service()

    normalized_session_id = str(session_id or "").strip()
    if not normalized_session_id:
        return None

    with s._RUNNING_SESSIONS_LOCK:
        active_turn_id = str(s._SESSION_ACTIVE_TURN_IDS.get(normalized_session_id) or "").strip()
        session_running = normalized_session_id in s._RUNNING_SESSION_IDS
    payload = s.load_chat_state(s.PROJECT_ROOT)
    agent_by_id = s._agent_lookup_for_conversations()
    target = s._load_conversation_detail_target(
        normalized_session_id,
        payload=payload,
        repair=False,
        agent_by_id=agent_by_id,
        lightweight=True,
    )
    if target is None:
        return None
    summary = s._build_session_summary(target, hydrate_agent=False)
    latest_message_payload = s._session_stream_initial_latest_message_payload(normalized_session_id)
    return {
        "type": "session_initial",
        "sessionId": normalized_session_id,
        "ledgerSeq": s._session_ledger_sequence(normalized_session_id),
        "summary": summary,
        "latestMessage": latest_message_payload,
        "activeTurnId": active_turn_id,
        "running": bool(session_running),
        "currentPhase": str(summary.get("currentPhase") or summary.get("status") or "").strip(),
        "updatedAt": str(summary.get("updatedAt") or summary.get("lastActive") or "").strip(),
    }


def resolve_session_stream_initial_payload(
    session_id: str,
    initial: str | None = "light",
) -> tuple[str, dict[str, Any] | None, dict[str, Any] | None]:
    """Resolve the initial SSE payload once before a session event stream starts."""
    s = _service()

    conversation_id = str(session_id or "").strip()
    if not conversation_id:
        raise s.SessionNotFoundError(
            s.text_for(s.get_web_language(), zh="未找到当前会话。", en="Session not found.")
        )

    initial_mode = s.normalize_session_stream_initial_mode(initial, default="light")
    if initial_mode == "full":
        detail = s.get_session_detail(conversation_id)
        if detail is None:
            raise s.SessionNotFoundError(
                s.text_for(s.get_web_language(), zh="未找到当前会话。", en="Session not found.")
            )
        return initial_mode, detail, None

    initial_state = s.get_session_stream_initial_state(conversation_id)
    if initial_state is None:
        raise s.SessionNotFoundError(
            s.text_for(s.get_web_language(), zh="未找到当前会话。", en="Session not found.")
        )
    return initial_mode, None, initial_state


def normalize_session_stream_initial_mode(initial: str | None, *, default: str = "light") -> str:
    s = _service()
    normalized_default = str(default or "light").strip().lower()
    if normalized_default not in {"full", "light", "none"}:
        normalized_default = "light"
    initial_mode = str(initial or normalized_default).strip().lower()
    if initial_mode not in {"full", "light", "none"}:
        return normalized_default
    return initial_mode


def _session_stream_initial_latest_message_payload(session_id: str) -> dict[str, Any]:
    s = _service()
    messages = s._messages_with_live_output(session_id)
    latest_message = s._latest_session_stream_preview_message(messages)
    preview = s._session_stream_preview_message_components(latest_message)
    if preview is None:
        return {
            "id": "",
            "role": "",
            "timestamp": "",
            "contentLength": 0,
            "thoughtLength": 0,
            "feedbackEventCount": 0,
            "toolCallCount": 0,
            "streaming": False,
        }
    return {
        "id": str(latest_message.get("id") or "").strip(),
        "role": preview["role"],
        "timestamp": str(latest_message.get("timestamp") or "").strip(),
        "contentLength": len(preview["content"]),
        "thoughtLength": len(preview["thought"]),
        "feedbackEventCount": len(preview["feedbackEvents"]),
        "toolCallCount": len(preview["toolCalls"]),
        "streaming": preview["streaming"],
    }


def _latest_session_stream_preview_message(messages: Any, *, scan_limit: int = 12) -> dict[str, Any] | None:
    s = _service()
    for raw in reversed(list(messages or [])[-scan_limit:]):
        preview = s._session_stream_preview_message_components(raw)
        if preview is None:
            continue
        if (
            preview["role"] == "assistant"
            and preview["content"]
            and s._looks_like_runtime_failure_notice(preview["content"])
            and not preview["thought"]
            and not preview["feedbackEvents"]
            and not preview["toolCalls"]
        ):
            continue
        return raw
    return None


def _session_stream_preview_message_components(raw: Any) -> dict[str, Any] | None:
    s = _service()
    if not isinstance(raw, dict):
        return None
    role = str(raw.get("role") or "").strip().lower()
    if role not in {"user", "assistant"}:
        return None
    content = s._sanitize_message_content(role, raw.get("content") or "")
    thought = s._sanitize_thought_text(raw.get("thought") or "")
    feedback_events = s._normalize_message_feedback_events(
        raw.get("feedbackEvents") or raw.get("feedback_events") or []
    )
    tool_calls = s._normalize_message_tool_calls(raw.get("toolCalls") or raw.get("tool_calls") or [])
    streaming = bool(raw.get("streaming"))
    if not content and not thought and not feedback_events and not tool_calls and not streaming:
        return None
    return {
        "role": role,
        "content": content,
        "thought": thought,
        "feedbackEvents": feedback_events,
        "toolCalls": tool_calls,
        "streaming": streaming,
    }


def _publish_session_detail_snapshot(session_id: str, *, detail: dict[str, Any] | None = None) -> None:
    s = _service()
    started_at = s._perf_counter()
    with s._SESSION_STREAM_SUBSCRIBERS_LOCK:
        subscribers = list(s._SESSION_STREAM_SUBSCRIBERS.get(session_id) or [])
    if not subscribers:
        return
    # Running turns can emit progress updates much faster than a full detail
    # projection can be assembled. Reserve or skip the busy snapshot interval
    # before hydrating detail, otherwise a throttled publication still pays the
    # expensive s.get_session_detail() cost.
    pre_reserved_busy_snapshot = False
    pre_throttled_count = 0
    if detail is None and s._is_session_running(session_id):
        interval_seconds = s._SESSION_STREAM_MIN_BUSY_SNAPSHOT_INTERVAL_SECONDS
        now = s._perf_counter()
        with s._SESSION_STREAM_LAST_SNAPSHOT_LOCK:
            last_snapshot_at = s._SESSION_STREAM_LAST_SNAPSHOT_AT.get(session_id, 0.0)
            if last_snapshot_at and now - last_snapshot_at < interval_seconds:
                pre_throttled_count = s._SESSION_STREAM_THROTTLED_COUNTS.get(session_id, 0) + 1
                s._SESSION_STREAM_THROTTLED_COUNTS[session_id] = pre_throttled_count
            else:
                pre_throttled_count = s._SESSION_STREAM_THROTTLED_COUNTS.pop(session_id, 0)
                s._SESSION_STREAM_LAST_SNAPSHOT_AT[session_id] = now
                pre_reserved_busy_snapshot = True
        if not pre_reserved_busy_snapshot:
            if pre_throttled_count % 10 == 1:
                s._record_session_detail_snapshot_throttled_event(
                    session_id=session_id,
                    subscriber_count=len(subscribers),
                    skipped_count=pre_throttled_count,
                    current_phase="running",
                    interval_ms=int(round(interval_seconds * 1000)),
                )
            return
    detail = detail if detail is not None else s.get_session_detail(
        session_id,
        message_limit=s._SESSION_STREAM_DETAIL_MESSAGE_LIMIT,
        transcript_scope=s._SESSION_STREAM_DETAIL_TRANSCRIPT_SCOPE,
    )
    if detail is None:
        return
    current_phase = str(detail.get("currentPhase") or detail.get("status") or "") if isinstance(detail, dict) else ""
    normalized_phase = current_phase.strip().lower()
    is_busy_snapshot = normalized_phase in s._SESSION_STREAM_BUSY_PHASES
    interval_seconds = s._SESSION_STREAM_MIN_BUSY_SNAPSHOT_INTERVAL_SECONDS
    now = s._perf_counter()
    should_throttle = False
    if pre_reserved_busy_snapshot:
        skipped_count = pre_throttled_count
        if skipped_count:
            s._record_session_detail_snapshot_throttled_event(
                session_id=session_id,
                subscriber_count=len(subscribers),
                skipped_count=skipped_count,
                current_phase=current_phase,
                interval_ms=int(round(interval_seconds * 1000)),
            )
    elif is_busy_snapshot:
        with s._SESSION_STREAM_LAST_SNAPSHOT_LOCK:
            last_snapshot_at = s._SESSION_STREAM_LAST_SNAPSHOT_AT.get(session_id, 0.0)
            if last_snapshot_at and now - last_snapshot_at < interval_seconds:
                should_throttle = True
                skipped_count = s._SESSION_STREAM_THROTTLED_COUNTS.get(session_id, 0) + 1
                s._SESSION_STREAM_THROTTLED_COUNTS[session_id] = skipped_count
                s._SESSION_STREAM_LAST_SNAPSHOT_AT[session_id] = last_snapshot_at
            else:
                skipped_count = s._SESSION_STREAM_THROTTLED_COUNTS.pop(session_id, 0)
                s._SESSION_STREAM_LAST_SNAPSHOT_AT[session_id] = now
        if should_throttle:
            if skipped_count % 10 == 1:
                s._record_session_detail_snapshot_throttled_event(
                    session_id=session_id,
                    subscriber_count=len(subscribers),
                    skipped_count=skipped_count,
                    current_phase=current_phase,
                    interval_ms=int(round(interval_seconds * 1000)),
                )
            return
        if skipped_count:
            s._record_session_detail_snapshot_throttled_event(
                session_id=session_id,
                subscriber_count=len(subscribers),
                skipped_count=skipped_count,
                current_phase=current_phase,
                interval_ms=int(round(interval_seconds * 1000)),
            )
    else:
        with s._SESSION_STREAM_LAST_SNAPSHOT_LOCK:
            s._SESSION_STREAM_LAST_SNAPSHOT_AT[session_id] = now
            skipped_count = s._SESSION_STREAM_THROTTLED_COUNTS.pop(session_id, 0)
        if skipped_count:
            s._record_session_detail_snapshot_throttled_event(
                session_id=session_id,
                subscriber_count=len(subscribers),
                skipped_count=skipped_count,
                current_phase=current_phase,
                interval_ms=int(round(interval_seconds * 1000)),
            )
    event = {
        "type": "session_detail",
        "sessionId": session_id,
        "ledgerSeq": s._coerce_nonnegative_int(detail.get("ledgerSeq") or 0) if isinstance(detail, dict) else 0,
        "detail": detail,
    }
    delivered_count = 0
    dropped_count = 0
    for subscriber in subscribers:
        dropped_count += s._coalesce_session_stream_queue(subscriber, event_type="session_detail")
        delivered, dropped = s._put_session_stream_event(subscriber, event)
        dropped_count += dropped
        if delivered:
            delivered_count += 1
    s._record_session_detail_snapshot_published_event(
        session_id=session_id,
        elapsed_ms=s._elapsed_ms(started_at),
        subscriber_count=len(subscribers),
        delivered_count=delivered_count,
        dropped_count=dropped_count,
        message_count=len(detail.get("messages") or []) if isinstance(detail, dict) else 0,
        current_phase=current_phase,
    )


def _publish_session_assistant_delta(
    session_id: str,
    state: Any,
    *,
    done: bool = False,
    include_feedback_events: bool = True,
) -> None:
    s = _service()
    started_at = s._perf_counter()
    with s._SESSION_STREAM_SUBSCRIBERS_LOCK:
        subscribers = list(s._SESSION_STREAM_SUBSCRIBERS.get(session_id) or [])
    if not subscribers:
        return
    event = {
        "type": "assistant_delta",
        "sessionId": session_id,
        "turnId": str(state.turn_id or "").strip(),
        "ledgerSeq": s._session_ledger_sequence(session_id),
        "stage": str(state.stage or "").strip(),
        "content": "",
        "thought": "",
        "contentDelta": str(state.content_delta or ""),
        "thoughtDelta": str(state.thought_delta or ""),
        "replaceContent": bool(state.replace_content),
        "replaceThought": bool(state.replace_thought),
        "updatedAt": str(state.updated_at or "").strip() or s._now_timestamp(),
        "done": bool(done),
    }
    if include_feedback_events:
        event["feedbackEvents"] = list(state.feedback_events or [])
    codex_transcript = s._build_codex_transcript_projection(
        message_id=s._live_assistant_message_id(session_id, state.turn_id),
        content=state.content,
        feedback_events=state.feedback_events,
        tool_calls=state.tool_calls,
        streaming=not done,
    )
    if codex_transcript:
        event["codexTranscript"] = codex_transcript
    turn_items = s._build_session_turn_items_projection(
        session_id=session_id,
        turn_id=state.turn_id,
        message_id=s._live_assistant_message_id(session_id, state.turn_id),
        content=state.content,
        thought=state.thought,
        codex_transcript=codex_transcript,
        done=done,
        source="assistant_delta",
    )
    if turn_items:
        event["itemId"] = next(
            (
                item["id"]
                for item in turn_items
                if str(item.get("type") or "") == "agent_message" and item.get("id")
            ),
            turn_items[0]["id"],
        )
        event["turnItems"] = turn_items
    recovery_event = s._assistant_delta_recovery_stream_event(
        {
            **event,
            "content": str(state.content or ""),
            "thought": str(state.thought or ""),
        }
    )
    delivered_count = 0
    dropped_count = 0
    for subscriber in subscribers:
        queued_event, coalesced_count = s._coalesce_session_assistant_delta_queue(subscriber, event)
        dropped_count += coalesced_count
        delivered, dropped = s._put_session_stream_event(
            subscriber,
            queued_event,
            recover_assistant_delta_on_drop=True,
            assistant_delta_recovery_event=recovery_event,
        )
        dropped_count += dropped
        if delivered:
            delivered_count += 1
    s._record_session_assistant_delta_published_event(
        session_id=session_id,
        turn_id=str(state.turn_id or "").strip(),
        stage=str(state.stage or "").strip(),
        elapsed_ms=s._elapsed_ms(started_at),
        subscriber_count=len(subscribers),
        delivered_count=delivered_count,
        dropped_count=dropped_count,
        content_chars=len(str(state.content_delta or "")),
        thought_chars=len(str(state.thought_delta or "")),
        item_id=str(event.get("itemId") or ""),
        turn_item_count=len(event.get("turnItems") or []),
        done=done,
    )


def _merge_session_assistant_delta_events(
    previous: dict[str, Any],
    current: dict[str, Any],
) -> dict[str, Any]:
    s = _service()
    merged = dict(current)
    previous_content_delta = str(previous.get("contentDelta") or "")
    current_content_delta = str(current.get("contentDelta") or "")
    previous_thought_delta = str(previous.get("thoughtDelta") or "")
    current_thought_delta = str(current.get("thoughtDelta") or "")
    previous_replace_content = bool(previous.get("replaceContent"))
    current_replace_content = bool(current.get("replaceContent"))
    previous_replace_thought = bool(previous.get("replaceThought"))
    current_replace_thought = bool(current.get("replaceThought"))
    if current_replace_content:
        merged["contentDelta"] = current_content_delta
    else:
        merged["contentDelta"] = previous_content_delta + current_content_delta
        merged["replaceContent"] = previous_replace_content
    if current_replace_thought:
        merged["thoughtDelta"] = current_thought_delta
    else:
        merged["thoughtDelta"] = previous_thought_delta + current_thought_delta
        merged["replaceThought"] = previous_replace_thought
    feedback_events = s._merge_session_assistant_delta_feedback_events(
        previous.get("feedbackEvents"),
        current.get("feedbackEvents"),
    )
    if feedback_events:
        merged["feedbackEvents"] = feedback_events
    else:
        merged.pop("feedbackEvents", None)
    codex_transcript = current.get("codexTranscript") or previous.get("codexTranscript")
    if codex_transcript:
        merged["codexTranscript"] = codex_transcript
    else:
        merged.pop("codexTranscript", None)
    turn_items = current.get("turnItems") or previous.get("turnItems")
    if turn_items:
        merged["turnItems"] = list(turn_items)
        merged["itemId"] = current.get("itemId") or previous.get("itemId") or (turn_items[0] or {}).get("id")
    else:
        merged.pop("turnItems", None)
        merged.pop("itemId", None)
    return merged


def _coalesce_session_assistant_delta_queue(
    subscriber: queue.Queue[dict[str, Any]],
    event: dict[str, Any],
) -> tuple[dict[str, Any], int]:
    s = _service()
    queued_events: list[dict[str, Any]] = []
    merged_event = dict(event)
    dropped_count = 0
    session_id = str(event.get("sessionId") or "")
    turn_id = str(event.get("turnId") or "")
    while True:
        try:
            existing = subscriber.get_nowait()
        except queue.Empty:
            break
        if (
            str(existing.get("type") or "") == "assistant_delta"
            and str(existing.get("sessionId") or "") == session_id
            and str(existing.get("turnId") or "") == turn_id
        ):
            merged_event = s._merge_session_assistant_delta_events(existing, merged_event)
            dropped_count += 1
            continue
        queued_events.append(existing)
    for existing in queued_events:
        try:
            subscriber.put_nowait(existing)
        except queue.Full:
            dropped_count += 1
    return merged_event, dropped_count


def _session_assistant_delta_feedback_event_key(event: dict[str, Any]) -> str:
    s = _service()
    call_id = str(event.get("callId") or event.get("toolCallId") or event.get("tool_call_id") or "").strip()
    if call_id:
        return f"call:{call_id}"
    sequence = s._coerce_nonnegative_int(event.get("sequence"))
    if sequence > 0:
        return f"seq:{sequence}"
    kind = str(event.get("kind") or "").strip()
    name = str(event.get("name") or "").strip()
    related_thought_sequence = s._coerce_nonnegative_int(event.get("relatedThoughtSequence"))
    try:
        arguments_signal = json.dumps(event.get("arguments") or {}, sort_keys=True, ensure_ascii=False)
    except TypeError:
        arguments_signal = str(event.get("arguments") or "")
    if name:
        return ":".join(("named", kind, name, str(related_thought_sequence or ""), arguments_signal))
    transport_status = str(event.get("transportStatus") or event.get("semanticStatus") or "").strip()
    if kind == "status" and transport_status:
        return ":".join(("status", transport_status, str(related_thought_sequence or "")))
    trace_path = str(event.get("tracePath") or "").strip()
    if trace_path:
        return f"trace:{trace_path}"
    timestamp = str(event.get("timestamp") or "").strip()
    if timestamp:
        return ":".join(("timestamp", kind, timestamp))
    return ":".join(
        str(event.get(key) or "")
        for key in ("kind", "summary", "resultPreview", "error")
    )


def _merge_session_assistant_delta_feedback_events(
    previous: Any,
    current: Any,
) -> list[dict[str, Any]]:
    s = _service()
    merged: dict[str, tuple[int, dict[str, Any]]] = {}
    for index, event in enumerate(list(previous or []) + list(current or [])):
        if not isinstance(event, dict):
            continue
        key = s._session_assistant_delta_feedback_event_key(event)
        first_index, previous_event = merged.get(key, (index, {}))
        merged[key] = (first_index, {**previous_event, **dict(event)})
    return [
        event
        for _, event in sorted(
            merged.values(),
            key=lambda item: (
                0 if s._coerce_nonnegative_int(item[1].get("sequence")) > 0 else 1,
                s._coerce_nonnegative_int(item[1].get("sequence")) or item[0],
                item[0],
            ),
        )
    ]


def _put_session_stream_event(
    subscriber: queue.Queue[dict[str, Any]],
    event: dict[str, Any],
    *,
    recover_assistant_delta_on_drop: bool = False,
    assistant_delta_recovery_event: dict[str, Any] | None = None,
) -> tuple[bool, int]:
    s = _service()
    dropped_count = 0
    try:
        subscriber.put_nowait(event)
        return True, dropped_count
    except queue.Full:
        dropped_event, dropped_extra_count = s._drop_session_stream_event_for_room(
            subscriber,
            prefer_non_assistant_delta=recover_assistant_delta_on_drop,
        )
        dropped_count += dropped_extra_count
        if dropped_event is not None:
            dropped_count += 1
        queued_event = event
        if recover_assistant_delta_on_drop and str((dropped_event or {}).get("type") or "") == "assistant_delta":
            queued_event = assistant_delta_recovery_event or s._assistant_delta_recovery_stream_event(event)
        try:
            subscriber.put_nowait(queued_event)
            return True, dropped_count
        except queue.Full:
            return False, dropped_count + 1


def _drop_session_stream_event_for_room(
    subscriber: queue.Queue[dict[str, Any]],
    *,
    prefer_non_assistant_delta: bool = False,
) -> tuple[dict[str, Any] | None, int]:
    s = _service()
    queued_events: list[dict[str, Any]] = []
    while True:
        try:
            queued_events.append(subscriber.get_nowait())
        except queue.Empty:
            break
    if not queued_events:
        return None, 0
    drop_index = 0
    if prefer_non_assistant_delta:
        for index, queued_event in enumerate(queued_events):
            if str(queued_event.get("type") or "") != "assistant_delta":
                drop_index = index
                break
    dropped_event = queued_events.pop(drop_index)
    dropped_extra_count = 0
    for queued_event in queued_events:
        try:
            subscriber.put_nowait(queued_event)
        except queue.Full:
            dropped_extra_count += 1
    return dropped_event, dropped_extra_count


def _assistant_delta_recovery_stream_event(event: dict[str, Any]) -> dict[str, Any]:
    s = _service()
    recovered_event = dict(event)
    recovered_event["contentDelta"] = str(event.get("content") or "")
    recovered_event["thoughtDelta"] = str(event.get("thought") or "")
    recovered_event["content"] = ""
    recovered_event["thought"] = ""
    recovered_event["replaceContent"] = True
    recovered_event["replaceThought"] = True
    return recovered_event


def _coalesce_session_stream_queue(
    subscriber: queue.Queue[dict[str, Any]],
    *,
    event_type: str,
) -> int:
    """Drop stale status snapshots for one SSE subscriber before enqueuing a newer one."""
    s = _service()

    normalized_event_type = str(event_type or "").strip()
    if normalized_event_type not in s._SESSION_STREAM_COALESCED_EVENT_TYPES:
        return 0
    kept: list[dict[str, Any]] = []
    dropped_count = 0
    while True:
        try:
            existing = subscriber.get_nowait()
        except queue.Empty:
            break
        if str(existing.get("type") or "").strip() == normalized_event_type:
            dropped_count += 1
            continue
        kept.append(existing)
    for existing in kept:
        try:
            subscriber.put_nowait(existing)
        except queue.Full:
            dropped_count += 1
    return dropped_count


def _register_session_stream_subscriber(session_id: str, subscriber: queue.Queue[dict[str, Any]]) -> None:
    s = _service()
    with s._SESSION_STREAM_SUBSCRIBERS_LOCK:
        bucket = s._SESSION_STREAM_SUBSCRIBERS.setdefault(session_id, set())
        bucket.add(subscriber)


def _unregister_session_stream_subscriber(session_id: str, subscriber: queue.Queue[dict[str, Any]]) -> None:
    s = _service()
    with s._SESSION_STREAM_SUBSCRIBERS_LOCK:
        bucket = s._SESSION_STREAM_SUBSCRIBERS.get(session_id)
        if not bucket:
            return
        bucket.discard(subscriber)
        if not bucket:
            s._SESSION_STREAM_SUBSCRIBERS.pop(session_id, None)


def _encode_sse_event(event_name: str, payload: dict[str, Any]) -> str:
    s = _service()
    body = json.dumps(payload, ensure_ascii=False)
    return f"event: {event_name}\ndata: {body}\n\n"


def _record_session_assistant_delta_published_event(
    *,
    session_id: str,
    turn_id: str,
    stage: str,
    elapsed_ms: int,
    subscriber_count: int,
    delivered_count: int,
    dropped_count: int,
    content_chars: int,
    thought_chars: int,
    item_id: str,
    turn_item_count: int,
    done: bool,
) -> None:
    s = _service()
    if subscriber_count <= 0:
        return
    try:
        s.record_runtime_scene_event(
            "conversation",
            "session_stream",
            "session.assistant_delta.published",
            level="info",
            outcome="published",
            message="Session assistant live output was published to active SSE subscribers.",
            fields={
                "sessionId": str(session_id or "").strip(),
                "turnId": str(turn_id or "").strip(),
                "stage": str(stage or "").strip(),
                "elapsedMs": max(0, int(elapsed_ms)),
                "subscriberCount": max(0, int(subscriber_count)),
                "deliveredCount": max(0, int(delivered_count)),
                "droppedCount": max(0, int(dropped_count)),
                "contentChars": max(0, int(content_chars)),
                "thoughtChars": max(0, int(thought_chars)),
                "itemId": str(item_id or "").strip(),
                "turnItemCount": max(0, int(turn_item_count)),
                "done": bool(done),
            },
            lifecycle=False,
        )
    except Exception:
        return


def _record_session_detail_snapshot_published_event(
    *,
    session_id: str,
    elapsed_ms: int,
    subscriber_count: int,
    delivered_count: int,
    dropped_count: int,
    message_count: int,
    current_phase: str,
) -> None:
    s = _service()
    if subscriber_count <= 0:
        return
    try:
        s.record_runtime_scene_event(
            "conversation",
            "session_stream",
            "session.detail_snapshot.published",
            level="info",
            outcome="published",
            message="Session detail snapshot was published to active SSE subscribers.",
            fields={
                "sessionId": str(session_id or "").strip(),
                "elapsedMs": max(0, int(elapsed_ms)),
                "subscriberCount": max(0, int(subscriber_count)),
                "deliveredCount": max(0, int(delivered_count)),
                "droppedCount": max(0, int(dropped_count)),
                "messageCount": max(0, int(message_count)),
                "currentPhase": str(current_phase or "").strip(),
            },
            lifecycle=False,
        )
    except Exception:
        return


def _record_session_detail_snapshot_throttled_event(
    *,
    session_id: str,
    subscriber_count: int,
    skipped_count: int,
    current_phase: str,
    interval_ms: int,
) -> None:
    s = _service()
    if subscriber_count <= 0:
        return
    try:
        s.record_runtime_scene_event(
            "conversation",
            "session_stream",
            "session.detail_snapshot.throttled",
            level="info",
            outcome="skipped",
            message="Session detail snapshot publish was throttled for a busy session.",
            fields={
                "sessionId": str(session_id or "").strip(),
                "subscriberCount": max(0, int(subscriber_count)),
                "skippedCount": max(0, int(skipped_count)),
                "currentPhase": str(current_phase or "").strip(),
                "minIntervalMs": max(0, int(interval_ms)),
            },
            lifecycle=False,
        )
    except Exception:
        return
