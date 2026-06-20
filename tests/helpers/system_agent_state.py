from __future__ import annotations

from typing import Any

from core.web.services import agent_directory_service, agent_mode_binding_service, supervised_agent_service, team_service
from core.web.services.self_evolution_control_service import SELF_EVOLUTION_AGENT_ROLES
from core.web.services.supervised_agent_service import SUPERVISED_AGENT_ROLES


def _supervised_role_keys() -> list[str]:
    return [role.role for role in SUPERVISED_AGENT_ROLES]


def _self_evolution_role_keys() -> list[str]:
    return [str(role.get("role") or "").strip() for role in SELF_EVOLUTION_AGENT_ROLES]


def _mark_config_agent_instances_present(supervised_slots: dict[str, str] | None = None) -> None:
    """Make the config workspace guard see fixed-role slots as explicitly handled.

    Most tests only need to exercise one protected Agent or unrelated demo Agents.
    Marking the rest as excluded avoids an expensive full system-Agent bootstrap
    while preserving the route's protected-slot semantics.
    """

    supervised_slots = {
        str(role or "").strip(): str(agent_id or "").strip()
        for role, agent_id in dict(supervised_slots or {}).items()
        if str(role or "").strip()
    }
    all_supervised = _supervised_role_keys()
    normalized_supervised_slots = {
        role: supervised_slots.get(role, "")
        for role in all_supervised
    }
    agent_mode_binding_service.update_mode_binding(
        "supervised_evolution",
        available_agent_ids=[
            agent_id
            for agent_id in normalized_supervised_slots.values()
            if agent_id
        ],
        slots=normalized_supervised_slots,
        excluded_slots=[
            role
            for role, agent_id in normalized_supervised_slots.items()
            if not agent_id
        ],
    )
    self_slots = {role: "" for role in _self_evolution_role_keys()}
    agent_mode_binding_service.update_mode_binding(
        "self_evolution",
        available_agent_ids=[],
        slots=self_slots,
        excluded_slots=list(self_slots),
    )


def _seed_supervised_fixed_role_agent(role: str) -> dict[str, Any]:
    normalized_role = str(role or "").strip()
    label_by_role = {item.role: item.label for item in SUPERVISED_AGENT_ROLES}
    label = label_by_role.get(normalized_role, normalized_role or "Supervised Agent")
    agent = agent_directory_service.create_agent_instance(
        display_name=label,
        primary_mode="supervised_evolution",
        role_key=normalized_role,
        prompt_template_id="prompt-chat-default",
        created_by="supervised_evolution",
        metadata={
            "agentMode": "supervised_evolution",
            "configSurface": "system",
            "fixedRole": True,
            "protected": True,
            "supervisedRole": normalized_role,
            "supervisedRoleLabel": label,
            "functionalDisplayName": label,
        },
    )
    _mark_config_agent_instances_present({normalized_role: str(agent.get("agentId") or "")})
    return agent


def _seed_supervised_fixed_role_agents() -> list[dict[str, Any]]:
    agents: list[dict[str, Any]] = []
    slots: dict[str, str] = {}
    for role in SUPERVISED_AGENT_ROLES:
        agent = _create_supervised_role_agent(role.role, role.label)
        agents.append(agent)
        slots[role.role] = str(agent.get("agentId") or "")
    _mark_config_agent_instances_present(slots)
    return agents


def _create_supervised_role_agent(role: str, label: str) -> dict[str, Any]:
    metadata = {
        "agentMode": "supervised_evolution",
        "configSurface": "model_config",
        "fixedRole": True,
        "protected": role in supervised_agent_service.CORE_SUPERVISED_AGENT_ROLES,
        "supervisedRole": role,
        "supervisedRoleLabel": label,
        "functionalDisplayName": label,
        "supervisedRoleContract": supervised_agent_service._supervised_role_contract(role),
    }
    agent = agent_directory_service.create_agent_instance(
        display_name=label,
        llm_bindings={"dialogue": {"modelId": "xiaomi_mimo_v2_5_pro_token_plan"}},
        primary_mode="supervised_evolution",
        role_key=role,
        prompt_template_id=f"prompt-supervised-{role}",
        created_by="supervised_evolution",
        metadata=metadata,
    )
    return agent_directory_service.update_agent_instance(
        str(agent.get("agentId") or ""),
        persona_profile=supervised_agent_service._supervised_role_persona_profile(role),
        task_profile=supervised_agent_service._supervised_role_task_profile(role),
    )


def _seed_system_team_bootstrap_ready() -> None:
    now = team_service.utc_now_iso()
    state = team_service._load_index()
    teams = [
        _system_team_payload(spec, now=now)
        for spec in team_service.EVOLUTION_SYSTEM_TEAM_SPECS
    ]
    teams.append(_ai_search_team_payload(now=now))
    existing = {
        str(item.get("teamId") or "").strip(): item
        for item in list(state.get("teams") or [])
        if isinstance(item, dict)
    }
    existing.update({str(team["teamId"]): team for team in teams})
    state["teams"] = list(existing.values())
    state["updatedAt"] = now
    team_service._save_index(state)
    team_service._ensure_ai_search_source_scope_file()


