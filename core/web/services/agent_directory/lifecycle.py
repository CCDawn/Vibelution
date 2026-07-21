"""Agent archive / purge / reset lifecycle helpers.

Claim scope: archive/purge/reset entrypoints and their private helpers.
Serializer wrappers stay on the facade (see session agent_sessions pattern).

Late-bound facade keeps monkeypatches stable.
"""

from __future__ import annotations

import shutil
from typing import Any


def _service():
    from core.web.services import agent_directory_service

    return agent_directory_service


def _agent_archive_protected(agent: dict[str, Any]) -> bool:
    s = _service()
    metadata = agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}
    if bool(metadata.get("protected")) or bool(metadata.get("fixedRole")):
        return True
    system_role = str(metadata.get("systemRole") or "").strip()
    research_org_role = str(metadata.get("researchOrgRole") or "").strip()
    system_owned_role = any(
        str(metadata.get(key) or "").strip()
        for key in ("selfEvolutionRole", "supervisedRole", "aiSearchRole")
    )
    if system_owned_role or system_role:
        return True
    return research_org_role in {"ceo", "organization_advisor", "capability_steward", s.KNOWLEDGE_STEWARD_ROLE_KEY}


def _archive_retired_self_evolution_agent(agent: dict[str, Any], retired_role: str) -> bool:
    s = _service()
    changed = False
    now = s.utc_now_iso()
    if str(agent.get("status") or "active").strip() != "archived":
        agent["status"] = "archived"
        changed = True
    metadata = dict(agent.get("metadata") or {})
    updates = {
        "retiredRole": s._normalize_role_key(retired_role),
        "retiredReason": "self_evolution_role_retired",
    }
    if not str(metadata.get("retiredAt") or "").strip():
        updates["retiredAt"] = now
    for key, value in updates.items():
        if metadata.get(key) != value:
            metadata[key] = value
            changed = True
    if agent.get("metadata") != metadata:
        agent["metadata"] = metadata
        changed = True
    if changed:
        agent["updatedAt"] = now
    return changed


def _delete_purged_agent_workspace(agent: dict[str, Any]) -> dict[str, Any]:
    s = _service()
    agent_id = str(agent.get("agentId") or "").strip()
    workspace_path = str(agent.get("workspacePath") or s._agent_workspace_relative_path(agent_id)).strip()
    if not workspace_path:
        return {"deleted": False, "deletedPaths": [], "skippedPaths": []}
    try:
        workspace = s._lexical_project_path(workspace_path)
        agents_root = s._lexical_project_path("workspace/agents")
        expected_private = s._lexical_project_path(
            s._agent_workspace_relative_path(agent_id)
        )
    except Exception:
        return {"deleted": False, "deletedPaths": [], "skippedPaths": [workspace_path]}
    if workspace != expected_private:
        return {"deleted": False, "deletedPaths": [], "skippedPaths": [workspace_path]}
    try:
        if not workspace.is_relative_to(agents_root):
            return {"deleted": False, "deletedPaths": [], "skippedPaths": [workspace_path]}
    except ValueError:
        return {"deleted": False, "deletedPaths": [], "skippedPaths": [workspace_path]}
    if s._path_has_reparse_component(workspace, stop_at=agents_root):
        return {
            "deleted": False,
            "deletedPaths": [],
            "skippedPaths": [
                f"{workspace_path} (symlink/junction/reparse point)"
            ],
        }
    if not workspace.exists():
        return {"deleted": False, "deletedPaths": [], "skippedPaths": []}
    relative_path = s._agent_workspace_relative_path(agent_id)
    try:
        if s._path_has_reparse_component(workspace, stop_at=agents_root):
            raise s.AgentDirectoryError(
                "Agent workspace path changed to a symlink, junction, or reparse point."
            )
        shutil.rmtree(workspace)
    except Exception as exc:
        return {"deleted": False, "deletedPaths": [], "skippedPaths": [f"{relative_path} ({type(exc).__name__})"]}
    return {"deleted": True, "deletedPaths": [relative_path], "skippedPaths": []}


