"""Create missing bundled Agent assets for a fresh installation.

AgentDirectory owns the configuration. Team bootstrap only binds these assets;
it must never copy its defaults back over an existing Agent.
"""

from __future__ import annotations

import threading
from typing import Any

_BOOTSTRAP_LOCK = threading.RLock()
GENERAL_ASSISTANT_PRESET = "general_assistant_v1"


def ensure_builtin_agents() -> dict[str, Any]:
    """Seed public defaults once, without importing any operator's Agent data."""
    from core.web.services import agent_directory_service as directory
    from core.web.services import session_service, team_service

    with _BOOTSTRAP_LOCK:
        agents = directory.list_agents(include_archived=True, detail="summary")
        created_ids: list[str] = []
        general = next(
            (agent for agent in agents if (agent.get("metadata") or {}).get("builtinPreset") == GENERAL_ASSISTANT_PRESET),
            None,
        )
        # An operator may archive a starter. Restart must not resurrect it.
        if general is None:
            general = directory.create_agent_instance(
                display_name="通用助手",
                llm_bindings=session_service.default_session_llm_bindings(),
                primary_mode="chat",
                prompt_template_id="prompt-chat-default",
                created_by="deployment_bootstrap",
                metadata={"builtinPreset": GENERAL_ASSISTANT_PRESET},
            )
            created_ids.append(general["agentId"])
        if general.get("status") != "archived":
            session_service.ensure_agent_direct_session(
                agent_id=general["agentId"],
                title=general["displayName"],
                created_by="deployment_bootstrap",
            )

        role_ids: list[str] = []
        for role in team_service.CHALLENGE_CUP_RESEARCH_TEAM_ROLES:
            role_name = str(role["role"])
            # Include archived assets: explicit operator lifecycle wins over seed.
            matches = [
                agent for agent in agents
                if (agent.get("metadata") or {}).get("challengeCupTeamId") == team_service.CHALLENGE_CUP_RESEARCH_TEAM_ID
                and (agent.get("metadata") or {}).get("challengeCupTeamRole") == role_name
            ]
            if matches:
                for agent in matches:
                    if (agent.get("metadata") or {}).get("builtinPreset") == f"research_role_v1:{role_name}" and agent.get("status") != "archived" and not agent.get("directSessionId"):
                        # Recover a seed interrupted after Agent persistence.
                        # Existing imported/configured assets remain untouched.
                        session_service.ensure_agent_direct_session(
                            agent_id=agent["agentId"], title=agent["displayName"],
                            created_by="deployment_bootstrap",
                            conversation_index_kind=directory.CONVERSATION_INDEX_KIND_TEAM_AGENT,
                        )
                role_ids.extend(str(agent["agentId"]) for agent in matches)
                continue
            label = str(role.get("label") or role_name)
            role_key = str(role.get("roleKey") or role_name)
            profiles = directory._challenge_cup_agent_profile_defaults(role_name, label)
            agent = directory.create_agent_instance(
                display_name=label,
                llm_bindings=session_service.default_session_llm_bindings(),
                primary_mode="research",
                role_key=role_key,
                prompt_template_id="prompt-chat-default",
                created_by=team_service.CHALLENGE_CUP_RESEARCH_TEAM_AGENT_CREATED_BY,
                metadata={
                    **team_service._challenge_cup_research_team_role_metadata(role),
                    **profiles,
                    "builtinPreset": f"research_role_v1:{role_name}",
                },
            )
            session_service.ensure_agent_direct_session(
                agent_id=agent["agentId"],
                title=label,
                created_by="deployment_bootstrap",
                conversation_index_kind=directory.CONVERSATION_INDEX_KIND_TEAM_AGENT,
            )
            created_ids.append(agent["agentId"])
            role_ids.append(agent["agentId"])

        return {"createdAgentIds": created_ids, "researchAgentIds": role_ids,
                "generalAssistantId": general["agentId"]}


def initialize_builtin_agent_catalog() -> dict[str, Any]:
    """Run before functional routes become ready, after Session storage opens."""
    from core.web.services import team_service
    from core.web.services.session.directory_runtime import (
        should_skip_directory_runtime_for_pytest,
        wait_for_directory_startup,
    )

    # Bare TestClient lifespans must never initialize the real operator store.
    # Isolated deployment tests call ensure_builtin_agents against their roots.
    if should_skip_directory_runtime_for_pytest():
        return {"skipped": "pytest"}
    phase = wait_for_directory_startup()
    if phase not in {"idle", "ready", "degraded"}:
        raise RuntimeError("Session storage is not ready for bundled Agent initialization")
    result = ensure_builtin_agents()
    from .public_presets import ensure_public_agent_presets

    result["publicPresetAgentIds"] = ensure_public_agent_presets()["publicPresetAgentIds"]
    # Reuse the existing owner for other system Teams, rather than a second seed
    # catalog for their Agent configuration or a write through list/get APIs.
    team_service.request_system_team_bootstrap(reason="deployment_startup", allow_sync_check=False)
    return result
