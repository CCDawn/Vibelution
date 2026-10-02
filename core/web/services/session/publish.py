"""Session SSE transport and stream publish helpers.

Claim scope: EventSource stream_session_events, stream initial payload helpers,
Last-Event-ID resume replay over the session journal, session_detail /
assistant_delta publish, subscriber queue coalescing.

DTO projection lives in ``projection.py``. Capture batching stays in
``stream_capture.py``. Late-bound facade keeps monkeypatches stable.
"""

from __future__ import annotations

import asyncio
import json
import queue
import time
from typing import Any
from uuid import uuid4

from .stream_transport_delta import SessionStreamItemDelta

# Last-Event-ID resume replay window (aligns with ZCode eventRetentionPerSession:
# a bounded, order-preserving replay range; older gaps honestly degrade to a
# full initial + client refetch instead of pretending the gap is covered).
SESSION_STREAM_RESUME_MAX_EVENTS = 2000
# Per-replayed-journal-event payload bound: resume replay exists to prove what
# was missed and mark the handover watermark, not to re-ship whole bodies.
SESSION_STREAM_RESUME_MAX_PAYLOAD_CHARS = 8192


def _service():
    from core.web.services import session_service

    return session_service


def _record_session_stream_lifecycle_event(
    *,
    session_id: str,
    stream_connection_id: str,
    transport: str,
    initial_mode: str,
    phase: str,
    event_count: int = 0,
    heartbeat_count: int = 0,
    duration_ms: int = 0,
    close_reason: str = "",
    error_type: str = "",
) -> None:
    s = _service()
    fields: dict[str, Any] = {
        "sessionId": str(session_id or "").strip(),
        "streamConnectionId": str(stream_connection_id or "").strip(),
        "transport": str(transport or "").strip(),
        "initialMode": str(initial_mode or "").strip(),
    }
    fields.update(
        {
            "eventCount": max(0, int(event_count or 0)),
            "heartbeatCount": max(0, int(heartbeat_count or 0)),
            "durationMs": max(0, int(duration_ms or 0)),
        }
    )
    normalized_close_reason = str(close_reason or "").strip()
    if normalized_close_reason:
        fields["closeReason"] = normalized_close_reason
    normalized_error_type = str(error_type or "").strip()
    if normalized_error_type:
        fields["errorType"] = normalized_error_type
    try:
        s.record_runtime_scene_event(
            "conversation",
            "session_stream",
            f"session.stream.{phase}",
            level="error" if phase == "failed" else "info",
            outcome="failed" if phase == "failed" else "observed",
            message=f"Session SSE stream {phase}.",
            fields=fields,
            lifecycle=True,
        )
    except Exception:
        return


def _stream_duration_ms(started_at: float) -> int:
    return max(0, round((time.perf_counter() - started_at) * 1000))


class _AsyncSessionStreamSubscriber(queue.Queue[dict[str, Any]]):
    """Bounded subscriber queue that wakes one async SSE consumer from any thread."""

    def __init__(self, *, maxsize: int, loop: asyncio.AbstractEventLoop) -> None:
        super().__init__(maxsize=maxsize)
        self._loop = loop
        self._ready = asyncio.Event()

    def put_nowait(self, item: dict[str, Any]) -> None:
        super().put_nowait(item)
        try:
            self._loop.call_soon_threadsafe(self._ready.set)
        except RuntimeError:
            # The HTTP client can disconnect while a worker is publishing its
            # last snapshot. The queue is unregistered by the stream finally.
            return

    async def get_async(self, *, timeout: float) -> dict[str, Any]:
        while True:
            try:
                return self.get_nowait()
            except queue.Empty:
                pass

            self._ready.clear()
            # Close the clear/await race: a publisher may have enqueued after
            # the first empty read but before the readiness flag was cleared.
            try:
                return self.get_nowait()
            except queue.Empty:
                pass

            await asyncio.wait_for(self._ready.wait(), timeout=timeout)


def _resolve_session_stream_bootstrap(
    session_id: str,
    initial_detail: dict[str, Any] | None,
    *,
    initial: str,
    initial_state: dict[str, Any] | None,
) -> tuple[str, str, dict[str, Any] | None, dict[str, Any] | None]:
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
    return conversation_id, initial_mode, detail, state


