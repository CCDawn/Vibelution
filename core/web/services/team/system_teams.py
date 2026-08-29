"""System Team ensure / materialize helpers.

Claim scope: Challenge Cup / knowledge expansion / evolution / AI search system
Team agent materialization and missing/repair probes.
Late-binds ``team_service`` for index locks, canvas IO, chat-room links, and shared helpers.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from core.infrastructure import developer_sandbox
from core.web.services import agent_directory_service
from core.web.services.team.canvas_primitives import _SAFE_ID_FRAGMENT


def _service():
    """Late-bound facade module (avoids import cycles at package import time)."""

    from core.web.services import team_service

    return team_service


def _is_trusted_challenge_cup_research_team_agent(agent: dict[str, Any] | None) -> bool:
    """Return whether an Agent belongs to the managed Challenge Cup lineage."""

    if not isinstance(agent, dict):
        return False
    s = _service()
    metadata = agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}
    try:
        managed_version = int(metadata.get("challengeCupTeamManagedVersion") or 0)
    except (TypeError, ValueError):
        managed_version = 0
    return (
        str(agent.get("createdBy") or "").strip()
        == s.CHALLENGE_CUP_RESEARCH_TEAM_AGENT_CREATED_BY
        and str(metadata.get("challengeCupTeamId") or "").strip()
        == s.CHALLENGE_CUP_RESEARCH_TEAM_ID
        and managed_version >= 1
    )


def _challenge_cup_research_team_placeholder(now: str) -> dict[str, Any]:
    s = _service()
    team = {
        "teamId": s.CHALLENGE_CUP_RESEARCH_TEAM_ID,
        "name": s.RESEARCH_TEAM_DISPLAY_NAME,
        "description": "挑战杯 125 题假说与研究计划的六 Agent 系统团队。",
        "purpose": "组织搜索、提炼、知识治理、执行、实验修订与独立评估。",
        "status": s.DEFAULT_TEAM_STATUS,
        "members": [],
        "linkedChatRoomId": "",
        "canvasPath": s._relative_path(
            s._team_canvas_path(s.CHALLENGE_CUP_RESEARCH_TEAM_ID)
        ),
        "createdAt": now,
        "updatedAt": now,
    }
    s._apply_team_contract(
        team,
        team_kind="research",
        team_source="research_organization",
    )
    return team


def evolution_system_teams_missing() -> bool:
    """Return whether the system Team bootstrap is required for the list surface."""

    s = _service()
    with s._TEAM_LOCK:
        state = s._load_index()
        if s._repair_index_shape(state):
            s._save_index(state)
        active_team_ids = {
            str(item.get("teamId") or "").strip()
            for item in list(state.get("teams") or [])
            if isinstance(item, dict)
            and str(item.get("status") or s.DEFAULT_TEAM_STATUS).strip() != "archived"
        }
    return not s.EVOLUTION_SYSTEM_TEAM_IDS.issubset(active_team_ids)


def challenge_cup_research_team_missing() -> bool:
    """Return whether the Challenge Cup Team has never been materialized."""

    s = _service()
    with s._TEAM_LOCK:
        state = s._load_index()
        return s._find_team(state, s.CHALLENGE_CUP_RESEARCH_TEAM_ID) is None


def bootstrap_challenge_cup_research_team() -> dict[str, Any]:
    """Materialize the Challenge Cup Team from six existing Agent assets.

    AgentDirectory is the only authority for the assets.  This bootstrap may
    create the Team projection, but it must never create, repair, reactivate or
    configure an Agent. Missing or duplicate role assets fail closed so drift
    is corrected at the Agent configuration surface.
    """

    s = _service()
    with s._CHALLENGE_CUP_RESEARCH_TEAM_BOOTSTRAP_LOCK:
        with s._TEAM_LOCK:
            state = s._load_index()
            existing = s._find_team(state, s.CHALLENGE_CUP_RESEARCH_TEAM_ID)
        if existing is not None:
            team = s.get_team(s.CHALLENGE_CUP_RESEARCH_TEAM_ID)
            agents = _challenge_cup_member_agents(team)
            return _challenge_cup_research_team_bootstrap_result(
                team=team,
                agents=agents,
                created=False,
            )

        agents = _materialize_challenge_cup_research_team_agents()
        members = s._challenge_cup_research_team_members_from_agents(agents)
        if len(members) != len(s.CHALLENGE_CUP_RESEARCH_TEAM_ROLES):
            raise s.TeamServiceError(
                "Challenge Cup bootstrap did not materialize all six Agent assets."
            )

        now = s.utc_now_iso()
        with s._TEAM_LOCK:
            state = s._load_index()
            existing = s._find_team(state, s.CHALLENGE_CUP_RESEARCH_TEAM_ID)
            if existing is not None:
                team = dict(existing)
                created = False
            else:
                team = _challenge_cup_research_team_placeholder(now)
                team.update(
                    {
                        "members": members,
                        "roleContractId": str(
                            s.CHALLENGE_CUP_RESEARCH_TEAM_ROLE_CONTRACT.get(
                                "teamRoleContractId"
                            )
                            or ""
                        ),
                        "roleContractVersion": s.CHALLENGE_CUP_RESEARCH_TEAM_ROLE_CONTRACT_VERSION,
                        "roleContractFingerprint": s.CHALLENGE_CUP_RESEARCH_TEAM_ROLE_CONTRACT_FINGERPRINT,
                        "participantPolicyVersion": s.CHALLENGE_CUP_RESEARCH_TEAM_PARTICIPANT_POLICY_VERSION,
                    }
                )
                state.setdefault("teams", []).append(team)
                state["updatedAt"] = now
                s._save_index(state)
                created = True

        if created:
            canvas_path = s._team_canvas_path(s.CHALLENGE_CUP_RESEARCH_TEAM_ID)
            if not canvas_path.exists():
                s._write_json(
                    canvas_path,
                    s._challenge_cup_canvas_storage_projection(
                        s._default_canvas_for_team(team)
                    ),
                )
            agent_refs = s._merged_agent_reference_maps(
                s._load_lightweight_agent_references(),
                agents,
            )
            with s._TEAM_LOCK:
                state = s._load_index()
                stored = s._find_team(state, s.CHALLENGE_CUP_RESEARCH_TEAM_ID)
                if stored is not None:
                    s._ensure_team_chat_room_link(stored, agent_refs=agent_refs)
                    state["updatedAt"] = str(stored.get("updatedAt") or now)
                    s._save_index(state)
                    team = dict(stored)

        result = _challenge_cup_research_team_bootstrap_result(
            team=team,
            agents=agents,
            created=created,
        )
        if created:
            s._record_team_event(
                "team.challenge_cup_assets_bootstrapped",
                result["team"],
                fields={
                    "memberCount": result["memberCount"],
                    "agentCount": result["agentCount"],
                    "directSessionCount": result["directSessionCount"],
                },
            )
        return result


def _challenge_cup_member_agents(team: dict[str, Any]) -> list[dict[str, Any]]:
    agents: list[dict[str, Any]] = []
    for member in list(team.get("members") or []):
        if not isinstance(member, dict):
            continue
        agent_id = str(member.get("agentId") or "").strip()
        agent = (
            agent_directory_service.get_agent(agent_id, include_archived=True)
            if agent_id
            else None
        )
        if agent:
            agents.append(agent)
    return agents


def _challenge_cup_research_team_bootstrap_result(
    *,
    team: dict[str, Any],
    agents: list[dict[str, Any]],
    created: bool,
) -> dict[str, Any]:
    s = _service()
    members = [
        dict(member)
        for member in list(team.get("members") or [])
        if isinstance(member, dict)
    ]
    return {
        "schemaVersion": s.SCHEMA_VERSION,
        "teamId": s.CHALLENGE_CUP_RESEARCH_TEAM_ID,
        "created": bool(created),
        "memberCount": len(members),
        "agentCount": len(agents),
        "directSessionCount": sum(
            1 for agent in agents if str(agent.get("directSessionId") or "").strip()
        ),
        "roles": [
            {
                "role": str(role.get("role") or ""),
                "roleKey": str(role.get("roleKey") or ""),
                "label": str(role.get("label") or ""),
                "agentId": next(
                    (
                        str(member.get("agentId") or "")
                        for member in members
                        if str(member.get("role") or "") == str(role.get("role") or "")
                    ),
                    "",
                ),
            }
            for role in s.CHALLENGE_CUP_RESEARCH_TEAM_ROLES
        ],
        "agents": agents,
        "team": team,
    }


def knowledge_expansion_team_agents_need_repair() -> bool:
    """Return whether the knowledge-expansion Team has stale Agent bindings."""

    s = _service()
    with s._TEAM_LOCK:
        state = s._load_index()
        team = s._find_team(state, s.KNOWLEDGE_EXPANSION_TEAM_ID)
        if not team:
            return True
        agent_refs = s._agent_reference_maps()
        active_agents = agent_refs.get("active_by_id") or {}
        expected_roles = {
            str(role.get("role") or "").strip()
            for role in s.KNOWLEDGE_EXPANSION_TEAM_ROLES
            if str(role.get("role") or "").strip()
        }
        member_agent_ids_by_role: dict[str, str] = {}
        for member in list(team.get("members") or []):
            if not isinstance(member, dict):
                continue
            role = str(member.get("role") or "").strip()
            agent_id = str(member.get("agentId") or "").strip()
            if role and role not in expected_roles:
                return True
            if agent_id and agent_id not in active_agents:
                return True
            if role in expected_roles:
                if not agent_id:
                    return True
                agent = active_agents.get(agent_id)
                if not agent:
                    return True
                metadata = agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}
                if (
                    str(metadata.get("knowledgeExpansionTeamId") or "").strip() != s.KNOWLEDGE_EXPANSION_TEAM_ID
                    or str(metadata.get("knowledgeExpansionTeamRole") or "").strip() != role
                    or not s._knowledge_expansion_team_agent_direct_session_available(agent)
                ):
                    return True
                member_agent_ids_by_role[role] = agent_id
        if set(member_agent_ids_by_role) != expected_roles:
            return True
        canvas_path = s._team_canvas_path(s.KNOWLEDGE_EXPANSION_TEAM_ID)
        if not canvas_path.exists():
            return True
        canvas = s._read_json(canvas_path)
        canvas_agent_ids_by_role: dict[str, str] = {}
        for node in list(canvas.get("nodes") or []):
            if not isinstance(node, dict):
                continue
            role = str(node.get("role") or "").strip()
            agent_id = str(node.get("agentId") or "").strip()
            if role and role not in expected_roles:
                return True
            if agent_id and agent_id not in active_agents:
                return True
            if role in expected_roles:
                if not agent_id or member_agent_ids_by_role.get(role) != agent_id:
                    return True
                canvas_agent_ids_by_role[role] = agent_id
        if set(canvas_agent_ids_by_role) != expected_roles:
            return True
        if s._knowledge_expansion_team_duplicate_agent_ids(set(member_agent_ids_by_role.values())):
            return True
    return False


def _knowledge_expansion_team_agent_direct_session_available(agent: dict[str, Any]) -> bool:
    s = _service()
    try:
        from core.web.services import session_service
    except Exception:
        return bool(str(agent.get("directSessionId") or "").strip())
    previous_root = session_service.PROJECT_ROOT
    session_service.PROJECT_ROOT = Path(s.PROJECT_ROOT).resolve()
    try:
        return s._agent_direct_session_available(agent, session_service=session_service)
    finally:
        session_service.PROJECT_ROOT = previous_root


def ensure_knowledge_expansion_team_agents(*, purge_stale: bool = True) -> dict[str, Any]:
    """Ensure the dedicated knowledge-expansion Team and role Agents exist."""

    s = _service()
    project_root = Path(s.PROJECT_ROOT).resolve()
    ensured_agents = s._ensure_knowledge_expansion_team_role_agents()
    members = s._knowledge_expansion_team_members_from_agents(ensured_agents)
    expected_agent_ids = {
        str(agent.get("agentId") or "").strip()
        for agent in ensured_agents
        if isinstance(agent, dict) and str(agent.get("agentId") or "").strip()
    }
    old_agent_ids = s._knowledge_expansion_team_bound_agent_ids()
    extra_agent_ids = s._knowledge_expansion_team_duplicate_agent_ids(expected_agent_ids)
    purge_candidates = sorted((old_agent_ids | extra_agent_ids) - expected_agent_ids)
    purge_results = s._purge_knowledge_expansion_team_agents(purge_candidates, project_root=project_root) if purge_stale else []
    now = s.utc_now_iso()
    agent_refs = s._merged_agent_reference_maps(s._load_lightweight_agent_references(), ensured_agents)
    with s._TEAM_LOCK:
        state = s._load_index()
        changed = s._repair_index_shape(state)
        for existing_team in list(state.get("teams") or []):
            if not isinstance(existing_team, dict):
                continue
            if str(existing_team.get("teamId") or "").strip() == s.KNOWLEDGE_EXPANSION_TEAM_ID:
                continue
            changed = s._repair_team(existing_team, agent_refs=agent_refs) or changed
        team = s._find_team(state, s.KNOWLEDGE_EXPANSION_TEAM_ID)
        created = team is None
        if team is None:
            team = {
                "teamId": s.KNOWLEDGE_EXPANSION_TEAM_ID,
                "name": s.KNOWLEDGE_EXPANSION_TEAM_DISPLAY_NAME,
                "description": "用于把本地和网络资料提炼为团队正式知识的系统团队。",
                "purpose": "组织资料寻找、资料提炼、资料关系整理和资料入库。",
                "status": s.DEFAULT_TEAM_STATUS,
                "members": members,
                "linkedChatRoomId": "",
                "canvasPath": s._relative_path(s._team_canvas_path(s.KNOWLEDGE_EXPANSION_TEAM_ID)),
                "createdAt": now,
                "updatedAt": now,
            }
            s._apply_team_contract(team, team_kind="knowledge_expansion", team_source="knowledge_expansion")
            state.setdefault("teams", []).append(team)
            changed = True
        else:
            if team.get("name") != s.KNOWLEDGE_EXPANSION_TEAM_DISPLAY_NAME:
                team["name"] = s.KNOWLEDGE_EXPANSION_TEAM_DISPLAY_NAME
                changed = True
            if str(team.get("description") or "").strip() != "用于把本地和网络资料提炼为团队正式知识的系统团队。":
                team["description"] = "用于把本地和网络资料提炼为团队正式知识的系统团队。"
                changed = True
            expected_purpose = "组织资料寻找、资料提炼、资料关系整理和资料入库。"
            if str(team.get("purpose") or "").strip() != expected_purpose:
                team["purpose"] = expected_purpose
                changed = True
            if team.get("members") != members:
                team["members"] = members
                changed = True
            team["status"] = s.DEFAULT_TEAM_STATUS
            team["canvasPath"] = s._relative_path(s._team_canvas_path(s.KNOWLEDGE_EXPANSION_TEAM_ID))
            s._apply_team_contract(team, team_kind="knowledge_expansion", team_source="knowledge_expansion")
        if changed:
            team["updatedAt"] = now
            state["updatedAt"] = now
            s._save_index(state)
        canvas = s._default_canvas_for_team(team)
        s._write_json(s._team_canvas_path(s.KNOWLEDGE_EXPANSION_TEAM_ID), canvas)
        s._ensure_team_chat_room_link(team, agent_refs=agent_refs)
        team["updatedAt"] = now
        state["updatedAt"] = now
        s._save_index(state)
    result = {
        "schemaVersion": s.SCHEMA_VERSION,
        "teamId": s.KNOWLEDGE_EXPANSION_TEAM_ID,
        "created": created,
        "memberCount": len(members),
        "agentCount": len(ensured_agents),
        "directSessionCount": sum(1 for agent in ensured_agents if str(agent.get("directSessionId") or "").strip()),
        "purgedAgentIds": [str(item.get("agentId") or "") for item in purge_results if item.get("deleted")],
        "purgeResults": purge_results,
        "roles": [
            {
                "role": str(role.get("role") or ""),
                "roleKey": str(role.get("roleKey") or ""),
                "label": str(role.get("label") or ""),
            }
            for role in s.KNOWLEDGE_EXPANSION_TEAM_ROLES
        ],
        "team": s.get_team(s.KNOWLEDGE_EXPANSION_TEAM_ID),
    }
    s._record_team_event(
        "team.knowledge_expansion_agents_repaired",
        result["team"],
        fields={
            "created": created,
            "memberCount": result["memberCount"],
            "agentCount": result["agentCount"],
            "directSessionCount": result["directSessionCount"],
            "purgedAgentCount": len(result["purgedAgentIds"]),
        },
    )
    return result


def ensure_evolution_system_teams() -> dict[str, Any]:
    """Ensure self-evolution and supervised-evolution roles are visible as Teams."""

    s = _service()
    ensured_agents = s._ensure_evolution_system_agents()
    agent_refs = s._merged_agent_reference_maps(
        s._load_lightweight_agent_references(),
        [agent for agents in ensured_agents.values() for agent in list(agents or []) if isinstance(agent, dict)],
    )
    teams: list[dict[str, Any]] = []
    with s._TEAM_LOCK:
        state = s._load_index()
        changed = s._repair_index_state(state, agent_refs=agent_refs)
        for spec in s.EVOLUTION_SYSTEM_TEAM_SPECS:
            team, team_changed = s._ensure_evolution_system_team_in_state(
                state,
                spec,
                ensured_agents,
                agent_refs=agent_refs,
            )
            changed = changed or team_changed
            if team:
                teams.append(dict(team))
        if changed:
            state["updatedAt"] = s.utc_now_iso()
            s._save_index(state)
    return {
        "schemaVersion": s.SCHEMA_VERSION,
        "teams": [s._team_detail_to_api(team, agent_refs=agent_refs) for team in teams],
        "updatedAt": s.utc_now_iso(),
    }


def ai_search_system_team_missing() -> bool:
    """Return whether the AI search scope Team should be materialized for the list surface."""

    s = _service()
    expected_roles = {str(role.get("role") or "").strip() for role in s.AI_SEARCH_SYSTEM_ROLES}
    with s._TEAM_LOCK:
        state = s._load_index()
        if s._repair_index_shape(state):
            s._save_index(state)
        team = s._find_team(state, s.AI_SEARCH_TEAM_ID)
        if not team or str(team.get("status") or s.DEFAULT_TEAM_STATUS).strip() == "archived":
            return True
        if str(team.get("teamKind") or s._infer_team_kind(team)).strip() != "ai_search":
            return True
        if str(team.get("sourceScopePath") or "").strip() != s._relative_path(s._ai_search_source_scope_path()):
            return True
        if s._ai_search_source_scope_needs_sync(s._ai_search_source_scope_path()):
            return True
        member_roles = {
            str(member.get("role") or "").strip()
            for member in list(team.get("members") or [])
            if isinstance(member, dict) and str(member.get("agentId") or "").strip()
        }
        return not expected_roles.issubset(member_roles)


def ensure_ai_search_system_team() -> dict[str, Any]:
    """Ensure the AI search source-scope team is visible in the Team workspace."""

    s = _service()
    ensured_agents = s._ensure_ai_search_system_agents()
    agent_refs = s._merged_agent_reference_maps(s._load_lightweight_agent_references(), ensured_agents)
    members = s._ai_search_members_from_agents(ensured_agents)
    now = s.utc_now_iso()
    with s._TEAM_LOCK:
        state = s._load_index()
        changed = s._repair_index_state(state, agent_refs=agent_refs)
        members = s._members_without_cross_team_conflicts(members, state, s.AI_SEARCH_TEAM_ID, source="ai_search")
        team = s._find_team(state, s.AI_SEARCH_TEAM_ID)
        created = team is None
        if team is None:
            team = {
                "teamId": s.AI_SEARCH_TEAM_ID,
                "name": s.AI_SEARCH_TEAM_DISPLAY_NAME,
                "description": "由 AI 最新动态搜索范围白名单自动同步的系统团队。",
                "purpose": "维护 AI 最新动态一键搜索的来源范围、可信度分层、默认启用策略与信号源质检。",
                "status": s.DEFAULT_TEAM_STATUS,
                "members": members,
                "linkedChatRoomId": "",
                "canvasPath": s._relative_path(s._team_canvas_path(s.AI_SEARCH_TEAM_ID)),
                "sourceScopePath": s._relative_path(s._ai_search_source_scope_path()),
                "systemTeamKind": "ai_search",
                "teamKind": "ai_search",
                "teamCategory": "AI 搜索系统团队",
                "teamSource": "ai_search",
                "teamTemplateId": "",
                "createdAt": now,
                "updatedAt": now,
            }
            state.setdefault("teams", []).append(team)
            changed = True
        else:
            expected = {
                "name": s.AI_SEARCH_TEAM_DISPLAY_NAME,
                "description": "由 AI 最新动态搜索范围白名单自动同步的系统团队。",
                "purpose": "维护 AI 最新动态一键搜索的来源范围、可信度分层、默认启用策略与信号源质检。",
                "status": s.DEFAULT_TEAM_STATUS,
                "members": members,
                "canvasPath": s._relative_path(s._team_canvas_path(s.AI_SEARCH_TEAM_ID)),
                "sourceScopePath": s._relative_path(s._ai_search_source_scope_path()),
                "systemTeamKind": "ai_search",
                "teamKind": "ai_search",
                "teamCategory": "AI 搜索系统团队",
                "teamSource": "ai_search",
                "teamTemplateId": "",
            }
            for key, value in expected.items():
                if team.get(key) != value:
                    team[key] = value
                    changed = True
            if changed:
                team["updatedAt"] = now
        if s._apply_team_contract(team, team_kind="ai_search", team_source="ai_search"):
            changed = True
        canvas_path = s._team_canvas_path(s.AI_SEARCH_TEAM_ID)
        if created or s._ai_search_canvas_needs_sync(canvas_path, team):
            s._write_json(canvas_path, s._ai_search_canvas_for_team(team))
            changed = True
        source_scope_changed = s._ensure_ai_search_source_scope_file()
        if source_scope_changed:
            changed = True
        if s._team_chat_room_needs_sync(team, agent_refs=agent_refs):
            s._ensure_team_chat_room_link(team, agent_refs=agent_refs)
            changed = True
        if changed:
            canvas = s._ai_search_canvas_for_team(team)
            source_scope = s._load_ai_search_source_scope()
            team["updatedAt"] = str(team.get("updatedAt") or now)
            state["updatedAt"] = team["updatedAt"]
            s._save_index(state)
            s._record_team_event(
                "team.ai_search_system_synced",
                team,
                fields={
                    "created": created,
                    "memberCount": len(members),
                    "nodeCount": len(canvas.get("nodes") or []),
                    "edgeCount": len(canvas.get("edges") or []),
                    "sourceScopePath": s._relative_path(s._ai_search_source_scope_path()),
                    "sourceScopeChanged": source_scope_changed,
                    "sourceGroupCount": len(source_scope.get("groups") or []),
                    "sourceCount": int((source_scope.get("summary") or {}).get("sourceCount") or 0),
                    "source": "ai_search",
                },
            )
    return s.get_team(s.AI_SEARCH_TEAM_ID)


def _ensure_evolution_system_agents() -> dict[str, list[dict[str, Any]]]:
    s = _service()
    project_root = Path(s.PROJECT_ROOT).resolve()
    ensured: dict[str, list[dict[str, Any]]] = {"self_evolution": [], "supervised_evolution": []}
    try:
        from .. import self_evolution_control_service

        previous_root = self_evolution_control_service.PROJECT_ROOT
        self_evolution_control_service.PROJECT_ROOT = project_root
        try:
            ensured["self_evolution"] = list(self_evolution_control_service.ensure_self_evolution_agent_instances())
        finally:
            self_evolution_control_service.PROJECT_ROOT = previous_root
    except Exception as exc:
        s._record_system_team_sync_failed("self_evolution", exc)
    try:
        from .. import supervised_agent_service

        previous_root = supervised_agent_service.PROJECT_ROOT
        supervised_agent_service.PROJECT_ROOT = project_root
        try:
            ensured["supervised_evolution"] = list(supervised_agent_service.ensure_supervised_agent_instances())
        finally:
            supervised_agent_service.PROJECT_ROOT = previous_root
    except Exception as exc:
        s._record_system_team_sync_failed("supervised_evolution", exc)
    return ensured


def _ensure_ai_search_system_agents() -> list[dict[str, Any]]:
    s = _service()
    project_root = Path(s.PROJECT_ROOT).resolve()
    ensured: list[dict[str, Any]] = []
    try:
        from core.web.services import session_service

        previous_root = session_service.PROJECT_ROOT
        session_service.PROJECT_ROOT = project_root
        try:
            for role in s.AI_SEARCH_SYSTEM_ROLES:
                agent = s._ensure_ai_search_role_agent(role, session_service=session_service)
                if agent:
                    ensured.append(agent)
        finally:
            session_service.PROJECT_ROOT = previous_root
    except Exception as exc:
        s._record_system_team_sync_failed("ai_search", exc)
    return ensured


def _materialize_challenge_cup_research_team_agents() -> list[dict[str, Any]]:
    """Resolve exactly one active Directory Agent for every fixed role."""

    s = _service()
    agents: list[dict[str, Any]] = []
    for role in s.CHALLENGE_CUP_RESEARCH_TEAM_ROLES:
        agent = _materialize_challenge_cup_research_team_agent(role)
        if agent is None:
            role_name = str(role.get("role") or "").strip()
            raise s.TeamServiceError(
                f"Challenge Cup AgentDirectory asset is missing: {role_name}"
            )
        agents.append(agent)
    agent_ids = [str(agent.get("agentId") or "").strip() for agent in agents]
    if len(agent_ids) != len(set(agent_ids)):
        raise s.TeamServiceError(
            "Challenge Cup AgentDirectory roles must reference six unique Agents."
        )
    return agents


def _materialize_challenge_cup_research_team_agent(
    role: dict[str, Any],
) -> dict[str, Any] | None:
    """Resolve one complete Agent SSOT asset without performing any write."""

    s = _service()
    role_name = str(role.get("role") or "").strip()
    role_key = str(role.get("roleKey") or role_name).strip()
    if not role_name or not role_key:
        return None

    return s._find_challenge_cup_research_team_agent(role)


def _ensure_knowledge_expansion_team_role_agents() -> list[dict[str, Any]]:
    s = _service()
    project_root = Path(s.PROJECT_ROOT).resolve()
    ensured: list[dict[str, Any]] = []
    try:
        from core.web.services import session_service

        previous_root = session_service.PROJECT_ROOT
        session_service.PROJECT_ROOT = project_root
        try:
            for role in s.KNOWLEDGE_EXPANSION_TEAM_ROLES:
                agent = s._ensure_knowledge_expansion_team_role_agent(role, session_service=session_service)
                if agent:
                    ensured.append(agent)
        finally:
            session_service.PROJECT_ROOT = previous_root
    except Exception as exc:
        s._record_system_team_sync_failed("knowledge_expansion_team", exc)
        raise
    return ensured


def _ensure_knowledge_expansion_team_role_agent(role: dict[str, Any], *, session_service: Any) -> dict[str, Any] | None:
    s = _service()
    role_name = str(role.get("role") or "").strip()
    role_key = str(role.get("roleKey") or role_name).strip()
    label = str(role.get("label") or role_name).strip() or role_name
    if not role_name or not role_key:
        return None

    if role_key == agent_directory_service.KNOWLEDGE_STEWARD_ROLE_KEY:
        agent_directory_service.repair_agent_directory()
        existing = agent_directory_service.get_agent(agent_directory_service.KNOWLEDGE_STEWARD_AGENT_ID, include_archived=False)
    else:
        existing = s._find_knowledge_expansion_team_agent(role_name)

    if existing and not s._agent_direct_session_available(existing, session_service=session_service):
        session_service.ensure_agent_direct_session(
            agent_id=str(existing.get("agentId") or ""),
            title=label,
            created_by=s.KNOWLEDGE_EXPANSION_TEAM_AGENT_CREATED_BY,
            conversation_index_kind=agent_directory_service.CONVERSATION_INDEX_KIND_TEAM_AGENT,
        )
        existing = agent_directory_service.get_agent(str(existing.get("agentId") or ""), include_archived=False)

    if not existing or not str(existing.get("directSessionId") or "").strip():
        session_detail = session_service.create_chat_session(
            title=label,
            llm_bindings=session_service.default_session_llm_bindings(),
            created_by=s.KNOWLEDGE_EXPANSION_TEAM_AGENT_CREATED_BY,
            conversation_index_kind=agent_directory_service.CONVERSATION_INDEX_KIND_TEAM_AGENT,
        )
        agent_id = str(session_detail.get("agentId") or "").strip()
        existing = agent_directory_service.get_agent(agent_id) if agent_id else None
        if not existing:
            raise s.TeamServiceError(f"Knowledge expansion role Agent was not created for role: {role_name}")

    if str(existing.get("status") or "active").strip() == "archived":
        existing = agent_directory_service.reactivate_agent_instance(
            str(existing.get("agentId") or ""),
            reason="knowledge_expansion_team_required",
            metadata=s._knowledge_expansion_team_role_metadata(role),
        )

    agent_id = str(existing.get("agentId") or "").strip()
    if not agent_id:
        return None
    expected_metadata = s._knowledge_expansion_team_role_metadata(role)
    prompt_template_id = (
        agent_directory_service.KNOWLEDGE_EXPANSION_ROLE_PROMPT_TEMPLATE_IDS.get(role_key, "")
        or "prompt-chat-default"
    )
    if role_key == agent_directory_service.KNOWLEDGE_STEWARD_ROLE_KEY:
        tool_policy = agent_directory_service._knowledge_steward_tool_policy()
    elif role_key in agent_directory_service.RESEARCH_SOURCE_ROLE_KEYS:
        tool_policy = agent_directory_service.default_research_source_tool_policy(
            str(existing.get("toolPolicyId") or f"tool-{agent_id}"),
            role_key=role_key,
        )
    else:
        tool_policy = agent_directory_service.default_research_role_tool_policy(
            str(existing.get("toolPolicyId") or f"tool-{agent_id}"),
            role_key=role_key,
        )
    update_kwargs: dict[str, Any] = {
        "display_name": label,
        "primary_mode": "research",
        "role_key": role_key,
        "metadata": expected_metadata,
        "status": "active",
        "tool_policy": tool_policy,
    }
    if prompt_template_id:
        update_kwargs["prompt_template_id"] = prompt_template_id
    return agent_directory_service.update_agent_instance(agent_id, **update_kwargs)


def _agent_direct_session_available(agent: dict[str, Any], *, session_service: Any) -> bool:
    session_id = str(agent.get("directSessionId") or "").strip()
    if not session_id:
        return False
    try:
        return not bool(session_service._is_session_workspace_intentionally_deleted(session_id))
    except Exception:
        return True


def _find_challenge_cup_research_team_agent(
    role: dict[str, Any] | str,
) -> dict[str, Any] | None:
    s = _service()
    role_spec = role if isinstance(role, dict) else {"role": role}
    normalized_role = str(role_spec.get("role") or "").strip()
    if not normalized_role:
        return None
    candidates: list[dict[str, Any]] = []
    for agent in agent_directory_service.list_agents(include_archived=True, detail="summary"):
        agent_id = str(agent.get("agentId") or "").strip()
        if not agent_id or agent_id == agent_directory_service.KNOWLEDGE_STEWARD_AGENT_ID:
            continue
        if not _is_trusted_challenge_cup_research_team_agent(agent):
            continue
        metadata = agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}
        if str(metadata.get("challengeCupTeamRole") or "").strip() != normalized_role:
            continue
        if str(agent.get("status") or "active").strip() == "archived":
            continue
        if not str(agent.get("directSessionId") or "").strip():
            continue
        candidates.append(agent)
    if not candidates:
        return None
    if len(candidates) > 1:
        candidate_ids = ", ".join(
            sorted(str(item.get("agentId") or "").strip() for item in candidates)
        )
        raise s.TeamServiceError(
            f"Challenge Cup AgentDirectory role is duplicated: {normalized_role} ({candidate_ids})"
        )
    candidates.sort(
        key=lambda item: (
            str(item.get("createdAt") or ""),
            str(item.get("agentId") or ""),
        )
    )
    return candidates[0]


def _find_knowledge_expansion_team_agent(role_name: str) -> dict[str, Any] | None:
    s = _service()
    normalized_role = str(role_name or "").strip()
    if not normalized_role:
        return None
    for agent in agent_directory_service.list_agents(include_archived=True, detail="summary"):
        metadata = agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}
        if (
            str(metadata.get("knowledgeExpansionTeamId") or "").strip() == s.KNOWLEDGE_EXPANSION_TEAM_ID
            and str(metadata.get("knowledgeExpansionTeamRole") or "").strip() == normalized_role
            and int(metadata.get("knowledgeExpansionTeamManagedVersion") or 0) >= 1
        ):
            return agent
    return None


def _challenge_cup_research_team_role_metadata(
    role: dict[str, Any],
) -> dict[str, Any]:
    s = _service()
    role_name = str(role.get("role") or "").strip()
    role_key = str(role.get("roleKey") or role_name).strip()
    label = str(role.get("label") or role_name).strip() or role_name
    responsibilities = [
        str(item or "").strip()
        for item in list(role.get("responsibilities") or [])
        if str(item or "").strip()
    ]
    return {
        "agentMode": "research",
        "configSurface": "agent_config",
        "fixedRole": True,
        "showInSessionIndex": False,
        "conversationIndexKind": agent_directory_service.CONVERSATION_INDEX_KIND_TEAM_AGENT,
        "conversationIndexVisibility": agent_directory_service.CONVERSATION_INDEX_VISIBILITY_TEAM_PRIVATE,
        "directSessionVisibility": "active_session",
        "challengeCupTeamId": s.CHALLENGE_CUP_RESEARCH_TEAM_ID,
        "challengeCupTeamManagedVersion": 2,
        "challengeCupTeamContractVersion": s.CHALLENGE_CUP_RESEARCH_TEAM_ROLE_CONTRACT_VERSION,
        "challengeCupTeamRoleContractFingerprint": s.CHALLENGE_CUP_RESEARCH_TEAM_ROLE_CONTRACT_FINGERPRINT,
        "challengeCupTeamParticipantPolicyVersion": s.CHALLENGE_CUP_RESEARCH_TEAM_PARTICIPANT_POLICY_VERSION,
        "challengeCupTeamRole": role_name,
        "challengeCupTeamRoleKey": role_key,
        "researchTeamRole": role_name,
        "researchTeamRoleKey": role_key,
        "researchAgentKey": role_key,
        "functionalDisplayName": label,
        "managedDomain": "challenge_cup_neuro_algorithm",
        "responsibilities": responsibilities,
    }


def _knowledge_expansion_team_role_metadata(role: dict[str, Any]) -> dict[str, Any]:
    s = _service()
    role_name = str(role.get("role") or "").strip()
    role_key = str(role.get("roleKey") or role_name).strip()
    label = str(role.get("label") or role_name).strip() or role_name
    responsibilities = [
        str(item or "").strip()
        for item in list(role.get("responsibilities") or [])
        if str(item or "").strip()
    ]
    return {
        "agentMode": "research",
        "configSurface": "team",
        "fixedRole": True,
        "showInSessionIndex": False,
        "conversationIndexKind": agent_directory_service.CONVERSATION_INDEX_KIND_TEAM_AGENT,
        "conversationIndexVisibility": agent_directory_service.CONVERSATION_INDEX_VISIBILITY_TEAM_PRIVATE,
        "directSessionVisibility": "active_session",
        "knowledgeExpansionTeamId": s.KNOWLEDGE_EXPANSION_TEAM_ID,
        "knowledgeExpansionTeamManagedVersion": 1,
        "knowledgeExpansionTeamRole": role_name,
        "knowledgeExpansionTeamRoleKey": role_key,
        "researchTeamRole": role_name,
        "researchTeamRoleKey": role_key,
        "researchAgentKey": role_key,
        "functionalDisplayName": label,
        "managedDomain": "team_knowledge_expansion",
        "responsibilities": responsibilities,
    }


def _challenge_cup_research_team_members_from_agents(agents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    s = _service()
    agents_by_role: dict[str, dict[str, Any]] = {}
    for agent in agents:
        metadata = agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}
        role = str(metadata.get("challengeCupTeamRole") or "").strip()
        if role:
            agents_by_role[role] = agent
    members: list[dict[str, Any]] = []
    for index, role in enumerate(s.CHALLENGE_CUP_RESEARCH_TEAM_ROLES, start=1):
        role_name = str(role.get("role") or "").strip()
        agent = agents_by_role.get(role_name)
        agent_id = str((agent or {}).get("agentId") or "").strip()
        if not agent_id:
            continue
        members.append(
            {
                "memberId": f"challenge-cup-{index:02d}-{role_name}",
                "agentId": agent_id,
                "role": role_name,
            }
        )
    return members


def _knowledge_expansion_team_members_from_agents(agents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    s = _service()
    agents_by_role: dict[str, dict[str, Any]] = {}
    for agent in agents:
        metadata = agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}
        role = str(metadata.get("knowledgeExpansionTeamRole") or "").strip()
        if role:
            agents_by_role[role] = agent
    members: list[dict[str, Any]] = []
    for index, role in enumerate(s.KNOWLEDGE_EXPANSION_TEAM_ROLES, start=1):
        role_name = str(role.get("role") or "").strip()
        agent = agents_by_role.get(role_name)
        agent_id = str((agent or {}).get("agentId") or "").strip()
        if not agent_id:
            continue
        members.append(
            {
                "memberId": f"knowledge-expansion-{index:02d}-{role_name}",
                "agentId": agent_id,
                "agentCode": str((agent or {}).get("agentCode") or "").strip(),
                "agentName": str((agent or {}).get("displayName") or role.get("label") or "").strip(),
                "role": role_name,
                "purpose": str(role.get("purpose") or role.get("label") or "").strip(),
                "responsibilities": [
                    str(item or "").strip()
                    for item in list(role.get("responsibilities") or [])
                    if str(item or "").strip()
                ],
                "agentStatus": "active",
            }
        )
    return members


def _knowledge_expansion_team_bound_agent_ids() -> set[str]:
    s = _service()
    agent_ids: set[str] = set()
    with s._TEAM_LOCK:
        state = s._load_index()
        team = s._find_team(state, s.KNOWLEDGE_EXPANSION_TEAM_ID)
        if team:
            for member in list(team.get("members") or []):
                if isinstance(member, dict):
                    agent_id = str(member.get("agentId") or "").strip()
                    if agent_id:
                        agent_ids.add(agent_id)
        canvas_path = s._team_canvas_path(s.KNOWLEDGE_EXPANSION_TEAM_ID)
        canvas = s._read_json(canvas_path) if canvas_path.exists() else {}
        for node in list(canvas.get("nodes") or []):
            if isinstance(node, dict):
                agent_id = str(node.get("agentId") or "").strip()
                if agent_id:
                    agent_ids.add(agent_id)
    return agent_ids


def _knowledge_expansion_team_duplicate_agent_ids(expected_agent_ids: set[str]) -> set[str]:
    s = _service()
    duplicates: set[str] = set()
    for agent in agent_directory_service.list_agents(include_archived=True, detail="summary"):
        agent_id = str(agent.get("agentId") or "").strip()
        if not agent_id or agent_id in expected_agent_ids:
            continue
        if agent_id == agent_directory_service.KNOWLEDGE_STEWARD_AGENT_ID:
            continue
        metadata = agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}
        if str(metadata.get("knowledgeExpansionTeamId") or "").strip() == s.KNOWLEDGE_EXPANSION_TEAM_ID:
            duplicates.add(agent_id)
    return duplicates


def _purge_knowledge_expansion_team_agents(agent_ids: list[str], *, project_root: Path) -> list[dict[str, Any]]:
    s = _service()
    return s._purge_team_agents(agent_ids, project_root=project_root)


def _purge_team_agents(agent_ids: list[str], *, project_root: Path) -> list[dict[str, Any]]:
    s = _service()
    results: list[dict[str, Any]] = []
    try:
        from core.web.services import session_service
    except Exception:
        session_service = None
    previous_root = getattr(session_service, "s.PROJECT_ROOT", None) if session_service else None
    if session_service:
        session_service.PROJECT_ROOT = project_root
    try:
        for agent_id in agent_ids:
            result = s._purge_team_agent(agent_id, session_service=session_service)
            if result:
                results.append(result)
    finally:
        if session_service and previous_root is not None:
            session_service.PROJECT_ROOT = previous_root
    return results


def _purge_team_agent(agent_id: str, *, session_service: Any | None) -> dict[str, Any] | None:
    s = _service()
    normalized_agent_id = str(agent_id or "").strip()
    if not s._safe_agent_workspace_name(normalized_agent_id):
        return None
    agent = agent_directory_service.get_agent(normalized_agent_id, include_archived=True)
    if not agent:
        orphan_result = s._delete_orphan_agent_workspace(normalized_agent_id)
        return {
            "agentId": normalized_agent_id,
            "deleted": bool(orphan_result.get("deleted")),
            "orphan": True,
            **orphan_result,
        }
    metadata = agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}
    if bool(metadata.get("protected")) or str(agent.get("agentId") or "") == agent_directory_service.KNOWLEDGE_STEWARD_AGENT_ID:
        return {"agentId": normalized_agent_id, "deleted": False, "skipped": "protected"}
    created_by = str(agent.get("createdBy") or "").strip()
    system_team_purge_kwargs: dict[str, str] | None = None
    if (
        str(metadata.get("conversationIndexKind") or "").strip() == agent_directory_service.CONVERSATION_INDEX_KIND_TEAM_AGENT
        and str(metadata.get("conversationIndexVisibility") or "").strip()
        == agent_directory_service.CONVERSATION_INDEX_VISIBILITY_TEAM_PRIVATE
    ):
        if (
            created_by == s.CHALLENGE_CUP_RESEARCH_TEAM_AGENT_CREATED_BY
            and str(metadata.get("challengeCupTeamId") or "").strip() == s.CHALLENGE_CUP_RESEARCH_TEAM_ID
        ):
            system_team_purge_kwargs = {
                "expected_created_by": s.CHALLENGE_CUP_RESEARCH_TEAM_AGENT_CREATED_BY,
                "expected_team_metadata_key": "challengeCupTeamId",
                "expected_team_id": s.CHALLENGE_CUP_RESEARCH_TEAM_ID,
            }
        elif (
            created_by == s.KNOWLEDGE_EXPANSION_TEAM_AGENT_CREATED_BY
            and str(metadata.get("knowledgeExpansionTeamId") or "").strip() == s.KNOWLEDGE_EXPANSION_TEAM_ID
        ):
            system_team_purge_kwargs = {
                "expected_created_by": s.KNOWLEDGE_EXPANSION_TEAM_AGENT_CREATED_BY,
                "expected_team_metadata_key": "knowledgeExpansionTeamId",
                "expected_team_id": s.KNOWLEDGE_EXPANSION_TEAM_ID,
            }
    direct_session_id = str(agent.get("directSessionId") or "").strip()
    if direct_session_id and session_service:
        try:
            session_service.mark_direct_session_agent_deleted(
                direct_session_id,
                agent_id=normalized_agent_id,
                agent_display_name=str(agent.get("displayName") or ""),
                previous_status=str(agent.get("status") or ""),
                hide_from_index=system_team_purge_kwargs is not None,
            )
        except Exception:
            pass
    try:
        if system_team_purge_kwargs is not None:
            result = agent_directory_service.purge_system_team_agent_instance(
                normalized_agent_id,
                **system_team_purge_kwargs,
            )
        else:
            if str(agent.get("status") or "active").strip() != "archived":
                agent_directory_service.archive_agent_instance(normalized_agent_id, repair_mode_bindings=True)
            result = agent_directory_service.purge_archived_agent_instance(normalized_agent_id)
        result["orphan"] = False
        return result
    except Exception as exc:
        return {"agentId": normalized_agent_id, "deleted": False, "orphan": False, "error": str(exc)}


def _delete_orphan_agent_workspace(agent_id: str) -> dict[str, Any]:
    s = _service()
    normalized_agent_id = str(agent_id or "").strip()
    if not s._safe_agent_workspace_name(normalized_agent_id):
        return {"deleted": False, "deletedPaths": [], "skippedPaths": [normalized_agent_id]}
    agents_root = developer_sandbox.seeded_sandbox_workspace_path(s._project_root(), "agents").resolve()
    target = (agents_root / normalized_agent_id).resolve()
    if agents_root not in target.parents:
        return {"deleted": False, "deletedPaths": [], "skippedPaths": [str(target)]}
    if not target.exists():
        return {"deleted": False, "deletedPaths": [], "skippedPaths": []}
    if target.is_dir():
        shutil.rmtree(target)
    else:
        target.unlink()
    return {"deleted": True, "deletedPaths": [str(target)], "skippedPaths": []}


def _safe_agent_workspace_name(value: str) -> bool:
    s = _service()
    normalized = str(value or "").strip()
    return bool(normalized) and _SAFE_ID_FRAGMENT.sub("", normalized) == normalized and normalized not in {".", ".."}


def _ensure_ai_search_role_agent(role: dict[str, Any], *, session_service: Any) -> dict[str, Any] | None:
    s = _service()
    role_key = str(role.get("role") or "").strip()
    label = str(role.get("label") or role_key).strip() or role_key
    if not role_key:
        return None
    existing = s._find_agent_by_ai_search_role(role_key)
    if not existing:
        session_detail = session_service.create_chat_session(
            title=label,
            llm_bindings=session_service.default_session_llm_bindings(),
            created_by="ai_search_team",
            conversation_index_kind=agent_directory_service.CONVERSATION_INDEX_KIND_TEAM_AGENT,
        )
        agent_id = str(session_detail.get("agentId") or "").strip()
        existing = agent_directory_service.get_agent(agent_id) if agent_id else None
        if not existing:
            raise RuntimeError(f"AI search role Agent was not created for role: {role_key}")
    if str(existing.get("status") or "active").strip() == "archived":
        existing = agent_directory_service.reactivate_agent_instance(
            str(existing.get("agentId") or ""),
            reason="ai_search_team_required",
            metadata={"protected": True, "fixedRole": True},
        )
    metadata = dict(existing.get("metadata") or {})
    expected_metadata = s._ai_search_role_metadata(role)
    needs_update = (
        str(existing.get("displayName") or "").strip() != label
        or str(existing.get("primaryMode") or "").strip() != "research"
        or str(existing.get("roleKey") or "").strip() != role_key
        or str(existing.get("promptTemplateId") or "").strip() != "prompt-chat-default"
        or any(metadata.get(key) != value for key, value in expected_metadata.items())
    )
    if needs_update:
        existing = agent_directory_service.update_agent_instance(
            str(existing.get("agentId") or ""),
            display_name=label,
            primary_mode="research",
            role_key=role_key,
            prompt_template_id="prompt-chat-default",
            metadata=expected_metadata,
            status="active",
        )
    return existing


def _find_agent_by_ai_search_role(role_key: str) -> dict[str, Any] | None:
    s = _service()
    normalized = str(role_key or "").strip()
    if not normalized:
        return None
    for agent in agent_directory_service.list_agents(include_archived=True, detail="summary"):
        metadata = agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}
        if str(metadata.get("aiSearchRole") or "").strip() == normalized:
            return agent
    return None


def _ai_search_role_metadata(role: dict[str, Any]) -> dict[str, Any]:
    s = _service()
    role_key = str(role.get("role") or "").strip()
    label = str(role.get("label") or role_key).strip() or role_key
    purpose = str(role.get("purpose") or "").strip()
    responsibilities = [str(item or "").strip() for item in list(role.get("responsibilities") or []) if str(item or "").strip()]
    expertise = [str(item or "").strip() for item in list(role.get("expertise") or []) if str(item or "").strip()]
    return {
        "agentMode": "ai_search",
        "configSurface": "team",
        "conversationIndexKind": agent_directory_service.CONVERSATION_INDEX_KIND_TEAM_AGENT,
        "conversationIndexVisibility": agent_directory_service.CONVERSATION_INDEX_VISIBILITY_TEAM_PRIVATE,
        "fixedRole": True,
        "protected": True,
        "showInSessionIndex": False,
        "teamId": s.AI_SEARCH_TEAM_ID,
        "aiSearchRole": role_key,
        "aiSearchRoleLabel": label,
        "directSessionVisibility": "active_session",
        "functionalDisplayName": label,
        "managedDomain": "ai_latest_news_source_scope",
        "personaProfile": {
            "personality": "证据优先、克制、偏好一手来源和可复盘边界。",
            "communicationStyle": "先说明来源可信度，再给纳入、默认启用或仅作信号的判断。",
            "background": "维护 AI 最新动态一键搜索的来源范围名单，避免搜索结果被噪声和非一手信息污染。",
            "expertise": expertise,
        },
        "taskProfile": {
            "mission": purpose,
            "responsibilities": "；".join(responsibilities) or purpose,
            "preferredTasks": "维护 AI 动态搜索源白名单、标注地区/语言/Tier/evidenceRole/enabledByDefault，并发现缺源或噪声源。",
            "avoidTasks": "不要把新闻、社区或社交信号直接当结论；不要自动发布、删除来源或写入正式知识库。",
            "successCriteria": "每个来源都有稳定 id、入口 URL、可信度层级、证据角色、默认启用状态和人工说明。",
            "deliverables": "搜索范围名单更新建议、缺源清单、信号源质检结论和一手证据回链要求。",
            "constraints": "本团队只维护搜索范围和来源质量，不执行真实发布、远程写入或知识库审批。",
        },
    }


def _ai_search_members_from_agents(agents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    s = _service()
    agents_by_role: dict[str, dict[str, Any]] = {}
    for agent in agents:
        if not isinstance(agent, dict):
            continue
        metadata = agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}
        role_key = str(metadata.get("aiSearchRole") or agent.get("roleKey") or "").strip()
        if role_key:
            agents_by_role[role_key] = agent
    members: list[dict[str, Any]] = []
    for index, role in enumerate(s.AI_SEARCH_SYSTEM_ROLES, start=1):
        role_key = str(role.get("role") or "").strip()
        agent = agents_by_role.get(role_key)
        agent_id = str((agent or {}).get("agentId") or "").strip()
        if not agent_id:
            continue
        members.append(
            {
                "memberId": f"ai-search-{index}",
                "agentId": agent_id,
                "agentCode": str((agent or {}).get("agentCode") or "").strip(),
                "agentName": str((agent or {}).get("displayName") or role.get("label") or "").strip(),
                "role": role_key,
                "purpose": str(role.get("label") or "").strip(),
                "responsibilities": list(role.get("responsibilities") or []),
                "agentStatus": "active",
            }
        )
    return members


def _ensure_evolution_system_team_in_state(
    state: dict[str, Any],
    spec: dict[str, str],
    ensured_agents: dict[str, list[dict[str, Any]]],
    *,
    agent_refs: dict[str, dict[str, dict[str, Any]]] | None = None,
) -> tuple[dict[str, Any] | None, bool]:
    s = _service()
    team_id = str(spec.get("teamId") or "").strip()
    source = str(spec.get("source") or "").strip()
    if not team_id or not source:
        return None, False
    members = s._system_members_from_agents(ensured_agents.get(source) or [], source=source)
    members = s._members_without_cross_team_conflicts(members, state, team_id, source=source)
    now = s.utc_now_iso()
    team = s._find_team(state, team_id)
    created = team is None
    changed = created
    if team is None:
        team = {
            "teamId": team_id,
            "name": str(spec.get("name") or team_id).strip(),
            "description": str(spec.get("description") or "").strip(),
            "purpose": str(spec.get("purpose") or "").strip(),
            "status": s.DEFAULT_TEAM_STATUS,
            "members": members,
            "linkedChatRoomId": "",
            "canvasPath": s._relative_path(s._team_canvas_path(team_id)),
            "systemTeamKind": source,
            "teamKind": str(spec.get("teamKind") or source).strip(),
            "teamCategory": str(spec.get("teamCategory") or "").strip(),
            "teamSource": str(spec.get("teamSource") or source).strip(),
            "teamTemplateId": "",
            "createdAt": now,
            "updatedAt": now,
        }
        s._apply_team_contract(
            team,
            team_kind=str(spec.get("teamKind") or source),
            team_category=str(spec.get("teamCategory") or ""),
            team_source=str(spec.get("teamSource") or source),
        )
        state.setdefault("teams", []).append(team)
    else:
        expected = {
            "name": str(spec.get("name") or team_id).strip(),
            "description": str(spec.get("description") or "").strip(),
            "purpose": str(spec.get("purpose") or "").strip(),
            "status": s.DEFAULT_TEAM_STATUS,
            "members": members,
            "canvasPath": s._relative_path(s._team_canvas_path(team_id)),
            "systemTeamKind": source,
            "teamKind": str(spec.get("teamKind") or source).strip(),
            "teamCategory": str(spec.get("teamCategory") or "").strip(),
            "teamSource": str(spec.get("teamSource") or source).strip(),
            "teamTemplateId": "",
        }
        for key, value in expected.items():
            if team.get(key) != value:
                team[key] = value
                changed = True
        if s._apply_team_contract(
            team,
            team_kind=str(spec.get("teamKind") or source),
            team_category=str(spec.get("teamCategory") or ""),
            team_source=str(spec.get("teamSource") or source),
        ):
            changed = True
        if changed:
            team["updatedAt"] = now
    canvas_path = s._team_canvas_path(team_id)
    if changed or not canvas_path.exists() or s._default_canvas_edges_missing_for_team(team, canvas_path):
        s._write_json(canvas_path, s._default_canvas_for_team(team))
    if s._team_chat_room_needs_sync(team, agent_refs=agent_refs):
        s._ensure_team_chat_room_link(team, agent_refs=agent_refs)
        changed = True
    if changed:
        s._record_team_event(
            "team.system_evolution_synced",
            team,
            fields={"created": created, "source": source, "memberCount": len(members)},
        )
    return team, changed


def _system_members_from_agents(agents: list[dict[str, Any]], *, source: str) -> list[dict[str, Any]]:
    s = _service()
    members: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, agent in enumerate(agents[:120]):
        if not isinstance(agent, dict):
            continue
        agent_id = str(agent.get("agentId") or "").strip()
        if not agent_id or agent_id in seen:
            continue
        if str(agent.get("status") or "active").strip() == "archived":
            continue
        metadata = agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}
        role = str(agent.get("roleKey") or "").strip()
        role_label = ""
        if source == "self_evolution":
            role = str(metadata.get("selfEvolutionRole") or role).strip()
            role_label = str(metadata.get("selfEvolutionRoleLabel") or "").strip()
        elif source == "supervised_evolution":
            role = str(metadata.get("supervisedRole") or role).strip()
            role_label = str(metadata.get("supervisedRoleLabel") or "").strip()
        seen.add(agent_id)
        members.append(
            {
                "memberId": s._safe_token(f"{source}-{role or index + 1}", default=f"member-{index + 1}", max_length=96),
                "agentId": agent_id,
                "agentCode": str(agent.get("agentCode") or "").strip(),
                "agentName": str(agent.get("displayName") or role_label or agent_id).strip(),
                "role": role,
                "purpose": role_label,
                "agentStatus": "active",
            }
        )
    return members
