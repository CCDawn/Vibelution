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


def _challenge_cup_research_team_migration_marker(
    *,
    phase: str,
    attempt: int,
    error: str = "",
) -> dict[str, Any]:
    s = _service()
    return {
        "targetContractVersion": s.CHALLENGE_CUP_RESEARCH_TEAM_ROLE_CONTRACT_VERSION,
        "targetFingerprint": s.CHALLENGE_CUP_RESEARCH_TEAM_ROLE_CONTRACT_FINGERPRINT,
        "phase": str(phase or "").strip(),
        "attempt": max(1, int(attempt or 1)),
        "error": str(error or "").strip()[:500],
    }


def _challenge_cup_research_team_marker_is_completed(team: dict[str, Any]) -> bool:
    s = _service()
    marker = team.get("roleMigration") if isinstance(team.get("roleMigration"), dict) else {}
    try:
        target_version = int(marker.get("targetContractVersion") or 0)
        attempt = int(marker.get("attempt") or 0)
    except (TypeError, ValueError):
        return False
    return (
        target_version == s.CHALLENGE_CUP_RESEARCH_TEAM_ROLE_CONTRACT_VERSION
        and str(marker.get("targetFingerprint") or "").strip()
        == s.CHALLENGE_CUP_RESEARCH_TEAM_ROLE_CONTRACT_FINGERPRINT
        and str(marker.get("phase") or "").strip() == "completed"
        and attempt >= 1
        and not str(marker.get("error") or "").strip()
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


def _write_challenge_cup_research_team_migration_marker(
    *,
    phase: str,
    attempt: int | None = None,
    error: str = "",
) -> tuple[bool, int]:
    """Persist a resumable migration phase before or after side effects."""

    s = _service()
    now = s.utc_now_iso()
    with s._TEAM_LOCK:
        state = s._load_index()
        changed = s._repair_index_shape(state)
        team = s._find_team(state, s.CHALLENGE_CUP_RESEARCH_TEAM_ID)
        created = team is None
        if team is None:
            team = _challenge_cup_research_team_placeholder(now)
            state.setdefault("teams", []).append(team)
            changed = True
        previous_marker = (
            team.get("roleMigration")
            if isinstance(team.get("roleMigration"), dict)
            else {}
        )
        try:
            previous_attempt = max(0, int(previous_marker.get("attempt") or 0))
        except (TypeError, ValueError):
            previous_attempt = 0
        resolved_attempt = (
            previous_attempt + 1
            if attempt is None
            else max(1, int(attempt or 1))
        )
        marker = _challenge_cup_research_team_migration_marker(
            phase=phase,
            attempt=resolved_attempt,
            error=error,
        )
        if team.get("roleMigration") != marker:
            team["roleMigration"] = marker
            team["updatedAt"] = now
            state["updatedAt"] = now
            changed = True
        if changed:
            s._save_index(state)
    return created, resolved_attempt


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


def challenge_cup_research_team_agents_need_repair() -> bool:
    """Return whether the Challenge Cup research Team has stale Agent bindings."""

    s = _service()
    with s._TEAM_LOCK:
        state = s._load_index()
        team = s._find_team(state, s.CHALLENGE_CUP_RESEARCH_TEAM_ID)
        if not team:
            return True
        if not _challenge_cup_research_team_marker_is_completed(team):
            return True
        active_binding = (
            team.get("activeBinding")
            if isinstance(team.get("activeBinding"), dict)
            else {}
        )
        if (
            int(team.get("roleContractVersion") or 0)
            != s.CHALLENGE_CUP_RESEARCH_TEAM_ROLE_CONTRACT_VERSION
            or str(team.get("roleContractFingerprint") or "").strip()
            != s.CHALLENGE_CUP_RESEARCH_TEAM_ROLE_CONTRACT_FINGERPRINT
            or str(active_binding.get("status") or "").strip()
            != "active"
        ):
            return True
        agent_refs = s._agent_reference_maps()
        active_agents = agent_refs.get("active_by_id") or {}
        expected_roles = {
            str(role.get("role") or "").strip()
            for role in s.CHALLENGE_CUP_RESEARCH_TEAM_ROLES
            if str(role.get("role") or "").strip()
        }
        members = list(team.get("members") or [])
        if len(members) != len(expected_roles) or any(
            not isinstance(member, dict) for member in members
        ):
            return True
        member_agent_ids_by_role: dict[str, str] = {}
        member_agent_ids: set[str] = set()
        roles_by_name = {
            str(role.get("role") or "").strip(): role
            for role in s.CHALLENGE_CUP_RESEARCH_TEAM_ROLES
            if isinstance(role, dict) and str(role.get("role") or "").strip()
        }
        for member in members:
            role = str(member.get("role") or "").strip()
            agent_id = str(member.get("agentId") or "").strip()
            if role not in expected_roles or role in member_agent_ids_by_role:
                return True
            if not agent_id or agent_id in member_agent_ids or agent_id not in active_agents:
                return True
            agent = agent_directory_service.get_agent(
                agent_id,
                include_archived=False,
            )
            if not _is_trusted_challenge_cup_research_team_agent(agent):
                return True
            if not _challenge_cup_research_team_agent_matches_role_contract(
                agent,
                roles_by_name[role],
            ):
                return True
            if not s._challenge_cup_research_team_agent_direct_session_available(agent):
                return True
            member_agent_ids_by_role[role] = agent_id
            member_agent_ids.add(agent_id)
        if set(member_agent_ids_by_role) != expected_roles or len(member_agent_ids) != len(expected_roles):
            return True
        if active_binding.get("productRoleAgentIds") != member_agent_ids_by_role:
            return True
        canvas_path = s._team_canvas_path(s.CHALLENGE_CUP_RESEARCH_TEAM_ID)
        if not canvas_path.exists():
            return True
        canvas = s._read_json(canvas_path)
        if not _challenge_cup_research_team_canvas_matches_binding(
            canvas,
            member_agent_ids_by_role,
        ):
            return True
        if s._challenge_cup_research_team_duplicate_agent_ids(set(member_agent_ids_by_role.values())):
            return True
        expected_legacy_bindings = _challenge_cup_research_team_expected_legacy_bindings(
            active_agent_ids=set(member_agent_ids_by_role.values()),
            require_agent_metadata=True,
        )
        if expected_legacy_bindings is None or team.get("legacyBindings") != expected_legacy_bindings:
            return True
        if s._team_chat_room_needs_sync(team, agent_refs=agent_refs):
            return True
    return False


def _challenge_cup_research_team_agent_direct_session_available(agent: dict[str, Any]) -> bool:
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


def ensure_challenge_cup_research_team_agents(*, purge_stale: bool = True) -> dict[str, Any]:
    """Reconcile the active v2 Team projection without deleting v1 identities."""

    s = _service()
    with s._CHALLENGE_CUP_RESEARCH_TEAM_MIGRATION_LOCK:
        return _ensure_challenge_cup_research_team_agents_locked(
            purge_stale=purge_stale,
        )


def _ensure_challenge_cup_research_team_agents_locked(
    *,
    purge_stale: bool,
) -> dict[str, Any]:
    """Run the resumable migration inside the project backend critical section."""

    s = _service()
    purge_results: list[dict[str, Any]] = []
    if not s.challenge_cup_research_team_agents_need_repair():
        team = s.get_team(s.CHALLENGE_CUP_RESEARCH_TEAM_ID)
        ensured_agents = [
            agent
            for member in list((team or {}).get("members") or [])
            if isinstance(member, dict)
            for agent in [
                agent_directory_service.get_agent(
                    str(member.get("agentId") or "").strip(),
                    include_archived=False,
                )
            ]
            if agent
        ]
        return _challenge_cup_research_team_ensure_result(
            team=team or {},
            ensured_agents=ensured_agents,
            legacy_bindings=list((team or {}).get("legacyBindings") or []),
            created=False,
            purge_stale=purge_stale,
            purge_results=purge_results,
        )

    created, attempt = _write_challenge_cup_research_team_migration_marker(
        phase="preparing"
    )
    try:
        ensured_agents = s._ensure_challenge_cup_research_team_role_agents()
        members = s._challenge_cup_research_team_members_from_agents(ensured_agents)
        if len(members) != len(s.CHALLENGE_CUP_RESEARCH_TEAM_ROLES):
            raise s.TeamServiceError(
                "Challenge Cup role migration did not materialize all canonical Agents."
            )
        expected_agent_ids = {
            str(agent.get("agentId") or "").strip()
            for agent in ensured_agents
            if isinstance(agent, dict) and str(agent.get("agentId") or "").strip()
        }
        legacy_bindings = s._mark_challenge_cup_research_team_legacy_agents(
            expected_agent_ids
        )
        now = s.utc_now_iso()
        agent_refs = s._merged_agent_reference_maps(
            s._load_lightweight_agent_references(),
            ensured_agents,
        )
        active_role_agent_ids = {
            str(member.get("role") or "").strip(): str(member.get("agentId") or "").strip()
            for member in members
            if isinstance(member, dict)
            and str(member.get("role") or "").strip()
            and str(member.get("agentId") or "").strip()
        }
        with s._TEAM_LOCK:
            state = s._load_index()
            changed = s._repair_index_shape(state)
            for existing_team in list(state.get("teams") or []):
                if not isinstance(existing_team, dict):
                    continue
                if str(existing_team.get("teamId") or "").strip() == s.CHALLENGE_CUP_RESEARCH_TEAM_ID:
                    continue
                changed = s._repair_team(existing_team, agent_refs=agent_refs) or changed
            team = s._find_team(state, s.CHALLENGE_CUP_RESEARCH_TEAM_ID)
            if team is None:
                team = _challenge_cup_research_team_placeholder(now)
                state.setdefault("teams", []).append(team)
                changed = True
            expected_fields = {
                "name": s.RESEARCH_TEAM_DISPLAY_NAME,
                "description": "挑战杯 125 题假说与研究计划的六 Agent 系统团队。",
                "purpose": "组织搜索、提炼、知识治理、执行、实验修订与独立评估。",
                "status": s.DEFAULT_TEAM_STATUS,
                "members": members,
                "canvasPath": s._relative_path(
                    s._team_canvas_path(s.CHALLENGE_CUP_RESEARCH_TEAM_ID)
                ),
                "roleContractId": str(
                    s.CHALLENGE_CUP_RESEARCH_TEAM_ROLE_CONTRACT.get(
                        "teamRoleContractId"
                    )
                    or ""
                ),
                "roleContractVersion": s.CHALLENGE_CUP_RESEARCH_TEAM_ROLE_CONTRACT_VERSION,
                "roleContractFingerprint": s.CHALLENGE_CUP_RESEARCH_TEAM_ROLE_CONTRACT_FINGERPRINT,
                "participantPolicyVersion": s.CHALLENGE_CUP_RESEARCH_TEAM_PARTICIPANT_POLICY_VERSION,
                "legacyReadMode": s.CHALLENGE_CUP_RESEARCH_TEAM_LEGACY_READ_MODE,
                "activeBinding": {
                    "status": "active",
                    "productRoleAgentIds": active_role_agent_ids,
                },
                "legacyBindings": legacy_bindings,
                "roleMigration": _challenge_cup_research_team_migration_marker(
                    phase="agents_bound",
                    attempt=attempt,
                ),
            }
            for key, value in expected_fields.items():
                if team.get(key) != value:
                    team[key] = value
                    changed = True
            team_before_contract = dict(team)
            s._apply_team_contract(
                team,
                team_kind="research",
                team_source="research_organization",
            )
            changed = changed or team != team_before_contract
            if changed:
                team["updatedAt"] = now
                state["updatedAt"] = now
                s._save_index(state)

        canvas_path = s._team_canvas_path(s.CHALLENGE_CUP_RESEARCH_TEAM_ID)
        existing_canvas = s._read_json(canvas_path) if canvas_path.exists() else {}
        if not _challenge_cup_research_team_canvas_matches_binding(
            existing_canvas,
            active_role_agent_ids,
        ):
            s._write_json(canvas_path, s._default_canvas_for_team(team))

        with s._TEAM_LOCK:
            state = s._load_index()
            team = s._find_team(state, s.CHALLENGE_CUP_RESEARCH_TEAM_ID)
            if team is None:
                raise s.TeamServiceError("Challenge Cup Team disappeared during migration.")
            if s._team_chat_room_needs_sync(team, agent_refs=agent_refs):
                s._ensure_team_chat_room_link(team, agent_refs=agent_refs)
                state["updatedAt"] = str(team.get("updatedAt") or s.utc_now_iso())
                s._save_index(state)

        _write_challenge_cup_research_team_migration_marker(
            phase="completed",
            attempt=attempt,
        )
    except Exception as exc:
        _write_challenge_cup_research_team_migration_marker(
            phase="failed",
            attempt=attempt,
            error=str(exc),
        )
        raise

    team = s.get_team(s.CHALLENGE_CUP_RESEARCH_TEAM_ID)
    result = _challenge_cup_research_team_ensure_result(
        team=team or {},
        ensured_agents=ensured_agents,
        legacy_bindings=legacy_bindings,
        created=created,
        purge_stale=purge_stale,
        purge_results=purge_results,
    )
    s._record_team_event(
        "team.challenge_cup_agents_repaired",
        result["team"],
        fields={
            "created": created,
            "memberCount": result["memberCount"],
            "agentCount": result["agentCount"],
            "directSessionCount": result["directSessionCount"],
            "purgedAgentCount": len(result["purgedAgentIds"]),
            "legacyAgentCount": len(result["legacyAgentIds"]),
            "roleContractVersion": s.CHALLENGE_CUP_RESEARCH_TEAM_ROLE_CONTRACT_VERSION,
            "roleContractFingerprint": s.CHALLENGE_CUP_RESEARCH_TEAM_ROLE_CONTRACT_FINGERPRINT,
            "purgeRequested": bool(purge_stale),
            "destructivePurgeSuppressed": True,
        },
    )
    return result


def _challenge_cup_research_team_ensure_result(
    *,
    team: dict[str, Any],
    ensured_agents: list[dict[str, Any]],
    legacy_bindings: list[dict[str, Any]],
    created: bool,
    purge_stale: bool,
    purge_results: list[dict[str, Any]],
) -> dict[str, Any]:
    s = _service()
    members = [
        member
        for member in list(team.get("members") or [])
        if isinstance(member, dict)
    ]
    result = {
        "schemaVersion": s.SCHEMA_VERSION,
        "teamId": s.CHALLENGE_CUP_RESEARCH_TEAM_ID,
        "created": created,
        "memberCount": len(members),
        "agentCount": len(ensured_agents),
        "directSessionCount": sum(1 for agent in ensured_agents if str(agent.get("directSessionId") or "").strip()),
        "purgedAgentIds": [str(item.get("agentId") or "") for item in purge_results if item.get("deleted")],
        "purgeResults": purge_results,
        "purgeRequested": bool(purge_stale),
        "legacyAgentIds": [str(item.get("agentId") or "") for item in legacy_bindings],
        "legacyBindings": legacy_bindings,
        "roles": [
            {
                "role": str(role.get("role") or ""),
                "roleKey": str(role.get("roleKey") or ""),
                "label": str(role.get("label") or ""),
            }
            for role in s.CHALLENGE_CUP_RESEARCH_TEAM_ROLES
        ],
        "team": team,
    }
    return result


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


def _challenge_cup_research_team_role_agent_expected_config(
    agent: dict[str, Any],
    role: dict[str, Any],
    *,
    source_role: str,
) -> dict[str, Any]:
    s = _service()
    agent_id = str(agent.get("agentId") or "").strip()
    role_name = str(role.get("role") or "").strip()
    role_key = str(role.get("roleKey") or role_name).strip()
    label = str(role.get("label") or role_name).strip() or role_name
    if role_key == agent_directory_service.KNOWLEDGE_STEWARD_ROLE_KEY:
        prompt_template_id = agent_directory_service.KNOWLEDGE_STEWARD_PROMPT_TEMPLATE_ID
        tool_policy = agent_directory_service._knowledge_steward_tool_policy()
    elif role_key in agent_directory_service.RESEARCH_SOURCE_ROLE_KEYS:
        prompt_template_id = (
            agent_directory_service.CHALLENGE_CUP_ROLE_PROMPT_TEMPLATE_IDS.get(
                role_key,
                "",
            )
            or "prompt-chat-default"
        )
        tool_policy = agent_directory_service.default_research_source_tool_policy(
            str(agent.get("toolPolicyId") or f"tool-{agent_id}"),
            role_key=role_key,
        )
    else:
        prompt_template_id = (
            agent_directory_service.CHALLENGE_CUP_ROLE_PROMPT_TEMPLATE_IDS.get(
                role_key,
                "",
            )
            or "prompt-chat-default"
        )
        tool_policy = agent_directory_service.default_research_role_tool_policy(
            str(agent.get("toolPolicyId") or f"tool-{agent_id}"),
            role_key=role_key,
        )
    return {
        "displayName": label,
        "llmBindings": {
            "dialogue": {
                "modelId": s.CHALLENGE_CUP_RESEARCH_TEAM_DIALOGUE_MODEL_REF,
            }
        },
        "primaryMode": "research",
        "roleKey": role_key,
        "permissionPreset": "full_access",
        "promptTemplateId": prompt_template_id,
        "toolPolicy": tool_policy,
        "metadata": s._challenge_cup_research_team_role_metadata(
            role,
            source_role=source_role,
        ),
        "status": "active",
    }


def _challenge_cup_research_team_agent_matches_expected_config(
    agent: dict[str, Any],
    expected: dict[str, Any],
) -> bool:
    for key in (
        "displayName",
        "llmBindings",
        "primaryMode",
        "roleKey",
        "permissionPreset",
        "promptTemplateId",
        "status",
    ):
        if agent.get(key) != expected.get(key):
            return False
    metadata = agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}
    expected_metadata = (
        expected.get("metadata")
        if isinstance(expected.get("metadata"), dict)
        else {}
    )
    if any(metadata.get(key) != value for key, value in expected_metadata.items()):
        return False
    current_policy = (
        agent.get("toolPolicy")
        if isinstance(agent.get("toolPolicy"), dict)
        else {}
    )
    expected_policy = dict(expected.get("toolPolicy") or {})
    if current_policy:
        expected_policy["policyVersion"] = current_policy.get("policyVersion") or 1
    policy_id = str(
        agent.get("toolPolicyId")
        or current_policy.get("policyId")
        or expected_policy.get("policyId")
        or ""
    ).strip()
    return agent_directory_service.normalize_tool_policy(
        current_policy,
        policy_id,
    ) == agent_directory_service.normalize_tool_policy(
        expected_policy,
        policy_id,
    )


