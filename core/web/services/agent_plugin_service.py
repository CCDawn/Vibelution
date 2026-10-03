"""Trusted first-party Agent plugin catalog and binding facade."""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import Any

from core.agent_plugins import installed_plugin_catalog
from core.agent_plugins.virtual_human_life.manifest import PLUGIN_ID

from .virtual_human_life_service import (
    get_virtual_human_life_service,
    update_virtual_human_binding,
    virtual_human_binding,
)

logger = logging.getLogger(__name__)

_SESSION_ACTIVITY_FIELDS = (
    "id",
    "status",
    "currentPhase",
    "lastTurnStatus",
    "terminalReason",
    "taskSummary",
    "updatedAt",
    "lastActive",
    "agentInboxPendingCount",
)

# Memoized terminal-activity stamps: the stamp is a pure function of the
# session's journal file, so an unchanged (mtime_ns, size) stat guarantees the
# memoized value. This bounds each 5s lobby poll to one stat per companion
# instead of a full journal replay; a changed file falls through to the shared
# snapshot loader (the ordinary Session read path — nothing here mutates it).
_COMPANION_ACTIVITY_STAMP_CACHE: dict[str, dict[str, Any]] = {}
_COMPANION_ACTIVITY_STAMP_CACHE_LOCK = threading.Lock()
_COMPANION_ACTIVITY_STAMP_CACHE_MAX_ENTRIES = 256


def _reset_companion_activity_stamp_cache_for_tests() -> None:
    """Drop memoized journal stamps (test isolation only)."""

    with _COMPANION_ACTIVITY_STAMP_CACHE_LOCK:
        _COMPANION_ACTIVITY_STAMP_CACHE.clear()


def _journal_stat_signature(session_id: str) -> tuple[int, int] | None:
    """Cheap (mtime_ns, size) identity of a session's journal file."""

    from core.chat.conversation_ledger import conversation_ledger_path

    from .session import journal_bridge

    normalized_session_id = str(session_id or "").strip()
    if not normalized_session_id:
        return None
    path = conversation_ledger_path(Path(journal_bridge.PROJECT_ROOT), normalized_session_id)
    try:
        stat = path.stat()
    except OSError:
        return None
    return (int(stat.st_mtime_ns), int(stat.st_size))


def _companion_terminal_activity_stamp(session_id: str) -> str | None:
    """Latest terminal journal stamp for one session, memoized per file state."""

    from core.chat.turn_journal import TERMINAL_EVENTS

    from .session.journal_bridge import load_session_conversation_events_snapshot

    normalized_session_id = str(session_id or "").strip()
    if not normalized_session_id:
        return None
    signature = _journal_stat_signature(normalized_session_id)
    now = time.perf_counter()
    with _COMPANION_ACTIVITY_STAMP_CACHE_LOCK:
        cached = _COMPANION_ACTIVITY_STAMP_CACHE.get(normalized_session_id)
        if cached is not None and cached.get("signature") == signature:
            cached["last_access"] = now
            return cached.get("stamp")

    def _stamp_from_events(events: list[Any]) -> str | None:
        terminal_events = [
            event
            for event in events
            if str(getattr(event, "event_type", "") or "").strip() in TERMINAL_EVENTS
            and str(getattr(event, "turn_id", "") or "").strip()
        ]
        if not terminal_events:
            return None
        latest = max(terminal_events, key=lambda event: int(getattr(event, "sequence", 0) or 0))
        return "turn:{turn_id}:{event_type}".format(
            turn_id=str(getattr(latest, "turn_id", "") or "").strip(),
            event_type=str(getattr(latest, "event_type", "") or "").strip(),
        )

    try:
        stamp = _stamp_from_events(load_session_conversation_events_snapshot(normalized_session_id))
    except Exception as exc:  # noqa: BLE001 - summary remains usable without inventing an unread completion
        logger.warning(
            "Companion Session terminal activity unavailable for %s: %s",
            normalized_session_id,
            type(exc).__name__,
        )
        # A transient read failure is not memoized: the next poll retries, and
        # the response simply carries no stamp for this request (unchanged).
        return None
    with _COMPANION_ACTIVITY_STAMP_CACHE_LOCK:
        _COMPANION_ACTIVITY_STAMP_CACHE[normalized_session_id] = {
            "signature": signature,
            "stamp": stamp,
            "last_access": time.perf_counter(),
        }
        while len(_COMPANION_ACTIVITY_STAMP_CACHE) > _COMPANION_ACTIVITY_STAMP_CACHE_MAX_ENTRIES:
            oldest_key = min(
                _COMPANION_ACTIVITY_STAMP_CACHE,
                key=lambda key: float(
                    _COMPANION_ACTIVITY_STAMP_CACHE.get(key, {}).get("last_access") or 0.0
                ),
            )
            _COMPANION_ACTIVITY_STAMP_CACHE.pop(oldest_key, None)
    return stamp


