"""Session list index cache (signature + inflight single-flight build).

Claim scope: session list cache only. Do not put stream/turn execution here.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any

from . import directory_runtime
from .. import agent_directory_service

PROJECT_ROOT = Path(__file__).resolve().parents[4]

_SESSION_LIST_CACHE_LOCK = threading.Lock()
_SESSION_LIST_CACHE_CONDITION = threading.Condition(_SESSION_LIST_CACHE_LOCK)
SESSION_LIST_CACHE_TTL_SECONDS = 4.0
_SESSION_LIST_CACHE_TTL_SECONDS = SESSION_LIST_CACHE_TTL_SECONDS
# Last-good snapshots are served instantly (stale-while-revalidate) when the
# exact signature misses. They stay eligible far longer than the freshness TTL
# because a 126-session summary page is cheap compared to a discarded-JSON
# rebuild; the bound is only a memory/trust ceiling.
SESSION_LIST_STALE_SERVE_MAX_SECONDS = 3600.0
# Cold session-index builds can legitimately cross 10 seconds under filesystem
# contention. Keep the fallback reclaim bounded without letting normal waiters
# replace a live builder before it can publish the shared snapshot.
_SESSION_LIST_INFLIGHT_STALE_SECONDS = 30.0
_SESSION_LIST_INFLIGHT_WAIT_SECONDS = 0.2
_SESSION_LIST_CACHE_MAX_ENTRIES = 4
_SESSION_LIST_LAST_GOOD_MAX_ENTRIES = 4
_SESSION_LIST_CACHE: dict[str, Any] = {}


def _perf_counter() -> float:
    return time.perf_counter()


def _project_root() -> Path:
    """Resolve the runtime project root, falling back to the checkout root.

    Tests swap ``session_service.PROJECT_ROOT`` to an isolated tree; keying the
    signature (and therefore the stale-serve slot) off the process checkout
    root leaked snapshots across project roots.
    """

    from core.web.services import session_service

    root = getattr(session_service, "PROJECT_ROOT", None)
    return Path(root) if root else PROJECT_ROOT


def session_list_source_signature() -> tuple[Any, ...]:
    """Return cheap file signatures for the read-only session index inputs."""

    def signature(path: Path) -> tuple[str, int, int]:
        try:
            stat = path.stat()
        except OSError:
            return (str(path), -1, -1)
        return (str(path), int(stat.st_mtime_ns), int(stat.st_size))

    project_root = _project_root()
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

    store_path = directory_runtime.conversation_store_path(project_root)
    return (
        str(project_root.resolve()),
        signature(store_path),
        signature(Path(f"{store_path}-wal")),
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
    entries = _SESSION_LIST_CACHE.get("entries")
    if not isinstance(entries, dict):
        return None
    entry = entries.get(signature)
    if not isinstance(entry, dict):
        return None
    snapshot = entry.get("sessions")
    if not isinstance(snapshot, list):
        return None
    cached_at = entry.get("cached_at")
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
        int(entry.get("conversation_count") or 0),
        int(entry.get("agent_count") or 0),
    )


def _session_list_inflight_key(signature: tuple[Any, ...]) -> tuple[Any, ...]:
    """Return a stable single-flight key across SQLite/WAL signature churn."""

    try:
        source_signature, include_hidden = signature
        project_root = source_signature[0]
        return (str(project_root), bool(include_hidden))
    except (IndexError, TypeError, ValueError):
        return signature


def _session_list_inflight_builds_locked() -> dict[tuple[Any, ...], float]:
    inflight_builds = _SESSION_LIST_CACHE.get("inflight_builds")
    if not isinstance(inflight_builds, dict):
        inflight_builds = {}
        _SESSION_LIST_CACHE["inflight_builds"] = inflight_builds
    return inflight_builds


def _latest_shared_build_cache_locked(
    *,
    now: float,
    inflight_key: tuple[Any, ...],
) -> tuple[list[dict[str, Any]], int, int, int] | None:
    """Return the result just published by a signature-shifting shared build."""

    entries = _SESSION_LIST_CACHE.get("entries")
    if not isinstance(entries, dict):
        return None
    for candidate_signature in reversed(tuple(entries)):
        if _session_list_inflight_key(candidate_signature) != inflight_key:
            continue
        shared = get_session_list_cache_locked(
            now=now,
            signature=candidate_signature,
            allow_stale_matching_signature=True,
        )
        if shared is not None:
            return shared
    return None


def _store_session_list_cache_entry_locked(
    *,
    signature: tuple[Any, ...],
    sessions: list[dict[str, Any]],
    cached_at: float,
    conversation_count: int,
    agent_count: int,
) -> None:
    entries = _SESSION_LIST_CACHE.get("entries")
    if not isinstance(entries, dict):
        entries = {}
        _SESSION_LIST_CACHE["entries"] = entries
    entries.pop(signature, None)
    entries[signature] = {
        "sessions": copy_session_list_snapshot(sessions),
        "cached_at": cached_at,
        "conversation_count": int(conversation_count),
        "agent_count": int(agent_count),
    }
    while len(entries) > _SESSION_LIST_CACHE_MAX_ENTRIES:
        entries.pop(next(iter(entries)))
    last_good_entries = _SESSION_LIST_CACHE.get("last_good")
    if not isinstance(last_good_entries, dict):
        last_good_entries = {}
        _SESSION_LIST_CACHE["last_good"] = last_good_entries
    last_good_key = _session_list_inflight_key(signature)
    last_good_entries.pop(last_good_key, None)
    last_good_entries[last_good_key] = {
        "sessions": copy_session_list_snapshot(sessions),
        "cached_at": cached_at,
        "conversation_count": int(conversation_count),
        "agent_count": int(agent_count),
    }
    while len(last_good_entries) > _SESSION_LIST_LAST_GOOD_MAX_ENTRIES:
        last_good_entries.pop(next(iter(last_good_entries)))


def get_last_good_session_list_snapshot(
    *,
    now: float,
    signature: tuple[Any, ...],
    max_age_seconds: float = SESSION_LIST_STALE_SERVE_MAX_SECONDS,
) -> tuple[list[dict[str, Any]], int, int, int] | None:
    """Return the newest snapshot for this source even when it is stale.

    Result shape: ``(sessions, cache_age_ms, conversation_count, agent_count)``.
    ``max_age_seconds`` bounds how long an old snapshot may be served; explicit
    mutation paths still purge this slot through ``invalidate_session_list_cache``.
    """

    with _SESSION_LIST_CACHE_LOCK:
        last_good_entries = _SESSION_LIST_CACHE.get("last_good")
        if not isinstance(last_good_entries, dict):
            return None
        entry = last_good_entries.get(_session_list_inflight_key(signature))
        if not isinstance(entry, dict):
            return None
        snapshot = entry.get("sessions")
        if not isinstance(snapshot, list):
            return None
        try:
            cache_age_seconds = now - float(entry.get("cached_at"))
        except (TypeError, ValueError):
            return None
        if cache_age_seconds < 0 or cache_age_seconds > max_age_seconds:
            return None
        return (
            copy_session_list_snapshot(snapshot),
            int(round(cache_age_seconds * 1000)),
            int(entry.get("conversation_count") or 0),
            int(entry.get("agent_count") or 0),
        )


def _session_list_refresh_key(signature: tuple[Any, ...]) -> tuple[Any, ...]:
    return _session_list_inflight_key(signature) + ("__refresh__",)


def reserve_session_list_refresh(
    *,
    now: float,
    signature: tuple[Any, ...],
) -> float | None:
    """Reserve the single background refresh worker; ``None`` when throttled.

    The reservation is independent of the signature-keyed inflight build slot
    so a stale serve never blocks an exact-signature build, and a burst of
    stale reads coalesces into one background rebuild.
    """

    refresh_key = _session_list_refresh_key(signature)
    with _SESSION_LIST_CACHE_CONDITION:
        inflight_builds = _session_list_inflight_builds_locked()
        existing = inflight_builds.get(refresh_key)
        if existing is not None:
            try:
                existing_age_seconds = now - float(existing)
            except (TypeError, ValueError):
                existing_age_seconds = _SESSION_LIST_INFLIGHT_STALE_SECONDS
            if existing_age_seconds < _SESSION_LIST_INFLIGHT_STALE_SECONDS:
                return None
            inflight_builds.pop(refresh_key, None)
        inflight_builds[refresh_key] = now
        return now


def release_session_list_refresh(
    *,
    started_at: float,
    signature: tuple[Any, ...],
) -> None:
    refresh_key = _session_list_refresh_key(signature)
    with _SESSION_LIST_CACHE_CONDITION:
        inflight_builds = _session_list_inflight_builds_locked()
        reserved = inflight_builds.get(refresh_key)
        if reserved is not None:
            try:
                matches = float(reserved) == float(started_at)
            except (TypeError, ValueError):
                matches = False
            if matches:
                inflight_builds.pop(refresh_key, None)
        _SESSION_LIST_CACHE_CONDITION.notify_all()


def is_session_list_refresh_reserved(*, signature: tuple[Any, ...]) -> bool:
    with _SESSION_LIST_CACHE_LOCK:
        inflight_builds = _session_list_inflight_builds_locked()
        return _session_list_refresh_key(signature) in inflight_builds


def begin_session_list_cache_build(
    *,
    now: float,
    signature: tuple[Any, ...],
    allow_stale_matching_signature: bool = False,
) -> tuple[tuple[list[dict[str, Any]], int, int, int] | None, bool, bool]:
    """Return cached sessions or reserve this caller as the index builder."""

    waited_for_inflight = False
    request_started_at = now
    with _SESSION_LIST_CACHE_CONDITION:
        cached = get_session_list_cache_locked(
            now=now,
            signature=signature,
            allow_stale_matching_signature=allow_stale_matching_signature,
        )
        if cached is not None:
            return cached, False, waited_for_inflight
        inflight_key = _session_list_inflight_key(signature)
        inflight_builds = _session_list_inflight_builds_locked()
        while inflight_key in inflight_builds:
            waited_for_inflight = True
            inflight_started_at = inflight_builds.get(inflight_key)
            try:
                inflight_age_seconds = now - float(inflight_started_at)
            except (TypeError, ValueError):
                inflight_age_seconds = _SESSION_LIST_INFLIGHT_STALE_SECONDS
            if inflight_age_seconds >= _SESSION_LIST_INFLIGHT_STALE_SECONDS:
                inflight_builds.pop(inflight_key, None)
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
            inflight_builds = _session_list_inflight_builds_locked()
            if inflight_key not in inflight_builds:
                shared = _latest_shared_build_cache_locked(
                    now=now,
                    inflight_key=inflight_key,
                )
                if shared is not None:
                    return shared, False, waited_for_inflight
                break
        inflight_builds = _session_list_inflight_builds_locked()
        # Reserve under the caller's timestamp so ``finish`` can prove
        # ownership after this call waited on another builder.
        inflight_builds[inflight_key] = request_started_at
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
        inflight_key = _session_list_inflight_key(signature)
        inflight_builds = _session_list_inflight_builds_locked()
        owns_inflight = inflight_key in inflight_builds
        if started_at is not None:
            try:
                owns_inflight = owns_inflight and (
                    float(inflight_builds.get(inflight_key)) == float(started_at)
                )
            except (TypeError, ValueError):
                owns_inflight = False
        if sessions is not None and started_at is not None:
            if not owns_inflight:
                _SESSION_LIST_CACHE_CONDITION.notify_all()
                return
            _store_session_list_cache_entry_locked(
                signature=signature,
                sessions=sessions,
                cached_at=started_at,
                conversation_count=conversation_count,
                agent_count=agent_count,
            )
            inflight_builds.pop(inflight_key, None)
        elif inflight_key in inflight_builds:
            if started_at is None or owns_inflight:
                inflight_builds.pop(inflight_key, None)
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
        _store_session_list_cache_entry_locked(
            signature=signature,
            sessions=sessions,
            cached_at=now,
            conversation_count=conversation_count,
            agent_count=agent_count,
        )


def invalidate_session_list_cache() -> None:
    """Drop every cached session list, including the stale-serve snapshot.

    Mutation paths (create/archive/delete/rename/repair) call this so the next
    read reflects the change immediately; signature-only churn never reaches
    here and stays eligible for serve-and-refresh.
    """

    with _SESSION_LIST_CACHE_CONDITION:
        for key in ("entries", "inflight_builds", "last_good"):
            _SESSION_LIST_CACHE.pop(key, None)
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
_get_last_good_session_list_snapshot = get_last_good_session_list_snapshot
_reserve_session_list_refresh = reserve_session_list_refresh
_release_session_list_refresh = release_session_list_refresh
_is_session_list_refresh_reserved = is_session_list_refresh_reserved
