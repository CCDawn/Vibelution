"""Trusted first-party Agent plugin catalog and binding facade."""

from __future__ import annotations

import logging
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


def _native_session_activity_by_id(
    companion_rows: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Read the native Session summary projection without changing its index rules."""

    from core.chat.turn_journal import TERMINAL_EVENTS

    from .session.journal_bridge import load_session_conversation_events_snapshot
    from .session_service import query_sessions

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
    for selected in selected_rows:
        agent_id = selected["agentId"]
        selected_session_id = selected["sessionId"]
        try:
            payload = query_sessions(limit=1, agent_id=agent_id)
        except Exception as exc:  # noqa: BLE001 - lobby life data remains available if Session projection is transiently unavailable
            logger.warning(
                "Companion Session activity projection unavailable for %s: %s",
                agent_id,
                type(exc).__name__,
            )
            continue
        row = next(
            (
                item
                for item in list(payload.get("items") or [])
                if isinstance(item, dict)
                and str(item.get("id") or "").strip() == selected_session_id
            ),
            None,
        )
        if row is None:
            continue
        session_id = selected_session_id
        activity = {
            field: row.get(field)
            for field in _SESSION_ACTIVITY_FIELDS
            if field in row
        }
        try:
            terminal_events = [
                event
                for event in load_session_conversation_events_snapshot(session_id)
                if str(getattr(event, "event_type", "") or "").strip() in TERMINAL_EVENTS
                and str(getattr(event, "turn_id", "") or "").strip()
            ]
        except Exception as exc:  # noqa: BLE001 - summary remains usable without inventing an unread completion
            logger.warning(
                "Companion Session terminal activity unavailable for %s: %s",
                session_id,
                type(exc).__name__,
            )
            terminal_events = []
        if terminal_events:
            latest = max(terminal_events, key=lambda event: int(getattr(event, "sequence", 0) or 0))
            activity["activityStamp"] = "turn:{turn_id}:{event_type}".format(
                turn_id=str(getattr(latest, "turn_id", "") or "").strip(),
                event_type=str(getattr(latest, "event_type", "") or "").strip(),
            )
        activity_by_id[session_id] = activity
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