def _record_agent_purged_event(agent: dict[str, Any], result: dict[str, Any]) -> None:
    s = _service()
    try:
        s.record_runtime_scene_event(
            "agent_directory",
            "agent",
            "agent.purged",
            message="Archived Agent was permanently deleted.",
            level="warning",
            outcome="deleted",
            fields={
                "agentId": str(agent.get("agentId") or "").strip(),
                "agentCode": s._normalize_agent_code(agent.get("agentCode")),
                "directSessionId": str(agent.get("directSessionId") or "").strip(),
                "workspaceDeleted": bool(result.get("workspaceDeleted")),
                "deletedPaths": list(result.get("deletedPaths") or []),
                "skippedPaths": list(result.get("skippedPaths") or []),
                "removedToolPolicy": bool(result.get("removedToolPolicy")),
                "removedMemoryPolicy": bool(result.get("removedMemoryPolicy")),
                "source": "AgentDirectory",
            },
            lifecycle=True,
        )
    except Exception:
        return


def _record_agent_reset_event(agent: dict[str, Any], summary: dict[str, Any]) -> None:
    s = _service()
    try:
        s.record_runtime_scene_event(
            "agent_directory",
            "reset",
            "agent.reset.completed",
            message="Agent debug reset completed.",
            level="info",
            outcome="reset",
            fields={
                "agentId": str(agent.get("agentId") or summary.get("agentId") or "").strip(),
                "agentCode": s._normalize_agent_code(agent.get("agentCode")),
                "directSessionId": str(agent.get("directSessionId") or "").strip(),
                "clearedRuntimeState": bool(summary.get("clearedRuntimeState")),
                "resetDirectSession": bool(summary.get("resetDirectSession")),
                "previousDirectSessionId": str(summary.get("previousDirectSessionId") or "").strip(),
                "replacementDirectSessionId": str(summary.get("replacementDirectSessionId") or "").strip(),
                "deletedPathCount": len(list(summary.get("deletedPaths") or [])),
                "skippedPathCount": len(list(summary.get("skippedPaths") or [])),
                "resetPersonaProfile": bool(summary.get("resetPersonaProfile")),
                "resetTaskProfile": bool(summary.get("resetTaskProfile")),
                "resetToolPolicy": bool(summary.get("resetToolPolicy")),
                "resetMemoryPolicy": bool(summary.get("resetMemoryPolicy")),
                "resetRuntimePolicy": bool(summary.get("resetRuntimePolicy")),
                "preserved": list(summary.get("preserved") or []),
                "source": "AgentDirectory",
            },
            lifecycle=True,
        )
    except Exception:
        return


def _reset_agent_direct_session(agent: dict[str, Any]) -> dict[str, Any]:
    s = _service()
    session_id = str(agent.get("directSessionId") or "").strip()
    if not session_id:
        return {"resetDirectSession": False, "replacementDirectSessionId": "", "skippedPaths": []}
    try:
        from core.web.services import session_service

        session_detail = session_service.get_session_detail(session_id)
        agent_id = str(agent.get("agentId") or "").strip()
        session_agent_id = str(session_detail.get("agentId") or "").strip()
        parent_session_id = str(session_detail.get("parentSessionId") or "").strip()
        root_session_id = str(session_detail.get("rootSessionId") or "").strip()
        if session_agent_id != agent_id:
            raise s.AgentDirectoryError("Requested direct session is not owned by this Agent.")
        if parent_session_id or (root_session_id and root_session_id != session_id):
            raise s.AgentDirectoryError("Only an Agent root direct session can be reset.")

        result = session_service.reset_agent_direct_session_lightweight(
            session_id,
            agent_id=agent_id,
            title=str(agent.get("displayName") or "").strip(),
        )
    except Exception as exc:
        raise s.AgentDirectoryError(f"Agent direct session reset failed: {type(exc).__name__}: {exc}") from exc
    replacement_direct_session_id = str(result.get("replacementDirectSessionId") or result.get("nextActiveSessionId") or "").strip()
    return {
        "resetDirectSession": True,
        "replacementDirectSessionId": replacement_direct_session_id,
        "skippedPaths": [],
    }


def agent_archive_protected(agent: dict[str, Any]) -> bool:
    s = _service()
    return s._agent_archive_protected(agent)


def archive_agent_instance(agent_id: str, *, repair_mode_bindings: bool = True) -> dict[str, Any]:
    s = _service()
    with s._STATE_LOCK:
        state = s.load_state()
        agent = s._find_agent(state, agent_id)
        if agent is None:
            raise s.AgentNotFoundError(f"Agent not found: {agent_id}")
        if s._agent_archive_protected(agent):
            raise s.AgentDirectoryError("Protected core Agent cannot be archived.")
        agent["status"] = "archived"
        agent["updatedAt"] = s.utc_now_iso()
        s.save_state(state)
    s._record_agent_event("agent.archived", agent, lifecycle=True)
    if repair_mode_bindings:
        from core.web.services.agent_mode_binding_service import remove_agent_from_mode_bindings

        remove_agent_from_mode_bindings(agent_id)
    return s._agent_to_api(agent)


