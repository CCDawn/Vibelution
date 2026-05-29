"""Persistent AgentInstance registry for chat-facing agents."""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import threading
import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable

from core.chat.chat_task_types import trim_lines

from .runtime_scene_service import record_runtime_scene_event


PROJECT_ROOT = Path(__file__).resolve().parents[3]
AGENT_REGISTRY_VERSION = 1
DEFAULT_AGENT_KIND = "persistent"
DEFAULT_TOOL_POLICY_ID = "default"
DEFAULT_MEMORY_POLICY_ID = "private"
DEFAULT_AGENT_PRIMARY_MODE = "chat"
AGENT_CODE_PREFIX = "A"
AGENT_SHARED_WORKSPACE_PATH = "workspace/shared"
AGENT_WORKSPACE_SUBDIRS = (
    "conversation",
    "memory",
    "events",
    "tmp",
    "logs",
    "artifacts",
    "scratch",
    "notes",
    "inbox",
    "outbox",
    "runs",
)
AGENT_TERRITORY_WRITE_SCOPES = ("private",)
AGENT_TERRITORY_READ_SCOPES = ("private", "shared")
TOOL_POLICY_WORKSPACE_SCOPES = ("private", "shared")
EXPLICIT_TOOL_POLICY_REQUIRED_TOOLS = {"research_knowledge_query_tool"}
KNOWN_AGENT_PRIMARY_MODES = {"chat", "research", "self_evolution", "supervised_evolution", "general"}
WRITE_RETRY_TIMEOUT_SECONDS = 2.0
_SAFE_ID_FRAGMENT = re.compile(r"[^A-Za-z0-9_.-]+")
_AGENT_CODE_PATTERN = re.compile(r"^[A-Z][A-Z0-9-]{1,15}$")
_AGENT_ID_LIKE_PATTERN = re.compile(r"^(agent[-_].+|[aA]\d{3,}|[A-Z][A-Z0-9-]{1,15})$")
_FUNCTIONAL_DISPLAY_NAME_TOKENS = (
    "agent",
    "智能体",
    "自进化",
    "监督进化",
    "科研",
    "执行",
    "评审",
    "总结",
    "基线",
    "候选",
    "审计",
    "裁决",
)
_PUBLIC_NAME_FAMILY = (
    "林",
    "沈",
    "顾",
    "许",
    "陆",
    "苏",
    "闻",
    "江",
    "程",
    "夏",
    "周",
    "宋",
    "叶",
    "秦",
    "唐",
    "白",
)
_PUBLIC_NAME_GIVEN = (
    "予安",
    "知微",
    "清和",
    "星辞",
    "若川",
    "明澈",
    "南栀",
    "云舒",
    "景行",
    "听澜",
    "以宁",
    "望舒",
    "言初",
    "书遥",
    "映白",
    "念青",
)
_STATE_LOCK = threading.RLock()
_CURRENT_AGENT_RUNTIME: ContextVar[dict[str, Any]] = ContextVar(
    "vibelution_current_agent_runtime",
    default={},
)


class AgentDirectoryError(ValueError):
    """Raised when an AgentInstance request is invalid."""


class AgentNotFoundError(AgentDirectoryError):
    """Raised when an AgentInstance does not exist."""


class AgentArchivedError(AgentDirectoryError):
    """Raised when an archived AgentInstance would be silently reactivated."""


class AgentMessageNotFoundError(AgentDirectoryError):
    """Raised when an Agent inbox message does not exist."""


@dataclass(frozen=True)
class ToolPolicyDecision:
    allowed: bool
    message: str = ""
    reason: str = ""
    policy_id: str = ""
    agent_id: str = ""


@dataclass(frozen=True)
class DelegationPolicyDecision:
    allowed: bool
    message: str = ""
    reason: str = ""
    agent_id: str = ""
    max_depth: int = 0
    max_concurrent: int = 0
    context_mode: str = ""


@dataclass(frozen=True)
class SupervisionPolicyDecision:
    allowed: bool
    message: str = ""
    reason: str = ""
    agent_id: str = ""
    action: str = ""
    supervision_enabled: bool = False
    requires_review: bool = False
    review_mode: str = "advisory"
    evidence_level: str = "standard"


@dataclass(frozen=True)
class AgentWorkspaceWriteDecision:
    allowed: bool
    path: str = ""
    scope: str = ""
    reason: str = ""
    message: str = ""
    agent_id: str = ""


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def default_state() -> dict[str, Any]:
    return {
        "version": AGENT_REGISTRY_VERSION,
        "updatedAt": utc_now_iso(),
        "agents": [],
        "toolPolicies": {
            DEFAULT_TOOL_POLICY_ID: default_tool_policy(DEFAULT_TOOL_POLICY_ID),
        },
        "memoryPolicies": {},
    }


def list_agents(*, include_archived: bool = False) -> list[dict[str, Any]]:
    with _STATE_LOCK:
        state = repair_agent_directory()
    agents = [
        _agent_to_api(item)
        for item in state.get("agents") or []
        if isinstance(item, dict) and (include_archived or str(item.get("status") or "active") != "archived")
    ]
    agents.sort(key=lambda item: str(item.get("updatedAt") or item.get("createdAt") or ""), reverse=True)
    return agents


def get_agent(agent_id: str, *, include_archived: bool = True) -> dict[str, Any] | None:
    normalized = str(agent_id or "").strip()
    if not normalized:
        return None
    with _STATE_LOCK:
        state = repair_agent_directory()
        agent = _find_agent(state, normalized)
    if not agent:
        return None
    if not include_archived and str(agent.get("status") or "") == "archived":
        return None
    return _agent_to_api(agent)