def _seed_ai_search_system_team_ready() -> dict[str, Any]:
    now = team_service.utc_now_iso()
    state = team_service._load_index()
    existing = [
        item
        for item in list(state.get("teams") or [])
        if isinstance(item, dict)
        and str(item.get("teamId") or "").strip() != team_service.AI_SEARCH_TEAM_ID
    ]
    team = _ai_search_team_payload(now=now)
    state["teams"] = [*existing, team]
    state["updatedAt"] = now
    team_service._save_index(state)
    team_service._ensure_ai_search_source_scope_file()
    return dict(team)


def _evolution_system_agent_payloads() -> dict[str, list[dict[str, Any]]]:
    return {
        "self_evolution": [
            _system_agent_payload(
                f"seed-self-{role.get('role')}",
                role=str(role.get("role") or ""),
                label=str(role.get("label") or role.get("role") or ""),
                mode="self_evolution",
                metadata_key="selfEvolutionRole",
                metadata_label_key="selfEvolutionRoleLabel",
            )
            for role in SELF_EVOLUTION_AGENT_ROLES
        ],
        "supervised_evolution": [
            _system_agent_payload(
                f"seed-supervised-{role.role}",
                role=role.role,
                label=role.label,
                mode="supervised_evolution",
                metadata_key="supervisedRole",
                metadata_label_key="supervisedRoleLabel",
            )
            for role in SUPERVISED_AGENT_ROLES
        ],
    }


def _system_agent_payload(
    agent_id: str,
    *,
    role: str,
    label: str,
    mode: str,
    metadata_key: str,
    metadata_label_key: str,
) -> dict[str, Any]:
    normalized_role = str(role or "").strip()
    normalized_label = str(label or normalized_role).strip()
    return {
        "agentId": str(agent_id or normalized_role).strip(),
        "agentCode": "",
        "displayName": normalized_label,
        "primaryMode": mode,
        "roleKey": normalized_role,
        "directSessionId": "",
        "status": "active",
        "metadata": {
            "fixedRole": True,
            "protected": True,
            metadata_key: normalized_role,
            metadata_label_key: normalized_label,
            "functionalDisplayName": normalized_label,
        },
    }


def _system_team_payload(spec: dict[str, Any], *, now: str) -> dict[str, Any]:
    team = {
        "teamId": str(spec.get("teamId") or "").strip(),
        "name": str(spec.get("name") or "").strip(),
        "description": str(spec.get("description") or "").strip(),
        "purpose": str(spec.get("purpose") or "").strip(),
        "status": team_service.DEFAULT_TEAM_STATUS,
        "members": [],
        "linkedChatRoomId": "",
        "canvasPath": team_service._relative_path(team_service._team_canvas_path(str(spec.get("teamId") or ""))),
        "systemTeamKind": str(spec.get("source") or "").strip(),
        "teamKind": str(spec.get("teamKind") or spec.get("source") or "").strip(),
        "teamCategory": str(spec.get("teamCategory") or "").strip(),
        "teamSource": str(spec.get("teamSource") or spec.get("source") or "").strip(),
        "teamTemplateId": "",
        "createdAt": now,
        "updatedAt": now,
    }
    team_service._apply_team_contract(
        team,
        team_kind=str(spec.get("teamKind") or spec.get("source") or ""),
        team_category=str(spec.get("teamCategory") or ""),
        team_source=str(spec.get("teamSource") or spec.get("source") or ""),
    )
    return team


def _ai_search_team_payload(*, now: str) -> dict[str, Any]:
    members = [
        {
            "memberId": f"ai-search-{index}",
            "agentId": f"seed-ai-search-{role.get('role')}",
            "agentCode": "",
            "agentName": str(role.get("label") or role.get("role") or "").strip(),
            "role": str(role.get("role") or "").strip(),
            "purpose": str(role.get("label") or "").strip(),
            "responsibilities": list(role.get("responsibilities") or []),
            "agentStatus": "active",
        }
        for index, role in enumerate(team_service.AI_SEARCH_SYSTEM_ROLES, start=1)
    ]
    return {
        "teamId": team_service.AI_SEARCH_TEAM_ID,
        "name": team_service.AI_SEARCH_TEAM_DISPLAY_NAME,
        "description": "Seeded AI search system Team for route readiness tests.",
        "purpose": "Seeded source-scope Team.",
        "status": team_service.DEFAULT_TEAM_STATUS,
        "members": members,
        "linkedChatRoomId": "",
        "canvasPath": team_service._relative_path(team_service._team_canvas_path(team_service.AI_SEARCH_TEAM_ID)),
        "sourceScopePath": team_service._relative_path(team_service._ai_search_source_scope_path()),
        "systemTeamKind": "ai_search",
        "teamKind": "ai_search",
        "teamCategory": "AI 搜索系统团队",
        "teamSource": "ai_search",
        "teamTemplateId": "",
        "createdAt": now,
        "updatedAt": now,
    }
