"""Prepare public Companion identities without activating their life or models.

This is an initial-preset adapter, called only until the catalog seed completes.
It persists the existing life pause before publishing an enabled binding, so a
crash cannot expose an unpaused Companion to the periodic supervisor.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from core.agent_plugins.virtual_human_life import native_wakeup
from core.agent_plugins.virtual_human_life.self_continuity import SESSION_PATH


def _ensure_helper(owner: dict[str, Any], *, steward: bool) -> dict[str, Any]:
    from core.web.services import agent_directory_service as directory
    from core.web.services import session_service
    from core.web.services import virtual_human_life_service as life

    owner_id = owner["agentId"]
    owner_key = "lifeStewardForAgentId" if steward else "selfWakeForAgentId"
    role = "virtual_human_life_steward" if steward else "virtual_human_self_wake"
    matches = [
        agent for agent in directory.list_agents(include_archived=True, detail="config")
        if (agent.get("metadata") or {}).get(owner_key) == owner_id
    ]
    if len(matches) > 1:
        raise ValueError("Public Companion has conflicting native helper identities.")
    title = f"{owner.get('displayName') or '虚拟人'}的{'生活管家' if steward else '自主行动'}"
    if matches:
        helper = matches[0]
        # Even an incomplete seed must respect an operator's explicit archive.
        if helper.get("status") == "archived":
            return helper
    else:
        created = session_service.create_chat_session(
            title=title,
            llm_bindings={},
            created_by=role,
            conversation_index_kind=directory.CONVERSATION_INDEX_KIND_HIDDEN,
            session_metadata={"source": role, "externalTaskId": owner_id},
            lightweight=True,
            activate=False,
            idempotency_key=f"public-companion:{owner_id}:{role}",
        )
        helper = directory.get_agent(str(created.get("agentId") or ""))
        if not helper or helper.get("directSessionId") != created.get("id"):
            raise ValueError("Public Companion helper has no verified native Session.")

    metadata = {
        "agentMode": "chat",
        "configSurface": "companion_life_world" if steward else "companion_self_wake",
        "conversationIndexKind": directory.CONVERSATION_INDEX_KIND_HIDDEN,
        "conversationIndexVisibility": directory.CONVERSATION_INDEX_VISIBILITY_HIDDEN,
        "showInSessionIndex": False,
        owner_key: owner_id,
    }
    if steward:
        metadata.update({
            "fixedRole": True,
            "directSessionVisibility": directory.SESSION_AGENT_VISIBILITY_ACTIVE,
            "functionalDisplayName": title,
            "virtualHumanLifeSteward": True,
        })
        policy = life._life_steward_tool_policy()
        prompt_id = life.LIFE_STEWARD_PROMPT_TEMPLATE_ID
    else:
        metadata["virtualHumanSelfWake"] = True
        policy = deepcopy(owner.get("toolPolicy") or {})
        policy["allowedTools"] = sorted(
            native_wakeup._allowed(policy)
            & (set(native_wakeup.VIRTUAL_HUMAN_TOOL_NAMES)
               - {"virtual_human_dialogue_decision_v2_tool"})
        )
        prompt_id = str(owner.get("promptTemplateId") or "prompt-chat-default")
    return directory.update_agent_instance(
        helper["agentId"],
        display_name=title if steward else str(owner.get("displayName") or "虚拟人"),
        llm_bindings={},
        primary_mode="chat",
        role_key=role,
        prompt_template_id=prompt_id,
        persona_profile={} if steward else deepcopy(owner.get("personaProfile") or {}),
        permission_preset="request_approval",
        tool_policy=policy,
        metadata=metadata,
        preserve_generated_display_name=True,
    )


def ensure_public_companion(agent_id: str, config: dict[str, Any]) -> dict[str, str]:
    """Seed one visible, paused Companion plus two dormant native helpers.

    The public catalog owns the completion marker. Never call this for a
    completed preset: subsequent configuration and lifecycle belong to users.
    """
    from core.web.services import agent_directory_service as directory
    from core.web.services import virtual_human_life_service as life

    service = life.get_virtual_human_life_service()
    with service._lock_for(agent_id):
        owner = directory.get_agent(agent_id, include_archived=True)
        if not owner or owner.get("status") == "archived":
            return {}
        # Only the domain's static configuration fields are admitted. Local
        # binding versions, references and runtime state never cross installs.
        safe_config = {
            key: deepcopy(config[key]) for key in (
                "homeLocation", "timezone", "locale", "nightlyPlanningTime",
                "heartbeatIntervalSeconds", "quietHours", "rhythmConfig",
                "lifeIdentityKind",
            ) if key in config
        }
        safe_config.update({"proactiveMessagesEnabled": False, "autonomyLevel": "assisted"})
        current = service.binding_for(agent_id)
        if not current:
            current = service.set_binding(
                agent_id, enabled=False, expected_version=0, config=safe_config,
            )
        # Initialization is deterministic, and preserves existing durable
        # state. The sole direct state write is Companion-only initial pause.
        service._ensure_initialized(agent_id, current)
        state = service.store.read_json(agent_id, "state.json")
        if not isinstance(state, dict):
            raise ValueError("Public Companion initialization produced no life state.")
        state["lifePaused"] = True
        state["pausedReason"] = "等待用户配置模型并恢复生活"
        service.store.write_json(agent_id, "state.json", state)
        binding = life.update_virtual_human_binding(
            agent_id, enabled=True,
            expected_version=int(current.get("configVersion") or 0),
            config=safe_config,
        )
        state = service.store.read_json(agent_id, "state.json") or {}
        # A fresh key per persisted state version also recovers a crash after
        # pause state persistence but before its receipt was committed.
        version = int(state.get("stateVersion") or 1)
        service.execute_command(
            agent_id, command="pauseLife", expected_version=version,
            idempotency_key=f"public-companion-pause:{agent_id}:{version}",
            arguments={"reason": "等待用户配置模型并恢复生活"},
        )
        owner = directory.get_agent(agent_id) or owner
        steward = _ensure_helper(owner, steward=True)
        worker = _ensure_helper(owner, steward=False)
        # Reuse the established pairing records. Normal confirm/ensure calls
        # can later claim these identities after the user supplies a model.
        next_config = deepcopy(binding)
        next_config["steward"] = {
            "enabled": False,
            "agentId": steward["agentId"],
            "sessionId": steward["directSessionId"],
            "promptPackId": life.LIFE_STEWARD_PROMPT_TEMPLATE_ID,
            "toolBundleId": life.LIFE_STEWARD_TOOL_BUNDLE_ID,
            "provisioningState": "disabled",
        }
        service.set_binding(
            agent_id, enabled=True,
            expected_version=int(binding["configVersion"]), config=next_config,
        )
        service.store.write_json(agent_id, SESSION_PATH, {
            "agentId": agent_id,
            "runtimeAgentId": worker["agentId"],
            "sessionId": worker["directSessionId"],
            "ownerToolPolicyStamp": native_wakeup._policy_stamp(owner),
        })
        return {"stewardAgentId": steward["agentId"], "selfWakeAgentId": worker["agentId"]}