def create_agent_instance(
    *,
    display_name: str = "",
    template_id: str = "",
    profile_id: str = "",
    primary_mode: str = DEFAULT_AGENT_PRIMARY_MODE,
    role_key: str = "",
    prompt_template_id: str = "",
    direct_session_id: str = "",
    workspace_path: str = "",
    created_by: str = "user",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    with _STATE_LOCK:
        state = repair_agent_directory()
        existing_ids = {
            str(item.get("agentId") or "").strip()
            for item in state.get("agents") or []
            if isinstance(item, dict)
        }
        now = utc_now_iso()
        agent_id = _new_agent_id(existing_ids)
        title = trim_lines(display_name or "", max_lines=1).strip() or "Agent"
        metadata_payload = dict(metadata or {})
        public_name = _agent_public_display_name(
            title,
            existing_agents=state.get("agents") or [],
            agent_id=agent_id,
            metadata=metadata_payload,
        )
        normalized_profile = str(profile_id or template_id or "primary").strip() or "primary"
        normalized_template = str(template_id or normalized_profile).strip() or normalized_profile
        agent_workspace = workspace_path or _agent_workspace_relative_path(agent_id)
        _ensure_agent_workspace(agent_workspace)
        memory_policy_id = f"memory-{agent_id}"
        agent = {
            "agentId": agent_id,
            "agentCode": _next_agent_code(state.get("agents") or []),
            "displayName": public_name,
            "kind": DEFAULT_AGENT_KIND,
            "primaryMode": _normalize_primary_mode(primary_mode),
            "roleKey": _normalize_role_key(role_key),
            "templateId": normalized_template,
            "profileId": normalized_profile,
            "promptTemplateId": _normalize_prompt_template_id(prompt_template_id),
            "directSessionId": str(direct_session_id or "").strip(),
            "workspacePath": agent_workspace,
            "toolPolicyId": DEFAULT_TOOL_POLICY_ID,
            "memoryPolicyId": memory_policy_id,
            "createdBy": str(created_by or "user").strip() or "user",
            "status": "active",
            "metadata": _with_functional_display_name(metadata_payload, title),
            "createdAt": now,
            "updatedAt": now,
        }
        policies = _memory_policies(state)
        policies[memory_policy_id] = default_memory_policy(memory_policy_id, agent_workspace)
        state["agents"] = list(state.get("agents") or []) + [agent]
        state["memoryPolicies"] = policies
        save_state(state)
    _record_agent_event("agent.created", agent, lifecycle=True)
    _record_agent_territory_event("agent_territory.resolved", agent, outcome="created")
    return _agent_to_api(agent)


def ensure_agent_for_session(
    session_id: str,
    *,
    display_name: str = "",
    profile_id: str = "primary",
    primary_mode: str = DEFAULT_AGENT_PRIMARY_MODE,
    role_key: str = "",
    prompt_template_id: str = "",
    existing_agent_id: str = "",
    session_workspace_path: str = "",
    created_by: str = "session_repair",
) -> dict[str, Any]:
    normalized_session_id = str(session_id or "").strip()
    if not normalized_session_id:
        raise AgentDirectoryError("Session id is required to bind an AgentInstance.")

    with _STATE_LOCK:
        state = repair_agent_directory()
        now = utc_now_iso()
        agent = _find_agent(state, existing_agent_id)
        if agent is None:
            agent = _find_agent_by_direct_session(state, normalized_session_id)
        if agent is None:
            created = create_agent_instance(
                display_name=display_name or normalized_session_id,
                template_id=profile_id,
                profile_id=profile_id,
                primary_mode=primary_mode,
                role_key=role_key,
                prompt_template_id=prompt_template_id,
                direct_session_id=normalized_session_id,
                created_by=created_by,
                metadata={"legacySessionWorkspacePath": str(session_workspace_path or "").strip()},
            )
            return created

        changed = False
        if not _normalize_agent_code(agent.get("agentCode")):
            agent["agentCode"] = _next_agent_code(
                state.get("agents") or [],
                exclude_agent_id=str(agent.get("agentId") or ""),
            )
            changed = True
        if str(agent.get("directSessionId") or "").strip() != normalized_session_id:
            agent["directSessionId"] = normalized_session_id
            changed = True
        normalized_primary_mode = _normalize_primary_mode(primary_mode or agent.get("primaryMode") or DEFAULT_AGENT_PRIMARY_MODE)
        if str(agent.get("primaryMode") or "").strip() != normalized_primary_mode:
            agent["primaryMode"] = normalized_primary_mode
            changed = True
        normalized_role_key = _normalize_role_key(role_key or agent.get("roleKey") or _infer_agent_role_key(agent))
        if str(agent.get("roleKey") or "").strip() != normalized_role_key:
            agent["roleKey"] = normalized_role_key
            changed = True
        normalized_prompt_template_id = _normalize_prompt_template_id(
            prompt_template_id or agent.get("promptTemplateId") or _infer_agent_prompt_template_id(agent)
        )
        if str(agent.get("promptTemplateId") or "").strip() != normalized_prompt_template_id:
            agent["promptTemplateId"] = normalized_prompt_template_id
            changed = True
        title = trim_lines(display_name or "", max_lines=1).strip()
        if title:
            metadata = _with_functional_display_name(dict(agent.get("metadata") or {}), title)
            if metadata != agent.get("metadata"):
                agent["metadata"] = metadata
                changed = True
            if _should_repair_public_display_name(agent, title):
                agent["displayName"] = _agent_public_display_name(
                    title,
                    existing_agents=state.get("agents") or [],
                    agent_id=str(agent.get("agentId") or ""),
                    metadata=metadata,
                )
                agent["metadata"] = _mark_display_name_generated(dict(agent.get("metadata") or {}), force=True)
                changed = True
        if not str(agent.get("displayName") or "").strip():
            agent["displayName"] = _agent_public_display_name(
                title or str(agent.get("agentId") or "Agent"),
                existing_agents=state.get("agents") or [],
                agent_id=str(agent.get("agentId") or ""),
                metadata=dict(agent.get("metadata") or {}),
            )
            changed = True
        normalized_profile = str(profile_id or agent.get("profileId") or "primary").strip() or "primary"
        if str(agent.get("profileId") or "").strip() != normalized_profile:
            agent["profileId"] = normalized_profile
            agent["templateId"] = normalized_profile
            changed = True
        if str(agent.get("status") or "active").strip() == "archived":
            _record_agent_event("agent.ensure.skipped_archived", agent, lifecycle=True)
            raise AgentArchivedError(f"Archived Agent cannot be ensured for session: {agent.get('agentId') or ''}")
        metadata = dict(agent.get("metadata") or {})
        legacy_path = str(session_workspace_path or "").strip()
        if legacy_path and metadata.get("legacySessionWorkspacePath") != legacy_path:
            metadata["legacySessionWorkspacePath"] = legacy_path
            agent["metadata"] = metadata
            changed = True
        workspace_path = str(agent.get("workspacePath") or "").strip() or _agent_workspace_relative_path(str(agent["agentId"]))
        if not agent.get("workspacePath"):
            agent["workspacePath"] = workspace_path
            changed = True
        _ensure_agent_workspace(workspace_path)
        memory_policy_id = str(agent.get("memoryPolicyId") or "").strip() or f"memory-{agent['agentId']}"
        if str(agent.get("memoryPolicyId") or "").strip() != memory_policy_id:
            agent["memoryPolicyId"] = memory_policy_id
            changed = True
        policies = _memory_policies(state)
        if memory_policy_id not in policies:
            policies[memory_policy_id] = default_memory_policy(memory_policy_id, workspace_path)
            state["memoryPolicies"] = policies
            changed = True
        if changed:
            agent["updatedAt"] = now
            save_state(state)
            _record_agent_event("agent.repaired", agent)
            _record_agent_territory_event("agent_territory.resolved", agent, outcome="repaired")
    return _agent_to_api(agent)


def update_agent_instance(
    agent_id: str,
    *,
    display_name: str | None = None,
    template_id: str | None = None,
    profile_id: str | None = None,
    primary_mode: str | None = None,
    role_key: str | None = None,
    prompt_template_id: str | None = None,
    tool_policy_id: str | None = None,
    memory_policy_id: str | None = None,
    tool_policy: dict[str, Any] | None = None,
    memory_policy: dict[str, Any] | None = None,
    delegation_policy: dict[str, Any] | None = None,
    supervision_policy: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    status: str | None = None,
    preserve_generated_display_name: bool = False,
) -> dict[str, Any]:
    updated_tool_policy: dict[str, Any] | None = None
    updated_memory_policy: dict[str, Any] | None = None
    updated_delegation_policy: dict[str, Any] | None = None
    updated_supervision_policy: dict[str, Any] | None = None
    with _STATE_LOCK:
        state = load_state()
        agent = _find_agent(state, agent_id)
        if agent is None:
            raise AgentNotFoundError(f"Agent not found: {agent_id}")
        if display_name is not None:
            title = trim_lines(display_name or "", max_lines=1).strip()
            if not title:
                raise AgentDirectoryError("Agent display name is required.")
            metadata_payload = dict(agent.get("metadata") or {})
            if preserve_generated_display_name:
                current_display_name = str(agent.get("displayName") or "").strip()
                metadata_payload = _with_functional_display_name(metadata_payload, title)
                if not current_display_name or _display_name_is_functional_or_machine(current_display_name, {**agent, "metadata": metadata_payload}):
                    agent["displayName"] = _agent_public_display_name(
                        title,
                        existing_agents=state.get("agents") or [],
                        agent_id=str(agent.get("agentId") or ""),
                        metadata=metadata_payload,
                    )
                    metadata_payload = _mark_display_name_generated(metadata_payload, force=True)
                else:
                    metadata_payload = _mark_display_name_generated(metadata_payload)
            else:
                agent["displayName"] = title[:120].rstrip()
                metadata_payload["displayNameSource"] = "user"
            agent["metadata"] = metadata_payload
        if template_id is not None:
            normalized_template = str(template_id or "").strip()
            if normalized_template:
                agent["templateId"] = normalized_template
        if profile_id is not None:
            normalized = str(profile_id or "").strip() or "primary"
            agent["profileId"] = normalized
            if template_id is None:
                agent["templateId"] = normalized
        if primary_mode is not None:
            agent["primaryMode"] = _normalize_primary_mode(primary_mode)
        if role_key is not None:
            agent["roleKey"] = _normalize_role_key(role_key)
        if prompt_template_id is not None:
            agent["promptTemplateId"] = _normalize_prompt_template_id(prompt_template_id)
        if metadata is not None:
            current = dict(agent.get("metadata") or {})
            current.update(dict(metadata or {}))
            agent["metadata"] = current
        if status is not None:
            normalized_status = str(status or "").strip() or "active"
            if normalized_status not in {"active", "archived"}:
                raise AgentDirectoryError("Unsupported AgentInstance status.")
            if normalized_status == "archived" and _agent_archive_protected(agent):
                raise AgentDirectoryError("Protected core Agent cannot be archived.")
            agent["status"] = normalized_status
        if tool_policy_id is not None:
            normalized_policy_id = str(tool_policy_id or "").strip() or DEFAULT_TOOL_POLICY_ID
            policies = _tool_policies(state)
            if normalized_policy_id not in policies:
                raise AgentDirectoryError(f"Unknown ToolPolicy: {normalized_policy_id}")
            agent["toolPolicyId"] = normalized_policy_id
            state["toolPolicies"] = policies
        if memory_policy_id is not None:
            normalized_memory_policy_id = str(memory_policy_id or "").strip()
            policies = _memory_policies(state)
            if not normalized_memory_policy_id or normalized_memory_policy_id not in policies:
                raise AgentDirectoryError(f"Unknown MemoryPolicy: {normalized_memory_policy_id}")
            agent["memoryPolicyId"] = normalized_memory_policy_id
            state["memoryPolicies"] = policies
        if tool_policy is not None:
            policy_id = str(agent.get("toolPolicyId") or DEFAULT_TOOL_POLICY_ID).strip() or DEFAULT_TOOL_POLICY_ID
            if policy_id == DEFAULT_TOOL_POLICY_ID:
                policy_id = f"tool-{agent['agentId']}"
                agent["toolPolicyId"] = policy_id
            policies = _tool_policies(state)
            updated_tool_policy = normalize_tool_policy(
                {**default_tool_policy(policy_id), **dict(tool_policy or {})},
                policy_id,
            )
            policies[policy_id] = updated_tool_policy
            state["toolPolicies"] = policies
        if memory_policy is not None:
            policy_id = str(agent.get("memoryPolicyId") or "").strip() or f"memory-{agent['agentId']}"
            if policy_id == DEFAULT_MEMORY_POLICY_ID:
                policy_id = f"memory-{agent['agentId']}"
                agent["memoryPolicyId"] = policy_id
            policies = _memory_policies(state)
            workspace_path = _agent_workspace_relative_path(str(agent["agentId"]))
            agent["workspacePath"] = workspace_path
            _ensure_agent_workspace(workspace_path)
            base_policy = policies.get(policy_id) if isinstance(policies.get(policy_id), dict) else default_memory_policy(policy_id, workspace_path)
            updated_memory_policy = normalize_memory_policy(
                {**base_policy, **dict(memory_policy or {})},
                policy_id,
                workspace_path,
            )
            policies[policy_id] = updated_memory_policy
            agent["memoryPolicyId"] = policy_id
            state["memoryPolicies"] = policies
        if delegation_policy is not None:
            metadata_payload = dict(agent.get("metadata") or {})
            updated_delegation_policy = normalize_delegation_policy(delegation_policy)
            metadata_payload["delegationPolicy"] = updated_delegation_policy
            agent["metadata"] = metadata_payload
        if supervision_policy is not None:
            metadata_payload = dict(agent.get("metadata") or {})
            updated_supervision_policy = normalize_supervision_policy(supervision_policy)
            metadata_payload["supervisionPolicy"] = updated_supervision_policy
            agent["metadata"] = metadata_payload
        agent["updatedAt"] = utc_now_iso()
        save_state(state)
    _record_agent_event("agent.updated", agent)
    if updated_tool_policy is not None:
        _record_agent_tool_policy_event(agent, updated_tool_policy)
    if updated_memory_policy is not None:
        _record_agent_memory_policy_event(agent, updated_memory_policy)
    if updated_delegation_policy is not None:
        _record_agent_delegation_policy_event(agent, updated_delegation_policy)
    if updated_supervision_policy is not None:
        _record_agent_supervision_policy_event(agent, updated_supervision_policy)
    return _agent_to_api(agent)


def list_agent_policy_options() -> dict[str, list[dict[str, Any]]]:
    """Return lightweight policy options for Agent configuration forms."""

    with _STATE_LOCK:
        state = repair_agent_directory()
    agents = [item for item in state.get("agents") or [] if isinstance(item, dict)]
    tool_policies = _tool_policies(state)
    memory_policies = _memory_policies(state)
    return {
        "toolPolicies": [
            {
                "policyId": policy_id,
                "agentCount": _count_policy_refs(agents, "toolPolicyId", policy_id),
                "allowedToolCount": len(list(policy.get("allowedTools") or [])),
                "preferredToolCount": len(list(policy.get("preferredTools") or [])),
                "blockedToolCount": len(list(policy.get("blockedTools") or [])),
                "networkAccess": str(policy.get("networkAccess") or "inherit"),
                "mutationAccess": str(policy.get("mutationAccess") or "inherit"),
                "maxCallsPerTurn": int(policy.get("maxCallsPerTurn") or 0),
            }
            for policy_id, policy in sorted(tool_policies.items())
        ],
        "memoryPolicies": [
            {
                "policyId": policy_id,
                "agentCount": _count_policy_refs(agents, "memoryPolicyId", policy_id),
                "privateMemoryRoot": str(policy.get("privateMemoryRoot") or ""),
                "readSharedGroupCount": len(list(policy.get("readSharedGroups") or [])),
                "writeSharedGroupCount": len(list(policy.get("writeSharedGroups") or [])),
                "hasInboxPath": bool(str(policy.get("agentInboxMessagesPath") or "").strip()),
            }
            for policy_id, policy in sorted(memory_policies.items())
        ],
    }


def archive_agent_instance(agent_id: str) -> dict[str, Any]:
    with _STATE_LOCK:
        state = load_state()
        agent = _find_agent(state, agent_id)
        if agent is None:
            raise AgentNotFoundError(f"Agent not found: {agent_id}")
        if _agent_archive_protected(agent):
            raise AgentDirectoryError("Protected core Agent cannot be archived.")
        agent["status"] = "archived"
        agent["updatedAt"] = utc_now_iso()
        save_state(state)
    _record_agent_event("agent.archived", agent, lifecycle=True)
    return _agent_to_api(agent)


def purge_archived_agent_instance(agent_id: str) -> dict[str, Any]:
    """Physically remove an archived AgentInstance and its private workspace."""

    normalized_agent_id = str(agent_id or "").strip()
    if not normalized_agent_id:
        raise AgentDirectoryError("Agent id is required.")
    with _STATE_LOCK:
        state = load_state()
        agent = _find_agent(state, normalized_agent_id)
        if agent is None:
            raise AgentNotFoundError(f"Agent not found: {normalized_agent_id}")
        if str(agent.get("status") or "active").strip() != "archived":
            raise AgentDirectoryError("Only archived Agents can be permanently deleted.")
        if _agent_archive_protected(agent):
            raise AgentDirectoryError("Protected core Agent cannot be purged.")
        agent_snapshot = dict(agent)
        agents = [
            item
            for item in state.get("agents") or []
            if not (
                isinstance(item, dict)
                and str(item.get("agentId") or "").strip() == normalized_agent_id
            )
        ]
        state["agents"] = agents
        tool_policy_id = str(agent.get("toolPolicyId") or "").strip()
        memory_policy_id = str(agent.get("memoryPolicyId") or "").strip()
        removed_tool_policy = False
        removed_memory_policy = False
        if tool_policy_id and tool_policy_id != DEFAULT_TOOL_POLICY_ID and _count_policy_refs(agents, "toolPolicyId", tool_policy_id) == 0:
            policies = _tool_policies(state)
            removed_tool_policy = policies.pop(tool_policy_id, None) is not None
            state["toolPolicies"] = policies
        if memory_policy_id and _count_policy_refs(agents, "memoryPolicyId", memory_policy_id) == 0:
            policies = _memory_policies(state)
            removed_memory_policy = policies.pop(memory_policy_id, None) is not None
            state["memoryPolicies"] = policies
        save_state(state)

    workspace_result = _delete_purged_agent_workspace(agent_snapshot)
    result = {
        "agentId": normalized_agent_id,
        "status": "purged",
        "deleted": True,
        "workspaceDeleted": bool(workspace_result.get("deleted")),
        "deletedPaths": list(workspace_result.get("deletedPaths") or []),
        "skippedPaths": list(workspace_result.get("skippedPaths") or []),
        "removedToolPolicy": removed_tool_policy,
        "removedMemoryPolicy": removed_memory_policy,
        "toolPolicyId": tool_policy_id,
        "memoryPolicyId": memory_policy_id,
    }
    _record_agent_purged_event(agent_snapshot, result)
    return result


def ensure_agent_purge_allowed(agent_id: str) -> dict[str, Any]:
    """Validate permanent deletion before callers mutate external Agent references."""

    normalized_agent_id = str(agent_id or "").strip()
    if not normalized_agent_id:
        raise AgentDirectoryError("Agent id is required.")
    with _STATE_LOCK:
        state = load_state()
        agent = _find_agent(state, normalized_agent_id)
        if agent is None:
            raise AgentNotFoundError(f"Agent not found: {normalized_agent_id}")
        if str(agent.get("status") or "active").strip() != "archived":
            raise AgentDirectoryError("Only archived Agents can be permanently deleted.")
        if _agent_archive_protected(agent):
            raise AgentDirectoryError("Protected core Agent cannot be purged.")
        return _agent_to_api(agent)


def reactivate_agent_instance(agent_id: str, *, reason: str = "", metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    """Explicitly restore an archived AgentInstance to active status."""

    with _STATE_LOCK:
        state = load_state()
        agent = _find_agent(state, agent_id)
        if agent is None:
            raise AgentNotFoundError(f"Agent not found: {agent_id}")
        if str(agent.get("status") or "active").strip() != "archived":
            return _agent_to_api(agent)
        current_metadata = dict(agent.get("metadata") or {})
        if metadata:
            current_metadata.update(dict(metadata))
        if reason:
            current_metadata["reactivatedReason"] = trim_lines(str(reason or ""), max_lines=2)
        agent["metadata"] = current_metadata
        agent["status"] = "active"
        agent["updatedAt"] = utc_now_iso()
        save_state(state)
    _record_agent_event("agent.reactivated", agent, lifecycle=True)
    return _agent_to_api(agent)


def ensure_agent_archive_allowed(agent_id: str) -> dict[str, Any]:
    """Validate archival before callers mutate external Agent references."""

    with _STATE_LOCK:
        state = load_state()
        agent = _find_agent(state, agent_id)
        if agent is None:
            raise AgentNotFoundError(f"Agent not found: {agent_id}")
        if _agent_archive_protected(agent):
            raise AgentDirectoryError("Protected core Agent cannot be archived.")
        return _agent_to_api(agent)


def repair_agent_directory() -> dict[str, Any]:
    with _STATE_LOCK:
        state = load_state()
        changed = False
        display_name_repaired_agents: list[dict[str, Any]] = []
        territory_repaired_agents: list[dict[str, Any]] = []
        used_agent_codes: set[str] = set()
        policies = _memory_policies(state)
        for agent in state.get("agents") or []:
            if not isinstance(agent, dict):
                continue
            territory_changed = False
            if not str(agent.get("primaryMode") or "").strip():
                agent["primaryMode"] = _infer_agent_primary_mode(agent)
                changed = True
            else:
                normalized_mode = _normalize_primary_mode(agent.get("primaryMode"))
                if agent.get("primaryMode") != normalized_mode:
                    agent["primaryMode"] = normalized_mode
                    changed = True
            if not str(agent.get("roleKey") or "").strip():
                role_key = _infer_agent_role_key(agent)
                if role_key:
                    agent["roleKey"] = role_key
                    changed = True
            else:
                normalized_role_key = _normalize_role_key(agent.get("roleKey"))
                if agent.get("roleKey") != normalized_role_key:
                    agent["roleKey"] = normalized_role_key
                    changed = True
            if not str(agent.get("promptTemplateId") or "").strip():
                prompt_template_id = _infer_agent_prompt_template_id(agent)
                if prompt_template_id:
                    agent["promptTemplateId"] = prompt_template_id
                    changed = True
            else:
                normalized_prompt_template_id = _normalize_prompt_template_id(agent.get("promptTemplateId"))
                if agent.get("promptTemplateId") != normalized_prompt_template_id:
                    agent["promptTemplateId"] = normalized_prompt_template_id
                    changed = True
            metadata = dict(agent.get("metadata") or {})
            display_name = str(agent.get("displayName") or "").strip()
            if display_name and _display_name_is_functional_or_machine(display_name, agent):
                metadata = _with_functional_display_name(metadata, display_name)
                agent["displayName"] = _agent_public_display_name(
                    display_name,
                    existing_agents=state.get("agents") or [],
                    agent_id=str(agent.get("agentId") or ""),
                    metadata=metadata,
                )
                metadata = _mark_display_name_generated(metadata, force=True)
                agent["metadata"] = metadata
                display_name_repaired_agents.append(dict(agent))
                changed = True
            elif not display_name:
                agent["displayName"] = _agent_public_display_name(
                    str(agent.get("agentId") or "Agent"),
                    existing_agents=state.get("agents") or [],
                    agent_id=str(agent.get("agentId") or ""),
                    metadata=metadata,
                )
                agent["metadata"] = _mark_display_name_generated(metadata)
                changed = True
            normalized_code = _normalize_agent_code(agent.get("agentCode"))
            if normalized_code and normalized_code not in used_agent_codes:
                if agent.get("agentCode") != normalized_code:
                    agent["agentCode"] = normalized_code
                    changed = True
                used_agent_codes.add(normalized_code)
            else:
                agent["agentCode"] = _next_agent_code(
                    state.get("agents") or [],
                    used_codes=used_agent_codes,
                    exclude_agent_id=str(agent.get("agentId") or ""),
                )
                used_agent_codes.add(str(agent["agentCode"]))
                changed = True
            workspace_path = str(agent.get("workspacePath") or "").strip()
            expected_workspace_path = _agent_workspace_relative_path(str(agent.get("agentId") or "agent"))
            if not workspace_path or not _is_agent_private_workspace_path(workspace_path, str(agent.get("agentId") or "")):
                metadata = dict(agent.get("metadata") or {})
                if workspace_path:
                    metadata["legacyWorkspacePath"] = workspace_path
                    agent["metadata"] = metadata
                workspace_path = expected_workspace_path
                agent["workspacePath"] = workspace_path
                changed = True
                territory_changed = True
            _ensure_agent_workspace(workspace_path)
            memory_policy_id = str(agent.get("memoryPolicyId") or "").strip() or f"memory-{agent.get('agentId')}"
            if str(agent.get("memoryPolicyId") or "").strip() != memory_policy_id:
                agent["memoryPolicyId"] = memory_policy_id
                changed = True
                territory_changed = True
            normalized_policy = normalize_memory_policy(
                policies.get(memory_policy_id, {}) if isinstance(policies.get(memory_policy_id), dict) else {},
                memory_policy_id,
                workspace_path,
            ) if memory_policy_id else {}
            if memory_policy_id and policies.get(memory_policy_id) != normalized_policy:
                policies[memory_policy_id] = normalized_policy
                changed = True
                territory_changed = True
            if territory_changed:
                territory_repaired_agents.append(dict(agent))
        state["memoryPolicies"] = policies
        if changed:
            save_state(state)
            for repaired_agent in display_name_repaired_agents:
                _record_agent_event("agent.display_name_repaired", repaired_agent)
            for repaired_agent in territory_repaired_agents:
                _record_agent_territory_event("agent_territory.resolved", repaired_agent, outcome="repaired")
        return state


def current_agent_runtime() -> dict[str, Any]:
    context = _CURRENT_AGENT_RUNTIME.get({})
    if isinstance(context, dict) and context:
        return dict(context)
    env_runtime = _agent_runtime_from_env()
    if not env_runtime.get("agentId"):
        return {}
    return env_runtime


def _agent_runtime_from_env() -> dict[str, Any]:
    agent_id = str(os.environ.get("VIBELUTION_AGENT_ID") or "").strip()
    if not agent_id:
        return {}
    session_id = str(os.environ.get("VIBELUTION_AGENT_DIRECT_SESSION_ID") or "").strip()
    agent = get_agent(agent_id) or {}
    return {
        "agentId": agent_id,
        "sessionId": session_id,
        "turnId": "",
        "roomId": "",
        "roundId": "",
        "supervisedRole": str(os.environ.get("VIBELUTION_SUPERVISED_ROLE") or "").strip(),
        "agent": agent,
        "toolPolicy": resolve_tool_policy_for_agent(agent_id),
        "memoryPolicy": resolve_memory_policy_for_agent(agent_id),
        "delegationPolicy": resolve_delegation_policy_for_agent(agent_id),
        "supervisionPolicy": resolve_supervision_policy_for_agent(agent_id),
    }


@contextmanager
def active_agent_runtime(
    agent_id: str = "",
    *,
    session_id: str = "",
    turn_id: str = "",
    room_id: str = "",
    round_id: str = "",
):
    agent = get_agent(agent_id) if agent_id else None
    context = {
        "agentId": str(agent_id or "").strip(),
        "sessionId": str(session_id or "").strip(),
        "turnId": str(turn_id or "").strip(),
        "roomId": str(room_id or "").strip(),
        "roundId": str(round_id or "").strip(),
        "agent": agent or {},
        "toolPolicy": resolve_tool_policy_for_agent(agent_id),
        "memoryPolicy": resolve_memory_policy_for_agent(agent_id),
        "delegationPolicy": resolve_delegation_policy_for_agent(agent_id),
        "supervisionPolicy": resolve_supervision_policy_for_agent(agent_id),
    }
    token = _CURRENT_AGENT_RUNTIME.set(context)
    try:
        yield context
    finally:
        _CURRENT_AGENT_RUNTIME.reset(token)


def filter_llm_tools_for_current_agent(tools: Iterable[Any]) -> list[Any]:
    policy = current_agent_runtime().get("toolPolicy") or {}
    allowed = set(str(item or "").strip() for item in policy.get("allowedTools") or [] if str(item or "").strip())
    blocked = set(str(item or "").strip() for item in policy.get("blockedTools") or [] if str(item or "").strip())
    if not allowed and not blocked:
        return [
            tool
            for tool in list(tools or [])
            if str(getattr(tool, "name", "") or "").strip() not in EXPLICIT_TOOL_POLICY_REQUIRED_TOOLS
        ]
    filtered = []
    for tool in list(tools or []):
        name = str(getattr(tool, "name", "") or "").strip()
        if not name:
            continue
        if name in EXPLICIT_TOOL_POLICY_REQUIRED_TOOLS and name not in allowed:
            continue
        if allowed and name not in allowed:
            continue
        if name in blocked:
            continue
        filtered.append(tool)
    return filtered


def resolve_tool_policy_for_agent(agent_id: str) -> dict[str, Any]:
    agent = _find_agent(load_state(), agent_id)
    if agent is None:
        return default_tool_policy(DEFAULT_TOOL_POLICY_ID)
    state = load_state()
    policy_id = str(agent.get("toolPolicyId") or DEFAULT_TOOL_POLICY_ID).strip() or DEFAULT_TOOL_POLICY_ID
    policy = _tool_policies(state).get(policy_id) or default_tool_policy(policy_id)
    return normalize_tool_policy(policy, policy_id)


def resolve_memory_policy_for_agent(agent_id: str) -> dict[str, Any]:
    state = load_state()
    agent = _find_agent(state, agent_id)
    if agent is None:
        return {}
    policy_id = str(agent.get("memoryPolicyId") or "").strip()
    policy = _memory_policies(state).get(policy_id)
    workspace_path = str(agent.get("workspacePath") or _agent_workspace_relative_path(agent_id)).strip()
    if isinstance(policy, dict):
        return normalize_memory_policy(policy, policy_id, workspace_path)
    return default_memory_policy(policy_id or f"memory-{agent_id}", workspace_path)


def resolve_agent_workspace_territory(agent_id: str) -> dict[str, Any]:
    state = load_state()
    agent = _find_agent(state, agent_id)
    if agent is None:
        return {}
    return _agent_workspace_territory(agent)


def ensure_agent_shared_workspace() -> Path:
    path = _resolve_project_path(AGENT_SHARED_WORKSPACE_PATH)
    shared_root = (_project_root() / "workspace" / "shared").resolve()
    if path != shared_root:
        raise AgentDirectoryError(f"Invalid shared workspace path: {path}")
    for subdir in ("memory", "artifacts", "notes", "logs", "research", "tmp"):
        (path / subdir).mkdir(parents=True, exist_ok=True)
    return path


def evaluate_agent_workspace_write(agent_id: str, path_value: str | Path, *, purpose: str = "") -> AgentWorkspaceWriteDecision:
    normalized_agent_id = str(agent_id or "").strip()
    if not normalized_agent_id:
        return AgentWorkspaceWriteDecision(
            False,
            path=str(path_value or ""),
            reason="missing_agent",
            message="Agent id is required for workspace writes.",
        )
    agent = get_agent(normalized_agent_id, include_archived=True)
    if not agent:
        return AgentWorkspaceWriteDecision(
            False,
            path=str(path_value or ""),
            reason="missing_agent",
            message=f"Agent not found: {normalized_agent_id}",
            agent_id=normalized_agent_id,
        )
    territory = _agent_workspace_territory(agent)
    target = _resolve_project_path(str(path_value or ""))
    private_root = _resolve_project_path(str(territory.get("privateRoot") or ""))
    shared_root = _resolve_project_path(str(territory.get("sharedRoot") or AGENT_SHARED_WORKSPACE_PATH))
    tool_policy = agent.get("toolPolicy") if isinstance(agent.get("toolPolicy"), dict) else resolve_tool_policy_for_agent(normalized_agent_id)
    write_scopes = set(_normalize_tool_policy_scopes(tool_policy.get("writeScopes") if isinstance(tool_policy, dict) else []))
    if _path_is_within(target, private_root):
        return AgentWorkspaceWriteDecision(
            True,
            path=_relative_project_path(target),
            scope="private",
            agent_id=normalized_agent_id,
        )
    if _path_is_within(target, shared_root):
        if "shared" in write_scopes:
            return AgentWorkspaceWriteDecision(
                True,
                path=_relative_project_path(target),
                scope="shared",
                agent_id=normalized_agent_id,
            )
        decision = AgentWorkspaceWriteDecision(
            False,
            path=_relative_project_path(target),
            scope="shared",
            reason="shared_write_requires_policy",
            message="Shared workspace writes require an explicit shared write policy.",
            agent_id=normalized_agent_id,
        )
        _record_agent_territory_write_blocked(agent, decision, purpose=purpose)
        return decision
    decision = AgentWorkspaceWriteDecision(
        False,
        path=_relative_project_path(target),
        scope="external",
        reason="outside_agent_territory",
        message="Agent writes must stay inside the Agent private territory unless a policy grants another scope.",
        agent_id=normalized_agent_id,
    )
    _record_agent_territory_write_blocked(agent, decision, purpose=purpose)
    return decision


def resolve_delegation_policy_for_agent(agent_id: str) -> dict[str, Any]:
    state = load_state()
    agent = _find_agent(state, agent_id)
    if agent is None:
        return normalize_delegation_policy({})
    metadata = agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}
    return normalize_delegation_policy(metadata.get("delegationPolicy") if isinstance(metadata, dict) else {})


def resolve_supervision_policy_for_agent(agent_id: str) -> dict[str, Any]:
    state = load_state()
    agent = _find_agent(state, agent_id)
    if agent is None:
        return normalize_supervision_policy({})
    metadata = agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}
    return normalize_supervision_policy(metadata.get("supervisionPolicy") if isinstance(metadata, dict) else {})


