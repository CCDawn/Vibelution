"""Persistent AgentInstance alignment for supervised evolution roles."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core.ui.chat_state import load_chat_state, save_chat_state

from . import agent_directory_service, session_service
from . import agent_mode_binding_service
from .runtime_scene_service import record_runtime_scene_event


PROJECT_ROOT = Path(__file__).resolve().parents[3]


class SupervisedAgentBindingError(ValueError):
    """Raised when a supervised fixed role cannot resolve its bound Agent."""


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
    previous_binding_root = agent_mode_binding_service.PROJECT_ROOT
    session_service.PROJECT_ROOT = project_root
    agent_directory_service.PROJECT_ROOT = project_root
    agent_mode_binding_service.PROJECT_ROOT = project_root
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
        _sync_supervised_mode_binding(ensured, preserve_existing_slots=True)
    finally:
        session_service.PROJECT_ROOT = previous_session_root
        agent_directory_service.PROJECT_ROOT = previous_agent_root
        agent_mode_binding_service.PROJECT_ROOT = previous_binding_root
    return ensured


def supervised_agent_bindings() -> dict[str, dict[str, Any]]:
    """Return run-safe AgentInstance bindings keyed by supervised role."""

    raw_slots = _raw_supervised_mode_slots()
    ensure_supervised_agent_instances()
    bindings: dict[str, dict[str, Any]] = {}
    mode_payload = agent_mode_binding_service.get_mode_bindings_payload()
    supervised_mode = (mode_payload.get("modes") or {}).get("supervised_evolution")
    slots = supervised_mode.get("slots") if isinstance(supervised_mode, dict) else {}
    for role in [item.role for item in SUPERVISED_AGENT_ROLES]:
        raw_agent_id = str(raw_slots.get(role) or "").strip()
        if raw_agent_id and not agent_directory_service.get_agent(raw_agent_id, include_archived=False):
            _record_supervised_binding_failure(role, agent_id=raw_agent_id, reason="missing_or_archived_slot_agent")
            raise SupervisedAgentBindingError(
                f"Supervised role slot points to an archived or missing Agent: {role} ({raw_agent_id})"
            )
        stale_warning = _supervised_slot_warning(mode_payload, role)
        if stale_warning:
            agent_id = str(stale_warning.get("agentId") or "").strip()
            _record_supervised_binding_failure(role, agent_id=agent_id, reason="missing_or_archived_slot_agent")
            raise SupervisedAgentBindingError(
                f"Supervised role slot points to an archived or missing Agent: {role} ({agent_id or 'unknown'})"
            )
        agent_id = str((slots or {}).get(role) or "").strip()
        if not agent_id:
            _record_supervised_binding_failure(role, agent_id="", reason="missing_slot_agent")
            raise SupervisedAgentBindingError(f"Supervised role slot is not configured: {role}")
        agent = agent_directory_service.get_agent(agent_id, include_archived=False)
        if not agent:
            _record_supervised_binding_failure(role, agent_id=agent_id, reason="missing_or_archived_slot_agent")
            raise SupervisedAgentBindingError(f"Supervised role slot points to an archived or missing Agent: {role} ({agent_id})")
        metadata = agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}
        bindings[role] = {
            "agentId": str(agent.get("agentId") or "").strip(),
            "agentCode": str(agent.get("agentCode") or "").strip(),
            "displayName": str(agent.get("displayName") or "").strip(),
            "primaryMode": str(agent.get("primaryMode") or "").strip(),
            "roleKey": str(agent.get("roleKey") or role).strip() or role,
            "profileId": str(agent.get("profileId") or "").strip(),
            "promptTemplateId": str(agent.get("promptTemplateId") or "").strip(),
            "directSessionId": str(agent.get("directSessionId") or "").strip(),
            "workspacePath": str(agent.get("workspacePath") or "").strip(),
            "toolPolicyId": str(agent.get("toolPolicyId") or "").strip(),
            "memoryPolicyId": str(agent.get("memoryPolicyId") or "").strip(),
            "role": role,
            "roleLabel": str(metadata.get("supervisedRoleLabel") or role).strip(),
        }
    return bindings


def _raw_supervised_mode_slots() -> dict[str, str]:
    path = agent_mode_binding_service.mode_binding_path()
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    for item in payload.get("bindings") or []:
        if not isinstance(item, dict):
            continue
        if str(item.get("mode") or "").strip() != "supervised_evolution":
            continue
        slots = item.get("slots") if isinstance(item.get("slots"), dict) else {}
        return {str(key): str(value or "").strip() for key, value in slots.items()}
    return {}


def _supervised_slot_warning(mode_payload: dict[str, Any], role: str) -> dict[str, str] | None:
    expected_field = f"slots.{role}"
    for warning in mode_payload.get("repairWarnings") or []:
        if not isinstance(warning, dict):
            continue
        if str(warning.get("mode") or "").strip() != "supervised_evolution":
            continue
        if str(warning.get("field") or "").strip() == expected_field:
            return {str(key): str(value or "") for key, value in warning.items()}
    return None


def _record_supervised_binding_failure(role: str, *, agent_id: str, reason: str) -> None:
    try:
        record_runtime_scene_event(
            "agent_runtime",
            "supervised_evolution",
            "agent_runtime.resolve_failed",
            message="Supervised evolution role Agent resolution failed",
            level="error",
            outcome="failed",
            fields={
                "mode": "supervised_evolution",
                "slot": str(role or "").strip(),
                "roleKey": str(role or "").strip(),
                "agentId": str(agent_id or "").strip(),
                "source": "ModeBinding.slots",
                "reason": str(reason or "").strip(),
            },
            lifecycle=True,
        )
    except Exception:
        return
def _sync_supervised_mode_binding(agents: list[dict[str, Any]], *, preserve_existing_slots: bool = False) -> None:
    active_agent_ids = [str(agent.get("agentId") or "").strip() for agent in agents if str(agent.get("agentId") or "").strip()]
    slots = {}
    if preserve_existing_slots:
        try:
            payload = agent_mode_binding_service.get_mode_bindings_payload()
            existing = ((payload.get("modes") or {}).get("supervised_evolution") or {}).get("slots")
            if isinstance(existing, dict):
                slots.update({str(key): str(value or "").strip() for key, value in existing.items()})
        except Exception:
            slots = {}
    for agent in agents:
        metadata = agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}
        role = str(metadata.get("supervisedRole") or agent.get("roleKey") or "").strip()
        agent_id = str(agent.get("agentId") or "").strip()
        if role and agent_id and not slots.get(role):
            slots[role] = agent_id
    if not active_agent_ids:
        return
    try:
        agent_mode_binding_service.update_mode_binding(
            "supervised_evolution",
            default_agent_id=active_agent_ids[0],
            available_agent_ids=active_agent_ids,
            slots=slots,
        )
    except Exception:
        return


def _ensure_supervised_role(role: SupervisedAgentRole) -> tuple[dict[str, Any], bool]:
    existing = _find_agent_by_supervised_role(role.role)
    changed = False
    if not existing:
        session_detail = session_service.create_chat_session(
            title=role.label,
            profile_id=role.profile_id,
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
        "functionalDisplayName": role.label,
    }
    needs_update = (
        str(existing.get("profileId") or "").strip() != role.profile_id
        or any(metadata.get(key) != value for key, value in expected_metadata.items())
        or str(existing.get("status") or "active").strip() == "archived"
    )
    if needs_update:
        if str(existing.get("status") or "active").strip() == "archived":
            existing = agent_directory_service.reactivate_agent_instance(
                str(existing.get("agentId") or ""),
                reason="supervised_fixed_role_bootstrap",
                metadata={"fixedRole": True, "supervisedRole": role.role},
            )
        existing = agent_directory_service.update_agent_instance(
            str(existing.get("agentId") or ""),
            profile_id=role.profile_id,
            primary_mode="supervised_evolution",
            role_key=role.role,
            prompt_template_id=f"prompt-supervised-{role.role}",
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
                profile_id=role.profile_id,
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
