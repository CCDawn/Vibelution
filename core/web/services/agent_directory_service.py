"""Persistent AgentInstance registry for chat-facing agents."""

from __future__ import annotations

import json
import os
import re
import tempfile
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
AGENT_WORKSPACE_SUBDIRS = ("conversation", "memory", "events", "tmp", "logs", "artifacts")
_SAFE_ID_FRAGMENT = re.compile(r"[^A-Za-z0-9_.-]+")
_CURRENT_AGENT_RUNTIME: ContextVar[dict[str, Any]] = ContextVar(
    "vibelution_current_agent_runtime",
    default={},
)


class AgentDirectoryError(ValueError):
    """Raised when an AgentInstance request is invalid."""


class AgentNotFoundError(AgentDirectoryError):
    """Raised when an AgentInstance does not exist."""


@dataclass(frozen=True)
class ToolPolicyDecision:
    allowed: bool
    message: str = ""
    reason: str = ""
    policy_id: str = ""
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
    direct_session_id: str = "",
    workspace_path: str = "",
    created_by: str = "user",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    state = load_state()
    existing_ids = {
        str(item.get("agentId") or "").strip()
        for item in state.get("agents") or []
        if isinstance(item, dict)
    }
    now = utc_now_iso()
    agent_id = _new_agent_id(existing_ids)
    title = trim_lines(display_name or "", max_lines=1).strip() or "Agent"
    normalized_profile = str(profile_id or template_id or "primary").strip() or "primary"
    normalized_template = str(template_id or normalized_profile).strip() or normalized_profile
    agent_workspace = workspace_path or _agent_workspace_relative_path(agent_id)
    _ensure_agent_workspace(agent_workspace)
    memory_policy_id = f"memory-{agent_id}"
    agent = {
        "agentId": agent_id,
        "displayName": title,
        "kind": DEFAULT_AGENT_KIND,
        "templateId": normalized_template,
        "profileId": normalized_profile,
        "directSessionId": str(direct_session_id or "").strip(),
        "workspacePath": agent_workspace,
        "toolPolicyId": DEFAULT_TOOL_POLICY_ID,
        "memoryPolicyId": memory_policy_id,
        "createdBy": str(created_by or "user").strip() or "user",
        "status": "active",
        "metadata": dict(metadata or {}),
        "createdAt": now,
        "updatedAt": now,
    }
    policies = _memory_policies(state)
    policies[memory_policy_id] = default_memory_policy(memory_policy_id, agent_workspace)
    state["agents"] = list(state.get("agents") or []) + [agent]
    state["memoryPolicies"] = policies
    save_state(state)
    _record_agent_event("agent.created", agent, lifecycle=True)
    return _agent_to_api(agent)


def ensure_agent_for_session(
    session_id: str,
    *,
    display_name: str = "",
    profile_id: str = "primary",
    existing_agent_id: str = "",
    session_workspace_path: str = "",
    created_by: str = "session_repair",
) -> dict[str, Any]:
    normalized_session_id = str(session_id or "").strip()
    if not normalized_session_id:
        raise AgentDirectoryError("Session id is required to bind an AgentInstance.")

    state = load_state()
    now = utc_now_iso()
    agent = _find_agent(state, existing_agent_id)
    if agent is None:
        agent = _find_agent_by_direct_session(state, normalized_session_id)
    if agent is None:
        created = create_agent_instance(
            display_name=display_name or normalized_session_id,
            template_id=profile_id,
            profile_id=profile_id,
            direct_session_id=normalized_session_id,
            created_by=created_by,
            metadata={"legacySessionWorkspacePath": str(session_workspace_path or "").strip()},
        )
        return created

    changed = False
    if str(agent.get("directSessionId") or "").strip() != normalized_session_id:
        agent["directSessionId"] = normalized_session_id
        changed = True
    title = trim_lines(display_name or "", max_lines=1).strip()
    if title and str(agent.get("displayName") or "").strip() != title:
        agent["displayName"] = title
        changed = True
    normalized_profile = str(profile_id or agent.get("profileId") or "primary").strip() or "primary"
    if str(agent.get("profileId") or "").strip() != normalized_profile:
        agent["profileId"] = normalized_profile
        agent["templateId"] = normalized_profile
        changed = True
    if str(agent.get("status") or "active").strip() == "archived":
        agent["status"] = "active"
        changed = True
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
    return _agent_to_api(agent)