def evaluate_current_delegation_policy(
    *,
    context_mode: str = "isolated",
    requested_depth: int | None = None,
    wake_message: bool = False,
) -> DelegationPolicyDecision:
    runtime = current_agent_runtime()
    agent_id = str(runtime.get("agentId") or "").strip()
    if not agent_id:
        return DelegationPolicyDecision(True, context_mode=str(context_mode or "isolated").strip() or "isolated")
    policy = runtime.get("delegationPolicy") or resolve_delegation_policy_for_agent(agent_id)
    decision = evaluate_delegation_policy(
        policy,
        agent_id=agent_id,
        context_mode=context_mode,
        requested_depth=requested_depth,
        wake_message=wake_message,
    )
    if not decision.allowed:
        _record_delegation_policy_block(agent_id, policy, decision)
    return decision


def evaluate_current_supervision_policy(
    *,
    action: str,
    human_override: bool = False,
    user_initiated: bool = False,
) -> SupervisionPolicyDecision:
    runtime = current_agent_runtime()
    agent_id = str(runtime.get("agentId") or "").strip()
    if not agent_id:
        return SupervisionPolicyDecision(True, action=str(action or "").strip())
    policy = runtime.get("supervisionPolicy") or resolve_supervision_policy_for_agent(agent_id)
    decision = evaluate_supervision_policy(
        policy,
        agent_id=agent_id,
        action=action,
        human_override=human_override,
        user_initiated=user_initiated,
    )
    record_supervision_policy_decision(decision)
    return decision