def _challenge_cup_research_team_agent_matches_role_contract(
    agent: dict[str, Any],
    role: dict[str, Any],
) -> bool:
    if not _is_trusted_challenge_cup_research_team_agent(agent):
        return False
    metadata = agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}
    source_role = str(
        metadata.get("challengeCupTeamLegacyRole")
        or metadata.get("challengeCupTeamRole")
        or role.get("role")
        or ""
    ).strip()
    expected = _challenge_cup_research_team_role_agent_expected_config(
        agent,
        role,
        source_role=source_role,
    )
    return _challenge_cup_research_team_agent_matches_expected_config(agent, expected)


def _ensure_challenge_cup_research_team_role_agents() -> list[dict[str, Any]]:
    s = _service()
    project_root = Path(s.PROJECT_ROOT).resolve()
    ensured: list[dict[str, Any]] = []
    try:
        from core.web.services import session_service

        previous_root = session_service.PROJECT_ROOT
        session_service.PROJECT_ROOT = project_root
        try:
            for role in s.CHALLENGE_CUP_RESEARCH_TEAM_ROLES:
                agent = s._ensure_challenge_cup_research_team_role_agent(role, session_service=session_service)
                if agent:
                    ensured.append(agent)
        finally:
            session_service.PROJECT_ROOT = previous_root
    except Exception as exc:
        s._record_system_team_sync_failed("challenge_cup_research_team", exc)
        raise
    return ensured