def _session_activity_row(row: dict[str, Any], *, session_id: str) -> dict[str, Any]:
    """Project the Companion-visible fields of one native Session summary row."""

    activity = {
        field: row.get(field)
        for field in _SESSION_ACTIVITY_FIELDS
        if field in row
    }
    stamp = _companion_terminal_activity_stamp(session_id)
    if stamp is not None:
        activity["activityStamp"] = stamp
    return activity


def _agent_scoped_session_row(agent_id: str, session_id: str) -> dict[str, Any] | None:
    """Resolve one Agent's direct-session row through the agent-scoped query.

    This is the original per-companion read: the agent-scoped query injects
    hidden or directory-stub direct sessions that a global page cannot show, so
    it stays the authority whenever the batched page cannot decide.
    """

    from .session_service import query_sessions

    try:
        payload = query_sessions(limit=1, agent_id=agent_id)
    except Exception as exc:  # noqa: BLE001 - lobby life data remains available if Session projection is transiently unavailable
        logger.warning(
            "Companion Session activity projection unavailable for %s: %s",
            agent_id,
            type(exc).__name__,
        )
        return None
    return next(
        (
            item
            for item in list(payload.get("items") or [])
            if isinstance(item, dict)
            and str(item.get("id") or "").strip() == session_id
        ),
        None,
    )