def evaluate_supervision_policy(
    policy: dict[str, Any],
    *,
    agent_id: str = "",
    action: str,
    human_override: bool = False,
    user_initiated: bool = False,
) -> SupervisionPolicyDecision:
    normalized_policy = normalize_supervision_policy(policy)
    normalized_action = str(action or "").strip() or "runtime_action"
    review_mode = str(normalized_policy.get("reviewMode") or "advisory").strip() or "advisory"
    evidence_level = str(normalized_policy.get("evidenceLevel") or "standard").strip() or "standard"
    supervision_enabled = bool(normalized_policy.get("supervisionEnabled", False))
    requires_review = bool(normalized_policy.get("requiresReview", False))
    base = {
        "agent_id": agent_id,
        "action": normalized_action,
        "supervision_enabled": supervision_enabled,
        "requires_review": requires_review,
        "review_mode": review_mode,
        "evidence_level": evidence_level,
    }
    if human_override or user_initiated:
        return SupervisionPolicyDecision(True, reason="human_override", **base)
    if not supervision_enabled:
        return SupervisionPolicyDecision(True, reason="supervision_disabled", **base)
    if review_mode == "disabled":
        return SupervisionPolicyDecision(True, reason="review_disabled", **base)
    if review_mode == "required" or requires_review:
        return SupervisionPolicyDecision(
            False,
            message="[监督策略提示] 当前 Agent 的自主动作需要先完成复核，本次动作已被阻止。",
            reason="supervision_review_required",
            **base,
        )
    return SupervisionPolicyDecision(True, reason="supervision_advisory", **base)


def record_supervision_policy_decision(decision: SupervisionPolicyDecision) -> None:
    if not decision.agent_id or not decision.supervision_enabled:
        return
    if decision.reason in {"human_override", "review_disabled", "supervision_disabled"}:
        return
    if not decision.allowed:
        _record_supervision_policy_block(decision)
        return
    if decision.review_mode == "advisory":
        _record_supervision_policy_observed(decision)


def evaluate_delegation_policy(
    policy: dict[str, Any],
    *,
    agent_id: str = "",
    context_mode: str = "isolated",
    requested_depth: int | None = None,
    wake_message: bool = False,
) -> DelegationPolicyDecision:
    normalized_policy = normalize_delegation_policy(policy)
    normalized_mode = str(context_mode or "isolated").strip().lower() or "isolated"
    max_depth = int(normalized_policy.get("maxDepth") or 0)
    max_concurrent = int(normalized_policy.get("maxConcurrent") or 0)
    if wake_message and not bool(normalized_policy.get("allowWakeMessages", True)):
        return DelegationPolicyDecision(
            False,
            message="[委托策略提示] 目标 Agent 的唤醒消息已关闭，消息会留在 inbox 中等待后续处理。",
            reason="wake_messages_disabled",
            agent_id=agent_id,
            max_depth=max_depth,
            max_concurrent=max_concurrent,
            context_mode=normalized_mode,
        )
    if not bool(normalized_policy.get("allowSubagents", False)):
        return DelegationPolicyDecision(
            False,
            message="[委托策略提示] 当前 Agent 的 DelegationPolicy 禁止派发子 Agent。",
            reason="subagents_disabled",
            agent_id=agent_id,
            max_depth=max_depth,
            max_concurrent=max_concurrent,
            context_mode=normalized_mode,
        )
    allowed_modes = set(str(item or "").strip().lower() for item in normalized_policy.get("allowedContextModes") or [])
    if normalized_mode not in allowed_modes:
        return DelegationPolicyDecision(
            False,
            message=f"[委托策略提示] 当前 Agent 不允许 `{normalized_mode}` 子 Agent 上下文模式。",
            reason="context_mode_not_allowed",
            agent_id=agent_id,
            max_depth=max_depth,
            max_concurrent=max_concurrent,
            context_mode=normalized_mode,
        )
    depth = _clamp_int(requested_depth, minimum=0, maximum=99, default=0) if requested_depth is not None else 0
    if max_depth <= 0 or depth > max_depth:
        return DelegationPolicyDecision(
            False,
            message="[委托策略提示] 当前 Agent 的子 Agent 深度上限不允许本次派发。",
            reason="max_depth_exceeded",
            agent_id=agent_id,
            max_depth=max_depth,
            max_concurrent=max_concurrent,
            context_mode=normalized_mode,
        )
    return DelegationPolicyDecision(
        True,
        agent_id=agent_id,
        max_depth=max_depth,
        max_concurrent=max_concurrent,
        context_mode=normalized_mode,
    )


def evaluate_delegation_wake_policy(policy: dict[str, Any], *, agent_id: str = "") -> DelegationPolicyDecision:
    normalized_policy = normalize_delegation_policy(policy)
    if bool(normalized_policy.get("allowWakeMessages", True)):
        return DelegationPolicyDecision(
            True,
            agent_id=agent_id,
            max_depth=int(normalized_policy.get("maxDepth") or 0),
            max_concurrent=int(normalized_policy.get("maxConcurrent") or 0),
            context_mode="agent_inbox",
        )
    return DelegationPolicyDecision(
        False,
        message="[委托策略提示] 目标 Agent 的唤醒消息已关闭，消息会留在 inbox 中等待后续处理。",
        reason="wake_messages_disabled",
        agent_id=agent_id,
        max_depth=int(normalized_policy.get("maxDepth") or 0),
        max_concurrent=int(normalized_policy.get("maxConcurrent") or 0),
        context_mode="agent_inbox",
    )


def evaluate_current_tool_policy(tool_name: str, tool_args: dict[str, Any]) -> ToolPolicyDecision:
    runtime = current_agent_runtime()
    agent_id = str(runtime.get("agentId") or "").strip()
    if not agent_id:
        return ToolPolicyDecision(True)
    policy = runtime.get("toolPolicy") or {}
    decision = evaluate_tool_policy(
        tool_name,
        tool_args,
        policy=policy,
        agent_id=agent_id,
    )
    if not decision.allowed:
        _record_policy_block(agent_id, policy, tool_name, tool_args, decision)
    return decision


def evaluate_tool_policy(
    tool_name: str,
    tool_args: dict[str, Any],
    *,
    policy: dict[str, Any],
    agent_id: str = "",
) -> ToolPolicyDecision:
    normalized_tool = str(tool_name or "").strip()
    policy_id = str(policy.get("policyId") or policy.get("id") or "").strip() or DEFAULT_TOOL_POLICY_ID
    allowed = set(str(item or "").strip() for item in policy.get("allowedTools") or [] if str(item or "").strip())
    blocked = set(str(item or "").strip() for item in policy.get("blockedTools") or [] if str(item or "").strip())
    if normalized_tool in EXPLICIT_TOOL_POLICY_REQUIRED_TOOLS and normalized_tool not in allowed:
        return _blocked_decision(
            normalized_tool,
            "tool_requires_explicit_allow",
            policy_id,
            agent_id,
            f"[工具策略提示] `{normalized_tool}` 是受限工具，需要在该 Agent 的 ToolPolicy.allowedTools 中显式授权后才能使用。",
        )
    if allowed and normalized_tool not in allowed:
        return _blocked_decision(
            normalized_tool,
            "tool_not_allowed",
            policy_id,
            agent_id,
            f"[工具策略提示] `{normalized_tool}` 不在该 Agent 的可见工具策略中。请换用允许的工具，或让用户调整该 Agent 的 ToolPolicy。",
        )
    if normalized_tool in blocked:
        return _blocked_decision(
            normalized_tool,
            "tool_blocked",
            policy_id,
            agent_id,
            f"[工具策略提示] `{normalized_tool}` 被该 Agent 的 ToolPolicy 标记为不可用。请换用其它工具，或让用户调整策略。",
        )
    if normalized_tool == "cli_tool":
        command = str((tool_args or {}).get("command") or "")
        for pattern in list(policy.get("blockedCommandPatterns") or []):
            pattern_text = str(pattern or "").strip()
            if pattern_text and re.search(pattern_text, command, flags=re.IGNORECASE):
                return _blocked_decision(
                    normalized_tool,
                    "blocked_command_pattern",
                    policy_id,
                    agent_id,
                    "[工具策略提示] 当前命令命中了该 Agent 的命令风险规则。请改写命令或让用户调整 ToolPolicy。",
                )
    return ToolPolicyDecision(True, policy_id=policy_id, agent_id=agent_id)


def write_group_context_event(agent_id: str, event: dict[str, Any]) -> dict[str, Any]:
    agent = get_agent(agent_id)
    if not agent:
        raise AgentNotFoundError(f"Agent not found: {agent_id}")
    workspace = _resolve_project_path(str(agent.get("workspacePath") or ""))
    events_dir = workspace / "events"
    events_dir.mkdir(parents=True, exist_ok=True)
    event_payload = {
        "eventId": str(event.get("eventId") or _new_event_id("groupctx")).strip(),
        "sourceRoomId": str(event.get("sourceRoomId") or "").strip(),
        "sourceRoundId": str(event.get("sourceRoundId") or "").strip(),
        "targetAgentId": str(agent_id or "").strip(),
        "targetSessionId": str(event.get("targetSessionId") or agent.get("directSessionId") or "").strip(),
        "topic": str(event.get("topic") or "").strip(),
        "summary": trim_lines(str(event.get("summary") or ""), max_lines=8),
        "ownMessage": trim_lines(str(event.get("ownMessage") or ""), max_lines=8),
        "peerHighlights": list(event.get("peerHighlights") or [])[:12],
        "promptEligible": bool(event.get("promptEligible", True)),
        "createdAt": str(event.get("createdAt") or utc_now_iso()).strip(),
    }
    _append_jsonl(events_dir / "group_context_events.jsonl", event_payload)
    _record_memory_event("memory.event_written", event_payload, agent_id=agent_id, lifecycle=True)
    _record_memory_event("group_context.synced", event_payload, agent_id=agent_id, lifecycle=True)
    return event_payload