def _initial_session_stream_event(
    conversation_id: str,
    initial_mode: str,
    detail: dict[str, Any] | None,
    state: dict[str, Any] | None,
) -> str | None:
    s = _service()
    if initial_mode == "full" and detail is not None:
        return s._encode_sse_event(
            "session_detail",
            {
                "type": "session_detail",
                "sessionId": conversation_id,
                "detail": detail,
            },
        )
    if initial_mode == "light" and state is not None:
        return s._encode_sse_event("session_initial", state)
    return None


def _session_stream_resume_prelude(
    conversation_id: str,
    last_event_id: int,
) -> list[str]:
    """SSE frames that compensate a reconnecting consumer before the live loop.

    ``last_event_id`` is the last journal sequence the consumer received. With
    a replayable gap this replays journal events in ``(last_event_id, toSeq]``
    and closes with a ``stream_resume`` marker; an over-window gap degrades to
    a light initial marked ``resume="partial"`` plus the same marker, so the
    consumer refetches the authoritative body instead of trusting the window.
    """

    if last_event_id <= 0:
        return []
    plan = build_session_stream_resume(conversation_id, last_event_id)
    frames = _session_stream_resume_frames(plan)
    if str(plan.get("resume") or "") != "partial":
        return frames
    s = _service()
    state = s.get_session_stream_initial_state(conversation_id)
    frames = [frames[-1]]
    if isinstance(state, dict):
        marked_state = dict(state)
        marked_state["resume"] = "partial"
        initial_frame = s._encode_sse_event("session_initial", marked_state)
        # The partial marker must carry the watermark so consumers can still
        # verify the live handover even though the replay itself was skipped.
        frames = [initial_frame, *frames]
    return frames


def stream_session_events(
    session_id: str,
    initial_detail: dict[str, Any] | None = None,
    *,
    initial: str = "full",
    initial_state: dict[str, Any] | None = None,
    last_event_id: int = 0,
):
    """Yield SSE events for one persisted chat session."""
    s = _service()
    stream_connection_id = uuid4().hex
    stream_started_at = time.perf_counter()
    event_count = 0
    heartbeat_count = 0
    opened = False
    failed = False
    conversation_id = ""
    initial_mode = ""
    try:
        conversation_id, initial_mode, detail, state = _resolve_session_stream_bootstrap(
            session_id,
            initial_detail,
            initial=initial,
            initial_state=initial_state,
        )
        subscriber: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=s._SESSION_STREAM_QUEUE_SIZE)
        s._register_session_stream_subscriber(conversation_id, subscriber)
        opened = True
        _record_session_stream_lifecycle_event(
            session_id=conversation_id,
            stream_connection_id=stream_connection_id,
            transport="sse_sync",
            initial_mode=initial_mode,
            phase="opened",
        )
        initial_event = _initial_session_stream_event(conversation_id, initial_mode, detail, state)
        if initial_event is not None:
            event_count += 1
            yield initial_event
        for resume_frame in _session_stream_resume_prelude(conversation_id, last_event_id):
            event_count += 1
            yield resume_frame
        item_delta = SessionStreamItemDelta()
        while True:
            try:
                event = subscriber.get(timeout=s._SESSION_STREAM_HEARTBEAT_SECONDS)
            except queue.Empty:
                heartbeat_count += 1
                yield ": keep-alive\n\n"
                continue
            event_count += 1
            yield s._encode_sse_event(
                str(event.get("type") or "message"),
                item_delta.compact(event),
                event_seq=int(event.get("ledgerSeq") or 0),
            )
    except Exception as exc:
        if opened:
            failed = True
            _record_session_stream_lifecycle_event(
                session_id=conversation_id,
                stream_connection_id=stream_connection_id,
                transport="sse_sync",
                initial_mode=initial_mode,
                phase="failed",
                event_count=event_count,
                heartbeat_count=heartbeat_count,
                duration_ms=_stream_duration_ms(stream_started_at),
                error_type=type(exc).__name__,
            )
        raise
    finally:
        if opened:
            try:
                _record_session_stream_lifecycle_event(
                    session_id=conversation_id,
                    stream_connection_id=stream_connection_id,
                    transport="sse_sync",
                    initial_mode=initial_mode,
                    phase="closed",
                    event_count=event_count,
                    heartbeat_count=heartbeat_count,
                    duration_ms=_stream_duration_ms(stream_started_at),
                    close_reason="error" if failed else "client_disconnect",
                )
            finally:
                s._unregister_session_stream_subscriber(conversation_id, subscriber)