def ensure_agent_archive_allowed(agent_id: str) -> dict[str, Any]:
    """Validate archival before callers mutate external Agent references."""
    s = _service()

    with s._STATE_LOCK:
        state = s.load_state()
        agent = s._find_agent(state, agent_id)
        if agent is None:
            raise s.AgentNotFoundError(f"Agent not found: {agent_id}")
        if s._agent_archive_protected(agent):
            raise s.AgentDirectoryError("Protected core Agent cannot be archived.")
        return s._agent_to_api(agent)


def ensure_agent_purge_allowed(agent_id: str) -> dict[str, Any]:
    """Validate permanent deletion before callers mutate external Agent references."""
    s = _service()

    normalized_agent_id = str(agent_id or "").strip()
    if not normalized_agent_id:
        raise s.AgentDirectoryError("Agent id is required.")
    with s._STATE_LOCK:
        state = s.load_state()
        agent = s._find_agent(state, normalized_agent_id)
        if agent is None:
            raise s.AgentNotFoundError(f"Agent not found: {normalized_agent_id}")
        if str(agent.get("status") or "active").strip() != "archived":
            raise s.AgentDirectoryError("Only archived Agents can be permanently deleted.")
        if s._agent_archive_protected(agent):
            raise s.AgentDirectoryError("Protected core Agent cannot be purged.")
        return s._agent_to_api(agent)


def ensure_agent_purge_workspace_deletable(agent: dict[str, Any]) -> dict[str, Any]:
    """Validate the purge workspace boundary before callers mutate external references."""
    s = _service()

    agent_id = str(agent.get("agentId") or "").strip()
    workspace_path = str(agent.get("workspacePath") or s._agent_workspace_relative_path(agent_id)).strip()
    if not agent_id or not workspace_path:
        return {"deletable": True, "workspacePath": workspace_path, "reason": "no_workspace_path"}
    try:
        workspace = s._lexical_project_path(workspace_path)
        agents_root = s._lexical_project_path("workspace/agents")
        expected_private = s._lexical_project_path(
            s._agent_workspace_relative_path(agent_id)
        )
    except Exception as exc:
        raise s.AgentDirectoryError(f"Agent workspace path could not be resolved: {type(exc).__name__}") from exc
    if workspace != expected_private:
        raise s.AgentDirectoryError(
            "Agent workspace path is not the expected private workspace: "
            + workspace_path
        )
    try:
        if not workspace.is_relative_to(agents_root):
            raise s.AgentDirectoryError(
                f"Agent workspace path is outside the agents root: {workspace_path}"
            )
    except ValueError as exc:
        raise s.AgentDirectoryError(
            f"Agent workspace path is outside the agents root: {workspace_path}"
        ) from exc
    if s._path_has_reparse_component(workspace, stop_at=agents_root):
        raise s.AgentDirectoryError(
            "Agent workspace path contains a symlink, junction, or reparse point."
        )
    if not workspace.exists():
        return {
            "deletable": True,
            "workspacePath": s._agent_workspace_relative_path(agent_id),
            "reason": "workspace_absent",
        }
    if not workspace.is_dir():
        raise s.AgentDirectoryError(
            f"Agent workspace path is not a directory: {workspace_path}"
        )
    return {
        "deletable": True,
        "workspacePath": s._agent_workspace_relative_path(agent_id),
        "reason": "workspace_present",
    }