def write_agent_inbox_message(
    target_agent_id: str,
    *,
    content: str,
    source_agent_id: str = "",
    source_session_id: str = "",
    source_room_id: str = "",
    source_round_id: str = "",
    thread_id: str = "",
    kind: str = "agent_direct_message",
    summary: str = "",
    prompt_eligible: bool = True,
    created_by: str = "agent",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    target_agent = get_agent(target_agent_id, include_archived=False)
    if not target_agent:
        raise AgentNotFoundError(f"Agent not found: {target_agent_id}")
    normalized_content = trim_lines(str(content or ""), max_lines=20).strip()
    if not normalized_content:
        raise AgentDirectoryError("Agent inbox message content is required.")
    normalized_source_agent_id = str(source_agent_id or "").strip()
    source_agent = get_agent(normalized_source_agent_id, include_archived=True) if normalized_source_agent_id else None
    if normalized_source_agent_id and not source_agent:
        raise AgentNotFoundError(f"Source agent not found: {normalized_source_agent_id}")
    now = utc_now_iso()
    message_id = _new_event_id("agentmsg")
    event_payload = {
        "eventId": message_id,
        "messageId": message_id,
        "threadId": str(thread_id or "").strip() or _agent_inbox_thread_id(source_agent, target_agent),
        "kind": trim_lines(str(kind or "agent_direct_message"), max_lines=1).strip() or "agent_direct_message",
        "status": "pending",
        "sourceAgentId": normalized_source_agent_id,
        "sourceAgentCode": str((source_agent or {}).get("agentCode") or "").strip(),
        "sourceAgentName": str((source_agent or {}).get("displayName") or "").strip(),
        "sourceSessionId": str(source_session_id or (source_agent or {}).get("directSessionId") or "").strip(),
        "sourceRoomId": str(source_room_id or "").strip(),
        "sourceRoundId": str(source_round_id or "").strip(),
        "targetAgentId": str(target_agent.get("agentId") or "").strip(),
        "targetAgentCode": str(target_agent.get("agentCode") or "").strip(),
        "targetAgentName": str(target_agent.get("displayName") or "").strip(),
        "targetSessionId": str(target_agent.get("directSessionId") or "").strip(),
        "content": normalized_content,
        "summary": trim_lines(str(summary or normalized_content), max_lines=4),
        "promptEligible": bool(prompt_eligible),
        "createdBy": str(created_by or "agent").strip() or "agent",
        "createdAt": now,
        "consumedAt": "",
        "consumedBySessionId": "",
        "consumedByTurnId": "",
        "metadata": _safe_metadata(metadata),
    }
    path = _agent_workspace_event_path(target_agent, "agent_inbox_messages.jsonl")
    _append_jsonl(path, event_payload)
    _record_memory_event("memory.event_written", event_payload, agent_id=str(target_agent.get("agentId") or ""))
    _record_memory_event("agent_inbox.message_written", event_payload, agent_id=str(target_agent.get("agentId") or ""), lifecycle=True)
    return event_payload


def list_agent_inbox_messages_for_agent(
    agent_id: str,
    *,
    limit: int = 20,
    status: str = "pending",
    prompt_eligible_only: bool = False,
) -> list[dict[str, Any]]:
    state = load_state()
    agent = _find_agent(state, agent_id)
    if not agent:
        return []
    path = _agent_workspace_event_path(agent, "agent_inbox_messages.jsonl")
    messages = _read_jsonl(path)
    normalized_status = str(status or "").strip().lower()
    if normalized_status:
        messages = [
            item for item in messages
            if str(item.get("status") or "pending").strip().lower() == normalized_status
        ]
    if prompt_eligible_only:
        messages = [item for item in messages if bool(item.get("promptEligible", True))]
    return messages[-max(1, int(limit or 1)) :]


def count_agent_inbox_messages_for_agent(agent_id: str, *, status: str = "pending") -> int:
    state = load_state()
    agent = _find_agent(state, agent_id)
    if not agent:
        return 0
    messages = _read_jsonl(_agent_workspace_event_path(agent, "agent_inbox_messages.jsonl"))
    normalized_status = str(status or "").strip().lower()
    if not normalized_status:
        return len(messages)
    return sum(
        1
        for item in messages
        if str(item.get("status") or "pending").strip().lower() == normalized_status
    )


def consume_agent_inbox_message(
    agent_id: str,
    message_id: str,
    *,
    consumed_by_session_id: str = "",
    consumed_by_turn_id: str = "",
) -> dict[str, Any]:
    agent = get_agent(agent_id, include_archived=True)
    if not agent:
        raise AgentNotFoundError(f"Agent not found: {agent_id}")
    normalized_message_id = str(message_id or "").strip()
    if not normalized_message_id:
        raise AgentMessageNotFoundError("Agent inbox message id is required.")
    path = _agent_workspace_event_path(agent, "agent_inbox_messages.jsonl")
    messages = _read_jsonl(path)
    for item in messages:
        if str(item.get("messageId") or item.get("eventId") or "").strip() != normalized_message_id:
            continue
        if str(item.get("status") or "pending").strip().lower() != "consumed":
            item["status"] = "consumed"
            item["consumedAt"] = utc_now_iso()
            item["consumedBySessionId"] = str(consumed_by_session_id or agent.get("directSessionId") or "").strip()
            item["consumedByTurnId"] = str(consumed_by_turn_id or "").strip()
            _write_jsonl(path, messages)
            _record_memory_event("agent_inbox.message_consumed", item, agent_id=str(agent.get("agentId") or ""), lifecycle=True)
        return item
    raise AgentMessageNotFoundError(f"Agent inbox message not found: {message_id}")


def revoke_agent_inbox_message(
    agent_id: str,
    message_id: str,
    *,
    revoked_by: str = "user",
    reason: str = "",
) -> dict[str, Any]:
    agent = get_agent(agent_id, include_archived=True)
    if not agent:
        raise AgentNotFoundError(f"Agent not found: {agent_id}")
    normalized_message_id = str(message_id or "").strip()
    if not normalized_message_id:
        raise AgentMessageNotFoundError("Agent inbox message id is required.")
    path = _agent_workspace_event_path(agent, "agent_inbox_messages.jsonl")
    messages = _read_jsonl(path)
    for item in messages:
        if str(item.get("messageId") or item.get("eventId") or "").strip() != normalized_message_id:
            continue
        if str(item.get("status") or "pending").strip().lower() != "revoked":
            item["status"] = "revoked"
            item["promptEligible"] = False
            item["revokedAt"] = utc_now_iso()
            item["revokedBy"] = str(revoked_by or "user").strip() or "user"
            item["revokeReason"] = trim_lines(str(reason or ""), max_lines=2)
            _write_jsonl(path, messages)
            _record_memory_event("agent_inbox.message_revoked", item, agent_id=str(agent.get("agentId") or ""), lifecycle=True)
        return item
    raise AgentMessageNotFoundError(f"Agent inbox message not found: {message_id}")


def write_current_tool_observation(
    *,
    tool_name: str,
    status: str,
    summary: str = "",
    arg_keys: list[str] | None = None,
) -> dict[str, Any] | None:
    runtime = current_agent_runtime()
    agent_id = str(runtime.get("agentId") or "").strip()
    if not agent_id:
        return None
    agent = _find_agent(load_state(), agent_id)
    if not agent:
        return None
    event_payload = {
        "eventId": _new_event_id("toolobs"),
        "agentId": agent_id,
        "sessionId": str(runtime.get("sessionId") or "").strip(),
        "turnId": str(runtime.get("turnId") or "").strip(),
        "roomId": str(runtime.get("roomId") or "").strip(),
        "roundId": str(runtime.get("roundId") or "").strip(),
        "toolName": str(tool_name or "").strip(),
        "status": str(status or "").strip(),
        "summary": trim_lines(str(summary or ""), max_lines=4),
        "argKeys": list(arg_keys or [])[:24],
        "createdAt": utc_now_iso(),
    }
    path = _resolve_project_path(str(agent.get("workspacePath") or "")) / "events" / "tool_observations.jsonl"
    _append_jsonl(path, event_payload)
    _record_memory_event("memory.event_written", event_payload, agent_id=agent_id)
    return event_payload


def list_group_context_events_for_agent(agent_id: str, *, limit: int = 8, prompt_eligible_only: bool = False) -> list[dict[str, Any]]:
    state = load_state()
    agent = _find_agent(state, agent_id)
    if not agent:
        return []
    path = _resolve_project_path(str(agent.get("workspacePath") or "")) / "events" / "group_context_events.jsonl"
    events = _read_jsonl(path)
    if prompt_eligible_only:
        events = [item for item in events if bool(item.get("promptEligible", True))]
    return events[-max(1, int(limit or 1)) :]


def build_agent_runtime_context_block(agent_id: str, *, limit: int = 6) -> str:
    agent = get_agent(agent_id)
    if not agent:
        return ""
    events = list_group_context_events_for_agent(agent_id, limit=limit, prompt_eligible_only=True)
    inbox_messages = list_agent_inbox_messages_for_agent(
        agent_id,
        limit=limit,
        status="pending",
        prompt_eligible_only=True,
    )
    memory_policy = resolve_memory_policy_for_agent(agent_id)
    tool_policy = resolve_tool_policy_for_agent(agent_id)
    lines = [
        "## Agent Runtime Context",
        f"AgentId: {agent.get('agentId') or ''}",
        f"AgentCode: {agent.get('agentCode') or ''}",
        f"AgentName: {agent.get('displayName') or ''}",
        f"AgentWorkspace: {agent.get('workspacePath') or ''}",
        f"MemoryRoot: {memory_policy.get('privateMemoryRoot') or ''}",
        _format_tool_policy_summary(tool_policy),
    ]
    if events:
        lines.append("GroupContextEvents:")
        for event in events[-limit:]:
            topic = trim_lines(str(event.get("topic") or ""), max_lines=1)
            summary = trim_lines(str(event.get("summary") or ""), max_lines=2)
            own = trim_lines(str(event.get("ownMessage") or ""), max_lines=2)
            peers = "; ".join(
                trim_lines(str(item or ""), max_lines=1)
                for item in list(event.get("peerHighlights") or [])[:3]
                if str(item or "").strip()
            )
            lines.append(f"- room={event.get('sourceRoomId') or ''} round={event.get('sourceRoundId') or ''}")
            if topic:
                lines.append(f"  topic: {topic}")
            if summary:
                lines.append(f"  summary: {summary}")
            if own:
                lines.append(f"  ownMessage: {own}")
            if peers:
                lines.append(f"  peerHighlights: {peers}")
    else:
        lines.append("GroupContextEvents: none")
    if inbox_messages:
        lines.append("AgentInboxMessages:")
        for message in inbox_messages[-limit:]:
            source_label = _agent_message_source_label(message)
            content = trim_lines(str(message.get("content") or message.get("summary") or ""), max_lines=3)
            summary = trim_lines(str(message.get("summary") or ""), max_lines=2)
            lines.append(
                f"- messageId={message.get('messageId') or ''} from={source_label} status={message.get('status') or 'pending'}"
            )
            if content:
                lines.append(f"  content: {content}")
            if summary and summary != content:
                lines.append(f"  summary: {summary}")
            if message.get("sourceRoomId") or message.get("sourceRoundId"):
                lines.append(
                    f"  source: room={message.get('sourceRoomId') or ''} round={message.get('sourceRoundId') or ''}"
                )
    else:
        lines.append("AgentInboxMessages: none")
    return "\n".join(line for line in lines if line is not None).strip()


def default_tool_policy(policy_id: str = DEFAULT_TOOL_POLICY_ID) -> dict[str, Any]:
    return {
        "policyId": str(policy_id or DEFAULT_TOOL_POLICY_ID),
        "allowedTools": [],
        "preferredTools": [],
        "blockedTools": [],
        "readScopes": [],
        "writeScopes": [],
        "allowedCommandKinds": [],
        "blockedCommandPatterns": [],
        "networkAccess": "inherit",
        "mutationAccess": "inherit",
        "maxCallsPerTurn": 0,
        "perToolRules": {},
    }


def normalize_tool_policy(policy: dict[str, Any], policy_id: str = "") -> dict[str, Any]:
    raw_policy = policy if isinstance(policy, dict) else {}
    payload = default_tool_policy(policy_id or str(raw_policy.get("policyId") or raw_policy.get("id") or DEFAULT_TOOL_POLICY_ID))
    payload.update(raw_policy)
    for key in (
        "allowedTools",
        "preferredTools",
        "blockedTools",
        "allowedCommandKinds",
        "blockedCommandPatterns",
    ):
        payload[key] = [str(item or "").strip() for item in list(payload.get(key) or []) if str(item or "").strip()]
    payload["readScopes"] = _normalize_tool_policy_scopes(payload.get("readScopes"))
    payload["writeScopes"] = _normalize_tool_policy_scopes(payload.get("writeScopes"))
    payload["perToolRules"] = dict(payload.get("perToolRules") or {})
    try:
        payload["maxCallsPerTurn"] = max(0, int(payload.get("maxCallsPerTurn") or 0))
    except (TypeError, ValueError):
        payload["maxCallsPerTurn"] = 0
    return payload


def _normalize_tool_policy_scopes(scopes: Any) -> list[str]:
    normalized: list[str] = []
    raw_scopes = [scopes] if isinstance(scopes, str) else list(scopes or [])
    for item in raw_scopes:
        scope = str(item or "").strip().lower()
        if scope not in TOOL_POLICY_WORKSPACE_SCOPES or scope in normalized:
            continue
        normalized.append(scope)
    return normalized


def default_memory_policy(policy_id: str, agent_workspace_path: str) -> dict[str, Any]:
    workspace_path = _workspace_path_for_policy(str(agent_workspace_path or "").strip(), "")
    return {
        "policyId": str(policy_id or "").strip(),
        "privateMemoryRoot": f"{workspace_path}/memory" if workspace_path else "",
        "episodicEventsPath": f"{workspace_path}/events/episodic_events.jsonl" if workspace_path else "",
        "groupContextEventsPath": f"{workspace_path}/events/group_context_events.jsonl" if workspace_path else "",
        "agentInboxMessagesPath": f"{workspace_path}/events/agent_inbox_messages.jsonl" if workspace_path else "",
        "toolObservationsPath": f"{workspace_path}/events/tool_observations.jsonl" if workspace_path else "",
        "summariesPath": f"{workspace_path}/memory/summaries.jsonl" if workspace_path else "",
        "readSharedGroups": [],
        "writeSharedGroups": [],
    }


def normalize_memory_policy(policy: dict[str, Any], policy_id: str, agent_workspace_path: str) -> dict[str, Any]:
    payload = default_memory_policy(policy_id, agent_workspace_path)
    payload.update(policy if isinstance(policy, dict) else {})
    payload["policyId"] = str(policy_id or payload.get("policyId") or "").strip()
    workspace_path = _workspace_path_for_policy(str(agent_workspace_path or "").strip(), str(payload.get("privateMemoryRoot") or ""))
    for key, suffix in (
        ("privateMemoryRoot", "memory"),
        ("episodicEventsPath", "events/episodic_events.jsonl"),
        ("groupContextEventsPath", "events/group_context_events.jsonl"),
        ("agentInboxMessagesPath", "events/agent_inbox_messages.jsonl"),
        ("toolObservationsPath", "events/tool_observations.jsonl"),
        ("summariesPath", "memory/summaries.jsonl"),
    ):
        value = str(payload.get(key) or "").strip()
        if workspace_path:
            value = f"{workspace_path}/{suffix}"
        payload[key] = value
    for key in ("readSharedGroups", "writeSharedGroups"):
        payload[key] = _unique_string_list(payload.get(key))
    return payload


def normalize_delegation_policy(policy: dict[str, Any] | None) -> dict[str, Any]:
    source = policy if isinstance(policy, dict) else {}
    allowed_modes = [
        mode
        for mode in _unique_string_list(source.get("allowedContextModes"))
        if mode in {"isolated", "fork"}
    ]
    if not allowed_modes:
        allowed_modes = ["isolated"]
    return {
        "allowSubagents": bool(source.get("allowSubagents", False)),
        "maxConcurrent": _clamp_int(source.get("maxConcurrent"), minimum=0, maximum=8, default=0),
        "maxDepth": _clamp_int(source.get("maxDepth"), minimum=0, maximum=4, default=0),
        "allowWakeMessages": bool(source.get("allowWakeMessages", True)),
        "allowedContextModes": allowed_modes,
    }


def normalize_supervision_policy(policy: dict[str, Any] | None) -> dict[str, Any]:
    source = policy if isinstance(policy, dict) else {}
    review_mode = str(source.get("reviewMode") or "advisory").strip().lower()
    if review_mode not in {"advisory", "required", "disabled"}:
        review_mode = "advisory"
    evidence_level = str(source.get("evidenceLevel") or "standard").strip().lower()
    if evidence_level not in {"light", "standard", "strict"}:
        evidence_level = "standard"
    requires_review = bool(source.get("requiresReview", review_mode == "required"))
    if review_mode == "required":
        requires_review = True
    if review_mode == "disabled":
        requires_review = False
    return {
        "supervisionEnabled": bool(source.get("supervisionEnabled", False)),
        "requiresReview": requires_review,
        "reviewMode": review_mode,
        "evidenceLevel": evidence_level,
    }


def load_state() -> dict[str, Any]:
    with _STATE_LOCK:
        path = registry_path()
        if not path.exists():
            return default_state()
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return default_state()
        if not isinstance(payload, dict):
            return default_state()
        state = default_state()
        state.update(payload)
        state["agents"] = list(state.get("agents") or []) if isinstance(state.get("agents"), list) else []
        state["toolPolicies"] = _tool_policies(state)
        state["memoryPolicies"] = _memory_policies(state)
        return state


def save_state(state: dict[str, Any]) -> dict[str, Any]:
    with _STATE_LOCK:
        payload = default_state()
        payload.update(state if isinstance(state, dict) else {})
        payload["version"] = AGENT_REGISTRY_VERSION
        payload["updatedAt"] = utc_now_iso()
        payload["agents"] = list(payload.get("agents") or []) if isinstance(payload.get("agents"), list) else []
        payload["toolPolicies"] = _tool_policies(payload)
        payload["memoryPolicies"] = _memory_policies(payload)
        _atomic_write_json(registry_path(), payload)
        return payload


def registry_path() -> Path:
    return _project_root() / "workspace" / "agents" / "agents.json"


def _agent_to_api(agent: dict[str, Any]) -> dict[str, Any]:
    workspace = str(agent.get("workspacePath") or "").strip()
    return {
        "agentId": str(agent.get("agentId") or "").strip(),
        "agentCode": _normalize_agent_code(agent.get("agentCode"))
        or _fallback_agent_code(agent.get("agentId")),
        "displayName": str(agent.get("displayName") or "").strip(),
        "kind": str(agent.get("kind") or DEFAULT_AGENT_KIND).strip() or DEFAULT_AGENT_KIND,
        "primaryMode": _normalize_primary_mode(agent.get("primaryMode") or _infer_agent_primary_mode(agent)),
        "roleKey": _normalize_role_key(agent.get("roleKey") or _infer_agent_role_key(agent)),
        "templateId": str(agent.get("templateId") or agent.get("profileId") or "").strip(),
        "profileId": str(agent.get("profileId") or agent.get("templateId") or "").strip(),
        "promptTemplateId": _normalize_prompt_template_id(
            agent.get("promptTemplateId") or _infer_agent_prompt_template_id(agent)
        ),
        "directSessionId": str(agent.get("directSessionId") or "").strip(),
        "workspacePath": workspace,
        "workspaceTerritory": _agent_workspace_territory(agent),
        "toolPolicyId": str(agent.get("toolPolicyId") or DEFAULT_TOOL_POLICY_ID).strip() or DEFAULT_TOOL_POLICY_ID,
        "memoryPolicyId": str(agent.get("memoryPolicyId") or "").strip(),
        "createdBy": str(agent.get("createdBy") or "").strip(),
        "status": str(agent.get("status") or "active").strip() or "active",
        "metadata": dict(agent.get("metadata") or {}),
        "createdAt": str(agent.get("createdAt") or "").strip(),
        "updatedAt": str(agent.get("updatedAt") or "").strip(),
        "memoryPolicy": resolve_memory_policy_for_agent(str(agent.get("agentId") or "").strip()),
        "toolPolicy": resolve_tool_policy_for_agent(str(agent.get("agentId") or "").strip()),
        "groupContextEvents": list_group_context_events_for_agent(str(agent.get("agentId") or "").strip(), limit=8),
        "agentInboxMessages": list_agent_inbox_messages_for_agent(
            str(agent.get("agentId") or "").strip(),
            limit=8,
            status="pending",
        ),
        "agentInboxPendingCount": count_agent_inbox_messages_for_agent(
            str(agent.get("agentId") or "").strip(),
            status="pending",
        ),
    }


def _tool_policies(state: dict[str, Any]) -> dict[str, Any]:
    raw = state.get("toolPolicies")
    policies = dict(raw) if isinstance(raw, dict) else {}
    policies.setdefault(DEFAULT_TOOL_POLICY_ID, default_tool_policy(DEFAULT_TOOL_POLICY_ID))
    return {
        str(policy_id): normalize_tool_policy(policy if isinstance(policy, dict) else {}, str(policy_id))
        for policy_id, policy in policies.items()
    }


def _memory_policies(state: dict[str, Any]) -> dict[str, Any]:
    raw = state.get("memoryPolicies")
    policies = dict(raw) if isinstance(raw, dict) else {}
    return {
        str(policy_id): normalize_memory_policy(policy if isinstance(policy, dict) else {}, str(policy_id), "")
        for policy_id, policy in policies.items()
    }


def _workspace_path_for_policy(agent_workspace_path: str, existing_private_root: str = "") -> str:
    workspace_path = str(agent_workspace_path or "").strip()
    if workspace_path:
        return workspace_path
    private_root = str(existing_private_root or "").strip().replace("\\", "/")
    suffix = "/memory"
    if private_root.endswith(suffix):
        return private_root[: -len(suffix)]
    return ""


def _agent_workspace_territory(agent: dict[str, Any]) -> dict[str, Any]:
    agent_id = str(agent.get("agentId") or "").strip()
    private_root = str(agent.get("workspacePath") or _agent_workspace_relative_path(agent_id)).strip()
    if not _is_agent_private_workspace_path(private_root, agent_id):
        private_root = _agent_workspace_relative_path(agent_id)
    subdirs = {
        subdir: f"{private_root}/{subdir}"
        for subdir in AGENT_WORKSPACE_SUBDIRS
    }
    return {
        "schemaVersion": 1,
        "agentId": agent_id,
        "privateRoot": private_root,
        "sharedRoot": AGENT_SHARED_WORKSPACE_PATH,
        "defaultWriteScope": "private",
        "readScopes": list(AGENT_TERRITORY_READ_SCOPES),
        "writeScopes": list(AGENT_TERRITORY_WRITE_SCOPES),
        "subdirs": subdirs,
        "memoryRoot": subdirs.get("memory", ""),
        "eventsRoot": subdirs.get("events", ""),
        "artifactsRoot": subdirs.get("artifacts", ""),
        "scratchRoot": subdirs.get("scratch", ""),
        "inboxRoot": subdirs.get("inbox", ""),
        "outboxRoot": subdirs.get("outbox", ""),
        "runsRoot": subdirs.get("runs", ""),
        "legacyWorkspacePath": str((agent.get("metadata") or {}).get("legacyWorkspacePath") or "").strip()
        if isinstance(agent.get("metadata"), dict)
        else "",
    }


def _count_policy_refs(agents: list[dict[str, Any]], field: str, policy_id: str) -> int:
    return sum(1 for agent in agents if str(agent.get(field) or "").strip() == policy_id)


def _agent_archive_protected(agent: dict[str, Any]) -> bool:
    metadata = agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}
    system_role = str(metadata.get("systemRole") or metadata.get("researchOrgRole") or "").strip()
    return bool(metadata.get("protected")) or system_role in {"ceo", "organization_advisor"}