def _ensure_challenge_cup_research_team_role_agent(role: dict[str, Any], *, session_service: Any) -> dict[str, Any] | None:
    s = _service()
    role_name = str(role.get("role") or "").strip()
    role_key = str(role.get("roleKey") or role_name).strip()
    label = str(role.get("label") or role_name).strip() or role_name
    if not role_name or not role_key:
        return None

    existing_summary = s._find_challenge_cup_research_team_agent(role)
    existing_id = str((existing_summary or {}).get("agentId") or "").strip()
    existing = (
        agent_directory_service.get_agent(existing_id, include_archived=True)
        if existing_id
        else None
    )
    existing_metadata = (
        existing.get("metadata")
        if isinstance((existing or {}).get("metadata"), dict)
        else {}
    )
    source_role = str(
        existing_metadata.get("challengeCupTeamLegacyRole")
        or existing_metadata.get("challengeCupTeamRole")
        or role_name
    ).strip()
    if (
        role_key == agent_directory_service.KNOWLEDGE_STEWARD_ROLE_KEY
        and str((existing or {}).get("agentId") or "").strip() == agent_directory_service.KNOWLEDGE_STEWARD_AGENT_ID
    ):
        existing = None

    if existing and not s._agent_direct_session_available(existing, session_service=session_service):
        session_service.ensure_agent_direct_session(
            agent_id=str(existing.get("agentId") or ""),
            title=label,
            created_by=s.CHALLENGE_CUP_RESEARCH_TEAM_AGENT_CREATED_BY,
            conversation_index_kind=agent_directory_service.CONVERSATION_INDEX_KIND_TEAM_AGENT,
        )
        existing = agent_directory_service.get_agent(str(existing.get("agentId") or ""), include_archived=False)

    if not existing:
        provisional_metadata = s._challenge_cup_research_team_role_metadata(
            role,
            source_role=role_name,
        )
        provisional_metadata.update(
            {
                "challengeCupTeamActiveBinding": False,
                "challengeCupTeamBindingStatus": "provisional",
            }
        )
        existing = agent_directory_service.create_agent_instance(
            display_name=label,
            llm_bindings={
                "dialogue": {
                    "modelId": s.CHALLENGE_CUP_RESEARCH_TEAM_DIALOGUE_MODEL_REF,
                }
            },
            primary_mode="research",
            role_key=role_key,
            created_by=s.CHALLENGE_CUP_RESEARCH_TEAM_AGENT_CREATED_BY,
            metadata=provisional_metadata,
        )
    if not str(existing.get("directSessionId") or "").strip():
        session_service.ensure_agent_direct_session(
            agent_id=str(existing.get("agentId") or ""),
            title=label,
            created_by=s.CHALLENGE_CUP_RESEARCH_TEAM_AGENT_CREATED_BY,
            conversation_index_kind=agent_directory_service.CONVERSATION_INDEX_KIND_TEAM_AGENT,
        )
        existing = agent_directory_service.get_agent(
            str(existing.get("agentId") or ""),
            include_archived=False,
        )
        if not existing:
            raise s.TeamServiceError(
                f"Challenge Cup role Agent was not created for role: {role_name}"
            )

    if str(existing.get("status") or "active").strip() == "archived":
        existing = agent_directory_service.reactivate_agent_instance(
            str(existing.get("agentId") or ""),
            reason="challenge_cup_research_team_required",
            metadata=s._challenge_cup_research_team_role_metadata(
                role,
                source_role=source_role,
            ),
        )

    agent_id = str(existing.get("agentId") or "").strip()
    if not agent_id:
        return None
    expected = _challenge_cup_research_team_role_agent_expected_config(
        existing,
        role,
        source_role=source_role,
    )
    if _challenge_cup_research_team_agent_matches_expected_config(existing, expected):
        return existing
    update_kwargs: dict[str, Any] = {
        "display_name": expected["displayName"],
        "llm_bindings": expected["llmBindings"],
        "primary_mode": expected["primaryMode"],
        "role_key": expected["roleKey"],
        "permission_preset": expected["permissionPreset"],
        "metadata": expected["metadata"],
        "status": expected["status"],
    }
    if expected["promptTemplateId"]:
        update_kwargs["prompt_template_id"] = expected["promptTemplateId"]
    if expected["toolPolicy"] is not None:
        update_kwargs["tool_policy"] = expected["toolPolicy"]
    existing = agent_directory_service.update_agent_instance(agent_id, **update_kwargs)
    return existing


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
    role_spec = role if isinstance(role, dict) else {"role": role}
    normalized_role = str(role_spec.get("role") or "").strip()
    if not normalized_role:
        return None
    aliases = [
        str(alias or "").strip()
        for alias in list(role_spec.get("legacyRoleAliases") or [])
        if str(alias or "").strip()
    ]
    alias_priority = {alias: index for index, alias in enumerate(aliases)}
    candidates: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
    for agent in agent_directory_service.list_agents(include_archived=True, detail="summary"):
        agent_id = str(agent.get("agentId") or "").strip()
        if not agent_id or agent_id == agent_directory_service.KNOWLEDGE_STEWARD_AGENT_ID:
            continue
        if not _is_trusted_challenge_cup_research_team_agent(agent):
            continue
        metadata = agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}
        source_role = str(
            metadata.get("challengeCupTeamRole")
            or metadata.get("challengeCupTeamLegacyRole")
            or ""
        ).strip()
        resolved_owner_id = str(
            (metadata.get("challengeCupTeamAliasResolution") or {}).get("ownerId")
            if isinstance(metadata.get("challengeCupTeamAliasResolution"), dict)
            else ""
        ).strip()
        if (
            source_role != normalized_role
            and source_role not in alias_priority
            and resolved_owner_id != normalized_role
        ):
            continue
        active_binding = metadata.get("challengeCupTeamActiveBinding") is True
        status = str(agent.get("status") or "active").strip() or "active"
        source_priority = -1 if source_role == normalized_role else alias_priority.get(source_role, len(aliases))
        candidates.append(
            (
                (
                    0 if active_binding else 1,
                    0 if status != "archived" else 1,
                    0 if source_role == normalized_role else 1,
                    source_priority,
                    0 if str(agent.get("directSessionId") or "").strip() else 1,
                    str(agent.get("createdAt") or ""),
                    agent_id,
                ),
                agent,
            )
        )
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0])
    return candidates[0][1]


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
    *,
    source_role: str = "",
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
    normalized_source_role = str(source_role or role_name).strip() or role_name
    owner = s.CHALLENGE_CUP_RESEARCH_TEAM_LEGACY_ROLE_OWNERS.get(
        normalized_source_role,
        {},
    )
    alias_resolution = {
        "sourceRole": normalized_source_role,
        "ownerType": str(owner.get("ownerType") or "product_agent"),
        "ownerId": str(owner.get("ownerId") or role_name),
        "aliasPriority": int(owner.get("aliasPriority") if owner else -1),
    }
    return {
        "agentMode": "research",
        "configSurface": "team",
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
        "challengeCupTeamActiveBinding": True,
        "challengeCupTeamBindingStatus": "active",
        "challengeCupTeamLegacyRole": normalized_source_role,
        "challengeCupTeamLegacyRoleAliases": list(role.get("legacyRoleAliases") or []),
        "challengeCupTeamAliasResolution": alias_resolution,
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


def _challenge_cup_research_team_canvas_matches_binding(
    canvas: dict[str, Any],
    agent_ids_by_role: dict[str, str],
) -> bool:
    nodes = list(canvas.get("nodes") or [])
    if len(nodes) != len(agent_ids_by_role) or any(
        not isinstance(node, dict) for node in nodes
    ):
        return False
    seen_roles: set[str] = set()
    seen_agent_ids: set[str] = set()
    for node in nodes:
        role = str(node.get("role") or "").strip()
        agent_id = str(node.get("agentId") or "").strip()
        if (
            role not in agent_ids_by_role
            or role in seen_roles
            or not agent_id
            or agent_id in seen_agent_ids
            or agent_ids_by_role.get(role) != agent_id
        ):
            return False
        seen_roles.add(role)
        seen_agent_ids.add(agent_id)
    return seen_roles == set(agent_ids_by_role)


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


def _challenge_cup_research_team_bound_agent_ids() -> set[str]:
    s = _service()
    agent_ids: set[str] = set()
    with s._TEAM_LOCK:
        state = s._load_index()
        team = s._find_team(state, s.CHALLENGE_CUP_RESEARCH_TEAM_ID)
        if team:
            for member in list(team.get("members") or []):
                if isinstance(member, dict):
                    agent_id = str(member.get("agentId") or "").strip()
                    if agent_id:
                        agent_ids.add(agent_id)
        canvas_path = s._team_canvas_path(s.CHALLENGE_CUP_RESEARCH_TEAM_ID)
        canvas = s._read_json(canvas_path) if canvas_path.exists() else {}
        for node in list(canvas.get("nodes") or []):
            if isinstance(node, dict):
                agent_id = str(node.get("agentId") or "").strip()
                if agent_id:
                    agent_ids.add(agent_id)
    return agent_ids


def _challenge_cup_research_team_alias_resolution(source_role: str) -> dict[str, Any]:
    s = _service()
    normalized_source_role = str(source_role or "").strip()
    owner = s.CHALLENGE_CUP_RESEARCH_TEAM_LEGACY_ROLE_OWNERS.get(
        normalized_source_role,
        {},
    )
    if owner:
        return {
            "sourceRole": normalized_source_role,
            "ownerType": str(owner.get("ownerType") or ""),
            "ownerId": str(owner.get("ownerId") or ""),
            "aliasPriority": int(owner.get("aliasPriority") or 0),
        }
    product_role_ids = {
        str(role.get("role") or "").strip()
        for role in s.CHALLENGE_CUP_RESEARCH_TEAM_ROLES
        if isinstance(role, dict) and str(role.get("role") or "").strip()
    }
    if normalized_source_role in product_role_ids:
        return {
            "sourceRole": normalized_source_role,
            "ownerType": "product_agent",
            "ownerId": normalized_source_role,
            "aliasPriority": -1,
        }
    system_capability_ids = {
        str(item.get("capabilityId") or "").strip()
        for item in list(
            s.CHALLENGE_CUP_RESEARCH_TEAM_ROLE_CONTRACT.get(
                "systemCapabilities"
            )
            or []
        )
        if isinstance(item, dict) and str(item.get("capabilityId") or "").strip()
    }
    if normalized_source_role in system_capability_ids:
        return {
            "sourceRole": normalized_source_role,
            "ownerType": "system_capability",
            "ownerId": normalized_source_role,
            "aliasPriority": -1,
        }
    return {
        "sourceRole": normalized_source_role,
        "ownerType": "unmapped_legacy",
        "ownerId": "",
        "aliasPriority": -1,
    }


def _challenge_cup_research_team_legacy_metadata(
    source_role: str,
) -> dict[str, Any]:
    s = _service()
    return {
        "challengeCupTeamManagedVersion": 2,
        "challengeCupTeamContractVersion": s.CHALLENGE_CUP_RESEARCH_TEAM_ROLE_CONTRACT_VERSION,
        "challengeCupTeamRoleContractFingerprint": s.CHALLENGE_CUP_RESEARCH_TEAM_ROLE_CONTRACT_FINGERPRINT,
        "challengeCupTeamParticipantPolicyVersion": s.CHALLENGE_CUP_RESEARCH_TEAM_PARTICIPANT_POLICY_VERSION,
        "challengeCupTeamActiveBinding": False,
        "challengeCupTeamBindingStatus": "legacy",
        "challengeCupTeamLegacyRole": source_role,
        "challengeCupTeamAliasResolution": s._challenge_cup_research_team_alias_resolution(
            source_role
        ),
    }


def _challenge_cup_research_team_legacy_binding(
    agent: dict[str, Any],
    *,
    source_role: str,
) -> dict[str, Any]:
    s = _service()
    resolution = s._challenge_cup_research_team_alias_resolution(source_role)
    return {
        "agentId": str(agent.get("agentId") or "").strip(),
        "directSessionId": str(agent.get("directSessionId") or "").strip(),
        "sourceRole": source_role,
        "ownerType": resolution["ownerType"],
        "ownerId": resolution["ownerId"],
        "aliasPriority": resolution["aliasPriority"],
        "status": "legacy",
        "activeBinding": False,
    }


def _challenge_cup_research_team_expected_legacy_bindings(
    *,
    active_agent_ids: set[str],
    require_agent_metadata: bool,
) -> list[dict[str, Any]] | None:
    expected: list[dict[str, Any]] = []
    for agent in agent_directory_service.list_agents(
        include_archived=True,
        detail="summary",
    ):
        agent_id = str(agent.get("agentId") or "").strip()
        if (
            not agent_id
            or agent_id in active_agent_ids
            or not _is_trusted_challenge_cup_research_team_agent(agent)
        ):
            continue
        metadata = agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}
        source_role = str(
            metadata.get("challengeCupTeamLegacyRole")
            or metadata.get("challengeCupTeamRole")
            or ""
        ).strip()
        expected_metadata = _challenge_cup_research_team_legacy_metadata(source_role)
        if require_agent_metadata and any(
            metadata.get(key) != value
            for key, value in expected_metadata.items()
        ):
            return None
        expected.append(
            _challenge_cup_research_team_legacy_binding(
                agent,
                source_role=source_role,
            )
        )
    return sorted(
        expected,
        key=lambda item: (
            str(item.get("sourceRole") or ""),
            str(item.get("agentId") or ""),
        ),
    )


