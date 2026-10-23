"""Global session-index event stream.

Per-session SSE (``/api/sessions/{id}/events``) only reaches a client that has
already opened that session. The session rail needs the opposite shape: one
connection that reports "this session's summary changed" for every session, so
the sidebar stops refetching the whole index after each turn settles and so
other windows do not need their own polling.

This module owns that fan-out. It is deliberately summary-level only: a frame
carries a session id and the kind of index change, never transcript content,
turn payloads or detail. Turn detail keeps flowing through the per-session
stream, which remains the single owner of transcript delivery.

Bounded queues matter here: a slow or stalled consumer must not block a turn
that is publishing, so a full queue drops its oldest frame instead of waiting.
"""

from __future__ import annotations

import asyncio
import json
import queue
import threading
import time
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Mapping

SESSION_INDEX_CHANGE_UPSERTED = "session.upserted"
SESSION_INDEX_CHANGE_REMOVED = "session.removed"

_HEARTBEAT_SECONDS = 15.0
_POLL_SECONDS = 0.5
_QUEUE_SIZE = 64

_SUBSCRIBERS_LOCK = threading.Lock()
_SUBSCRIBERS: set[queue.Queue[dict[str, Any]]] = set()


def _utc_now_text() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def normalize_session_index_change_type(change_type: str) -> str:
    """Map a caller's change kind onto the two frames the rail understands."""

    normalized = str(change_type or "").strip().lower()
    if normalized in {"remove", "removed", "delete", "deleted", "archive", "archived"}:
        return SESSION_INDEX_CHANGE_REMOVED
    return SESSION_INDEX_CHANGE_UPSERTED


def subscribe_session_index_events() -> queue.Queue[dict[str, Any]]:
    subscriber: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=_QUEUE_SIZE)
    with _SUBSCRIBERS_LOCK:
        _SUBSCRIBERS.add(subscriber)
    return subscriber


def unsubscribe_session_index_events(subscriber: queue.Queue[dict[str, Any]]) -> None:
    with _SUBSCRIBERS_LOCK:
        _SUBSCRIBERS.discard(subscriber)


def session_index_subscriber_count() -> int:
    with _SUBSCRIBERS_LOCK:
        return len(_SUBSCRIBERS)


def _offer(subscriber: queue.Queue[dict[str, Any]], payload: dict[str, Any]) -> None:
    try:
        subscriber.put_nowait(payload)
        return
    except queue.Full:
        pass
    # A stalled reader must not back-pressure the turn that is publishing.
    # Drop the oldest frame and retry once; if it is still full the frame is lost
    # and the client recovers on its next index read.
    try:
        subscriber.get_nowait()
    except queue.Empty:
        pass
    try:
        subscriber.put_nowait(payload)
    except queue.Full:
        pass


_INDEX_PATCH_FIELDS = (
    "lastActive",
    "updatedAt",
    "status",
    "currentPhase",
    "lastTurnStatus",
    "lastTurnTerminalTurnId",
    "terminalReason",
    "pinnedAtMs",
    "archiveState",
    "taskSummary",
)


def index_patch_from_detail(detail: Mapping[str, Any] | None) -> dict[str, Any]:
    """Pick the index-row fields a settled detail projection can hand the rail.

    Only keys the detail actually carries are forwarded: an absent key must not
    clear the row's current value, so the rail keeps whatever it already shows.
    """

    if not isinstance(detail, Mapping):
        return {}
    return {
        field_name: detail[field_name]
        for field_name in _INDEX_PATCH_FIELDS
        if field_name in detail
    }


def _normalize_index_patch(patch: Mapping[str, Any] | None) -> dict[str, Any]:
    """Keep only the index-row fields a rail can apply without a refetch.

    Empty values are preserved on purpose: clearing a terminal reason is a real
    change, and dropping the key would leave the stale value on screen.
    """

    if not patch:
        return {}
    normalized: dict[str, Any] = {}
    for field_name in _INDEX_PATCH_FIELDS:
        if field_name in patch:
            normalized[field_name] = patch[field_name]
    return normalized


def publish_session_index_delta(
    session_id: str,
    change_type: str,
    *,
    patch: Mapping[str, Any] | None = None,
) -> int:
    """Fan out one index change. Returns how many subscribers accepted it.

    Returns 0 without doing any work when nobody is listening, which is the
    common case for headless runs and for tests that never open the rail.

    ``patch`` carries the index-row fields this change actually moved. The rail
    applies them in place; a frame without a patch still means "this row moved",
    so the client falls back to a single index read.
    """

    normalized_session_id = str(session_id or "").strip()
    if not normalized_session_id:
        return 0
    with _SUBSCRIBERS_LOCK:
        subscribers = list(_SUBSCRIBERS)
    if not subscribers:
        return 0
    payload: dict[str, Any] = {
        "type": normalize_session_index_change_type(change_type),
        "sessionId": normalized_session_id,
        "at": _utc_now_text(),
    }
    normalized_patch = _normalize_index_patch(patch)
    if normalized_patch:
        payload["patch"] = normalized_patch
    for subscriber in subscribers:
        _offer(subscriber, payload)
    return len(subscribers)


def publish_session_index_change_safely(
    session_id: str,
    change_type: str,
    *,
    patch: Mapping[str, Any] | None = None,
) -> int:
    """Publish one index change without letting a rail failure reach the caller.

    Removal and archive are metadata flips: nothing about them may fail a user
    action just because nobody holds a rail connection, so every transport
    problem degrades to "no listeners" instead of surfacing.
    """

    try:
        return publish_session_index_delta(session_id, change_type, patch=patch)
    except Exception:
        return 0


def encode_session_index_sse_frame(payload: dict[str, Any]) -> str:
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    event_type = str(payload.get("type") or "message")
    return f"event: {event_type}\ndata: {body}\n\n"


def _poll(subscriber: queue.Queue[dict[str, Any]], timeout: float) -> dict[str, Any] | None:
    try:
        return subscriber.get(timeout=timeout)
    except queue.Empty:
        return None


async def stream_session_index_events_async(
    *,
    heartbeat_seconds: float = _HEARTBEAT_SECONDS,
) -> AsyncIterator[str]:
    """Yield summary-level index frames as SSE text.

    Heartbeats keep proxies and browsers from closing an idle stream; the rail
    can be quiet for minutes when no turn is running.
    """

    subscriber = subscribe_session_index_events()
    loop = asyncio.get_running_loop()
    try:
        yield encode_session_index_sse_frame({"type": "ready", "at": _utc_now_text()})
        last_heartbeat = time.monotonic()
        while True:
            payload = await loop.run_in_executor(None, _poll, subscriber, _POLL_SECONDS)
            now = time.monotonic()
            if payload is None:
                if now - last_heartbeat >= heartbeat_seconds:
                    last_heartbeat = now
                    yield encode_session_index_sse_frame(
                        {"type": "heartbeat", "at": _utc_now_text()}
                    )
                continue
            last_heartbeat = now
            yield encode_session_index_sse_frame(payload)
    finally:
        unsubscribe_session_index_events(subscriber)


__all__ = [
    "SESSION_INDEX_CHANGE_REMOVED",
    "SESSION_INDEX_CHANGE_UPSERTED",
    "encode_session_index_sse_frame",
    "index_patch_from_detail",
    "normalize_session_index_change_type",
    "publish_session_index_delta",
    "publish_session_index_change_safely",
    "session_index_subscriber_count",
    "stream_session_index_events_async",
    "subscribe_session_index_events",
    "unsubscribe_session_index_events",
]