def _find_agent(state: dict[str, Any], agent_id: str) -> dict[str, Any] | None:
    normalized = str(agent_id or "").strip()
    if not normalized:
        return None
    for item in state.get("agents") or []:
        if isinstance(item, dict) and str(item.get("agentId") or "").strip() == normalized:
            return item
    return None


def _find_agent_by_direct_session(state: dict[str, Any], session_id: str) -> dict[str, Any] | None:
    normalized = str(session_id or "").strip()
    if not normalized:
        return None
    for item in state.get("agents") or []:
        if isinstance(item, dict) and str(item.get("directSessionId") or "").strip() == normalized:
            return item
    return None


def _new_agent_id(existing_ids: set[str] | None = None) -> str:
    existing = set(existing_ids or set())
    base = f"agent-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    candidate = base
    suffix = 2
    while candidate in existing:
        candidate = f"{base}-{suffix}"
        suffix += 1
    return candidate


def _normalize_agent_code(value: Any) -> str:
    normalized = re.sub(r"\s+", "", str(value or "").strip().upper())
    if _AGENT_CODE_PATTERN.match(normalized):
        return normalized
    return ""


def _unique_string_list(values: Any) -> list[str]:
    if values is None or isinstance(values, (str, bytes)):
        return []
    try:
        iterator = iter(values)
    except TypeError:
        return []
    result: list[str] = []
    seen: set[str] = set()
    for value in iterator:
        item = str(value or "").strip()
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return result


