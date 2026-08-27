"""Trusted first-party Agent plugin catalog and binding facade."""

from __future__ import annotations

from typing import Any

from core.agent_plugins import installed_plugin_catalog
from core.agent_plugins.virtual_human_life.manifest import PLUGIN_ID

from .virtual_human_life_service import (
    get_virtual_human_life_service,
    update_virtual_human_binding,
    virtual_human_binding,
)


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


def list_virtual_human_companions() -> list[dict[str, Any]]:
    """Return active, enabled virtual humans for the desktop lobby.

    Agent Directory remains the identity/session authority. The plugin service
    contributes only its binding and life snapshot, so the frontend does not
    need an Agent list plus one binding/snapshot request per row.
    """

    service = get_virtual_human_life_service()
    companions: list[dict[str, Any]] = []
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
        companions.append(
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
                "snapshot": service.snapshot(agent_id),
            }
        )
    return companions


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
    "list_virtual_human_companions",
    "update_agent_plugin_binding",
]