def purge_archived_agent_instance(
    agent_id: str,
    *,
    allow_active: bool = False,
    _allow_protected_system_repair: bool = False,
) -> dict[str, Any]:
    """Physically remove an AgentInstance and its private workspace."""
    s = _service()

    normalized_agent_id = str(agent_id or "").strip()
    if not normalized_agent_id:
        raise s.AgentDirectoryError("Agent id is required.")
    with s._STATE_LOCK:
        state = s.load_state()
        agent = s._find_agent(state, normalized_agent_id)
        if agent is None:
            raise s.AgentNotFoundError(f"Agent not found: {normalized_agent_id}")
        previous_status = str(agent.get("status") or "active").strip() or "active"
        if previous_status != "archived" and not allow_active:
            raise s.AgentDirectoryError("Only archived Agents can be permanently deleted.")
        if s._agent_archive_protected(agent) and not _allow_protected_system_repair:
            raise s.AgentDirectoryError("Protected core Agent cannot be purged.")
        agent_snapshot = dict(agent)
        agent_snapshot["status"] = previous_status
        tool_policy_id = str(agent.get("toolPolicyId") or "").strip()
        memory_policy_id = str(agent.get("memoryPolicyId") or "").strip()

    workspace_result = s._delete_purged_agent_workspace(agent_snapshot)
    if list(workspace_result.get("skippedPaths") or []):
        skipped = ", ".join(str(item) for item in list(workspace_result.get("skippedPaths") or [])[:3])
        raise s.AgentDirectoryError(f"Agent workspace could not be fully deleted: {skipped}")

    with s._STATE_LOCK:
        state = s.load_state()
        agent = s._find_agent(state, normalized_agent_id)
        if agent is None:
            raise s.AgentNotFoundError(f"Agent not found: {normalized_agent_id}")
        current_status = str(agent.get("status") or "active").strip() or "active"
        if current_status != "archived" and not allow_active:
            raise s.AgentDirectoryError("Only archived Agents can be permanently deleted.")
        if s._agent_archive_protected(agent) and not _allow_protected_system_repair:
            raise s.AgentDirectoryError("Protected core Agent cannot be purged.")
        agents = [
            item
            for item in state.get("agents") or []
            if not (
                isinstance(item, dict)
                and str(item.get("agentId") or "").strip() == normalized_agent_id
            )
        ]
        state["agents"] = agents
        removed_tool_policy = False
        removed_memory_policy = False
        if tool_policy_id and tool_policy_id != s.DEFAULT_TOOL_POLICY_ID and s._count_policy_refs(agents, "toolPolicyId", tool_policy_id) == 0:
            policies = s._tool_policies(state)
            removed_tool_policy = policies.pop(tool_policy_id, None) is not None
            state["toolPolicies"] = policies
        if memory_policy_id and s._count_policy_refs(agents, "memoryPolicyId", memory_policy_id) == 0:
            policies = s._memory_policies(state)
            removed_memory_policy = policies.pop(memory_policy_id, None) is not None
            state["memoryPolicies"] = policies
        s.save_state(state)

    result = {
        "agentId": normalized_agent_id,
        "status": "purged",
        "previousStatus": str(agent_snapshot.get("status") or "").strip(),
        "deleted": True,
        "workspaceDeleted": bool(workspace_result.get("deleted")),
        "deletedPaths": list(workspace_result.get("deletedPaths") or []),
        "skippedPaths": list(workspace_result.get("skippedPaths") or []),
        "removedToolPolicy": removed_tool_policy,
        "removedMemoryPolicy": removed_memory_policy,
        "toolPolicyId": tool_policy_id,
        "memoryPolicyId": memory_policy_id,
    }
    s._record_agent_purged_event(agent_snapshot, result)
    return result


def purge_system_team_agent_instance(
    agent_id: str,
    *,
    expected_created_by: str,
    expected_team_metadata_key: str,
    expected_team_id: str,
) -> dict[str, Any]:
    """Purge a stale system-team Agent after validating its ownership boundary."""
    s = _service()

    normalized_agent_id = str(agent_id or "").strip()
    normalized_created_by = str(expected_created_by or "").strip()
    normalized_team_key = str(expected_team_metadata_key or "").strip()
    normalized_team_id = str(expected_team_id or "").strip()
    if not normalized_agent_id or not normalized_created_by or not normalized_team_key or not normalized_team_id:
        raise s.AgentDirectoryError("System team purge requires agent id, owner, team key, and team id.")
    if normalized_agent_id == s.KNOWLEDGE_STEWARD_AGENT_ID:
        raise s.AgentDirectoryError("Knowledge steward Agent cannot be purged by system team repair.")

    with s._STATE_LOCK:
        state = s.load_state()
        agent = s._find_agent(state, normalized_agent_id)
        if agent is None:
            raise s.AgentNotFoundError(f"Agent not found: {normalized_agent_id}")
        metadata = agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}
        if bool(metadata.get("protected")):
            raise s.AgentDirectoryError("Protected core Agent cannot be purged.")
        if str(agent.get("createdBy") or "").strip() != normalized_created_by:
            raise s.AgentDirectoryError("System team purge owner mismatch.")
        if str(metadata.get(normalized_team_key) or "").strip() != normalized_team_id:
            raise s.AgentDirectoryError("System team purge team mismatch.")
        if str(metadata.get("conversationIndexKind") or "").strip() != s.CONVERSATION_INDEX_KIND_TEAM_AGENT:
            raise s.AgentDirectoryError("System team purge requires a team Agent.")
        if str(metadata.get("conversationIndexVisibility") or "").strip() != s.CONVERSATION_INDEX_VISIBILITY_TEAM_PRIVATE:
            raise s.AgentDirectoryError("System team purge requires a team-private Agent.")

    return s.purge_archived_agent_instance(
        normalized_agent_id,
        allow_active=True,
        _allow_protected_system_repair=True,
    )