def _clamp_int(value: Any, *, minimum: int, maximum: int, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def _next_agent_code(
    agents: list[Any],
    *,
    used_codes: set[str] | None = None,
    exclude_agent_id: str = "",
) -> str:
    used = set(used_codes or set())
    for item in list(agents or []):
        if not isinstance(item, dict):
            continue
        if exclude_agent_id and str(item.get("agentId") or "").strip() == exclude_agent_id:
            continue
        code = _normalize_agent_code(item.get("agentCode"))
        if code:
            used.add(code)
    index = 1
    while True:
        candidate = f"{AGENT_CODE_PREFIX}{index:03d}"
        if candidate not in used:
            return candidate
        index += 1


def _fallback_agent_code(agent_id: Any) -> str:
    fragment = _safe_fragment(agent_id)[-3:].upper()
    return f"{AGENT_CODE_PREFIX}{fragment or '000'}"


def _agent_public_display_name(
    seed: str,
    *,
    existing_agents: list[Any],
    agent_id: str,
    metadata: dict[str, Any] | None = None,
) -> str:
    source = f"{agent_id}|{seed}|{(metadata or {}).get('supervisedRole') or ''}|{(metadata or {}).get('researchAgentKey') or ''}"
    total = sum((index + 1) * ord(char) for index, char in enumerate(source))
    names = [f"{family}{given}" for family in _PUBLIC_NAME_FAMILY for given in _PUBLIC_NAME_GIVEN]
    used = {
        str(item.get("displayName") or "").strip()
        for item in existing_agents
        if isinstance(item, dict) and str(item.get("agentId") or "").strip() != str(agent_id or "").strip()
    }
    for offset in range(len(names)):
        candidate = names[(total + offset) % len(names)]
        if candidate not in used:
            return candidate
    return f"{names[total % len(names)]}{len(used) + 1}"


def _with_functional_display_name(metadata: dict[str, Any], title: str) -> dict[str, Any]:
    result = dict(metadata or {})
    normalized = trim_lines(title or "", max_lines=1).strip()
    if normalized and not result.get("functionalDisplayName"):
        result["functionalDisplayName"] = normalized
    if normalized and _display_title_should_be_generated(normalized):
        result = _mark_display_name_generated(result)
    return result


def _mark_display_name_generated(metadata: dict[str, Any], *, force: bool = False) -> dict[str, Any]:
    result = dict(metadata or {})
    if force or str(result.get("displayNameSource") or "").strip() != "user":
        result["displayNameSource"] = "generated_person_name"
    return result


def _display_title_should_be_generated(title: str) -> bool:
    normalized = str(title or "").strip()
    if not normalized:
        return True
    lowered = normalized.lower()
    return (
        normalized == "Agent"
        or "agent" in lowered
        or "智能体" in normalized
        or _AGENT_ID_LIKE_PATTERN.match(normalized) is not None
    )


def _display_name_is_functional_or_machine(display_name: str, agent: dict[str, Any]) -> bool:
    metadata = agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}
    source = str(metadata.get("displayNameSource") or "").strip()
    normalized = str(display_name or "").strip()
    if source == "user":
        return _display_name_is_legacy_functional_user_name(normalized, agent)
    return (
        _display_title_should_be_generated(normalized)
        or normalized == str(metadata.get("functionalDisplayName") or "").strip()
    )


def _should_repair_public_display_name(agent: dict[str, Any], incoming_title: str) -> bool:
    metadata = agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}
    source = str(metadata.get("displayNameSource") or "").strip()
    if source == "user" and not _display_name_is_legacy_functional_user_name(agent.get("displayName") or "", agent):
        return False
    current = str(agent.get("displayName") or "").strip()
    if not current:
        return True
    return _display_name_is_functional_or_machine(current, agent) or _display_title_should_be_generated(incoming_title)


def _display_name_is_legacy_functional_user_name(display_name: str, agent: dict[str, Any]) -> bool:
    normalized = str(display_name or "").strip()
    if not normalized:
        return False
    metadata = agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}
    functional_names = {
        str(metadata.get("functionalDisplayName") or "").strip(),
        str(metadata.get("selfEvolutionRoleLabel") or "").strip(),
        str(metadata.get("supervisedRoleLabel") or "").strip(),
    }
    if normalized not in {item for item in functional_names if item}:
        return False
    if _display_title_should_be_generated(normalized):
        return True
    lowered = normalized.lower()
    if any(token in lowered or token in normalized for token in _FUNCTIONAL_DISPLAY_NAME_TOKENS):
        return True
    return _agent_has_functional_identity(agent)


def _agent_has_functional_identity(agent: dict[str, Any]) -> bool:
    metadata = agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}
    if any(str(metadata.get(key) or "").strip() for key in ("agentMode", "selfEvolutionRole", "supervisedRole", "researchAgentKey")):
        return True
    if bool(metadata.get("fixedRole")):
        return True
    return _normalize_primary_mode(agent.get("primaryMode")) in {"research", "self_evolution", "supervised_evolution"}


def _normalize_primary_mode(value: Any) -> str:
    normalized = str(value or "").strip().lower().replace("-", "_")
    return normalized if normalized in KNOWN_AGENT_PRIMARY_MODES else "general"


def _normalize_role_key(value: Any) -> str:
    return _safe_fragment(value).lower().replace("-", "_") if str(value or "").strip() else ""


def _normalize_prompt_template_id(value: Any) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        return ""
    return _safe_fragment(normalized)


def _infer_agent_primary_mode(agent: dict[str, Any]) -> str:
    metadata = agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}
    mode = str(metadata.get("agentMode") or metadata.get("primaryMode") or "").strip()
    if mode:
        return _normalize_primary_mode(mode)
    if str(metadata.get("researchAgentKey") or "").strip():
        return "research"
    if str(metadata.get("supervisedRole") or "").strip():
        return "supervised_evolution"
    created_by = str(agent.get("createdBy") or metadata.get("createdBy") or "").strip().lower()
    if "research" in created_by:
        return "research"
    if "supervised" in created_by:
        return "supervised_evolution"
    if "self_evolution" in created_by or "self-evolution" in created_by:
        return "self_evolution"
    return DEFAULT_AGENT_PRIMARY_MODE


def _infer_agent_role_key(agent: dict[str, Any]) -> str:
    metadata = agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}
    research_key = str(metadata.get("researchAgentKey") or "").strip()
    if research_key:
        return _normalize_role_key(f"research_{research_key}")
    supervised_role = str(metadata.get("supervisedRole") or "").strip()
    if supervised_role:
        return _normalize_role_key(supervised_role)
    return ""


def _infer_agent_prompt_template_id(agent: dict[str, Any]) -> str:
    metadata = agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}
    explicit = str(metadata.get("promptTemplateId") or "").strip()
    if explicit:
        return _normalize_prompt_template_id(explicit)
    research_key = str(metadata.get("researchAgentKey") or "").strip()
    if research_key:
        return _normalize_prompt_template_id(f"prompt-research-{research_key}")
    supervised_role = str(metadata.get("supervisedRole") or "").strip()
    if supervised_role:
        return _normalize_prompt_template_id(f"prompt-supervised-{supervised_role}")
    if _infer_agent_primary_mode(agent) == "chat":
        return "prompt-chat-default"
    return ""


def _new_event_id(prefix: str) -> str:
    return f"{prefix}-{datetime.now().strftime('%Y%m%d-%H%M%S-%f')}"


def _safe_fragment(value: Any) -> str:
    raw = str(value or "").strip()
    token = _SAFE_ID_FRAGMENT.sub("-", raw).strip("._-")
    return token or "agent"


def _agent_workspace_relative_path(agent_id: str) -> str:
    return f"workspace/agents/{_safe_fragment(agent_id)}"


def _is_agent_private_workspace_path(path_value: str, agent_id: str) -> bool:
    if not str(agent_id or "").strip():
        return False
    try:
        actual = _resolve_project_path(path_value)
        expected = _resolve_project_path(_agent_workspace_relative_path(agent_id))
    except Exception:
        return False
    return actual == expected


def _ensure_agent_workspace(path_value: str) -> Path:
    path = _resolve_project_path(path_value)
    agents_root = (_project_root() / "workspace" / "agents").resolve()
    if not path.is_relative_to(agents_root):
        raise AgentDirectoryError(f"Invalid agent workspace path: {path}")
    path.mkdir(parents=True, exist_ok=True)
    for subdir in AGENT_WORKSPACE_SUBDIRS:
        (path / subdir).mkdir(parents=True, exist_ok=True)
    ensure_agent_shared_workspace()
    return path


def _delete_purged_agent_workspace(agent: dict[str, Any]) -> dict[str, Any]:
    agent_id = str(agent.get("agentId") or "").strip()
    workspace_path = str(agent.get("workspacePath") or _agent_workspace_relative_path(agent_id)).strip()
    if not workspace_path:
        return {"deleted": False, "deletedPaths": [], "skippedPaths": []}
    try:
        resolved = _resolve_project_path(workspace_path)
        agents_root = (_project_root() / "workspace" / "agents").resolve()
    except Exception:
        return {"deleted": False, "deletedPaths": [], "skippedPaths": [workspace_path]}
    expected_private = _resolve_project_path(_agent_workspace_relative_path(agent_id))
    if resolved != expected_private:
        return {"deleted": False, "deletedPaths": [], "skippedPaths": [_relative_project_path(resolved)]}
    try:
        if not resolved.is_relative_to(agents_root):
            return {"deleted": False, "deletedPaths": [], "skippedPaths": [_relative_project_path(resolved)]}
    except ValueError:
        return {"deleted": False, "deletedPaths": [], "skippedPaths": [_relative_project_path(resolved)]}
    if not resolved.exists():
        return {"deleted": False, "deletedPaths": [], "skippedPaths": []}
    relative_path = _relative_project_path(resolved)
    try:
        shutil.rmtree(resolved)
    except Exception as exc:
        return {"deleted": False, "deletedPaths": [], "skippedPaths": [f"{relative_path} ({type(exc).__name__})"]}
    return {"deleted": True, "deletedPaths": [relative_path], "skippedPaths": []}


def _resolve_project_path(path_value: str) -> Path:
    raw = str(path_value or "").strip()
    path = Path(raw)
    if not path.is_absolute():
        path = _project_root() / path
    return path.resolve()


def _relative_project_path(path: Path) -> str:
    resolved = Path(path).resolve()
    root = _project_root().resolve()
    try:
        return resolved.relative_to(root).as_posix()
    except ValueError:
        return str(resolved)


def _path_is_within(path: Path, root: Path) -> bool:
    resolved_path = Path(path).resolve()
    resolved_root = Path(root).resolve()
    return resolved_path == resolved_root or resolved_root in resolved_path.parents


def _project_root() -> Path:
    root = Path(PROJECT_ROOT).resolve()
    return root.parent if root.name.lower() == "workspace" else root


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")


def _write_jsonl(path: Path, payloads: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        json.dumps(item, ensure_ascii=False, sort_keys=True)
        for item in list(payloads or [])
        if isinstance(item, dict)
    ]
    path.write_text(("\n".join(lines) + "\n") if lines else "", encoding="utf-8", newline="\n")


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    events: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    for line in lines:
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            events.append(payload)
    return events


def _agent_workspace_event_path(agent: dict[str, Any], filename: str) -> Path:
    return _resolve_project_path(str(agent.get("workspacePath") or "")) / "events" / filename


def _agent_inbox_thread_id(source_agent: dict[str, Any] | None, target_agent: dict[str, Any]) -> str:
    source_id = str((source_agent or {}).get("agentId") or "external").strip() or "external"
    target_id = str(target_agent.get("agentId") or "target").strip() or "target"
    return f"agent:{source_id}->{target_id}"


def _agent_message_source_label(message: dict[str, Any]) -> str:
    code = str(message.get("sourceAgentCode") or "").strip()
    name = str(message.get("sourceAgentName") or "").strip()
    source_id = str(message.get("sourceAgentId") or "").strip()
    if code and name:
        return f"{code} · {name}"
    return name or code or source_id or str(message.get("createdBy") or "external").strip() or "external"


