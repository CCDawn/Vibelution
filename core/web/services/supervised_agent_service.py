"""Persistent AgentInstance alignment for supervised evolution roles."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core.ui.chat_state import load_chat_state, save_chat_state

from . import agent_directory_service, session_service
from .runtime_scene_service import record_runtime_scene_event


PROJECT_ROOT = Path(__file__).resolve().parents[3]


@dataclass(frozen=True)
class SupervisedAgentRole:
    role: str
    label: str
    profile_id: str


SUPERVISED_AGENT_ROLES: tuple[SupervisedAgentRole, ...] = (
    SupervisedAgentRole("baseline", "监督进化基线 Agent", "supervised_baseline"),
    SupervisedAgentRole("candidate", "监督进化候选 Agent", "supervised_candidate"),
    SupervisedAgentRole("reviewer", "监督进化评审 Agent", "primary"),
    SupervisedAgentRole("auditor", "监督进化审计 Agent", "primary"),
    SupervisedAgentRole("judge", "监督进化裁决 Agent", "primary"),
)


def ensure_supervised_agent_instances() -> list[dict[str, Any]]:
    """Ensure supervised evolution roles are visible as persistent AgentInstances."""

    project_root = Path(PROJECT_ROOT).resolve()
    previous_session_root = session_service.PROJECT_ROOT
    previous_agent_root = agent_directory_service.PROJECT_ROOT
    session_service.PROJECT_ROOT = project_root
    agent_directory_service.PROJECT_ROOT = project_root
    original_active_session_id = _active_session_id(project_root)
    ensured: list[dict[str, Any]] = []
    changed_roles: list[str] = []
    try:
        for role in SUPERVISED_AGENT_ROLES:
            try:
                agent, changed = _ensure_supervised_role(role)
            except Exception as exc:
                _record_supervised_agent_event(
                    "supervised.agent_instance.sync_failed",
                    role=role,
                    level="warning",
                    outcome="failed",
                    fields={"errorType": type(exc).__name__, "message": str(exc)},
                )
                continue
            ensured.append(agent)
            if changed:
                changed_roles.append(role.role)
        if changed_roles:
            _restore_active_session(project_root, original_active_session_id)
            try:
                record_runtime_scene_event(
                    "agent_directory",
                    "agent",
                    "supervised.agent_instance.synced",
                    message="Supervised evolution agent instances synced",
                    level="info",
                    outcome="written",
                    fields={
                        "roleCount": len(SUPERVISED_AGENT_ROLES),
                        "changedRoles": changed_roles,
                        "agentIds": [str(agent.get("agentId") or "") for agent in ensured],
                    },
                    lifecycle=True,
                )
            except Exception:
                pass
    finally:
        session_service.PROJECT_ROOT = previous_session_root
        agent_directory_service.PROJECT_ROOT = previous_agent_root
    return ensured


def supervised_agent_bindings() -> dict[str, dict[str, Any]]:
    """Return run-safe AgentInstance bindings keyed by supervised role."""

    bindings: dict[str, dict[str, Any]] = {}
    for agent in ensure_supervised_agent_instances():
        metadata = agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}
        role = str(metadata.get("supervisedRole") or "").strip()
        if not role:
            continue
        bindings[role] = {
            "agentId": str(agent.get("agentId") or "").strip(),
            "displayName": str(agent.get("displayName") or "").strip(),
            "profileId": str(agent.get("profileId") or "").strip(),
            "directSessionId": str(agent.get("directSessionId") or "").strip(),
            "workspacePath": str(agent.get("workspacePath") or "").strip(),
            "role": role,
            "roleLabel": str(metadata.get("supervisedRoleLabel") or role).strip(),
        }
    return bindings


def _ensure_supervised_role(role: SupervisedAgentRole) -> tuple[dict[str, Any], bool]:
    existing = _find_agent_by_supervised_role(role.role)
    changed = False
    if not existing:
        session_detail = session_service.create_chat_session(
            title=role.label,
            agent_profile_id=role.profile_id,
            created_by="supervised_evolution",
        )
        agent_id = str(session_detail.get("agentId") or "").strip()
        existing = agent_directory_service.get_agent(agent_id) if agent_id else None
        if not existing:
            raise RuntimeError(f"Supervised agent was not created for role: {role.role}")
        changed = True

    metadata = dict(existing.get("metadata") or {})
    expected_metadata = {
        "agentMode": "supervised_evolution",
        "configSurface": "model_config",
        "fixedRole": True,
        "supervisedRole": role.role,
        "supervisedRoleLabel": role.label,
    }
    needs_update = (
        str(existing.get("displayName") or "").strip() != role.label
        or str(existing.get("profileId") or "").strip() != role.profile_id
        or any(metadata.get(key) != value for key, value in expected_metadata.items())
        or str(existing.get("status") or "active").strip() == "archived"
    )
    if needs_update:
        existing = agent_directory_service.update_agent_instance(
            str(existing.get("agentId") or ""),
            display_name=role.label,
            profile_id=role.profile_id,
            metadata=expected_metadata,
            status="active",
        )
        changed = True

    direct_session_id = str(existing.get("directSessionId") or "").strip()
    if direct_session_id:
        try:
            session_service.update_chat_session(
                direct_session_id,
                title=role.label,
                agent_profile_id=role.profile_id,
            )
        except Exception:
            pass
    return existing, changed


def _find_agent_by_supervised_role(role: str) -> dict[str, Any] | None:
    normalized = str(role or "").strip()
    if not normalized:
        return None
    for agent in agent_directory_service.list_agents(include_archived=True):
        metadata = agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}
        if str(metadata.get("supervisedRole") or "").strip() == normalized:
            return agent
    return None


def _active_session_id(project_root: Path) -> str:
    try:
        return str(load_chat_state(project_root).get("active_conversation_id") or "").strip()
    except Exception:
        return ""


def _restore_active_session(project_root: Path, session_id: str) -> None:
    normalized = str(session_id or "").strip()
    if not normalized:
        return
    try:
        state = load_chat_state(project_root)
        conversations = state.get("conversations") if isinstance(state.get("conversations"), list) else []
        if any(str(item.get("conversation_id") or "").strip() == normalized for item in conversations if isinstance(item, dict)):
            state["active_conversation_id"] = normalized
            save_chat_state(project_root, state)
    except Exception:
        return


def _record_supervised_agent_event(
    event_code: str,
    *,
    role: SupervisedAgentRole,
    level: str,
    outcome: str,
    fields: dict[str, Any] | None = None,
) -> None:
    try:
        record_runtime_scene_event(
            "agent_directory",
            "agent",
            event_code,
            message=event_code,
            level=level,
            outcome=outcome,
            fields={
                "supervisedRole": role.role,
                "supervisedRoleLabel": role.label,
                "profileId": role.profile_id,
                **dict(fields or {}),
            },
            lifecycle=True,
        )
    except Exception:
        return