def _mark_challenge_cup_research_team_legacy_agents(
    active_agent_ids: set[str],
) -> list[dict[str, Any]]:
    """Mark unselected v1 identities as readable history without archiving them."""

    legacy_bindings: list[dict[str, Any]] = []
    for agent in agent_directory_service.list_agents(
        include_archived=True,
        detail="summary",
    ):
        agent_id = str(agent.get("agentId") or "").strip()
        if not agent_id or agent_id in active_agent_ids:
            continue
        if not _is_trusted_challenge_cup_research_team_agent(agent):
            continue
        metadata = (
            agent.get("metadata")
            if isinstance(agent.get("metadata"), dict)
            else {}
        )
        source_role = str(
            metadata.get("challengeCupTeamLegacyRole")
            or metadata.get("challengeCupTeamRole")
            or ""
        ).strip()
        legacy_metadata = _challenge_cup_research_team_legacy_metadata(source_role)
        current_matches = all(metadata.get(key) == value for key, value in legacy_metadata.items())
        updated = agent
        if not current_matches:
            updated = agent_directory_service.update_agent_instance(
                agent_id,
                metadata=legacy_metadata,
            )
        legacy_bindings.append(
            _challenge_cup_research_team_legacy_binding(
                updated,
                source_role=source_role,
            )
        )
    return sorted(
        legacy_bindings,
        key=lambda item: (
            str(item.get("sourceRole") or ""),
            str(item.get("agentId") or ""),
        ),
    )