def _safe_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(metadata, dict):
        return {}
    safe: dict[str, Any] = {}
    for key, value in list(metadata.items())[:32]:
        normalized_key = str(key or "").strip()
        if not normalized_key:
            continue
        if isinstance(value, (str, int, float, bool)) or value is None:
            safe[normalized_key] = value
        elif isinstance(value, (list, tuple)):
            safe[normalized_key] = [
                item if isinstance(item, (str, int, float, bool)) or item is None else str(item)
                for item in list(value)[:24]
            ]
        else:
            safe[normalized_key] = str(value)
    return safe


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
        deadline = time.monotonic() + WRITE_RETRY_TIMEOUT_SECONDS
        attempt = 0
        while True:
            try:
                os.replace(temp_path, path)
                if attempt:
                    _record_state_write_event(
                        "agent_directory.state_write_retried",
                        level="warning",
                        outcome="recovered",
                        fields={"attempts": attempt, "pathName": path.name},
                    )
                return
            except PermissionError as exc:
                attempt += 1
                if time.monotonic() >= deadline:
                    _record_state_write_event(
                        "agent_directory.state_write_failed",
                        level="error",
                        outcome="failed",
                        fields={"attempts": attempt, "pathName": path.name, "errorType": type(exc).__name__},
                    )
                    raise
                time.sleep(min(0.05 * attempt, 0.25))
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


def _record_state_write_event(
    event_code: str,
    *,
    level: str,
    outcome: str,
    fields: dict[str, Any],
) -> None:
    try:
        record_runtime_scene_event(
            "agent_directory",
            "state_write",
            event_code,
            message=event_code,
            level=level,
            outcome=outcome,
            fields=fields,
        )
    except Exception:
        return


def _blocked_decision(tool_name: str, reason: str, policy_id: str, agent_id: str, message: str) -> ToolPolicyDecision:
    return ToolPolicyDecision(False, message=message, reason=reason, policy_id=policy_id, agent_id=agent_id)


def _record_agent_event(event_code: str, agent: dict[str, Any], *, lifecycle: bool = False) -> None:
    try:
        record_runtime_scene_event(
            "agent_directory",
            "agent",
            event_code,
            message=event_code,
            level="info",
            outcome="observed",
            fields={
                "agentId": str(agent.get("agentId") or "").strip(),
                "agentCode": _normalize_agent_code(agent.get("agentCode")),
                "directSessionId": str(agent.get("directSessionId") or "").strip(),
                "primaryMode": _normalize_primary_mode(agent.get("primaryMode")),
                "roleKey": _normalize_role_key(agent.get("roleKey")),
                "profileId": str(agent.get("profileId") or "").strip(),
                "promptTemplateId": _normalize_prompt_template_id(agent.get("promptTemplateId")),
                "status": str(agent.get("status") or "").strip(),
            },
            lifecycle=lifecycle,
        )
    except Exception:
        return


def _record_agent_purged_event(agent: dict[str, Any], result: dict[str, Any]) -> None:
    try:
        record_runtime_scene_event(
            "agent_directory",
            "agent",
            "agent.purged",
            message="Archived Agent was permanently deleted.",
            level="warning",
            outcome="deleted",
            fields={
                "agentId": str(agent.get("agentId") or "").strip(),
                "agentCode": _normalize_agent_code(agent.get("agentCode")),
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


def _record_agent_territory_event(event_code: str, agent: dict[str, Any], *, outcome: str = "observed", level: str = "info") -> None:
    try:
        territory = _agent_workspace_territory(agent)
        record_runtime_scene_event(
            "agent_directory",
            "territory",
            event_code,
            message=event_code,
            level=level,
            outcome=outcome,
            fields={
                "agentId": str(agent.get("agentId") or "").strip(),
                "agentCode": _normalize_agent_code(agent.get("agentCode")),
                "privateRoot": str(territory.get("privateRoot") or "").strip(),
                "sharedRoot": str(territory.get("sharedRoot") or "").strip(),
                "defaultWriteScope": str(territory.get("defaultWriteScope") or "").strip(),
                "writeScopeCount": len(list(territory.get("writeScopes") or [])),
                "legacyWorkspace": bool(str(territory.get("legacyWorkspacePath") or "").strip()),
            },
            lifecycle=True,
        )
    except Exception:
        return


def _record_agent_territory_write_blocked(
    agent: dict[str, Any],
    decision: AgentWorkspaceWriteDecision,
    *,
    purpose: str = "",
) -> None:
    try:
        record_runtime_scene_event(
            "agent_directory",
            "territory",
            "agent_territory.write_blocked",
            message=decision.message or "Agent workspace write blocked.",
            level="warning",
            outcome="blocked",
            fields={
                "agentId": str(agent.get("agentId") or decision.agent_id or "").strip(),
                "agentCode": _normalize_agent_code(agent.get("agentCode")),
                "path": decision.path,
                "scope": decision.scope,
                "reason": decision.reason,
                "purpose": trim_lines(str(purpose or ""), max_lines=1),
            },
            lifecycle=True,
        )
    except Exception:
        return


def _record_agent_tool_policy_event(agent: dict[str, Any], policy: dict[str, Any]) -> None:
    try:
        record_runtime_scene_event(
            "agent_directory",
            "tool_policy",
            "agent.tool_policy.updated",
            message="agent.tool_policy.updated",
            level="info",
            outcome="observed",
            fields={
                "agentId": str(agent.get("agentId") or "").strip(),
                "agentCode": _normalize_agent_code(agent.get("agentCode")),
                "toolPolicyId": str(policy.get("policyId") or agent.get("toolPolicyId") or "").strip(),
                "allowedToolCount": len(list(policy.get("allowedTools") or [])),
                "blockedToolCount": len(list(policy.get("blockedTools") or [])),
                "preferredToolCount": len(list(policy.get("preferredTools") or [])),
                "readScopeCount": len(list(policy.get("readScopes") or [])),
                "writeScopeCount": len(list(policy.get("writeScopes") or [])),
                "sharedWriteEnabled": "shared" in set(_normalize_tool_policy_scopes(policy.get("writeScopes"))),
            },
            lifecycle=True,
        )
    except Exception:
        return


def _record_agent_memory_policy_event(agent: dict[str, Any], policy: dict[str, Any]) -> None:
    try:
        record_runtime_scene_event(
            "agent_directory",
            "memory_policy",
            "agent.memory_policy.updated",
            message="agent.memory_policy.updated",
            level="info",
            outcome="observed",
            fields={
                "agentId": str(agent.get("agentId") or "").strip(),
                "agentCode": _normalize_agent_code(agent.get("agentCode")),
                "memoryPolicyId": str(policy.get("policyId") or agent.get("memoryPolicyId") or "").strip(),
                "readSharedGroupCount": len(list(policy.get("readSharedGroups") or [])),
                "writeSharedGroupCount": len(list(policy.get("writeSharedGroups") or [])),
                "hasPrivateMemoryRoot": bool(str(policy.get("privateMemoryRoot") or "").strip()),
            },
            lifecycle=True,
        )
    except Exception:
        return


def _record_agent_delegation_policy_event(agent: dict[str, Any], policy: dict[str, Any]) -> None:
    try:
        record_runtime_scene_event(
            "agent_directory",
            "delegation_policy",
            "agent.delegation_policy.updated",
            message="agent.delegation_policy.updated",
            level="info",
            outcome="observed",
            fields={
                "agentId": str(agent.get("agentId") or "").strip(),
                "agentCode": _normalize_agent_code(agent.get("agentCode")),
                "allowSubagents": bool(policy.get("allowSubagents", False)),
                "maxConcurrent": int(policy.get("maxConcurrent") or 0),
                "maxDepth": int(policy.get("maxDepth") or 0),
                "allowWakeMessages": bool(policy.get("allowWakeMessages", False)),
                "allowedContextModeCount": len(list(policy.get("allowedContextModes") or [])),
            },
            lifecycle=True,
        )
    except Exception:
        return


def _record_agent_supervision_policy_event(agent: dict[str, Any], policy: dict[str, Any]) -> None:
    try:
        record_runtime_scene_event(
            "agent_directory",
            "supervision_policy",
            "agent.supervision_policy.updated",
            message="agent.supervision_policy.updated",
            level="info",
            outcome="observed",
            fields={
                "agentId": str(agent.get("agentId") or "").strip(),
                "agentCode": _normalize_agent_code(agent.get("agentCode")),
                "supervisionEnabled": bool(policy.get("supervisionEnabled", False)),
                "requiresReview": bool(policy.get("requiresReview", False)),
                "reviewMode": str(policy.get("reviewMode") or "").strip(),
                "evidenceLevel": str(policy.get("evidenceLevel") or "").strip(),
            },
            lifecycle=True,
        )
    except Exception:
        return


def _record_policy_block(
    agent_id: str,
    policy: dict[str, Any],
    tool_name: str,
    tool_args: dict[str, Any],
    decision: ToolPolicyDecision,
) -> None:
    try:
        record_runtime_scene_event(
            "tool_policy",
            "execute",
            "tool.policy_blocked",
            message=decision.message or "Tool policy blocked a call.",
            level="warning",
            outcome="blocked",
            fields={
                "agentId": agent_id,
                "policyId": str(policy.get("policyId") or policy.get("id") or decision.policy_id or ""),
                "toolName": str(tool_name or "").strip(),
                "argKeys": sorted(str(key) for key in (tool_args or {}).keys())[:24],
                "blockedReason": decision.reason,
            },
            lifecycle=True,
        )
    except Exception:
        return


def _record_delegation_policy_block(
    agent_id: str,
    policy: dict[str, Any],
    decision: DelegationPolicyDecision,
) -> None:
    try:
        record_runtime_scene_event(
            "delegation_policy",
            "execute",
            "delegation.policy_blocked",
            message=decision.message or "DelegationPolicy blocked a runtime delegation action.",
            level="warning",
            outcome="blocked",
            fields={
                "agentId": agent_id,
                "blockedReason": decision.reason,
                "contextMode": decision.context_mode,
                "maxDepth": decision.max_depth,
                "maxConcurrent": decision.max_concurrent,
                "allowSubagents": bool(policy.get("allowSubagents", False)),
                "allowWakeMessages": bool(policy.get("allowWakeMessages", True)),
            },
            lifecycle=True,
        )
    except Exception:
        return


def _record_supervision_policy_block(decision: SupervisionPolicyDecision) -> None:
    try:
        record_runtime_scene_event(
            "supervision_policy",
            "execute",
            "supervision.policy_blocked",
            message=decision.message or "SupervisionPolicy blocked a runtime action.",
            level="warning",
            outcome="blocked",
            fields={
                "agentId": decision.agent_id,
                "action": decision.action,
                "blockedReason": decision.reason,
                "requiresReview": decision.requires_review,
                "reviewMode": decision.review_mode,
                "evidenceLevel": decision.evidence_level,
            },
            lifecycle=True,
        )
    except Exception:
        return


def _record_supervision_policy_observed(decision: SupervisionPolicyDecision) -> None:
    try:
        record_runtime_scene_event(
            "supervision_policy",
            "execute",
            "supervision.policy_observed",
            message="SupervisionPolicy observed an advisory runtime action.",
            level="info",
            outcome="observed",
            fields={
                "agentId": decision.agent_id,
                "action": decision.action,
                "reason": decision.reason,
                "requiresReview": decision.requires_review,
                "reviewMode": decision.review_mode,
                "evidenceLevel": decision.evidence_level,
            },
            lifecycle=True,
        )
    except Exception:
        return


def _record_memory_event(event_code: str, payload: dict[str, Any], *, agent_id: str, lifecycle: bool = False) -> None:
    try:
        record_runtime_scene_event(
            "agent_memory",
            "events",
            event_code,
            message=event_code,
            level="info",
            outcome="written",
            fields={
                "agentId": agent_id,
                "eventId": str(payload.get("eventId") or "").strip(),
                "messageId": str(payload.get("messageId") or "").strip(),
                "sourceAgentId": str(payload.get("sourceAgentId") or "").strip(),
                "targetAgentId": str(payload.get("targetAgentId") or agent_id).strip(),
                "sourceRoomId": str(payload.get("sourceRoomId") or "").strip(),
                "sourceRoundId": str(payload.get("sourceRoundId") or "").strip(),
                "status": str(payload.get("status") or "").strip(),
                "promptEligible": bool(payload.get("promptEligible", True)),
            },
            lifecycle=lifecycle,
        )
    except Exception:
        return


def _format_tool_policy_summary(policy: dict[str, Any]) -> str:
    allowed = list(policy.get("allowedTools") or [])
    blocked = list(policy.get("blockedTools") or [])
    preferred = list(policy.get("preferredTools") or [])
    write_scopes = _normalize_tool_policy_scopes(policy.get("writeScopes"))
    parts = [f"ToolPolicy: {policy.get('policyId') or DEFAULT_TOOL_POLICY_ID}"]
    if allowed:
        parts.append(f"allowed={', '.join(allowed[:12])}")
    else:
        parts.append("allowed=global_pool")
    if preferred:
        parts.append(f"preferred={', '.join(preferred[:8])}")
    if blocked:
        parts.append(f"blocked={', '.join(blocked[:8])}")
    parts.append(f"writeScopes={', '.join(write_scopes) if write_scopes else 'private_only'}")
    return "; ".join(parts)