async def stream_session_events_async(
    session_id: str,
    initial_detail: dict[str, Any] | None = None,
    *,
    initial: str = "full",
    initial_state: dict[str, Any] | None = None,
    last_event_id: int = 0,
):
    """Yield SSE events without occupying a worker while the stream is idle."""
    s = _service()
    stream_connection_id = uuid4().hex
    stream_started_at = time.perf_counter()
    event_count = 0
    heartbeat_count = 0
    opened = False
    failed = False
    conversation_id = ""
    initial_mode = ""
    try:
        conversation_id, initial_mode, detail, state = _resolve_session_stream_bootstrap(
            session_id,
            initial_detail,
            initial=initial,
            initial_state=initial_state,
        )
        subscriber = _AsyncSessionStreamSubscriber(
            maxsize=s._SESSION_STREAM_QUEUE_SIZE,
            loop=asyncio.get_running_loop(),
        )
        s._register_session_stream_subscriber(conversation_id, subscriber)
        opened = True
        _record_session_stream_lifecycle_event(
            session_id=conversation_id,
            stream_connection_id=stream_connection_id,
            transport="sse_async",
            initial_mode=initial_mode,
            phase="opened",
        )
        initial_event = _initial_session_stream_event(conversation_id, initial_mode, detail, state)
        if initial_event is not None:
            event_count += 1
            yield initial_event
        for resume_frame in _session_stream_resume_prelude(conversation_id, last_event_id):
            event_count += 1
            yield resume_frame
        item_delta = SessionStreamItemDelta()
        while True:
            try:
                event = await subscriber.get_async(timeout=s._SESSION_STREAM_HEARTBEAT_SECONDS)
            except TimeoutError:
                heartbeat_count += 1
                yield ": keep-alive\n\n"
                continue
            event_count += 1
            yield s._encode_sse_event(
                str(event.get("type") or "message"),
                item_delta.compact(event),
                event_seq=int(event.get("ledgerSeq") or 0),
            )
    except Exception as exc:
        if opened:
            failed = True
            _record_session_stream_lifecycle_event(
                session_id=conversation_id,
                stream_connection_id=stream_connection_id,
                transport="sse_async",
                initial_mode=initial_mode,
                phase="failed",
                event_count=event_count,
                heartbeat_count=heartbeat_count,
                duration_ms=_stream_duration_ms(stream_started_at),
                error_type=type(exc).__name__,
            )
        raise
    finally:
        if opened:
            try:
                _record_session_stream_lifecycle_event(
                    session_id=conversation_id,
                    stream_connection_id=stream_connection_id,
                    transport="sse_async",
                    initial_mode=initial_mode,
                    phase="closed",
                    event_count=event_count,
                    heartbeat_count=heartbeat_count,
                    duration_ms=_stream_duration_ms(stream_started_at),
                    close_reason="error" if failed else "client_disconnect",
                )
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
    agent_by_id = s._agent_lookup_for_conversations()
    target = s._load_conversation_detail_target(
        normalized_session_id,
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
    if initial_mode == "none":
        # The caller already owns the authoritative bootstrap detail. Avoid
        # rebuilding the session summary/message projection before opening the
        # incremental event stream.
        return initial_mode, None, None
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
    if role == "assistant":
        if not isinstance(raw.get("turnItems"), list):
            return None
        turn_items = [item for item in raw["turnItems"] if isinstance(item, dict)]
        content = "\n".join(
            s._sanitize_message_content("assistant", item.get("text") or "")
            for item in turn_items
            if str(item.get("type") or "").strip() in {"agent_message", "error"}
            and str(item.get("text") or "").strip()
        ).strip()
        thought = "\n".join(
            s._sanitize_thought_text(item.get("text") or "")
            for item in turn_items
            if str(item.get("type") or "").strip() == "reasoning"
            and str(item.get("text") or "").strip()
        ).strip()
        feedback_events = [
            item
            for item in turn_items
            if str(item.get("type") or "").strip() in {"status", "retry", "error"}
        ]
        tool_calls = [
            item for item in turn_items if str(item.get("type") or "").strip() == "tool_call"
        ]
        streaming = str(raw.get("status") or "").strip().lower() == "running" or any(
            str(item.get("status") or "").strip().lower() in {"pending", "running"}
            for item in turn_items
        )
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
    content = s._sanitize_message_content("user", raw.get("content") or "")
    if not content:
        return None
    return {
        "role": role,
        "content": content,
        "thought": "",
        "feedbackEvents": [],
        "toolCalls": [],
        "streaming": False,
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
        claim = _claim_session_detail_snapshot_slot(
            s,
            session_id,
            subscribers,
            now=now,
            interval_seconds=interval_seconds,
        )
        if claim is None:
            return
        pre_reserved_busy_snapshot, pre_throttled_count = claim
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
        claim = _claim_session_detail_snapshot_slot(
            s,
            session_id,
            subscribers,
            now=now,
            interval_seconds=interval_seconds,
        )
        if claim is None:
            return
        reserved, skipped_count = claim
        should_throttle = not reserved
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
        skipped_count = _clear_session_detail_snapshot_slot(s, session_id, subscribers, now=now)
        if skipped_count is None:
            return
        if skipped_count:
            s._record_session_detail_snapshot_throttled_event(
                session_id=session_id,
                subscriber_count=len(subscribers),
                skipped_count=skipped_count,
                current_phase=current_phase,
                interval_ms=int(round(interval_seconds * 1000)),
            )
    subscribers = _current_session_stream_subscribers(s, session_id, subscribers)
    if not subscribers:
        return
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
        "updatedAt": str(state.updated_at or "").strip() or s._now_timestamp(),
        "done": bool(done),
    }
    # `include_feedback_events` is retained only as a caller compatibility
    # parameter. Feedback is represented by status/tool/retry TurnItems now.
    codex_transcript = s._build_codex_transcript_projection(
        message_id=s._live_assistant_message_id(session_id, state.turn_id),
        content=state.content,
        feedback_events=state.feedback_events,
        tool_calls=state.tool_calls,
        streaming=not done,
    )
    turn_items = s._build_session_turn_items_projection(
        session_id=session_id,
        turn_id=state.turn_id,
        message_id=s._live_assistant_message_id(session_id, state.turn_id),
        content=state.content,
        thought=state.thought,
        mental_snapshot=state.mental_snapshot,
        codex_transcript=codex_transcript,
        done=done,
        source="assistant_delta",
        stage=state.stage,
    )
    event["turnItems"] = turn_items
    recovery_event = s._assistant_delta_recovery_stream_event(event)
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
        content_chars=0,
        thought_chars=0,
        item_id=str((turn_items[0] or {}).get("itemId") or "") if turn_items else "",
        turn_item_count=len(event.get("turnItems") or []),
        done=done,
    )