def _challenge_cup_research_team_duplicate_agent_ids(expected_agent_ids: set[str]) -> set[str]:
    s = _service()
    duplicates: set[str] = set()
    for agent in agent_directory_service.list_agents(include_archived=True, detail="summary"):
        agent_id = str(agent.get("agentId") or "").strip()
        if not agent_id or agent_id in expected_agent_ids:
            continue
        if agent_id == agent_directory_service.KNOWLEDGE_STEWARD_AGENT_ID:
            continue
        if not _is_trusted_challenge_cup_research_team_agent(agent):
            continue
        metadata = agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}
        if not (
                metadata.get("challengeCupTeamActiveBinding") is False
                and str(metadata.get("challengeCupTeamBindingStatus") or "").strip()
                == "legacy"
                and int(metadata.get("challengeCupTeamContractVersion") or 0)
                == s.CHALLENGE_CUP_RESEARCH_TEAM_ROLE_CONTRACT_VERSION
                and str(
                    metadata.get("challengeCupTeamRoleContractFingerprint") or ""
                ).strip()
                == s.CHALLENGE_CUP_RESEARCH_TEAM_ROLE_CONTRACT_FINGERPRINT
            ):
            duplicates.add(agent_id)
    return duplicates


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
    return s._purge_challenge_cup_research_team_agents(agent_ids, project_root=project_root)


def _purge_challenge_cup_research_team_agents(agent_ids: list[str], *, project_root: Path) -> list[dict[str, Any]]:
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
            result = s._purge_challenge_cup_research_team_agent(agent_id, session_service=session_service)
            if result:
                results.append(result)
    finally:
        if session_service and previous_root is not None:
            session_service.PROJECT_ROOT = previous_root
    return results


def _purge_challenge_cup_research_team_agent(agent_id: str, *, session_service: Any | None) -> dict[str, Any] | None:
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
