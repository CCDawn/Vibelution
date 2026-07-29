"""Session list index cache (signature + inflight single-flight build).

Claim scope: session list cache only. Do not put stream/turn execution here.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any

from core.ui.chat_state import chat_state_path

from .. import agent_directory_service

PROJECT_ROOT = Path(__file__).resolve().parents[4]

_SESSION_LIST_CACHE_LOCK = threading.Lock()
_SESSION_LIST_CACHE_CONDITION = threading.Condition(_SESSION_LIST_CACHE_LOCK)
SESSION_LIST_CACHE_TTL_SECONDS = 4.0
_SESSION_LIST_CACHE_TTL_SECONDS = SESSION_LIST_CACHE_TTL_SECONDS
# Cold session-index builds can legitimately cross 10 seconds under filesystem
# contention. Keep the fallback reclaim bounded without letting normal waiters
# replace a live builder before it can publish the shared snapshot.
_SESSION_LIST_INFLIGHT_STALE_SECONDS = 30.0
_SESSION_LIST_INFLIGHT_WAIT_SECONDS = 0.2
_SESSION_LIST_CACHE: dict[str, Any] = {}


def _perf_counter() -> float:
    return time.perf_counter()


def session_list_source_signature() -> tuple[Any, ...]:
    """Return cheap file signatures for the read-only session index inputs."""

    def signature(path: Path) -> tuple[str, int, int]:
        try:
            stat = path.stat()
        except OSError:
            return (str(path), -1, -1)
        return (str(path), int(stat.st_mtime_ns), int(stat.st_size))

    inbox_signatures: list[tuple[str, tuple[str, bool, int, int]]] = []
    state = agent_directory_service.load_state()
    agents = list(state.get("agents") or []) if isinstance(state, dict) else []
    for agent in agents:
        if not isinstance(agent, dict):
            continue
        agent_id = str(agent.get("agentId") or "").strip()
        if not agent_id:
            continue
        inbox_path = agent_directory_service._agent_workspace_event_path(
            agent,
            "agent_inbox_messages.jsonl",
        )
        inbox_signatures.append(
            (
                agent_id,
                agent_directory_service._jsonl_signature(inbox_path),
            )
        )

    return (
        str(PROJECT_ROOT.resolve()),
        signature(chat_state_path(PROJECT_ROOT)),
        signature(agent_directory_service.registry_path()),
        tuple(inbox_signatures),
    )


def copy_session_list_snapshot(sessions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [copy_session_summary_snapshot(item) for item in sessions if isinstance(item, dict)]


def copy_session_summary_snapshot(item: dict[str, Any]) -> dict[str, Any]:
    snapshot = dict(item)
    child_session_ids = snapshot.get("childSessionIds")
    if isinstance(child_session_ids, list):
        snapshot["childSessionIds"] = list(child_session_ids)
    result_card = snapshot.get("resultCard")
    if isinstance(result_card, dict):
        copied_card = dict(result_card)
        changed_files = copied_card.get("changedFiles")
        if isinstance(changed_files, list):
            copied_card["changedFiles"] = list(changed_files)
        validations = copied_card.get("validations")
        if isinstance(validations, list):
            copied_card["validations"] = list(validations)
        snapshot["resultCard"] = copied_card
    return snapshot


def get_session_list_cache(
    *,
    now: float,
    signature: tuple[Any, ...],
    allow_stale_matching_signature: bool = False,
) -> tuple[list[dict[str, Any]], int, int, int] | None:
    with _SESSION_LIST_CACHE_LOCK:
        return get_session_list_cache_locked(
            now=now,
            signature=signature,
            allow_stale_matching_signature=allow_stale_matching_signature,
        )


def get_session_list_cache_locked(
    *,
    now: float,
    signature: tuple[Any, ...],
    allow_stale_matching_signature: bool = False,
) -> tuple[list[dict[str, Any]], int, int, int] | None:
    snapshot = _SESSION_LIST_CACHE.get("sessions")
    if not isinstance(snapshot, list):
        return None
    if _SESSION_LIST_CACHE.get("signature") != signature:
        return None
    cached_at = _SESSION_LIST_CACHE.get("cached_at")
    try:
        cache_age_seconds = now - float(cached_at)
    except (TypeError, ValueError):
        return None
    if cache_age_seconds < 0:
        return None
    if not allow_stale_matching_signature and cache_age_seconds > _SESSION_LIST_CACHE_TTL_SECONDS:
        return None
    return (
        copy_session_list_snapshot(snapshot),
        int(round(cache_age_seconds * 1000)),
        int(_SESSION_LIST_CACHE.get("conversation_count") or 0),
        int(_SESSION_LIST_CACHE.get("agent_count") or 0),
    )


def begin_session_list_cache_build(
    *,
    now: float,
    signature: tuple[Any, ...],
    allow_stale_matching_signature: bool = False,
) -> tuple[tuple[list[dict[str, Any]], int, int, int] | None, bool, bool]:
    """Return cached sessions or reserve this caller as the index builder."""

    waited_for_inflight = False
    with _SESSION_LIST_CACHE_CONDITION:
        cached = get_session_list_cache_locked(
            now=now,
            signature=signature,
            allow_stale_matching_signature=allow_stale_matching_signature,
        )
        if cached is not None:
            return cached, False, waited_for_inflight
        while _SESSION_LIST_CACHE.get("inflight_signature") == signature:
            waited_for_inflight = True
            inflight_started_at = _SESSION_LIST_CACHE.get("inflight_started_at")
            try:
                inflight_age_seconds = now - float(inflight_started_at)
            except (TypeError, ValueError):
                inflight_age_seconds = _SESSION_LIST_INFLIGHT_STALE_SECONDS
            if inflight_age_seconds >= _SESSION_LIST_INFLIGHT_STALE_SECONDS:
                _SESSION_LIST_CACHE.pop("inflight_signature", None)
                _SESSION_LIST_CACHE.pop("inflight_started_at", None)
                break
            remaining_stale_seconds = max(
                _SESSION_LIST_INFLIGHT_STALE_SECONDS - inflight_age_seconds,
                0.0,
            )
            _SESSION_LIST_CACHE_CONDITION.wait(
                timeout=min(_SESSION_LIST_INFLIGHT_WAIT_SECONDS, remaining_stale_seconds)
            )
            now = _perf_counter()
            cached = get_session_list_cache_locked(
                now=now,
                signature=signature,
                allow_stale_matching_signature=allow_stale_matching_signature,
            )
            if cached is not None:
                return cached, False, waited_for_inflight
            if _SESSION_LIST_CACHE.get("inflight_signature") != signature:
                break
        _SESSION_LIST_CACHE["inflight_signature"] = signature
        _SESSION_LIST_CACHE["inflight_started_at"] = now
        return None, True, waited_for_inflight


def finish_session_list_cache_build(
    *,
    signature: tuple[Any, ...],
    sessions: list[dict[str, Any]] | None = None,
    started_at: float | None = None,
    conversation_count: int = 0,
    agent_count: int = 0,
) -> None:
    with _SESSION_LIST_CACHE_CONDITION:
        owns_inflight = _SESSION_LIST_CACHE.get("inflight_signature") == signature
        if started_at is not None:
            try:
                owns_inflight = owns_inflight and (
                    float(_SESSION_LIST_CACHE.get("inflight_started_at")) == float(started_at)
                )
            except (TypeError, ValueError):
                owns_inflight = False
        if sessions is not None and started_at is not None:
            if not owns_inflight:
                _SESSION_LIST_CACHE_CONDITION.notify_all()
                return
            _SESSION_LIST_CACHE.clear()
            _SESSION_LIST_CACHE.update(
                {
                    "sessions": copy_session_list_snapshot(sessions),
                    "cached_at": started_at,
                    "signature": signature,
                    "conversation_count": int(conversation_count),
                    "agent_count": int(agent_count),
                }
            )
        elif _SESSION_LIST_CACHE.get("inflight_signature") == signature:
            if started_at is None or owns_inflight:
                _SESSION_LIST_CACHE.pop("inflight_signature", None)
                _SESSION_LIST_CACHE.pop("inflight_started_at", None)
        _SESSION_LIST_CACHE_CONDITION.notify_all()


def set_session_list_cache(
    sessions: list[dict[str, Any]],
    *,
    now: float,
    signature: tuple[Any, ...],
    conversation_count: int,
    agent_count: int,
) -> None:
    with _SESSION_LIST_CACHE_LOCK:
        _SESSION_LIST_CACHE.clear()
        _SESSION_LIST_CACHE.update(
            {
                "sessions": copy_session_list_snapshot(sessions),
                "cached_at": now,
                "signature": signature,
                "conversation_count": int(conversation_count),
                "agent_count": int(agent_count),
            }
        )


def invalidate_session_list_cache() -> None:
    with _SESSION_LIST_CACHE_CONDITION:
        _SESSION_LIST_CACHE.clear()
        _SESSION_LIST_CACHE_CONDITION.notify_all()


# Private aliases matching historical session_service names (facade wiring).
_session_list_source_signature = session_list_source_signature
_copy_session_list_snapshot = copy_session_list_snapshot
_copy_session_summary_snapshot = copy_session_summary_snapshot
_get_session_list_cache = get_session_list_cache
_get_session_list_cache_locked = get_session_list_cache_locked
_begin_session_list_cache_build = begin_session_list_cache_build
_finish_session_list_cache_build = finish_session_list_cache_build
_set_session_list_cache = set_session_list_cache
_invalidate_session_list_cache_core = invalidate_session_list_cache