def _merge_session_assistant_delta_events(
    previous: dict[str, Any],
    current: dict[str, Any],
) -> dict[str, Any]:
    merged = dict(current)
    # Prefer the newest turnItems snapshot (full rebuild from live state). Fall back
    # to the previous package only when the current frame omitted items entirely.
    current_turn_items = current.get("turnItems")
    previous_turn_items = previous.get("turnItems")
    if isinstance(current_turn_items, list) and current_turn_items:
        turn_items = list(current_turn_items)
    elif isinstance(previous_turn_items, list) and previous_turn_items:
        turn_items = list(previous_turn_items)
    else:
        turn_items = []
    if turn_items:
        merged["turnItems"] = turn_items
    else:
        merged.pop("turnItems", None)
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
    return dict(event)


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
            # Lock order is always subscribers -> snapshot state. A publisher
            # that already copied the old bucket must revalidate before it can
            # repopulate these per-session throttle maps.
            with s._SESSION_STREAM_LAST_SNAPSHOT_LOCK:
                s._SESSION_STREAM_LAST_SNAPSHOT_AT.pop(session_id, None)
                s._SESSION_STREAM_THROTTLED_COUNTS.pop(session_id, None)


def _has_current_session_stream_subscriber_locked(
    s: Any,
    session_id: str,
    candidates: list[Any],
) -> bool:
    bucket = s._SESSION_STREAM_SUBSCRIBERS.get(session_id) or set()
    return any(candidate in bucket for candidate in candidates)