def update_agent_instance(
    agent_id: str,
    *,
    display_name: str | None = None,
    profile_id: str | None = None,
    tool_policy: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    state = load_state()
    agent = _find_agent(state, agent_id)
    if agent is None:
        raise AgentNotFoundError(f"Agent not found: {agent_id}")
    if display_name is not None:
        title = trim_lines(display_name or "", max_lines=1).strip()
        if not title:
            raise AgentDirectoryError("Agent display name is required.")
        agent["displayName"] = title[:120].rstrip()
    if profile_id is not None:
        normalized = str(profile_id or "").strip() or "primary"
        agent["profileId"] = normalized
        agent["templateId"] = normalized
    if metadata is not None:
        current = dict(agent.get("metadata") or {})
        current.update(dict(metadata or {}))
        agent["metadata"] = current
    if status is not None:
        normalized_status = str(status or "").strip() or "active"
        if normalized_status not in {"active", "archived"}:
            raise AgentDirectoryError("Unsupported AgentInstance status.")
        agent["status"] = normalized_status
    if tool_policy is not None:
        policy_id = str(agent.get("toolPolicyId") or DEFAULT_TOOL_POLICY_ID).strip() or DEFAULT_TOOL_POLICY_ID
        if policy_id == DEFAULT_TOOL_POLICY_ID:
            policy_id = f"tool-{agent['agentId']}"
            agent["toolPolicyId"] = policy_id
        policies = _tool_policies(state)
        policies[policy_id] = normalize_tool_policy({**default_tool_policy(policy_id), **dict(tool_policy or {})}, policy_id)
        state["toolPolicies"] = policies
    agent["updatedAt"] = utc_now_iso()
    save_state(state)
    _record_agent_event("agent.updated", agent)
    return _agent_to_api(agent)


def archive_agent_instance(agent_id: str) -> dict[str, Any]:
    state = load_state()
    agent = _find_agent(state, agent_id)
    if agent is None:
        raise AgentNotFoundError(f"Agent not found: {agent_id}")
    agent["status"] = "archived"
    agent["updatedAt"] = utc_now_iso()
    save_state(state)
    _record_agent_event("agent.archived", agent, lifecycle=True)
    return _agent_to_api(agent)


def repair_agent_directory() -> dict[str, Any]:
    state = load_state()
    changed = False
    policies = _memory_policies(state)
    for agent in state.get("agents") or []:
        if not isinstance(agent, dict):
            continue
        workspace_path = str(agent.get("workspacePath") or "").strip()
        if not workspace_path:
            workspace_path = _agent_workspace_relative_path(str(agent.get("agentId") or "agent"))
            agent["workspacePath"] = workspace_path
            changed = True
        _ensure_agent_workspace(workspace_path)
        memory_policy_id = str(agent.get("memoryPolicyId") or "").strip() or f"memory-{agent.get('agentId')}"
        if str(agent.get("memoryPolicyId") or "").strip() != memory_policy_id:
            agent["memoryPolicyId"] = memory_policy_id
            changed = True
        if memory_policy_id and memory_policy_id not in policies:
            policies[memory_policy_id] = default_memory_policy(memory_policy_id, workspace_path)
            changed = True
    state["memoryPolicies"] = policies
    if changed:
        save_state(state)
    return state


def current_agent_runtime() -> dict[str, Any]:
    context = _CURRENT_AGENT_RUNTIME.get({})
    return dict(context) if isinstance(context, dict) else {}


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
        return list(tools or [])
    filtered = []
    for tool in list(tools or []):
        name = str(getattr(tool, "name", "") or "").strip()
        if not name:
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
    if isinstance(policy, dict):
        return dict(policy)
    return default_memory_policy(policy_id or f"memory-{agent_id}", str(agent.get("workspacePath") or ""))


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
    memory_policy = resolve_memory_policy_for_agent(agent_id)
    tool_policy = resolve_tool_policy_for_agent(agent_id)
    lines = [
        "## Agent Runtime Context",
        f"AgentId: {agent.get('agentId') or ''}",
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
    payload = default_tool_policy(policy_id or str(policy.get("policyId") or policy.get("id") or DEFAULT_TOOL_POLICY_ID))
    payload.update(policy if isinstance(policy, dict) else {})
    for key in (
        "allowedTools",
        "preferredTools",
        "blockedTools",
        "readScopes",
        "writeScopes",
        "allowedCommandKinds",
        "blockedCommandPatterns",
    ):
        payload[key] = [str(item or "").strip() for item in list(payload.get(key) or []) if str(item or "").strip()]
    payload["perToolRules"] = dict(payload.get("perToolRules") or {})
    try:
        payload["maxCallsPerTurn"] = max(0, int(payload.get("maxCallsPerTurn") or 0))
    except (TypeError, ValueError):
        payload["maxCallsPerTurn"] = 0
    return payload


def default_memory_policy(policy_id: str, agent_workspace_path: str) -> dict[str, Any]:
    workspace_path = str(agent_workspace_path or "").strip()
    return {
        "policyId": str(policy_id or "").strip(),
        "privateMemoryRoot": f"{workspace_path}/memory" if workspace_path else "",
        "episodicEventsPath": f"{workspace_path}/events/episodic_events.jsonl" if workspace_path else "",
        "groupContextEventsPath": f"{workspace_path}/events/group_context_events.jsonl" if workspace_path else "",
        "toolObservationsPath": f"{workspace_path}/events/tool_observations.jsonl" if workspace_path else "",
        "summariesPath": f"{workspace_path}/memory/summaries.jsonl" if workspace_path else "",
        "readSharedGroups": [],
        "writeSharedGroups": [],
    }


def load_state() -> dict[str, Any]:
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
    return PROJECT_ROOT / "workspace" / "agents" / "agents.json"


def _agent_to_api(agent: dict[str, Any]) -> dict[str, Any]:
    workspace = str(agent.get("workspacePath") or "").strip()
    return {
        "agentId": str(agent.get("agentId") or "").strip(),
        "displayName": str(agent.get("displayName") or "").strip(),
        "kind": str(agent.get("kind") or DEFAULT_AGENT_KIND).strip() or DEFAULT_AGENT_KIND,
        "templateId": str(agent.get("templateId") or agent.get("profileId") or "").strip(),
        "profileId": str(agent.get("profileId") or agent.get("templateId") or "").strip(),
        "directSessionId": str(agent.get("directSessionId") or "").strip(),
        "workspacePath": workspace,
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
    return dict(raw) if isinstance(raw, dict) else {}


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


def _new_event_id(prefix: str) -> str:
    return f"{prefix}-{datetime.now().strftime('%Y%m%d-%H%M%S-%f')}"


def _safe_fragment(value: Any) -> str:
    raw = str(value or "").strip()
    token = _SAFE_ID_FRAGMENT.sub("-", raw).strip("._-")
    return token or "agent"


def _agent_workspace_relative_path(agent_id: str) -> str:
    return f"workspace/agents/{_safe_fragment(agent_id)}"


def _ensure_agent_workspace(path_value: str) -> Path:
    path = _resolve_project_path(path_value)
    agents_root = (PROJECT_ROOT / "workspace" / "agents").resolve()
    if not path.is_relative_to(agents_root):
        raise AgentDirectoryError(f"Invalid agent workspace path: {path}")
    path.mkdir(parents=True, exist_ok=True)
    for subdir in AGENT_WORKSPACE_SUBDIRS:
        (path / subdir).mkdir(parents=True, exist_ok=True)
    return path


def _resolve_project_path(path_value: str) -> Path:
    raw = str(path_value or "").strip()
    path = Path(raw)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path.resolve()


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")


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


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
        os.replace(temp_path, path)
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


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
                "directSessionId": str(agent.get("directSessionId") or "").strip(),
                "profileId": str(agent.get("profileId") or "").strip(),
                "status": str(agent.get("status") or "").strip(),
            },
            lifecycle=lifecycle,
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
                "sourceRoomId": str(payload.get("sourceRoomId") or "").strip(),
                "sourceRoundId": str(payload.get("sourceRoundId") or "").strip(),
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
    parts = [f"ToolPolicy: {policy.get('policyId') or DEFAULT_TOOL_POLICY_ID}"]
    if allowed:
        parts.append(f"allowed={', '.join(allowed[:12])}")
    else:
        parts.append("allowed=global_pool")
    if preferred:
        parts.append(f"preferred={', '.join(preferred[:8])}")
    if blocked:
        parts.append(f"blocked={', '.join(blocked[:8])}")
    return "; ".join(parts)