def reset_agent_instance(
    agent_id: str,
    *,
    clear_runtime_state: bool = True,
    reset_direct_session: bool = True,
    direct_session_id: str = "",
    reset_persona_profile: bool = False,
    reset_task_profile: bool = False,
    reset_tool_policy: bool = False,
    reset_memory_policy: bool = False,
    reset_runtime_policy: bool = False,
) -> dict[str, Any]:
    """Reset a single Agent for debugging without changing team, room, or mode membership."""
    s = _service()

    normalized_agent_id = str(agent_id or "").strip()
    normalized_direct_session_id = str(direct_session_id or "").strip()
    if not normalized_agent_id:
        raise s.AgentDirectoryError("Agent id is required.")

    reset_summary: dict[str, Any] = {
        "agentId": normalized_agent_id,
        "clearedRuntimeState": False,
        "resetDirectSession": False,
        "previousDirectSessionId": "",
        "replacementDirectSessionId": "",
        "deletedPaths": [],
        "skippedPaths": [],
        "resetPersonaProfile": False,
        "resetTaskProfile": False,
        "resetToolPolicy": False,
        "resetMemoryPolicy": False,
        "resetRuntimePolicy": False,
        "preserved": ["agent_identity", "team_membership", "chat_room_membership", "mode_membership"],
    }
    updated_tool_policy: dict[str, Any] | None = None
    updated_memory_policy: dict[str, Any] | None = None
    updated_delegation_policy: dict[str, Any] | None = None
    updated_supervision_policy: dict[str, Any] | None = None
    updated_persona_profile: dict[str, Any] | None = None
    updated_task_profile: dict[str, Any] | None = None
    with s._STATE_LOCK:
        state = s.load_state()
        agent = s._find_agent(state, normalized_agent_id)
        if agent is None:
            raise s.AgentNotFoundError(f"Agent not found: {normalized_agent_id}")
        if str(agent.get("status") or "active").strip() == "archived":
            raise s.AgentDirectoryError("Archived Agent cannot be reset. Restore or purge archived data instead.")
        agent_snapshot = dict(agent)
        stored_direct_session_id = str(agent_snapshot.get("directSessionId") or "").strip()
        if normalized_direct_session_id:
            if stored_direct_session_id and stored_direct_session_id != normalized_direct_session_id:
                raise s.AgentDirectoryError(
                    "Requested direct session does not match the Agent's active direct session."
                )
            agent_snapshot["directSessionId"] = normalized_direct_session_id
        reset_summary["previousDirectSessionId"] = str(agent_snapshot.get("directSessionId") or "").strip()
        now = s.utc_now_iso()
        profileless_session_agent = s._is_profileless_session_agent(agent)
        if reset_persona_profile:
            metadata = dict(agent.get("metadata") or {})
            if profileless_session_agent:
                metadata.pop("personaProfile", None)
            else:
                updated_persona_profile = s.normalize_persona_profile({})
                metadata["personaProfile"] = updated_persona_profile
                metadata["personaProfileDefaultsDisabled"] = True
                reset_summary["resetPersonaProfile"] = True
            agent["metadata"] = metadata
        if reset_task_profile:
            metadata = dict(agent.get("metadata") or {})
            if profileless_session_agent:
                metadata.pop("taskProfile", None)
            else:
                updated_task_profile = s.normalize_task_profile({})
                metadata["taskProfile"] = updated_task_profile
                metadata["taskProfileDefaultsDisabled"] = True
                reset_summary["resetTaskProfile"] = True
            agent["metadata"] = metadata
        if reset_tool_policy:
            previous_policy_id = str(agent.get("toolPolicyId") or s.DEFAULT_TOOL_POLICY_ID).strip() or s.DEFAULT_TOOL_POLICY_ID
            policy_id = s._default_tool_policy_id_for_agent(normalized_agent_id, str(agent.get("primaryMode") or ""))
            agent["toolPolicyId"] = policy_id
            policies = s._tool_policies(state)
            if previous_policy_id != s.DEFAULT_TOOL_POLICY_ID and s._count_policy_refs(state.get("agents") or [], "toolPolicyId", previous_policy_id) == 0:
                policies.pop(previous_policy_id, None)
            policies[policy_id] = s._default_tool_policy_for_agent(
                policy_id,
                str(agent.get("primaryMode") or ""),
                role_key=str(agent.get("roleKey") or ""),
            )
            state["toolPolicies"] = policies
            updated_tool_policy = s.normalize_tool_policy(policies.get(policy_id) or s.default_tool_policy(policy_id), policy_id)
            reset_summary["resetToolPolicy"] = True
        if reset_memory_policy:
            policy_id = str(agent.get("memoryPolicyId") or "").strip() or f"memory-{normalized_agent_id}"
            workspace_path = s._agent_workspace_relative_path(normalized_agent_id)
            agent["workspacePath"] = workspace_path
            agent["memoryPolicyId"] = policy_id
            s._ensure_agent_workspace(workspace_path)
            policies = s._memory_policies(state)
            updated_memory_policy = s.default_memory_policy(policy_id, workspace_path)
            policies[policy_id] = updated_memory_policy
            state["memoryPolicies"] = policies
            reset_summary["resetMemoryPolicy"] = True
        if reset_runtime_policy:
            metadata = dict(agent.get("metadata") or {})
            updated_delegation_policy = s.normalize_delegation_policy({})
            updated_supervision_policy = s.normalize_supervision_policy({})
            metadata["delegationPolicy"] = updated_delegation_policy
            metadata["supervisionPolicy"] = updated_supervision_policy
            agent["metadata"] = metadata
            reset_summary["resetRuntimePolicy"] = True
        agent["updatedAt"] = now
        s.save_state(state)

    if clear_runtime_state:
        runtime_cleanup = s._clear_agent_runtime_state(agent_snapshot)
        reset_summary["clearedRuntimeState"] = True
        reset_summary["deletedPaths"] = list(runtime_cleanup.get("deletedPaths") or [])
        reset_summary["skippedPaths"] = list(runtime_cleanup.get("skippedPaths") or [])
    if reset_direct_session:
        direct_session_cleanup = s._reset_agent_direct_session(agent_snapshot)
        reset_summary["resetDirectSession"] = bool(direct_session_cleanup.get("resetDirectSession"))
        reset_summary["replacementDirectSessionId"] = str(direct_session_cleanup.get("replacementDirectSessionId") or "").strip()
        reset_summary["skippedPaths"].extend(list(direct_session_cleanup.get("skippedPaths") or []))
        if reset_summary["resetDirectSession"] and reset_summary["replacementDirectSessionId"]:
            with s._STATE_LOCK:
                state = s.load_state()
                agent = s._find_agent(state, normalized_agent_id)
                if agent is not None:
                    metadata = dict(agent.get("metadata") or {})
                    metadata["directSessionVisibility"] = s.SESSION_AGENT_VISIBILITY_ACTIVE
                    agent["metadata"] = metadata
                    agent["updatedAt"] = s.utc_now_iso()
                    s.save_state(state)

    updated_agent = s.get_agent(normalized_agent_id)
    s._record_agent_reset_event(updated_agent or agent_snapshot, reset_summary)
    if updated_tool_policy is not None and updated_agent:
        s._record_agent_tool_policy_event(updated_agent, updated_tool_policy)
    if updated_memory_policy is not None and updated_agent:
        s._record_agent_memory_policy_event(updated_agent, updated_memory_policy)
    if updated_delegation_policy is not None and updated_agent:
        s._record_agent_delegation_policy_event(updated_agent, updated_delegation_policy)
    if updated_supervision_policy is not None and updated_agent:
        s._record_agent_supervision_policy_event(updated_agent, updated_supervision_policy)
    if updated_persona_profile is not None and updated_agent:
        s._record_agent_persona_profile_event(updated_agent, updated_persona_profile)
    if updated_task_profile is not None and updated_agent:
        s._record_agent_task_profile_event(updated_agent, updated_task_profile)
    return {
        "agent": updated_agent,
        "resetSummary": reset_summary,
    }
