"""Session conversation ledger bridge: events cache, append, ledger seq.

Claim scope: journal/ledger read cache + append/invalidate + sequence helpers.
Do not put submit/worker/stream publish, live_output recovery, or DTO projection here.

``project_root`` is injectable so the session_service facade can forward its
monkeypatchable ``PROJECT_ROOT`` (tests and agent-kernel root binding).
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any

from core.chat.chat_task_types import trim_lines
from core.chat.conversation_ledger import (
    append_conversation_event,
    conversation_ledger_path,
    latest_ledger_sequence,
    load_conversation_events,
)

from ..runtime_scene_service import record_runtime_scene_event

DEFAULT_PROJECT_ROOT = Path(__file__).resolve().parents[4]
# Alias for package-local defaults / direct module tests.
PROJECT_ROOT = DEFAULT_PROJECT_ROOT

SESSION_CONVERSATION_EVENTS_CACHE_MAX_ENTRIES = 64
_SESSION_CONVERSATION_EVENTS_CACHE_MAX_ENTRIES = SESSION_CONVERSATION_EVENTS_CACHE_MAX_ENTRIES

_SESSION_CONVERSATION_EVENTS_CACHE_LOCK = threading.Lock()
_SESSION_CONVERSATION_EVENTS_CACHE_CONDITION = threading.Condition(
    _SESSION_CONVERSATION_EVENTS_CACHE_LOCK
)
_SESSION_CONVERSATION_EVENTS_CACHE: dict[str, dict[str, Any]] = {}
_SESSION_CONVERSATION_EVENTS_INFLIGHT: dict[str, object] = {}


def _perf_counter() -> float:
    return time.perf_counter()


def _resolve_project_root(project_root: Path | None) -> Path:
    return Path(project_root) if project_root is not None else Path(PROJECT_ROOT)


def session_conversation_events_signature(
    session_id: str,
    *,
    project_root: Path | None = None,
) -> tuple[str, int, int, int]:
    """Cheap signature for ledger file + latest sequence."""

    normalized_session_id = str(session_id or "").strip()
    if not normalized_session_id:
        return ("", 0, -1, -1)
    root = _resolve_project_root(project_root)
    path = conversation_ledger_path(root, normalized_session_id)
    try:
        stat = path.stat()
        modified_ns = int(stat.st_mtime_ns)
        size = int(stat.st_size)
    except OSError:
        modified_ns = -1
        size = -1
    try:
        sequence = latest_ledger_sequence(root, normalized_session_id)
    except Exception:
        sequence = 0
    return (str(path), int(sequence or 0), modified_ns, size)


def prune_session_conversation_events_cache_locked() -> None:
    while len(_SESSION_CONVERSATION_EVENTS_CACHE) > _SESSION_CONVERSATION_EVENTS_CACHE_MAX_ENTRIES:
        oldest_key = min(
            _SESSION_CONVERSATION_EVENTS_CACHE,
            key=lambda key: float(
                _SESSION_CONVERSATION_EVENTS_CACHE.get(key, {}).get("last_access") or 0.0
            ),
        )
        _SESSION_CONVERSATION_EVENTS_CACHE.pop(oldest_key, None)


def invalidate_session_conversation_events_cache(session_id: str = "") -> None:
    normalized_session_id = str(session_id or "").strip()
    with _SESSION_CONVERSATION_EVENTS_CACHE_CONDITION:
        if normalized_session_id:
            _SESSION_CONVERSATION_EVENTS_CACHE.pop(normalized_session_id, None)
        else:
            _SESSION_CONVERSATION_EVENTS_CACHE.clear()
        _SESSION_CONVERSATION_EVENTS_CACHE_CONDITION.notify_all()


def load_session_conversation_events_cached(
    session_id: str,
    *,
    project_root: Path | None = None,
) -> list[Any]:
    """Load ledger events with signature cache + single-flight inflight wait."""

    normalized_session_id = str(session_id or "").strip()
    if not normalized_session_id:
        return []
    root = _resolve_project_root(project_root)
    owner = object()
    while True:
        signature = session_conversation_events_signature(
            normalized_session_id,
            project_root=root,
        )
        now = _perf_counter()
        with _SESSION_CONVERSATION_EVENTS_CACHE_CONDITION:
            cached = _SESSION_CONVERSATION_EVENTS_CACHE.get(normalized_session_id)
            if cached and cached.get("signature") == signature:
                cached["last_access"] = now
                return list(cached.get("events") or ())
            if normalized_session_id not in _SESSION_CONVERSATION_EVENTS_INFLIGHT:
                _SESSION_CONVERSATION_EVENTS_INFLIGHT[normalized_session_id] = owner
                break
            _SESSION_CONVERSATION_EVENTS_CACHE_CONDITION.wait()

    try:
        events = list(load_conversation_events(root, normalized_session_id) or [])
    except Exception:
        with _SESSION_CONVERSATION_EVENTS_CACHE_CONDITION:
            if _SESSION_CONVERSATION_EVENTS_INFLIGHT.get(normalized_session_id) is owner:
                _SESSION_CONVERSATION_EVENTS_INFLIGHT.pop(normalized_session_id, None)
            _SESSION_CONVERSATION_EVENTS_CACHE_CONDITION.notify_all()
        raise
    with _SESSION_CONVERSATION_EVENTS_CACHE_CONDITION:
        if _SESSION_CONVERSATION_EVENTS_INFLIGHT.get(normalized_session_id) is owner:
            _SESSION_CONVERSATION_EVENTS_CACHE[normalized_session_id] = {
                "signature": signature,
                "events": tuple(events),
                "last_access": now,
            }
            _SESSION_CONVERSATION_EVENTS_INFLIGHT.pop(normalized_session_id, None)
            prune_session_conversation_events_cache_locked()
        _SESSION_CONVERSATION_EVENTS_CACHE_CONDITION.notify_all()
        return list(events)


def load_session_conversation_events_snapshot(
    session_id: str,
    *,
    project_root: Path | None = None,
) -> list[Any]:
    """Return the current session ledger snapshot through the shared signature cache."""

    return load_session_conversation_events_cached(session_id, project_root=project_root)


def session_ledger_sequence(
    session_id: str,
    *,
    project_root: Path | None = None,
) -> int:
    normalized_session_id = str(session_id or "").strip()
    if not normalized_session_id:
        return 0
    root = _resolve_project_root(project_root)
    try:
        return latest_ledger_sequence(root, normalized_session_id)
    except Exception:
        return 0


def append_session_conversation_event(
    session_id: str,
    turn_id: str,
    event_type: str,
    *,
    status: str = "",
    payload: dict[str, Any] | None = None,
    source: str = "session_service",
    visible_in_model: bool = True,
    projection_kind: str = "",
    tool_call_id: str = "",
    correlation_id: str = "",
    source_kind: str = "",
    project_root: Path | None = None,
) -> None:
    """Append a ledger event and invalidate the session events cache."""

    normalized_session_id = str(session_id or "").strip()
    normalized_event_type = str(event_type or "").strip()
    if not normalized_session_id or not normalized_event_type:
        return
    root = _resolve_project_root(project_root)
    try:
        append_conversation_event(
            root,
            normalized_session_id,
            str(turn_id or "").strip(),
            normalized_event_type,
            status=status,
            payload=payload or {},
            source=source,
            visible_in_model=visible_in_model,
            projection_kind=projection_kind,
            tool_call_id=tool_call_id,
            correlation_id=correlation_id,
            source_kind=source_kind,
        )
        invalidate_session_conversation_events_cache(normalized_session_id)
    except Exception as exc:
        try:
            record_runtime_scene_event(
                "conversation",
                "conversation_ledger",
                "conversation.ledger.append_failed",
                level="warning",
                outcome="failed",
                message="Failed to append a chat conversation ledger event.",
                fields={
                    "sessionId": normalized_session_id,
                    "turnId": str(turn_id or "").strip(),
                    "eventType": normalized_event_type,
                    "errorType": type(exc).__name__,
                    "errorPreview": trim_lines(str(exc), max_lines=2),
                },
                lifecycle=True,
            )
        except Exception:
            pass
        raise


# Private aliases matching historical session_service names (module-direct use).
_session_conversation_events_signature = session_conversation_events_signature
_prune_session_conversation_events_cache_locked = prune_session_conversation_events_cache_locked
_invalidate_session_conversation_events_cache = invalidate_session_conversation_events_cache
_load_session_conversation_events_cached = load_session_conversation_events_cached
_session_ledger_sequence = session_ledger_sequence
_append_session_conversation_event = append_session_conversation_event