def _current_session_stream_subscribers(
    s: Any,
    session_id: str,
    candidates: list[Any],
) -> list[Any]:
    with s._SESSION_STREAM_SUBSCRIBERS_LOCK:
        bucket = s._SESSION_STREAM_SUBSCRIBERS.get(session_id) or set()
        return [candidate for candidate in candidates if candidate in bucket]


def _claim_session_detail_snapshot_slot(
    s: Any,
    session_id: str,
    candidates: list[Any],
    *,
    now: float,
    interval_seconds: float,
) -> tuple[bool, int] | None:
    """Reserve one snapshot interval only for a subscriber still in this bucket."""

    with s._SESSION_STREAM_SUBSCRIBERS_LOCK:
        if not _has_current_session_stream_subscriber_locked(s, session_id, candidates):
            return None
        with s._SESSION_STREAM_LAST_SNAPSHOT_LOCK:
            last_snapshot_at = s._SESSION_STREAM_LAST_SNAPSHOT_AT.get(session_id, 0.0)
            if last_snapshot_at and now - last_snapshot_at < interval_seconds:
                skipped_count = s._SESSION_STREAM_THROTTLED_COUNTS.get(session_id, 0) + 1
                s._SESSION_STREAM_THROTTLED_COUNTS[session_id] = skipped_count
                return False, skipped_count
            skipped_count = s._SESSION_STREAM_THROTTLED_COUNTS.pop(session_id, 0)
            s._SESSION_STREAM_LAST_SNAPSHOT_AT[session_id] = now
            return True, skipped_count


def _clear_session_detail_snapshot_slot(
    s: Any,
    session_id: str,
    candidates: list[Any],
    *,
    now: float,
) -> int | None:
    with s._SESSION_STREAM_SUBSCRIBERS_LOCK:
        if not _has_current_session_stream_subscriber_locked(s, session_id, candidates):
            return None
        with s._SESSION_STREAM_LAST_SNAPSHOT_LOCK:
            s._SESSION_STREAM_LAST_SNAPSHOT_AT[session_id] = now
            return s._SESSION_STREAM_THROTTLED_COUNTS.pop(session_id, 0)


def _encode_sse_event(event_name: str, payload: dict[str, Any], *, event_seq: int = 0) -> str:
    body = json.dumps(payload, ensure_ascii=False)
    seq = max(0, int(event_seq or 0))
    if not seq:
        # Payloads carry their own ledger watermark on the session stream.
        seq = max(0, int(payload.get("ledgerSeq") or payload.get("seq") or 0))
    if seq > 0:
        return f"id: {seq}\nevent: {event_name}\ndata: {body}\n\n"
    return f"event: {event_name}\ndata: {body}\n\n"


def parse_session_stream_last_event_id(value: str | None) -> int:
    """Parse an SSE ``Last-Event-ID`` header into a journal sequence."""

    if value is None or not value.strip():
        return 0
    try:
        parsed = int(value.strip())
    except ValueError as exc:
        raise ValueError("Last-Event-ID must be a non-negative journal sequence") from exc
    if parsed < 0:
        raise ValueError("Last-Event-ID must be a non-negative journal sequence")
    return parsed


def _session_stream_journal_event_attributes(event: Any) -> dict[str, Any]:
    sequence = max(0, int(getattr(event, "sequence", 0) or 0))
    payload = getattr(event, "payload", None)
    if not isinstance(payload, dict):
        payload = {}
    return {
        "seq": sequence,
        "eventId": str(getattr(event, "event_id", "") or "").strip(),
        "turnId": str(getattr(event, "turn_id", "") or "").strip(),
        "eventType": str(getattr(event, "event_type", "") or "").strip(),
        "status": str(getattr(event, "status", "") or "").strip(),
        "timestamp": str(getattr(event, "timestamp", "") or "").strip(),
        "payload": payload,
    }