def _native_session_activity_by_id(
    companion_rows: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Read the native Session summary projection without changing its index rules.

    One agent-set page replaces the per-companion ``query_sessions`` round trip:
    items arrive in ``updatedAt_desc`` order, so the first row of an agent's
    group is that agent's newest session — exactly the row the per-agent
    ``limit=1`` query used to return. A companion is resolved from the page only
    when its direct session IS that newest row; every other case (page
    truncation, hidden or stub-only direct sessions, direct session not the
    newest) falls back to the agent-scoped query, so produced values are
    identical to the per-companion reads this replaces.
    """

    from .session_service import _SESSION_QUERY_MAX_LIMIT, query_sessions

    selected_rows = [
        {
            "agentId": str(row.get("agentId") or "").strip(),
            "sessionId": str(row.get("directSessionId") or "").strip(),
        }
        for row in companion_rows
        if isinstance(row, dict)
        and str(row.get("agentId") or "").strip()
        and str(row.get("directSessionId") or "").strip()
    ]
    activity_by_id: dict[str, dict[str, Any]] = {}
    pending_rows = list(selected_rows)
    if pending_rows:
        try:
            payload = query_sessions(limit=max(1, int(_SESSION_QUERY_MAX_LIMIT)))
        except Exception as exc:  # noqa: BLE001 - a failed batch degrades to the per-agent reads below
            logger.warning(
                "Companion Session activity batch projection unavailable: %s",
                type(exc).__name__,
            )
            payload = None
        newest_by_agent: dict[str, dict[str, Any]] = {}
        for item in list((payload or {}).get("items") or []):
            if not isinstance(item, dict):
                continue
            owner = str(item.get("agentId") or "").strip()
            if owner and owner not in newest_by_agent:
                newest_by_agent[owner] = item
        still_pending: list[dict[str, str]] = []
        for selected in pending_rows:
            agent_id = selected["agentId"]
            session_id = selected["sessionId"]
            newest = newest_by_agent.get(agent_id)
            if newest is None or str(newest.get("id") or "").strip() != session_id:
                still_pending.append(selected)
                continue
            activity_by_id[session_id] = _session_activity_row(newest, session_id=session_id)
        pending_rows = still_pending
    for selected in pending_rows:
        agent_id = selected["agentId"]
        session_id = selected["sessionId"]
        row = _agent_scoped_session_row(agent_id, session_id)
        if row is None:
            continue
        activity_by_id[session_id] = _session_activity_row(row, session_id=session_id)
    return activity_by_id


def list_agent_plugin_catalog() -> list[dict[str, Any]]:
    return installed_plugin_catalog()


def list_agent_plugins(agent_id: str) -> dict[str, Any]:
    get_virtual_human_life_service().require_agent(agent_id)
    return {
        "agentId": str(agent_id or "").strip(),
        "plugins": [
            {
                **plugin,
                "binding": (
                    virtual_human_binding(agent_id)
                    if str(plugin.get("pluginId") or "") == PLUGIN_ID
                    else None
                ),
            }
            for plugin in installed_plugin_catalog()
        ],
    }


def _enabled_companion_directory_rows() -> list[dict[str, Any]]:
    service = get_virtual_human_life_service()
    companion_rows: list[dict[str, Any]] = []
    for agent in service.agent_lister():
        if not isinstance(agent, dict):
            continue
        agent_id = str(agent.get("agentId") or "").strip()
        direct_session_id = str(agent.get("directSessionId") or "").strip()
        status = str(agent.get("status") or "active").strip() or "active"
        if not agent_id or not direct_session_id or status.lower() != "active":
            continue
        binding = service.binding_for(agent_id)
        if not binding or not bool(binding.get("enabled")):
            continue
        companion_rows.append(
            {
                "agentId": agent_id,
                "agentCode": str(agent.get("agentCode") or "").strip(),
                "displayName": str(agent.get("displayName") or "").strip() or agent_id,
                "directSessionId": direct_session_id,
                "avatarImageUrl": str(agent.get("avatarImageUrl") or "").strip(),
                "personaProfile": (
                    dict(agent.get("personaProfile") or {})
                    if isinstance(agent.get("personaProfile"), dict)
                    else {}
                ),
                "status": status,
            }
        )
    return companion_rows


def _companion_activity_rows(
    companion_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    session_activity_by_id = _native_session_activity_by_id(companion_rows)
    return [
        {
            "agentId": str(row.get("agentId") or "").strip(),
            "displayName": str(row.get("displayName") or "").strip(),
            "directSessionId": str(row.get("directSessionId") or "").strip(),
            "sessionActivity": session_activity_by_id.get(
                str(row.get("directSessionId") or "").strip()
            ),
        }
        for row in companion_rows
    ]


def list_virtual_human_companion_activity() -> list[dict[str, Any]]:
    """Return a lightweight Companion-only projection of native Session activity."""

    return _companion_activity_rows(_enabled_companion_directory_rows())


def list_virtual_human_companions() -> list[dict[str, Any]]:
    """Return active, enabled virtual humans for the desktop lobby.

    Agent Directory remains the identity/session authority. The plugin service
    contributes only its binding and life snapshot, so the frontend does not
    need an Agent list plus one binding/snapshot request per row.
    """

    service = get_virtual_human_life_service()
    companion_rows = _enabled_companion_directory_rows()
    activity_by_agent_id = {
        str(row.get("agentId") or "").strip(): row.get("sessionActivity")
        for row in _companion_activity_rows(companion_rows)
    }
    return [
        {
            **row,
            **(
                {"sessionActivity": activity}
                if (
                    activity := activity_by_agent_id.get(
                        str(row.get("agentId") or "").strip()
                    )
                ) is not None
                else {}
            ),
            "snapshot": service.snapshot(str(row.get("agentId") or "").strip()),
        }
        for row in companion_rows
    ]


def update_agent_plugin_binding(
    agent_id: str,
    plugin_id: str,
    *,
    enabled: bool,
    expected_version: int,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized_plugin_id = str(plugin_id or "").strip()
    if normalized_plugin_id != PLUGIN_ID:
        raise KeyError(f"Agent plugin not found: {normalized_plugin_id}")
    return update_virtual_human_binding(
        agent_id,
        enabled=enabled,
        expected_version=expected_version,
        config=config,
    )


__all__ = [
    "list_agent_plugin_catalog",
    "list_agent_plugins",
    "list_virtual_human_companion_activity",
    "list_virtual_human_companions",
    "update_agent_plugin_binding",
]