def build_session_stream_resume(
    session_id: str,
    last_event_id: int,
) -> dict[str, Any]:
    """Build a bounded Last-Event-ID resume plan over the session journal.

    The plan covers journal events in ``(last_event_id, watermark]``. When the
    gap exceeds the bounded retention window the mode degrades to ``partial``:
    the caller falls back to a full initial payload and the client refetches
    instead of receiving a replay that silently under-covers the gap.
    """

    s = _service()
    normalized_session_id = str(session_id or "").strip()
    from_seq = max(0, int(last_event_id or 0))
    watermark = s._session_ledger_sequence(normalized_session_id)
    plan: dict[str, Any] = {
        "sessionId": normalized_session_id,
        "resume": "replayed",
        "fromSeq": from_seq,
        "toSeq": max(0, int(watermark or 0)),
        "replayedCount": 0,
        "events": [],
    }
    if not normalized_session_id or watermark <= from_seq:
        return plan
    try:
        events = list(s._load_session_conversation_events_cached(normalized_session_id) or [])
    except Exception:
        events = []
    if not events and watermark > 0:
        # The journal is unreadable while the watermark advanced: replaying an
        # empty window must not masquerade as covered — degrade honestly.
        plan["resume"] = "partial"
        return plan
    missed = sorted(
        (
            _session_stream_journal_event_attributes(event)
            for event in events
            if from_seq < int(getattr(event, "sequence", 0) or 0) <= watermark
        ),
        key=lambda item: item["seq"],
    )
    if len(missed) > SESSION_STREAM_RESUME_MAX_EVENTS:
        # Honest degradation: replay only the newest bounded window and mark
        # the resume partial so the client refetches the authoritative body.
        missed = missed[-SESSION_STREAM_RESUME_MAX_EVENTS:]
        plan["resume"] = "partial"
    plan["events"] = missed
    plan["replayedCount"] = len(missed) if plan["resume"] == "replayed" else 0
    return plan


def _session_stream_resume_journal_payload(
    session_id: str,
    missed_event: dict[str, Any],
) -> dict[str, Any]:
    payload = missed_event.get("payload")
    frame_payload: dict[str, Any] = {
        "type": "session_journal_event",
        "sessionId": str(session_id or "").strip(),
        "seq": max(0, int(missed_event.get("seq") or 0)),
        "eventId": str(missed_event.get("eventId") or ""),
        "turnId": str(missed_event.get("turnId") or ""),
        "eventType": str(missed_event.get("eventType") or ""),
        "status": str(missed_event.get("status") or ""),
        "timestamp": str(missed_event.get("timestamp") or ""),
    }
    encoded_length = len(json.dumps(payload or {}, ensure_ascii=False, default=str))
    if encoded_length <= SESSION_STREAM_RESUME_MAX_PAYLOAD_CHARS:
        frame_payload["payload"] = payload or {}
    else:
        frame_payload["payloadTruncated"] = True
    return frame_payload


def _session_stream_resume_event_payload(plan: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "stream_resume",
        "sessionId": str(plan.get("sessionId") or ""),
        "resume": str(plan.get("resume") or "replayed"),
        "fromSeq": max(0, int(plan.get("fromSeq") or 0)),
        "toSeq": max(0, int(plan.get("toSeq") or 0)),
        "replayedCount": max(0, int(plan.get("replayedCount") or 0)),
    }


def _session_stream_resume_frames(plan: dict[str, Any]) -> list[str]:
    """Encode one SSE frame per missed journal event plus the resume marker.

    The marker's ``toSeq`` is the journal watermark at plan time; live frames
    that follow carry ``ledgerSeq >= toSeq``, so a consumer can verify the
    replay→live handover has no gap and no overlap.
    """

    s = _service()
    session_id = str(plan.get("sessionId") or "")
    frames: list[str] = []
    for missed_event in plan.get("events") or []:
        payload = _session_stream_resume_journal_payload(session_id, missed_event)
        frames.append(
            s._encode_sse_event(
                "session_journal_event",
                payload,
                event_seq=max(0, int(missed_event.get("seq") or 0)),
            )
        )
    resume_payload = _session_stream_resume_event_payload(plan)
    frames.append(
        s._encode_sse_event(
            "stream_resume",
            resume_payload,
            event_seq=max(0, int(resume_payload.get("toSeq") or 0)),
        )
    )
    return frames


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
