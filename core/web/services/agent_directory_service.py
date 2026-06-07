"""Persistent AgentInstance registry for chat-facing agents."""

from __future__ import annotations

import base64
import binascii
import json
import os
import re
import secrets
import shutil
import tempfile
import threading
import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Iterable
from urllib.parse import quote

from core.chat.chat_task_types import trim_lines
from core.llm.agent_runtime import (
    AGENT_LLM_SLOTS,
    DEFAULT_AGENT_LLM_SLOT,
    agent_dialogue_model_id,
    agent_llm_model_id,
    normalize_agent_llm_bindings,
)

from .runtime_scene_service import record_runtime_scene_event


PROJECT_ROOT = Path(__file__).resolve().parents[3]
AGENT_REGISTRY_VERSION = 1
DEFAULT_AGENT_KIND = "persistent"
DEFAULT_TOOL_POLICY_ID = "default"
DEFAULT_MEMORY_POLICY_ID = "private"
DEFAULT_AGENT_PRIMARY_MODE = "chat"
DEFAULT_SESSION_AGENT_ALLOWED_TOOLS = (
    # Codex-like local work loop: use cli_tool for locate/read/search/verify,
    # then edit through structured mutation tools.
    "apply_patch_tool",
    "apply_diff_edit_tool",
    "write_file_tool",
    "cli_tool",
    "python_lint_tool",
    "run_test_for_tool",
    # External and media capabilities stay available when the user intent needs them.
    "web_search_tool",
    "web_fetch_tool",
    "image2_generate_tool",
    # Conversation diagnostics and memory are core Agent capabilities.
    "conversation_log_inspect_tool",
    "create_child_session_tool",
    "list_child_sessions_tool",
    "session_reference_query_tool",
    "agent_message_tool",
    "get_core_context_tool",
    "get_current_goal_tool",
    "search_memory_tool",
    "search_error_archive_tool",
    "record_learning_tool",
    "compress_context_tool",
    # Lightweight state and repository evidence.
    "task_list_tool",
    "get_git_status_summary_tool",
    "get_recent_changes_tool",
    "get_entity_history_tool",
    "explain_current_worktree_tool",
)
DEFAULT_SESSION_AGENT_PREFERRED_TOOLS = (
    "cli_tool",
    "create_child_session_tool",
    "list_child_sessions_tool",
    "session_reference_query_tool",
    "conversation_log_inspect_tool",
    "get_core_context_tool",
    "search_memory_tool",
)
AGENT_LLM_BINDING_SLOTS = AGENT_LLM_SLOTS
KNOWLEDGE_STEWARD_AGENT_ID = "agent-knowledge-steward"
KNOWLEDGE_STEWARD_TOOL_POLICY_ID = "tool-knowledge-steward"
KNOWLEDGE_STEWARD_MEMORY_POLICY_ID = "memory-knowledge-steward"
KNOWLEDGE_STEWARD_ROLE_KEY = "knowledge_steward"
KNOWLEDGE_STEWARD_FUNCTIONAL_NAME = "知识库管理员"
KNOWLEDGE_STEWARD_DIRECT_SESSION_ID = "agent-knowledge-steward-direct"
AGENT_CODE_PREFIX = "A"
AGENT_SHARED_WORKSPACE_PATH = "workspace/shared"
AGENT_AVATAR_RELATIVE_DIR = PurePosixPath("workspace/avatars")
AGENT_AVATAR_FILENAMES = (
    "01-session-agent.png",
    "02-diagnose-agent.png",
    "03-inspect-agent.png",
    "04-summarize-agent.png",
    "05-broad-explorer.png",
    "06-deep-investigator.png",
    "07-evidence-reviewer.png",
    "08-theme-synthesizer.png",
    "09-card-planner.png",
    "image2-1779953260549-43de200a.png",
    "image2-1779954683508-9fcd1834.png",
)
AGENT_AVATAR_ROLE_DEFAULTS = (
    (("chat",), "01-session-agent.png"),
    (("general",), "01-session-agent.png"),
    (("research", "broad"), "05-broad-explorer.png"),
    (("research", "deep"), "06-deep-investigator.png"),
    (("research", "theme"), "08-theme-synthesizer.png"),
    (("research", "card"), "09-card-planner.png"),
    (("research", "planner"), "09-card-planner.png"),
    (("summar",), "04-summarize-agent.png"),
    (("review",), "07-evidence-reviewer.png"),
    (("evidence",), "07-evidence-reviewer.png"),
    (("judge",), "07-evidence-reviewer.png"),
    (("audit",), "03-inspect-agent.png"),
    (("inspect",), "03-inspect-agent.png"),
    (("diagnose",), "02-diagnose-agent.png"),
    (("debug",), "02-diagnose-agent.png"),
    (("baseline",), "02-diagnose-agent.png"),
    (("candidate",), "03-inspect-agent.png"),
)
AGENT_PERSONA_PROFILE_TEXT_FIELDS = (
    "gender",
    "age",
    "pronouns",
    "personality",
    "communicationStyle",
    "background",
    "collaborationPreference",
    "identityNotes",
)
AGENT_PERSONA_PROFILE_FIELDS = (*AGENT_PERSONA_PROFILE_TEXT_FIELDS, "expertise")
AGENT_PERSONA_PROFILE_TEXT_LINE_LIMITS = {
    "gender": 1,
    "age": 1,
    "pronouns": 1,
    "personality": 4,
    "communicationStyle": 4,
    "background": 6,
    "collaborationPreference": 4,
    "identityNotes": 6,
}
AGENT_TASK_PROFILE_TEXT_FIELDS = (
    "mission",
    "responsibilities",
    "preferredTasks",
    "avoidTasks",
    "successCriteria",
    "deliverables",
    "constraints",
    "handoffNotes",
)
AGENT_TASK_PROFILE_FIELDS = (*AGENT_TASK_PROFILE_TEXT_FIELDS, "taskTypes")
AGENT_TASK_PROFILE_TEXT_LINE_LIMITS = {
    "mission": 4,
    "responsibilities": 8,
    "preferredTasks": 8,
    "avoidTasks": 6,
    "successCriteria": 6,
    "deliverables": 6,
    "constraints": 6,
    "handoffNotes": 6,
}
AGENT_CREATION_REQUIRED_FIELDS = (
    "displayName",
    "llmBindings",
    "primaryMode",
    "roleKey",
    "promptTemplateId",
    "personaProfile",
    "taskProfile",
    "toolPolicy",
    "memoryPolicy",
)
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
EXPLICIT_TOOL_POLICY_REQUIRED_TOOLS = {
    "computer_use_task_tool",
    "knowledge_governance_tasks_tool",
    "knowledge_ingestion_tool",
    "knowledge_proposal_tool",
    "knowledge_governance_plan_tool",
    "knowledge_query_tool",
    "knowledge_rag_retrieve_tool",
    "knowledge_operations_health_tool",
    "knowledge_rating_suggestion_tool",
    "knowledge_steward_recommendations_tool",
    "knowledge_steward_workbench_tool",
    "research_knowledge_query_tool",
    "research_agent_creation_proposal_tool",
    "research_communication_edge_proposal_tool",
    "research_proposal_apply_tool",
    "record_learning_tool",
    "search_error_archive_tool",
    "search_memory_tool",
}
KNOWN_AGENT_PRIMARY_MODES = {"chat", "research", "self_evolution", "supervised_evolution", "general"}
WRITE_RETRY_TIMEOUT_SECONDS = 2.0
MAX_AGENT_AVATAR_IMAGE_BYTES = 5 * 1024 * 1024
_AGENT_AVATAR_CONTENT_TYPE_EXTENSIONS = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
}
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
_REPAIRED_STATE_CACHE_SIGNATURE: tuple[str, bool, int, int] | None = None
_REPAIRED_STATE_CACHE: dict[str, Any] | None = None
_JSONL_RECENT_CACHE: dict[tuple[str, bool, int, int, int, str, bool], list[dict[str, Any]]] = {}
_JSONL_COUNT_CACHE: dict[tuple[str, bool, int, int, str], int] = {}
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


class AgentMemoryProposalNotFoundError(AgentDirectoryError):
    """Raised when an Agent project-memory proposal does not exist."""


@dataclass(frozen=True)
class ToolPolicyDecision:
    allowed: bool
    message: str = ""
    reason: str = ""
    policy_id: str = ""
    agent_id: str = ""


@dataclass(frozen=True)
class EffectiveToolVisibility:
    policy_id: str
    visible_tools: tuple[str, ...] = ()
    configured_unavailable_tools: tuple[str, ...] = ()
    blocked_tools: tuple[str, ...] = ()
    hidden_restricted_tools: tuple[str, ...] = ()
    preferred_tools: tuple[str, ...] = ()
    write_scopes: tuple[str, ...] = ()


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


@dataclass(frozen=True)
class AgentApiHydrationContext:
    state: dict[str, Any]
    tool_policies: dict[str, dict[str, Any]]
    memory_policies: dict[str, dict[str, Any]]
    tool_governance_requests_by_agent: dict[str, list[dict[str, Any]]]
    group_context_events_by_agent: dict[str, list[dict[str, Any]]]
    agent_inbox_messages_by_agent: dict[str, list[dict[str, Any]]]
    agent_inbox_pending_count_by_agent: dict[str, int]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


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


def list_agents(*, include_archived: bool = False, detail: str = "full") -> list[dict[str, Any]]:
    started = time.perf_counter()
    timings: dict[str, float] = {}
    normalized_detail = str(detail or "full").strip().lower()
    if normalized_detail not in {"full", "summary"}:
        normalized_detail = "full"
    repair_cache_hit = False
    lock_wait_started = time.perf_counter()
    with _STATE_LOCK:
        timings["lock_wait"] = round((time.perf_counter() - lock_wait_started) * 1000, 1)
        stage_started = time.perf_counter()
        state, repair_cache_hit = _load_repaired_state_for_read()
        timings["repair"] = round((time.perf_counter() - stage_started) * 1000, 1)
    stage_started = time.perf_counter()
    raw_agents = [
        item
        for item in state.get("agents") or []
        if isinstance(item, dict) and (include_archived or str(item.get("status") or "active") != "archived")
    ]
    timings["filter"] = round((time.perf_counter() - stage_started) * 1000, 1)
    hydration_timings: dict[str, float] = {}
    if normalized_detail == "summary":
        timings["hydrate"] = 0.0
        stage_started = time.perf_counter()
        agents = [_agent_to_api_summary(item) for item in raw_agents]
        timings["to_api"] = round((time.perf_counter() - stage_started) * 1000, 1)
    else:
        stage_started = time.perf_counter()
        hydration = _build_agent_api_hydration_context(state, raw_agents, timings=hydration_timings)
        timings["hydrate"] = round((time.perf_counter() - stage_started) * 1000, 1)
        stage_started = time.perf_counter()
        agents = [_agent_to_api(item, hydration=hydration) for item in raw_agents]
        timings["to_api"] = round((time.perf_counter() - stage_started) * 1000, 1)
    stage_started = time.perf_counter()
    agents.sort(key=lambda item: str(item.get("updatedAt") or item.get("createdAt") or ""), reverse=True)
    timings["sort"] = round((time.perf_counter() - stage_started) * 1000, 1)
    timings["total"] = round((time.perf_counter() - started) * 1000, 1)
    _record_agent_list_loaded(
        include_archived=include_archived,
        detail=normalized_detail,
        raw_agent_count=len(raw_agents),
        returned_agent_count=len(agents),
        timings=timings,
        hydration_timings=hydration_timings,
        repair_cache_hit=repair_cache_hit,
    )
    return agents


def get_agent(agent_id: str, *, include_archived: bool = True) -> dict[str, Any] | None:
    normalized = str(agent_id or "").strip()
    if not normalized:
        return None
    with _STATE_LOCK:
        state, _ = _load_repaired_state_for_read()
        agent = _find_agent(state, normalized)
    if not agent:
        return None
    if not include_archived and str(agent.get("status") or "") == "archived":
        return None
    return _agent_to_api(agent)


def create_agent_instance(
    *,
    display_name: str = "",
    llm_bindings: dict[str, Any] | None = None,
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
        normalized_llm_bindings = normalize_agent_llm_bindings(llm_bindings)
        normalized_primary_mode = _normalize_primary_mode(primary_mode)
        normalized_role_key = _normalize_role_key(role_key)
        normalized_prompt_template_id = _normalize_prompt_template_id(prompt_template_id)
        agent_workspace = workspace_path or _agent_workspace_relative_path(agent_id)
        _ensure_agent_workspace(agent_workspace)
        tool_policy_id = _default_tool_policy_id_for_agent(agent_id, normalized_primary_mode)
        memory_policy_id = f"memory-{agent_id}"
        tool_policy = _default_tool_policy_for_agent(tool_policy_id, normalized_primary_mode)
        metadata_payload = _with_agent_creation_spec(
            metadata_payload,
            created_by=str(created_by or "user").strip() or "user",
            display_name=title,
            llm_bindings=normalized_llm_bindings,
            primary_mode=normalized_primary_mode,
            role_key=normalized_role_key,
            prompt_template_id=normalized_prompt_template_id,
            tool_policy_id=tool_policy_id,
            memory_policy_id=memory_policy_id,
            memory_policy={"policyId": memory_policy_id},
            created_at=now,
        )
        agent = {
            "agentId": agent_id,
            "agentCode": _next_agent_code(state.get("agents") or []),
            "displayName": public_name,
            "kind": DEFAULT_AGENT_KIND,
            "primaryMode": normalized_primary_mode,
            "roleKey": normalized_role_key,
            "llmBindings": normalized_llm_bindings,
            "promptTemplateId": normalized_prompt_template_id,
            "directSessionId": str(direct_session_id or "").strip(),
            "workspacePath": agent_workspace,
            "toolPolicyId": tool_policy_id,
            "memoryPolicyId": memory_policy_id,
            "createdBy": str(created_by or "user").strip() or "user",
            "status": "active",
            "metadata": _with_functional_display_name(metadata_payload, title),
            "createdAt": now,
            "updatedAt": now,
        }
        _ensure_agent_default_avatar(agent)
        tool_policies = _tool_policies(state)
        tool_policies[tool_policy_id] = tool_policy
        state["toolPolicies"] = tool_policies
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
    llm_bindings: dict[str, Any] | None = None,
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
        normalized_llm_bindings = normalize_agent_llm_bindings(llm_bindings)
        agent = _find_agent(state, existing_agent_id)
        if agent is None:
            agent = _find_agent_by_direct_session(state, normalized_session_id)
        if agent is None:
            created = create_agent_instance(
                display_name=display_name or normalized_session_id,
                llm_bindings=normalized_llm_bindings,
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
        if normalized_llm_bindings and normalize_agent_llm_bindings(agent.get("llmBindings")) != normalized_llm_bindings:
            agent["llmBindings"] = normalized_llm_bindings
            changed = True
        if str(agent.get("status") or "active").strip() == "archived":
            _record_agent_event("agent.ensure.skipped_archived", agent, lifecycle=True)
            raise AgentArchivedError(f"Archived Agent cannot be ensured for session: {agent.get('agentId') or ''}")
        policy_changed = _ensure_session_agent_tool_policy(state, agent)
        if policy_changed:
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
            _record_agent_territory_event("agent_territory.resolved", agent, outcome="repaired")
    return _agent_to_api(agent)


def update_agent_instance(
    agent_id: str,
    *,
    display_name: str | None = None,
    direct_session_id: str | None = None,
    llm_bindings: dict[str, Any] | None = None,
    primary_mode: str | None = None,
    role_key: str | None = None,
    prompt_template_id: str | None = None,
    tool_policy_id: str | None = None,
    memory_policy_id: str | None = None,
    tool_policy: dict[str, Any] | None = None,
    memory_policy: dict[str, Any] | None = None,
    delegation_policy: dict[str, Any] | None = None,
    supervision_policy: dict[str, Any] | None = None,
    persona_profile: dict[str, Any] | None = None,
    task_profile: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    status: str | None = None,
    preserve_generated_display_name: bool = False,
) -> dict[str, Any]:
    updated_tool_policy: dict[str, Any] | None = None
    updated_memory_policy: dict[str, Any] | None = None
    updated_delegation_policy: dict[str, Any] | None = None
    updated_supervision_policy: dict[str, Any] | None = None
    updated_persona_profile: dict[str, Any] | None = None
    updated_task_profile: dict[str, Any] | None = None
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
        if llm_bindings is not None:
            agent["llmBindings"] = normalize_agent_llm_bindings(llm_bindings)
        if direct_session_id is not None:
            agent["directSessionId"] = str(direct_session_id or "").strip()
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
        if persona_profile is not None:
            metadata_payload = dict(agent.get("metadata") or {})
            if _is_profileless_session_agent(agent):
                metadata_payload.pop("personaProfile", None)
            else:
                updated_persona_profile = normalize_persona_profile(persona_profile)
                metadata_payload["personaProfile"] = updated_persona_profile
            agent["metadata"] = metadata_payload
        if task_profile is not None:
            metadata_payload = dict(agent.get("metadata") or {})
            if _is_profileless_session_agent(agent):
                metadata_payload.pop("taskProfile", None)
            else:
                updated_task_profile = normalize_task_profile(task_profile)
                metadata_payload["taskProfile"] = updated_task_profile
            agent["metadata"] = metadata_payload
        _refresh_agent_onboarding_metadata(state, agent)
        _ensure_agent_default_avatar(agent)
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
    if updated_persona_profile is not None:
        _record_agent_persona_profile_event(agent, updated_persona_profile)
    if updated_task_profile is not None:
        _record_agent_task_profile_event(agent, updated_task_profile)
    return _agent_to_api(agent)


def list_agent_policy_options() -> dict[str, list[dict[str, Any]]]:
    """Return lightweight policy options for Agent configuration forms."""

    with _STATE_LOCK:
        state = repair_agent_directory()
    agents = [item for item in state.get("agents") or [] if isinstance(item, dict)]
    return build_agent_policy_options(state=state, agents=agents)


def build_agent_policy_options(
    *,
    state: dict[str, Any] | None = None,
    agents: list[dict[str, Any]] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Build lightweight policy options from an already-loaded Agent registry snapshot."""

    source_state = state if isinstance(state, dict) else load_state()
    source_agents = list(agents or [])
    if not source_agents:
        source_agents = [item for item in source_state.get("agents") or [] if isinstance(item, dict)]
    tool_policies = _tool_policies(source_state)
    memory_policies = _memory_policies(source_state)
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
                "readKnowledgeBaseCount": len(list(policy.get("readKnowledgeBaseIds") or [])),
                "proposeKnowledgeBaseCount": len(list(policy.get("proposeKnowledgeBaseIds") or [])),
                "reviewKnowledgeBaseCount": len(list(policy.get("reviewKnowledgeBaseIds") or [])),
                "rateKnowledgeBaseCount": len(list(policy.get("rateKnowledgeBaseIds") or [])),
                "hasInboxPath": bool(str(policy.get("agentInboxMessagesPath") or "").strip()),
            }
            for policy_id, policy in sorted(memory_policies.items())
        ],
    }


def archive_agent_instance(agent_id: str, *, repair_mode_bindings: bool = True) -> dict[str, Any]:
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
    if repair_mode_bindings:
        from .agent_mode_binding_service import remove_agent_from_mode_bindings

        remove_agent_from_mode_bindings(agent_id)
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
        tool_policy_id = str(agent.get("toolPolicyId") or "").strip()
        memory_policy_id = str(agent.get("memoryPolicyId") or "").strip()

    workspace_result = _delete_purged_agent_workspace(agent_snapshot)
    if list(workspace_result.get("skippedPaths") or []):
        skipped = ", ".join(str(item) for item in list(workspace_result.get("skippedPaths") or [])[:3])
        raise AgentDirectoryError(f"Agent workspace could not be fully deleted: {skipped}")

    with _STATE_LOCK:
        state = load_state()
        agent = _find_agent(state, normalized_agent_id)
        if agent is None:
            raise AgentNotFoundError(f"Agent not found: {normalized_agent_id}")
        if str(agent.get("status") or "active").strip() != "archived":
            raise AgentDirectoryError("Only archived Agents can be permanently deleted.")
        if _agent_archive_protected(agent):
            raise AgentDirectoryError("Protected core Agent cannot be purged.")
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
        if tool_policy_id and tool_policy_id != DEFAULT_TOOL_POLICY_ID and _count_policy_refs(agents, "toolPolicyId", tool_policy_id) == 0:
            policies = _tool_policies(state)
            removed_tool_policy = policies.pop(tool_policy_id, None) is not None
            state["toolPolicies"] = policies
        if memory_policy_id and _count_policy_refs(agents, "memoryPolicyId", memory_policy_id) == 0:
            policies = _memory_policies(state)
            removed_memory_policy = policies.pop(memory_policy_id, None) is not None
            state["memoryPolicies"] = policies
        save_state(state)

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


def reset_agent_instance(
    agent_id: str,
    *,
    clear_runtime_state: bool = True,
    reset_direct_session: bool = True,
    reset_persona_profile: bool = False,
    reset_task_profile: bool = False,
    reset_tool_policy: bool = False,
    reset_memory_policy: bool = False,
    reset_runtime_policy: bool = False,
) -> dict[str, Any]:
    """Reset a single Agent for debugging without changing team, room, or mode membership."""

    normalized_agent_id = str(agent_id or "").strip()
    if not normalized_agent_id:
        raise AgentDirectoryError("Agent id is required.")

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
    with _STATE_LOCK:
        state = load_state()
        agent = _find_agent(state, normalized_agent_id)
        if agent is None:
            raise AgentNotFoundError(f"Agent not found: {normalized_agent_id}")
        if str(agent.get("status") or "active").strip() == "archived":
            raise AgentDirectoryError("Archived Agent cannot be reset. Restore or purge archived data instead.")
        agent_snapshot = dict(agent)
        reset_summary["previousDirectSessionId"] = str(agent_snapshot.get("directSessionId") or "").strip()
        now = utc_now_iso()
        profileless_session_agent = _is_profileless_session_agent(agent)
        if reset_persona_profile:
            metadata = dict(agent.get("metadata") or {})
            if profileless_session_agent:
                metadata.pop("personaProfile", None)
            else:
                updated_persona_profile = normalize_persona_profile({})
                metadata["personaProfile"] = updated_persona_profile
                reset_summary["resetPersonaProfile"] = True
            agent["metadata"] = metadata
        if reset_task_profile:
            metadata = dict(agent.get("metadata") or {})
            if profileless_session_agent:
                metadata.pop("taskProfile", None)
            else:
                updated_task_profile = normalize_task_profile({})
                metadata["taskProfile"] = updated_task_profile
                reset_summary["resetTaskProfile"] = True
            agent["metadata"] = metadata
        if reset_tool_policy:
            previous_policy_id = str(agent.get("toolPolicyId") or DEFAULT_TOOL_POLICY_ID).strip() or DEFAULT_TOOL_POLICY_ID
            policy_id = _default_tool_policy_id_for_agent(normalized_agent_id, str(agent.get("primaryMode") or ""))
            agent["toolPolicyId"] = policy_id
            policies = _tool_policies(state)
            if previous_policy_id != DEFAULT_TOOL_POLICY_ID and _count_policy_refs(state.get("agents") or [], "toolPolicyId", previous_policy_id) == 0:
                policies.pop(previous_policy_id, None)
            policies[policy_id] = _default_tool_policy_for_agent(policy_id, str(agent.get("primaryMode") or ""))
            state["toolPolicies"] = policies
            updated_tool_policy = normalize_tool_policy(policies.get(policy_id) or default_tool_policy(policy_id), policy_id)
            reset_summary["resetToolPolicy"] = True
        if reset_memory_policy:
            policy_id = str(agent.get("memoryPolicyId") or "").strip() or f"memory-{normalized_agent_id}"
            workspace_path = _agent_workspace_relative_path(normalized_agent_id)
            agent["workspacePath"] = workspace_path
            agent["memoryPolicyId"] = policy_id
            _ensure_agent_workspace(workspace_path)
            policies = _memory_policies(state)
            updated_memory_policy = default_memory_policy(policy_id, workspace_path)
            policies[policy_id] = updated_memory_policy
            state["memoryPolicies"] = policies
            reset_summary["resetMemoryPolicy"] = True
        if reset_runtime_policy:
            metadata = dict(agent.get("metadata") or {})
            updated_delegation_policy = normalize_delegation_policy({})
            updated_supervision_policy = normalize_supervision_policy({})
            metadata["delegationPolicy"] = updated_delegation_policy
            metadata["supervisionPolicy"] = updated_supervision_policy
            agent["metadata"] = metadata
            reset_summary["resetRuntimePolicy"] = True
        agent["updatedAt"] = now
        save_state(state)

    if clear_runtime_state:
        runtime_cleanup = _clear_agent_runtime_state(agent_snapshot)
        reset_summary["clearedRuntimeState"] = True
        reset_summary["deletedPaths"] = list(runtime_cleanup.get("deletedPaths") or [])
        reset_summary["skippedPaths"] = list(runtime_cleanup.get("skippedPaths") or [])
    if reset_direct_session:
        direct_session_cleanup = _reset_agent_direct_session(agent_snapshot)
        reset_summary["resetDirectSession"] = bool(direct_session_cleanup.get("resetDirectSession"))
        reset_summary["replacementDirectSessionId"] = str(direct_session_cleanup.get("replacementDirectSessionId") or "").strip()
        reset_summary["skippedPaths"].extend(list(direct_session_cleanup.get("skippedPaths") or []))

    updated_agent = get_agent(normalized_agent_id)
    _record_agent_reset_event(updated_agent or agent_snapshot, reset_summary)
    if updated_tool_policy is not None and updated_agent:
        _record_agent_tool_policy_event(updated_agent, updated_tool_policy)
    if updated_memory_policy is not None and updated_agent:
        _record_agent_memory_policy_event(updated_agent, updated_memory_policy)
    if updated_delegation_policy is not None and updated_agent:
        _record_agent_delegation_policy_event(updated_agent, updated_delegation_policy)
    if updated_supervision_policy is not None and updated_agent:
        _record_agent_supervision_policy_event(updated_agent, updated_supervision_policy)
    if updated_persona_profile is not None and updated_agent:
        _record_agent_persona_profile_event(updated_agent, updated_persona_profile)
    if updated_task_profile is not None and updated_agent:
        _record_agent_task_profile_event(updated_agent, updated_task_profile)
    return {
        "agent": updated_agent,
        "resetSummary": reset_summary,
    }


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
        knowledge_steward_result = _ensure_knowledge_steward_agent(state)
        if knowledge_steward_result.get("changed"):
            changed = True
        display_name_repaired_agents: list[dict[str, Any]] = []
        avatar_defaulted_agents: list[dict[str, Any]] = []
        territory_repaired_agents: list[dict[str, Any]] = []
        llm_binding_migrated_agents: list[dict[str, Any]] = []
        used_agent_codes: set[str] = set()
        policies = _memory_policies(state)
        for agent in state.get("agents") or []:
            if not isinstance(agent, dict):
                continue
            llm_migration = _migrate_agent_llm_bindings_to_new_design(agent)
            if llm_migration.get("changed"):
                llm_binding_migrated_agents.append(
                    {
                        "agentId": str(agent.get("agentId") or "").strip(),
                        "agentCode": _normalize_agent_code(agent.get("agentCode")),
                        "legacyModelSourceId": str(llm_migration.get("legacyModelSourceId") or "").strip(),
                        "legacyTemplateId": str(llm_migration.get("legacyTemplateId") or "").strip(),
                        "dialogueModelId": str(llm_migration.get("dialogueModelId") or "").strip(),
                        "migrated": bool(llm_migration.get("migrated")),
                    }
                )
                changed = True
            if _normalize_agent_legacy_metadata_fields(agent):
                changed = True
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
            avatar_result = _ensure_agent_default_avatar(agent)
            if avatar_result:
                avatar_defaulted_agents.append(dict(agent))
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
            if _ensure_session_agent_tool_policy(state, agent):
                changed = True
            _refresh_agent_onboarding_metadata(state, agent)
        state["memoryPolicies"] = policies
        if changed:
            save_state(state)
            for repaired_agent in display_name_repaired_agents:
                _record_agent_event("agent.display_name_repaired", repaired_agent)
            if avatar_defaulted_agents:
                _record_agent_avatar_defaults_event(avatar_defaulted_agents)
            if knowledge_steward_result.get("changed"):
                _record_knowledge_steward_repaired_event(
                    knowledge_steward_result.get("agent") or {},
                    created=bool(knowledge_steward_result.get("created")),
                    repaired_fields=list(knowledge_steward_result.get("repairedFields") or []),
                )
            if llm_binding_migrated_agents:
                _record_agent_llm_binding_migration_event(llm_binding_migrated_agents)
            for repaired_agent in territory_repaired_agents:
                _record_agent_territory_event("agent_territory.resolved", repaired_agent, outcome="repaired")
        return state


def _load_repaired_state_for_read() -> tuple[dict[str, Any], bool]:
    """Return a repaired registry snapshot without repeating repair on every read."""

    global _REPAIRED_STATE_CACHE
    global _REPAIRED_STATE_CACHE_SIGNATURE
    signature = _registry_state_signature()
    if _REPAIRED_STATE_CACHE is not None and _REPAIRED_STATE_CACHE_SIGNATURE == signature:
        return _REPAIRED_STATE_CACHE, True
    state = repair_agent_directory()
    _REPAIRED_STATE_CACHE = state
    _REPAIRED_STATE_CACHE_SIGNATURE = _registry_state_signature()
    return state, False


def _invalidate_repaired_state_cache() -> None:
    global _REPAIRED_STATE_CACHE
    global _REPAIRED_STATE_CACHE_SIGNATURE
    _REPAIRED_STATE_CACHE = None
    _REPAIRED_STATE_CACHE_SIGNATURE = None


def _registry_state_signature() -> tuple[str, bool, int, int]:
    path = registry_path()
    try:
        stat = path.stat()
    except OSError:
        return (str(path), False, 0, 0)
    return (str(path), True, int(stat.st_mtime_ns), int(stat.st_size))


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
    agent = _agent_from_runtime_env(agent_id)
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


def _agent_from_runtime_env(agent_id: str) -> dict[str, Any]:
    agent = get_agent(agent_id) or {}
    env_bindings = _agent_llm_bindings_from_runtime_env()
    if not env_bindings:
        return agent
    payload = dict(agent) if isinstance(agent, dict) else {}
    payload["agentId"] = str(payload.get("agentId") or agent_id or "").strip()
    payload["llmBindings"] = {
        **normalize_agent_llm_bindings(payload.get("llmBindings")),
        **env_bindings,
    }
    payload.setdefault("directSessionId", str(os.environ.get("VIBELUTION_AGENT_DIRECT_SESSION_ID") or "").strip())
    payload.setdefault("workspacePath", str(os.environ.get("VIBELUTION_AGENT_WORKSPACE_PATH") or "").strip())
    metadata = dict(payload.get("metadata") or {})
    supervised_role = str(os.environ.get("VIBELUTION_SUPERVISED_ROLE") or "").strip()
    if supervised_role:
        metadata.setdefault("supervisedRole", supervised_role)
    if metadata:
        payload["metadata"] = metadata
    return payload


def _agent_llm_bindings_from_runtime_env() -> dict[str, dict[str, str]]:
    bindings: dict[str, dict[str, str]] = {}
    raw_bindings = str(os.environ.get("VIBELUTION_AGENT_LLM_BINDINGS_JSON") or "").strip()
    if raw_bindings:
        try:
            payload = json.loads(raw_bindings)
        except json.JSONDecodeError as exc:
            raise AgentDirectoryError("Runtime Agent LLM bindings env is not valid JSON.") from exc
        bindings = normalize_agent_llm_bindings(payload)
    model_id = str(os.environ.get("VIBELUTION_AGENT_LLM_MODEL_ID") or "").strip()
    if model_id:
        slot = str(os.environ.get("VIBELUTION_AGENT_LLM_SLOT") or DEFAULT_AGENT_LLM_SLOT).strip() or DEFAULT_AGENT_LLM_SLOT
        bindings[slot] = {"modelId": model_id}
    return bindings


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


def _tool_name_list(tools: Iterable[Any]) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()
    for tool in list(tools or []):
        name = str(getattr(tool, "name", "") or tool or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        names.append(name)
    return names


def compute_effective_tool_visibility(
    tools: Iterable[Any],
    *,
    policy: dict[str, Any] | None = None,
) -> EffectiveToolVisibility:
    normalized_policy = policy if isinstance(policy, dict) else {}
    policy_id = str(normalized_policy.get("policyId") or normalized_policy.get("id") or DEFAULT_TOOL_POLICY_ID).strip()
    policy_id = policy_id or DEFAULT_TOOL_POLICY_ID
    tool_names = _tool_name_list(tools)
    tool_name_set = set(tool_names)
    allowed = tuple(
        name
        for name in _tool_name_list(normalized_policy.get("allowedTools") or [])
        if name
    )
    blocked = tuple(
        name
        for name in _tool_name_list(normalized_policy.get("blockedTools") or [])
        if name
    )
    preferred = tuple(
        name
        for name in _tool_name_list(normalized_policy.get("preferredTools") or [])
        if name in tool_name_set
    )
    blocked_set = set(blocked)
    allowed_set = set(allowed)

    if not allowed_set and not blocked_set:
        visible = tuple(
            name
            for name in tool_names
            if name not in EXPLICIT_TOOL_POLICY_REQUIRED_TOOLS
        )
    else:
        visible = tuple(
            name
            for name in tool_names
            if name not in blocked_set
            and (not allowed_set or name in allowed_set)
            and (name not in EXPLICIT_TOOL_POLICY_REQUIRED_TOOLS or name in allowed_set)
        )

    hidden_restricted = tuple(
        name
        for name in sorted(EXPLICIT_TOOL_POLICY_REQUIRED_TOOLS)
        if name in tool_name_set and name not in visible
    )
    configured_unavailable = tuple(
        name
        for name in allowed
        if name not in tool_name_set
    )
    return EffectiveToolVisibility(
        policy_id=policy_id,
        visible_tools=visible,
        configured_unavailable_tools=configured_unavailable,
        blocked_tools=tuple(name for name in blocked if name),
        hidden_restricted_tools=hidden_restricted,
        preferred_tools=preferred,
        write_scopes=tuple(_normalize_tool_policy_scopes(normalized_policy.get("writeScopes"))),
    )


def effective_visible_tool_names_for_current_agent(tools: Iterable[Any] | None = None) -> list[str]:
    runtime = current_agent_runtime()
    if tools is None:
        try:
            from tools.Key_Tools import create_llm_facing_tools

            tools = create_llm_facing_tools()
        except Exception:
            tools = []
    visibility = compute_effective_tool_visibility(tools or [], policy=runtime.get("toolPolicy") or {})
    return list(visibility.visible_tools)


def filter_llm_tools_for_current_agent(tools: Iterable[Any]) -> list[Any]:
    tool_list = list(tools or [])
    visible_names = set(effective_visible_tool_names_for_current_agent(tool_list))
    return [
        tool
        for tool in tool_list
        if str(getattr(tool, "name", "") or "").strip() in visible_names
    ]


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


def disable_group_context_events_for_room(
    source_room_id: str,
    *,
    agent_ids: list[str] | None = None,
    reason: str = "chat_room_reset",
) -> dict[str, Any]:
    normalized_room_id = str(source_room_id or "").strip()
    if not normalized_room_id:
        return {"sourceRoomId": "", "changedAgentCount": 0, "disabledEventCount": 0}
    target_agent_ids = {
        str(item or "").strip()
        for item in list(agent_ids or [])
        if str(item or "").strip()
    }
    state = load_state()
    changed_agent_count = 0
    disabled_event_count = 0
    now = utc_now_iso()
    for agent in list(state.get("agents") or []):
        if not isinstance(agent, dict):
            continue
        agent_id = str(agent.get("agentId") or "").strip()
        if target_agent_ids and agent_id not in target_agent_ids:
            continue
        path = _agent_workspace_event_path(agent, "group_context_events.jsonl")
        events = _read_jsonl(path)
        changed = False
        agent_disabled_count = 0
        for event in events:
            if str(event.get("sourceRoomId") or "").strip() != normalized_room_id:
                continue
            if not bool(event.get("promptEligible", True)):
                continue
            event["promptEligible"] = False
            event["disabledAt"] = now
            event["disabledReason"] = trim_lines(str(reason or "chat_room_reset"), max_lines=1) or "chat_room_reset"
            changed = True
            agent_disabled_count += 1
        if not changed:
            continue
        _write_jsonl(path, events)
        changed_agent_count += 1
        disabled_event_count += agent_disabled_count
        _record_memory_event(
            "group_context.disabled_for_room",
            {
                "sourceRoomId": normalized_room_id,
                "targetAgentId": agent_id,
                "disabledEventCount": agent_disabled_count,
                "reason": trim_lines(str(reason or "chat_room_reset"), max_lines=1) or "chat_room_reset",
                "disabledAt": now,
            },
            agent_id=agent_id,
            lifecycle=True,
        )
    return {
        "sourceRoomId": normalized_room_id,
        "changedAgentCount": changed_agent_count,
        "disabledEventCount": disabled_event_count,
    }


def write_project_memory_update_proposal(
    agent_id: str,
    *,
    lane_id: str,
    update: str,
    focus: str = "",
    details: str = "",
    related_files: list[str] | None = None,
    source_session_id: str = "",
    source_turn_id: str = "",
) -> dict[str, Any]:
    agent = get_agent(agent_id, include_archived=False)
    if not agent:
        raise AgentNotFoundError(f"Agent not found: {agent_id}")
    normalized_lane_id = trim_lines(str(lane_id or ""), max_lines=1).strip()
    normalized_update = trim_lines(str(update or ""), max_lines=8).strip()
    if not normalized_lane_id:
        raise AgentDirectoryError("Project memory update lane id is required.")
    if not normalized_update:
        raise AgentDirectoryError("Project memory update summary is required.")
    now = utc_now_iso()
    proposal_id = _new_event_id("memupd")
    event_payload = {
        "eventId": proposal_id,
        "proposalId": proposal_id,
        "kind": "project_memory_update",
        "status": "pending",
        "agentId": str(agent.get("agentId") or "").strip(),
        "agentCode": str(agent.get("agentCode") or "").strip(),
        "agentName": str(agent.get("displayName") or "").strip(),
        "sessionId": str(source_session_id or agent.get("directSessionId") or "").strip(),
        "turnId": str(source_turn_id or "").strip(),
        "laneId": normalized_lane_id,
        "focus": trim_lines(str(focus or ""), max_lines=2),
        "update": normalized_update,
        "details": trim_lines(str(details or normalized_update), max_lines=12),
        "relatedFiles": _unique_string_list(list(related_files or []))[:12],
        "createdAt": now,
        "resolvedAt": "",
        "resolvedBy": "",
        "resolutionNote": "",
    }
    path = _agent_workspace_event_path(agent, "project_memory_updates.jsonl")
    _append_jsonl(path, event_payload)
    _record_memory_event("memory.event_written", event_payload, agent_id=str(agent.get("agentId") or ""))
    _record_memory_event(
        "project_memory_update.proposed",
        event_payload,
        agent_id=str(agent.get("agentId") or ""),
        lifecycle=True,
    )
    return event_payload


def list_project_memory_update_proposals(
    *,
    agent_id: str = "",
    status: str = "pending",
    limit: int = 50,
) -> list[dict[str, Any]]:
    state = load_state()
    normalized_agent_id = str(agent_id or "").strip()
    if normalized_agent_id:
        agents = [_find_agent(state, normalized_agent_id)]
    else:
        agents = [item for item in state.get("agents") or [] if isinstance(item, dict)]
    normalized_status = str(status or "").strip().lower()
    proposals: list[dict[str, Any]] = []
    for agent in agents:
        if not agent:
            continue
        path = _agent_workspace_event_path(agent, "project_memory_updates.jsonl")
        for item in _read_jsonl(path):
            if normalized_status and str(item.get("status") or "pending").strip().lower() != normalized_status:
                continue
            proposals.append(item)
    proposals.sort(
        key=lambda item: (
            str(item.get("createdAt") or ""),
            str(item.get("proposalId") or item.get("eventId") or ""),
        )
    )
    return proposals[: max(1, int(limit or 1))]


def resolve_project_memory_update_proposal(
    agent_id: str,
    proposal_id: str,
    *,
    status: str,
    resolved_by: str = "",
    resolution_note: str = "",
) -> dict[str, Any]:
    agent = get_agent(agent_id, include_archived=True)
    if not agent:
        raise AgentNotFoundError(f"Agent not found: {agent_id}")
    normalized_proposal_id = str(proposal_id or "").strip()
    if not normalized_proposal_id:
        raise AgentMemoryProposalNotFoundError("Project memory update proposal id is required.")
    normalized_status = str(status or "").strip().lower()
    if normalized_status not in {"pending", "applied", "rejected", "conflict", "superseded"}:
        raise AgentDirectoryError("Unsupported project memory update proposal status.")
    path = _agent_workspace_event_path(agent, "project_memory_updates.jsonl")
    proposals = _read_jsonl(path)
    for item in proposals:
        if str(item.get("proposalId") or item.get("eventId") or "").strip() != normalized_proposal_id:
            continue
        item["status"] = normalized_status
        if normalized_status == "pending":
            item["resolvedAt"] = ""
            item["resolvedBy"] = ""
            item["resolutionNote"] = ""
        else:
            item["resolvedAt"] = utc_now_iso()
            item["resolvedBy"] = trim_lines(str(resolved_by or "coordinator"), max_lines=1) or "coordinator"
            item["resolutionNote"] = trim_lines(str(resolution_note or ""), max_lines=4)
        _write_jsonl(path, proposals)
        _record_memory_event(
            "project_memory_update.resolved",
            item,
            agent_id=str(agent.get("agentId") or ""),
            lifecycle=True,
        )
        return item
    raise AgentMemoryProposalNotFoundError(f"Project memory update proposal not found: {proposal_id}")


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
    normalized_content = str(content or "").strip()
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
    messages = _read_recent_jsonl(path, limit=max(1, int(limit or 1)), status=status)
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
    return _count_jsonl_matching_status(_agent_workspace_event_path(agent, "agent_inbox_messages.jsonl"), status=status)


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


def consume_all_agent_inbox_messages(
    agent_id: str,
    *,
    consumed_by_session_id: str = "",
    consumed_by_turn_id: str = "",
) -> dict[str, Any]:
    agent = get_agent(agent_id, include_archived=True)
    if not agent:
        raise AgentNotFoundError(f"Agent not found: {agent_id}")
    path = _agent_workspace_event_path(agent, "agent_inbox_messages.jsonl")
    messages = _read_jsonl(path)
    now = utc_now_iso()
    consumed_ids: list[str] = []
    for item in messages:
        if str(item.get("status") or "pending").strip().lower() == "consumed":
            continue
        item["status"] = "consumed"
        item["consumedAt"] = now
        item["consumedBySessionId"] = str(consumed_by_session_id or agent.get("directSessionId") or "").strip()
        item["consumedByTurnId"] = str(consumed_by_turn_id or "").strip()
        consumed_ids.append(str(item.get("messageId") or item.get("eventId") or "").strip())
    if consumed_ids:
        _write_jsonl(path, messages)
        _record_memory_event(
            "agent_inbox.messages_consumed",
            {
                "eventId": _new_event_id("agentinbox"),
                "messageId": "",
                "targetAgentId": str(agent.get("agentId") or "").strip(),
                "status": "consumed",
                "createdAt": now,
                "metadata": {"consumedCount": len(consumed_ids)},
            },
            agent_id=str(agent.get("agentId") or ""),
            lifecycle=True,
        )
    return {
        "agentId": str(agent.get("agentId") or "").strip(),
        "consumed": True,
        "consumedCount": len(consumed_ids),
        "consumedMessageIds": [item for item in consumed_ids if item],
        "remainingPendingCount": count_agent_inbox_messages_for_agent(agent_id, status="pending"),
    }


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
    events = _read_recent_jsonl(path, limit=max(1, int(limit or 1)))
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
    lines = [
        "## Agent Runtime Context",
        f"AgentId: {agent.get('agentId') or ''}",
        f"AgentCode: {agent.get('agentCode') or ''}",
        f"AgentName: {agent.get('displayName') or ''}",
        f"AgentWorkspace: {agent.get('workspacePath') or ''}",
        f"MemoryRoot: {memory_policy.get('privateMemoryRoot') or ''}",
        f"ProjectMemoryUpdatesPath: {memory_policy.get('projectMemoryUpdatesPath') or ''}",
        "TeamKnowledgeAccess:",
        f"- ReadKnowledgeBaseIds: {', '.join(list(memory_policy.get('readKnowledgeBaseIds') or [])) or 'team-membership'}",
        f"- ProposeKnowledgeBaseIds: {', '.join(list(memory_policy.get('proposeKnowledgeBaseIds') or [])) or 'team-membership'}",
        f"- ReviewKnowledgeBaseIds: {', '.join(list(memory_policy.get('reviewKnowledgeBaseIds') or [])) or 'team-review-roles'}",
        f"- RateKnowledgeBaseIds: {', '.join(list(memory_policy.get('rateKnowledgeBaseIds') or [])) or 'team-review-roles'}",
        "- Knowledge bodies are tool-readable only; do not treat team knowledge as prompt-injected memory.",
    ]
    persona_lines = _format_persona_profile_context(agent.get("personaProfile"))
    if persona_lines:
        lines.extend(persona_lines)
    task_lines = _format_task_profile_context(agent.get("taskProfile"))
    if task_lines:
        lines.extend(task_lines)
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


def default_session_agent_tool_policy(policy_id: str) -> dict[str, Any]:
    payload = default_tool_policy(policy_id)
    payload["allowedTools"] = list(DEFAULT_SESSION_AGENT_ALLOWED_TOOLS)
    payload["preferredTools"] = list(DEFAULT_SESSION_AGENT_PREFERRED_TOOLS)
    payload["readScopes"] = ["private", "shared"]
    payload["writeScopes"] = ["private"]
    return payload


def _default_tool_policy_id_for_agent(agent_id: str, primary_mode: str) -> str:
    if _is_session_agent_primary_mode(primary_mode):
        return f"tool-{agent_id}"
    return DEFAULT_TOOL_POLICY_ID


def _default_tool_policy_for_agent(policy_id: str, primary_mode: str) -> dict[str, Any]:
    if _is_session_agent_primary_mode(primary_mode):
        return default_session_agent_tool_policy(policy_id)
    return default_tool_policy(policy_id)


def _is_session_agent_primary_mode(primary_mode: str) -> bool:
    return str(primary_mode or "").strip() in {"", "chat"}


def _is_profileless_session_agent(agent: dict[str, Any]) -> bool:
    primary_mode = _normalize_primary_mode(agent.get("primaryMode") or _infer_agent_primary_mode(agent))
    role_key = _normalize_role_key(agent.get("roleKey") or _infer_agent_role_key(agent))
    return _is_session_agent_primary_mode(primary_mode) and not role_key


def _ensure_session_agent_tool_policy(state: dict[str, Any], agent: dict[str, Any]) -> bool:
    if not _is_session_agent_primary_mode(str(agent.get("primaryMode") or "")):
        return False
    agent_id = str(agent.get("agentId") or "").strip()
    if not agent_id:
        return False
    policies = _tool_policies(state)
    current_policy_id = str(agent.get("toolPolicyId") or DEFAULT_TOOL_POLICY_ID).strip() or DEFAULT_TOOL_POLICY_ID
    current_policy = normalize_tool_policy(policies.get(current_policy_id) or default_tool_policy(current_policy_id), current_policy_id)
    allowed = set(_tool_name_list(current_policy.get("allowedTools") or []))
    preferred = set(_tool_name_list(current_policy.get("preferredTools") or []))
    needs_session_defaults = (
        current_policy_id == DEFAULT_TOOL_POLICY_ID
        or not allowed
        or not set(DEFAULT_SESSION_AGENT_ALLOWED_TOOLS).issubset(allowed)
    )
    if not needs_session_defaults:
        return False

    policy_id = current_policy_id if current_policy_id != DEFAULT_TOOL_POLICY_ID else f"tool-{agent_id}"
    merged_allowed = [
        *list(current_policy.get("allowedTools") or []),
        *list(DEFAULT_SESSION_AGENT_ALLOWED_TOOLS),
    ]
    merged_preferred = [
        *list(DEFAULT_SESSION_AGENT_PREFERRED_TOOLS),
        *list(current_policy.get("preferredTools") or []),
    ]
    updated = normalize_tool_policy(
        {
            **current_policy,
            "policyId": policy_id,
            "allowedTools": merged_allowed,
            "preferredTools": merged_preferred,
            "readScopes": current_policy.get("readScopes") or ["private", "shared"],
            "writeScopes": current_policy.get("writeScopes") or ["private"],
        },
        policy_id,
    )
    policies[policy_id] = updated
    state["toolPolicies"] = policies
    agent["toolPolicyId"] = policy_id
    return True


def normalize_persona_profile(profile: dict[str, Any] | None) -> dict[str, Any]:
    raw = profile if isinstance(profile, dict) else {}
    normalized: dict[str, Any] = {}
    for field in AGENT_PERSONA_PROFILE_TEXT_FIELDS:
        normalized[field] = trim_lines(
            str(raw.get(field) or ""),
            max_lines=AGENT_PERSONA_PROFILE_TEXT_LINE_LIMITS.get(field, 3),
        ).strip()
    expertise_values: list[str] = []
    raw_expertise = raw.get("expertise")
    if isinstance(raw_expertise, str):
        candidates = re.split(r"[,，;；\n]+", raw_expertise)
    elif isinstance(raw_expertise, (list, tuple)):
        candidates = list(raw_expertise)
    else:
        candidates = []
    seen: set[str] = set()
    for item in candidates:
        value = trim_lines(str(item or ""), max_lines=1).strip()
        if not value or value in seen:
            continue
        expertise_values.append(value[:80].rstrip())
        seen.add(value)
        if len(expertise_values) >= 12:
            break
    normalized["expertise"] = expertise_values
    return normalized


def agent_persona_profile_has_content(profile: dict[str, Any] | None) -> bool:
    return _persona_profile_has_content(normalize_persona_profile(profile))


def _persona_profile_has_content(profile: dict[str, Any]) -> bool:
    return any(str(profile.get(field) or "").strip() for field in AGENT_PERSONA_PROFILE_TEXT_FIELDS) or bool(profile.get("expertise"))


def _persona_profile_for_agent(agent: dict[str, Any]) -> dict[str, Any]:
    metadata = agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}
    raw = metadata.get("personaProfile") if isinstance(metadata.get("personaProfile"), dict) else {}
    return normalize_persona_profile(raw)


def _format_persona_profile_context(profile: Any) -> list[str]:
    normalized = normalize_persona_profile(profile if isinstance(profile, dict) else {})
    if not _persona_profile_has_content(normalized):
        return []
    labels = {
        "gender": "Gender",
        "age": "Age",
        "pronouns": "Pronouns",
        "personality": "Personality",
        "communicationStyle": "CommunicationStyle",
        "background": "Background",
        "collaborationPreference": "CollaborationPreference",
        "identityNotes": "IdentityNotes",
    }
    lines = [
        "AgentPersonaProfile:",
        "- Contract: descriptive persona and collaboration guidance; do not use age/gender as capability, permission, or safety gates.",
    ]
    for field in AGENT_PERSONA_PROFILE_TEXT_FIELDS:
        value = str(normalized.get(field) or "").strip()
        if value:
            lines.append(f"- {labels[field]}: {value}")
    expertise = [str(item or "").strip() for item in list(normalized.get("expertise") or []) if str(item or "").strip()]
    if expertise:
        lines.append(f"- Expertise: {', '.join(expertise[:12])}")
    return lines


def normalize_task_profile(profile: dict[str, Any] | None) -> dict[str, Any]:
    raw = profile if isinstance(profile, dict) else {}
    normalized: dict[str, Any] = {}
    for field in AGENT_TASK_PROFILE_TEXT_FIELDS:
        normalized[field] = trim_lines(
            str(raw.get(field) or ""),
            max_lines=AGENT_TASK_PROFILE_TEXT_LINE_LIMITS.get(field, 4),
        ).strip()
    task_types: list[str] = []
    raw_task_types = raw.get("taskTypes")
    if isinstance(raw_task_types, str):
        candidates = re.split(r"[,，;；\n]+", raw_task_types)
    elif isinstance(raw_task_types, (list, tuple)):
        candidates = list(raw_task_types)
    else:
        candidates = []
    seen: set[str] = set()
    for item in candidates:
        value = trim_lines(str(item or ""), max_lines=1).strip()
        if not value or value in seen:
            continue
        task_types.append(value[:80].rstrip())
        seen.add(value)
        if len(task_types) >= 16:
            break
    normalized["taskTypes"] = task_types
    return normalized


def agent_task_profile_has_content(profile: dict[str, Any] | None) -> bool:
    return _task_profile_has_content(normalize_task_profile(profile))


def _task_profile_has_content(profile: dict[str, Any]) -> bool:
    return any(str(profile.get(field) or "").strip() for field in AGENT_TASK_PROFILE_TEXT_FIELDS) or bool(profile.get("taskTypes"))


def _task_profile_for_agent(agent: dict[str, Any]) -> dict[str, Any]:
    metadata = agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}
    raw = metadata.get("taskProfile") if isinstance(metadata.get("taskProfile"), dict) else {}
    return normalize_task_profile(raw)


def _with_agent_creation_spec(
    metadata: dict[str, Any],
    *,
    created_by: str,
    display_name: str,
    llm_bindings: dict[str, Any],
    primary_mode: str,
    role_key: str,
    prompt_template_id: str,
    tool_policy_id: str,
    memory_policy_id: str,
    memory_policy: dict[str, Any] | None = None,
    created_at: str,
) -> dict[str, Any]:
    payload = dict(metadata or {})
    persona_profile = normalize_persona_profile(payload.get("personaProfile") if isinstance(payload.get("personaProfile"), dict) else {})
    task_profile = normalize_task_profile(payload.get("taskProfile") if isinstance(payload.get("taskProfile"), dict) else {})
    is_work_session = _is_session_agent_primary_mode(primary_mode)
    if is_work_session:
        payload.pop("personaProfile", None)
        payload.pop("taskProfile", None)
    else:
        payload["personaProfile"] = persona_profile
        payload["taskProfile"] = task_profile
    tool_policy = payload.get("toolPolicy") if isinstance(payload.get("toolPolicy"), dict) else {}
    metadata_memory_policy = payload.get("memoryPolicy") if isinstance(payload.get("memoryPolicy"), dict) else {}
    effective_memory_policy = memory_policy if isinstance(memory_policy, dict) else metadata_memory_policy
    missing = _agent_creation_missing_fields(
        display_name=display_name,
        llm_bindings=llm_bindings,
        primary_mode=primary_mode,
        role_key=role_key,
        prompt_template_id=prompt_template_id,
        persona_profile=persona_profile,
        task_profile=task_profile,
        tool_policy_id=tool_policy_id,
        tool_policy=tool_policy,
        memory_policy_id=memory_policy_id,
        memory_policy=effective_memory_policy,
    )
    required_fields = [
        field
        for field in AGENT_CREATION_REQUIRED_FIELDS
        if not is_work_session or field not in {"roleKey", "personaProfile", "taskProfile"}
    ]
    payload["creationSpec"] = {
        "schemaVersion": 1,
        "source": str(created_by or "user").strip() or "user",
        "requiredFields": required_fields,
        "createdAt": created_at,
    }
    payload["onboardingStatus"] = "incomplete" if missing else "complete"
    payload["onboardingMissing"] = missing
    return payload


def _refresh_agent_onboarding_metadata(state: dict[str, Any], agent: dict[str, Any]) -> None:
    metadata = dict(agent.get("metadata") or {})
    if not isinstance(metadata.get("creationSpec"), dict):
        return
    agent_id = str(agent.get("agentId") or "").strip()
    tool_policy_id = str(agent.get("toolPolicyId") or DEFAULT_TOOL_POLICY_ID).strip() or DEFAULT_TOOL_POLICY_ID
    memory_policy_id = str(agent.get("memoryPolicyId") or "").strip()
    tool_policies = _tool_policies(state)
    memory_policies = _memory_policies(state)
    missing = _agent_creation_missing_fields(
        display_name=str(agent.get("displayName") or "").strip(),
        llm_bindings=normalize_agent_llm_bindings(agent.get("llmBindings")),
        primary_mode=_normalize_primary_mode(agent.get("primaryMode")),
        role_key=_normalize_role_key(agent.get("roleKey")),
        prompt_template_id=_normalize_prompt_template_id(agent.get("promptTemplateId")),
        persona_profile=_persona_profile_for_agent(agent),
        task_profile=_task_profile_for_agent(agent),
        tool_policy_id=tool_policy_id,
        tool_policy=tool_policies.get(tool_policy_id) if isinstance(tool_policies.get(tool_policy_id), dict) else {},
        memory_policy_id=memory_policy_id,
        memory_policy=memory_policies.get(memory_policy_id) if isinstance(memory_policies.get(memory_policy_id), dict) else {},
    )
    metadata["onboardingStatus"] = "incomplete" if missing else "complete"
    metadata["onboardingMissing"] = missing
    if agent_id:
        creation_spec = dict(metadata.get("creationSpec") or {})
        creation_spec["agentId"] = agent_id
        metadata["creationSpec"] = creation_spec
    agent["metadata"] = metadata


def _agent_creation_missing_fields(
    *,
    display_name: str,
    llm_bindings: dict[str, Any],
    primary_mode: str,
    role_key: str,
    prompt_template_id: str,
    persona_profile: dict[str, Any],
    task_profile: dict[str, Any],
    tool_policy_id: str,
    tool_policy: dict[str, Any],
    memory_policy_id: str,
    memory_policy: dict[str, Any],
) -> list[str]:
    missing: list[str] = []
    if not str(display_name or "").strip():
        missing.append("displayName")
    if not agent_dialogue_model_id({"llmBindings": llm_bindings}):
        missing.append("llmBindings")
    if not str(primary_mode or "").strip():
        missing.append("primaryMode")
    is_work_session = _is_session_agent_primary_mode(primary_mode)
    if not is_work_session and not str(role_key or "").strip():
        missing.append("roleKey")
    if not str(prompt_template_id or "").strip():
        missing.append("promptTemplateId")
    if not is_work_session and not _persona_profile_has_content(persona_profile):
        missing.append("personaProfile")
    if not is_work_session and not _task_profile_has_content(task_profile):
        missing.append("taskProfile")
    allowed_tools = list(tool_policy.get("allowedTools") or []) if isinstance(tool_policy, dict) else []
    if str(tool_policy_id or "").strip() == DEFAULT_TOOL_POLICY_ID and not allowed_tools:
        missing.append("toolPolicy")
    if not str(memory_policy_id or "").strip() or not isinstance(memory_policy, dict) or not memory_policy:
        missing.append("memoryPolicy")
    return missing


def _normalize_agent_record_for_storage(agent: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(agent or {})
    normalized["llmBindings"] = normalize_agent_llm_bindings(normalized.get("llmBindings"))
    metadata = dict(normalized.get("metadata") or {})
    if _is_profileless_session_agent({**normalized, "metadata": metadata}):
        if isinstance(metadata.get("personaProfile"), dict):
            metadata.pop("personaProfile", None)
        if isinstance(metadata.get("taskProfile"), dict):
            metadata.pop("taskProfile", None)
    creation_spec = dict(metadata.get("creationSpec") or {})
    required_fields = list(creation_spec.get("requiredFields") or []) if isinstance(creation_spec.get("requiredFields"), list) else []
    if required_fields:
        creation_spec["requiredFields"] = [
            "llmBindings" if str(item or "").strip() == "profileId" else str(item or "").strip()
            for item in required_fields
            if str(item or "").strip() and str(item or "").strip() not in {"templateId", "profile_id", "template_id"}
        ]
        metadata["creationSpec"] = creation_spec
    migration = dict(metadata.get("llmBindingMigration") or {})
    legacy_profile_id = str(migration.pop("legacyProfileId", "") or "").strip()
    if legacy_profile_id and not str(migration.get("legacyModelSourceId") or "").strip():
        migration["legacyModelSourceId"] = legacy_profile_id
    if migration:
        metadata["llmBindingMigration"] = migration
    normalized["metadata"] = metadata
    normalized.pop("profileId", None)
    normalized.pop("profile_id", None)
    normalized.pop("templateId", None)
    normalized.pop("template_id", None)
    return normalized


def _normalize_agent_legacy_metadata_fields(agent: dict[str, Any]) -> bool:
    before = json.dumps(agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}, ensure_ascii=False, sort_keys=True)
    normalized = _normalize_agent_record_for_storage(agent)
    agent["metadata"] = normalized.get("metadata", {})
    after = json.dumps(agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}, ensure_ascii=False, sort_keys=True)
    return before != after


def _profile_id_to_model_id(profile_id: str) -> str:
    normalized = str(profile_id or "").strip()
    candidates = [normalized] if normalized else []
    if "primary" not in candidates:
        candidates.append("primary")
    try:
        from config.settings import get_config

        config = get_config()
        for candidate in candidates:
            try:
                profile = config.llm.get_profile(profile_id=candidate)
                model_id, _entry = config.llm.get_model_library_entry_for_profile(profile)
            except Exception:
                continue
            if model_id:
                return str(model_id).strip()
        model_library = getattr(config.llm, "model_library", {}) or {}
        if isinstance(model_library, dict):
            for model_id, item in model_library.items():
                if isinstance(item, dict) and str(model_id or "").strip():
                    return str(model_id).strip()
    except Exception:
        return ""
    return ""


def _migrate_agent_llm_bindings_to_new_design(agent: dict[str, Any]) -> dict[str, Any]:
    old_profile_id = str(agent.get("profileId") or agent.get("profile_id") or "").strip()
    old_template_id = str(agent.get("templateId") or agent.get("template_id") or "").strip()
    before = normalize_agent_llm_bindings(agent.get("llmBindings"))
    after = dict(before)
    migrated = False
    if not str(after.get(DEFAULT_AGENT_LLM_SLOT, {}).get("modelId") or "").strip():
        model_id = _profile_id_to_model_id(old_profile_id or old_template_id)
        if model_id:
            after[DEFAULT_AGENT_LLM_SLOT] = {"modelId": model_id}
            migrated = True
    had_legacy_fields = any(key in agent for key in ("profileId", "profile_id", "templateId", "template_id"))
    agent["llmBindings"] = after
    for key in ("profileId", "profile_id", "templateId", "template_id"):
        agent.pop(key, None)
    if migrated or before != after or had_legacy_fields:
        metadata = dict(agent.get("metadata") or {})
        migration = dict(metadata.get("llmBindingMigration") or {})
        migration.update(
            {
                "schemaVersion": 1,
                "source": "agent_registry_repair",
                "migratedAt": utc_now_iso(),
                "legacyModelSourceId": old_profile_id,
                "legacyTemplateId": old_template_id,
                "dialogueModelId": str(after.get(DEFAULT_AGENT_LLM_SLOT, {}).get("modelId") or "").strip(),
            }
        )
        metadata["llmBindingMigration"] = migration
        agent["metadata"] = metadata
        agent["updatedAt"] = utc_now_iso()
        return {
            "changed": True,
            "migrated": migrated,
            "legacyModelSourceId": old_profile_id,
            "legacyTemplateId": old_template_id,
            "dialogueModelId": str(after.get(DEFAULT_AGENT_LLM_SLOT, {}).get("modelId") or "").strip(),
        }
    return {"changed": False}


def _format_task_profile_context(profile: Any) -> list[str]:
    normalized = normalize_task_profile(profile if isinstance(profile, dict) else {})
    if not _task_profile_has_content(normalized):
        return []
    labels = {
        "mission": "Mission",
        "responsibilities": "Responsibilities",
        "preferredTasks": "PreferredTasks",
        "avoidTasks": "AvoidTasks",
        "successCriteria": "SuccessCriteria",
        "deliverables": "Deliverables",
        "constraints": "Constraints",
        "handoffNotes": "HandoffNotes",
    }
    lines = [
        "AgentTaskProfile:",
        "- Contract: descriptive task-fit and operating-scope guidance; do not use it as an automatic permission, routing, or scheduling gate.",
    ]
    task_types = [str(item or "").strip() for item in list(normalized.get("taskTypes") or []) if str(item or "").strip()]
    if task_types:
        lines.append(f"- TaskTypes: {', '.join(task_types[:16])}")
    for field in AGENT_TASK_PROFILE_TEXT_FIELDS:
        value = str(normalized.get(field) or "").strip()
        if value:
            lines.append(f"- {labels[field]}: {value}")
    return lines


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
        normalized_values: list[str] = []
        seen_values: set[str] = set()
        for item in list(payload.get(key) or []):
            value = str(item or "").strip()
            if not value or value in seen_values:
                continue
            normalized_values.append(value)
            seen_values.add(value)
        payload[key] = normalized_values
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
        "projectMemoryUpdatesPath": f"{workspace_path}/events/project_memory_updates.jsonl" if workspace_path else "",
        "toolObservationsPath": f"{workspace_path}/events/tool_observations.jsonl" if workspace_path else "",
        "summariesPath": f"{workspace_path}/memory/summaries.jsonl" if workspace_path else "",
        "readSharedGroups": [],
        "writeSharedGroups": [],
        "readKnowledgeBaseIds": [],
        "proposeKnowledgeBaseIds": [],
        "reviewKnowledgeBaseIds": [],
        "rateKnowledgeBaseIds": [],
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
        ("projectMemoryUpdatesPath", "events/project_memory_updates.jsonl"),
        ("toolObservationsPath", "events/tool_observations.jsonl"),
        ("summariesPath", "memory/summaries.jsonl"),
    ):
        value = str(payload.get(key) or "").strip()
        if workspace_path:
            value = f"{workspace_path}/{suffix}"
        payload[key] = value
    for key in (
        "readSharedGroups",
        "writeSharedGroups",
        "readKnowledgeBaseIds",
        "proposeKnowledgeBaseIds",
        "reviewKnowledgeBaseIds",
        "rateKnowledgeBaseIds",
    ):
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
        raw_agents = list(payload.get("agents") or []) if isinstance(payload.get("agents"), list) else []
        payload["agents"] = [
            normalized
            for item in raw_agents
            if isinstance(item, dict)
            for normalized in [_normalize_agent_record_for_storage(item)]
        ]
        payload["toolPolicies"] = _tool_policies(payload)
        payload["memoryPolicies"] = _memory_policies(payload)
        _atomic_write_json(registry_path(), payload)
        _invalidate_repaired_state_cache()
        return payload


def registry_path() -> Path:
    return _project_root() / "workspace" / "agents" / "agents.json"


def agent_avatar_image_url(avatar_image_path: object) -> str:
    filename = agent_avatar_filename(avatar_image_path)
    if not filename:
        return ""
    return f"/api/agents/avatar-image/{quote(filename)}"


def list_agent_avatar_options() -> dict[str, Any]:
    options: list[dict[str, Any]] = []
    for filename in _available_agent_avatar_filenames():
        path = str(AGENT_AVATAR_RELATIVE_DIR / filename)
        file_path = resolve_agent_avatar_file(filename)
        options.append(
            {
                "filename": filename,
                "path": path,
                "url": agent_avatar_image_url(path),
                "source": "workspace",
                "sizeBytes": file_path.stat().st_size if file_path.exists() else 0,
            }
        )
    return {
        "directory": str(AGENT_AVATAR_RELATIVE_DIR),
        "options": options,
        "count": len(options),
    }


def update_agent_avatar(
    agent_id: str,
    *,
    avatar_image_path: str = "",
    reset_to_default: bool = False,
) -> dict[str, Any]:
    with _STATE_LOCK:
        state = load_state()
        agent = _find_agent(state, agent_id)
        if agent is None:
            raise AgentNotFoundError(f"Agent not found: {agent_id}")
        metadata = dict(agent.get("metadata") or {})
        if reset_to_default:
            default_path = _default_agent_avatar_path(agent)
            if not default_path:
                raise AgentDirectoryError("No default Agent avatar is available.")
            metadata["avatarImagePath"] = default_path
            metadata["avatarImageSource"] = "default"
        else:
            filename = agent_avatar_filename(avatar_image_path)
            if not filename:
                raise AgentDirectoryError("Invalid Agent avatar image path.")
            path = resolve_agent_avatar_file(filename)
            if not path.exists() or not path.is_file():
                raise AgentDirectoryError("Agent avatar image does not exist.")
            metadata["avatarImagePath"] = str(AGENT_AVATAR_RELATIVE_DIR / filename)
            metadata["avatarImageSource"] = "custom"
        agent["metadata"] = metadata
        agent["updatedAt"] = utc_now_iso()
        save_state(state)
    _record_agent_avatar_updated_event(agent)
    return _agent_to_api(agent)


def store_agent_avatar_image(
    agent_id: str,
    *,
    filename: str,
    content_type: str,
    data_base64: str,
) -> dict[str, Any]:
    with _STATE_LOCK:
        state = load_state()
        agent = _find_agent(state, agent_id)
        if agent is None:
            raise AgentNotFoundError(f"Agent not found: {agent_id}")
    normalized_type = str(content_type or "").split(";")[0].strip().lower()
    extension = _AGENT_AVATAR_CONTENT_TYPE_EXTENSIONS.get(normalized_type)
    if not extension:
        raise AgentDirectoryError("Agent avatar only supports PNG, JPG, or WebP images.")
    payload = _decode_agent_avatar_payload(data_base64)
    _validate_agent_avatar_signature(payload, normalized_type)

    avatar_dir = (_project_root() / AGENT_AVATAR_RELATIVE_DIR).resolve()
    avatar_dir.mkdir(parents=True, exist_ok=True)
    safe_stem = _sanitize_avatar_stem(filename or agent_id)
    output_name = f"agent-avatar-{int(time.time())}-{secrets.token_hex(4)}-{safe_stem}{extension}"
    output_path = resolve_agent_avatar_file(output_name)
    output_path.write_bytes(payload)
    relative_path = str(AGENT_AVATAR_RELATIVE_DIR / output_name)
    updated = update_agent_avatar(agent_id, avatar_image_path=relative_path)
    _record_agent_avatar_uploaded_event(updated, content_type=normalized_type, size_bytes=len(payload))
    return {
        "path": relative_path,
        "url": agent_avatar_image_url(relative_path),
        "contentType": normalized_type,
        "sizeBytes": len(payload),
        "agent": updated,
    }


def agent_avatar_filename(avatar_image_path: object) -> str:
    value = str(avatar_image_path or "").strip().replace("\\", "/")
    if not value:
        return ""
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts:
        return ""
    if path.parent != AGENT_AVATAR_RELATIVE_DIR:
        return ""
    filename = path.name
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", filename):
        return ""
    if Path(filename).suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
        return ""
    return filename


def _ensure_knowledge_steward_agent(state: dict[str, Any]) -> dict[str, Any]:
    agents = list(state.get("agents") or [])
    tool_policies = _tool_policies(state)
    memory_policies = _memory_policies(state)
    now = utc_now_iso()
    agent = _find_agent(state, KNOWLEDGE_STEWARD_AGENT_ID)
    created = False
    changed = False
    repaired_fields: list[str] = []
    workspace_path = _agent_workspace_relative_path(KNOWLEDGE_STEWARD_AGENT_ID)

    if agent is None:
        metadata = _knowledge_steward_metadata()
        llm_bindings = normalize_agent_llm_bindings(
            {DEFAULT_AGENT_LLM_SLOT: {"modelId": _profile_id_to_model_id("primary")}}
        )
        agent = {
            "agentId": KNOWLEDGE_STEWARD_AGENT_ID,
            "agentCode": _next_agent_code(agents),
            "displayName": _agent_public_display_name(
                KNOWLEDGE_STEWARD_FUNCTIONAL_NAME,
                existing_agents=agents,
                agent_id=KNOWLEDGE_STEWARD_AGENT_ID,
                metadata=metadata,
            ),
            "kind": DEFAULT_AGENT_KIND,
            "primaryMode": "general",
            "roleKey": KNOWLEDGE_STEWARD_ROLE_KEY,
            "llmBindings": llm_bindings,
            "promptTemplateId": "prompt-chat-default",
            "directSessionId": KNOWLEDGE_STEWARD_DIRECT_SESSION_ID,
            "workspacePath": workspace_path,
            "toolPolicyId": KNOWLEDGE_STEWARD_TOOL_POLICY_ID,
            "memoryPolicyId": KNOWLEDGE_STEWARD_MEMORY_POLICY_ID,
            "createdBy": "system_repair",
            "status": "active",
            "metadata": metadata,
            "createdAt": now,
            "updatedAt": now,
        }
        _ensure_agent_default_avatar(agent)
        agents.append(agent)
        state["agents"] = agents
        created = True
        changed = True
        repaired_fields.append("agent")

    if not isinstance(agent, dict):
        return {"changed": False, "created": False, "agent": {}, "repairedFields": []}

    expected = {
        "kind": DEFAULT_AGENT_KIND,
        "primaryMode": "general",
        "roleKey": KNOWLEDGE_STEWARD_ROLE_KEY,
        "promptTemplateId": "prompt-chat-default",
        "directSessionId": KNOWLEDGE_STEWARD_DIRECT_SESSION_ID,
        "workspacePath": workspace_path,
        "toolPolicyId": KNOWLEDGE_STEWARD_TOOL_POLICY_ID,
        "memoryPolicyId": KNOWLEDGE_STEWARD_MEMORY_POLICY_ID,
        "status": "active",
    }
    for key, value in expected.items():
        if str(agent.get(key) or "").strip() != value:
            agent[key] = value
            changed = True
            repaired_fields.append(key)

    llm_repair = _migrate_agent_llm_bindings_to_new_design(agent)
    if llm_repair.get("changed"):
        changed = True
        repaired_fields.append("llmBindings")

    if not _normalize_agent_code(agent.get("agentCode")):
        agent["agentCode"] = _next_agent_code(agents, exclude_agent_id=KNOWLEDGE_STEWARD_AGENT_ID)
        changed = True
        repaired_fields.append("agentCode")

    metadata = dict(agent.get("metadata") or {})
    merged_metadata = _merge_system_agent_metadata(metadata, _knowledge_steward_metadata())
    if metadata != merged_metadata:
        agent["metadata"] = merged_metadata
        changed = True
        repaired_fields.append("metadata")

    title = str(agent.get("displayName") or "").strip()
    if not title or _display_name_is_functional_or_machine(title, agent):
        agent["displayName"] = _agent_public_display_name(
            KNOWLEDGE_STEWARD_FUNCTIONAL_NAME,
            existing_agents=agents,
            agent_id=KNOWLEDGE_STEWARD_AGENT_ID,
            metadata=dict(agent.get("metadata") or {}),
        )
        changed = True
        repaired_fields.append("displayName")

    avatar_changed = _ensure_agent_default_avatar(agent)
    if avatar_changed:
        changed = True
        repaired_fields.append("avatar")

    _ensure_agent_workspace(workspace_path)
    tool_policy = _knowledge_steward_tool_policy()
    memory_policy = _knowledge_steward_memory_policy(workspace_path)
    if tool_policies.get(KNOWLEDGE_STEWARD_TOOL_POLICY_ID) != tool_policy:
        tool_policies[KNOWLEDGE_STEWARD_TOOL_POLICY_ID] = tool_policy
        changed = True
        repaired_fields.append("toolPolicy")
    if memory_policies.get(KNOWLEDGE_STEWARD_MEMORY_POLICY_ID) != memory_policy:
        memory_policies[KNOWLEDGE_STEWARD_MEMORY_POLICY_ID] = memory_policy
        changed = True
        repaired_fields.append("memoryPolicy")
    state["toolPolicies"] = tool_policies
    state["memoryPolicies"] = memory_policies
    if changed:
        agent["updatedAt"] = now
    return {
        "changed": changed,
        "created": created,
        "agent": dict(agent),
        "repairedFields": sorted(set(repaired_fields)),
    }


def _knowledge_steward_tool_policy() -> dict[str, Any]:
    return normalize_tool_policy(
        {
            **default_tool_policy(KNOWLEDGE_STEWARD_TOOL_POLICY_ID),
            "allowedTools": [
                "agent_message_tool",
                "knowledge_query_tool",
                "knowledge_proposal_tool",
                "knowledge_ingestion_tool",
                "knowledge_governance_tasks_tool",
                "knowledge_operations_health_tool",
                "knowledge_governance_plan_tool",
                "knowledge_steward_recommendations_tool",
                "knowledge_steward_workbench_tool",
                "knowledge_rating_suggestion_tool",
            ],
            "preferredTools": [
                "knowledge_governance_tasks_tool",
                "knowledge_operations_health_tool",
                "knowledge_governance_plan_tool",
                "knowledge_steward_workbench_tool",
                "knowledge_steward_recommendations_tool",
                "knowledge_query_tool",
                "knowledge_rating_suggestion_tool",
            ],
            "readScopes": ["private", "shared"],
            "writeScopes": ["private"],
            "networkAccess": "none",
            "mutationAccess": "restricted",
            "maxCallsPerTurn": 12,
        },
        KNOWLEDGE_STEWARD_TOOL_POLICY_ID,
    )


def _knowledge_steward_memory_policy(workspace_path: str) -> dict[str, Any]:
    return normalize_memory_policy(
        {
            **default_memory_policy(KNOWLEDGE_STEWARD_MEMORY_POLICY_ID, workspace_path),
            "readSharedGroups": ["project"],
            "writeSharedGroups": [],
            "readKnowledgeBaseIds": [],
            "proposeKnowledgeBaseIds": [],
            "reviewKnowledgeBaseIds": [],
            "rateKnowledgeBaseIds": [],
        },
        KNOWLEDGE_STEWARD_MEMORY_POLICY_ID,
        workspace_path,
    )


def _knowledge_steward_metadata() -> dict[str, Any]:
    return {
        "systemRole": KNOWLEDGE_STEWARD_ROLE_KEY,
        "fixedRole": True,
        "protected": True,
        "functionalDisplayName": KNOWLEDGE_STEWARD_FUNCTIONAL_NAME,
        "displayNameSource": "generated_person_name",
        "agentMode": "general",
        "managedDomain": "team_knowledge",
        "governanceRole": "knowledge_steward",
        "phaseIntroduced": "memory_platform_phase3",
        "permissionBoundary": "proposal_and_rating_suggestion_only",
        "personaProfile": {
            "personality": "审慎、耐心、重视证据链和权限边界。",
            "communicationStyle": "先给治理结论，再列来源、风险和需要审核的动作。",
            "background": "长期维护团队知识库、来源登记、精炼提案、评级建议和复审队列。",
            "collaborationPreference": "向 owner、lead、steward 或 coordinator 提交可审核建议，不绕过正式审核。",
            "expertise": ["团队知识治理", "来源溯源", "知识评级", "治理任务队列"],
        },
        "taskProfile": {
            "mission": "维护团队知识库质量，推动来源证据、精炼候选和评级建议进入可审核状态。",
            "responsibilities": (
                "查看知识治理任务；整理来源摄取包；提交精炼提案；提交评级建议；"
                "生成复审摘要；发现权限或证据缺口时上报。"
            ),
            "preferredTasks": "来源登记、候选知识整理、评级建议、证据链追踪、治理队列巡检。",
            "avoidTasks": "不要直接应用正式知识、删除知识、跨团队授权、修改 ACL 或绕过 reviewer。",
            "successCriteria": "每条建议都有来源、时间戳、目标知识库、理由和可审核状态。",
            "deliverables": "治理任务摘要、摄取包、精炼提案、评级建议、复审风险清单。",
            "constraints": "正式 KnowledgeItem 落盘仍必须由具备审核权限的角色或用户确认。",
            "handoffNotes": "需要最终审核时交给 Team owner/lead/steward/coordinator 或用户。",
            "taskTypes": ["knowledge_governance", "source_ingestion", "rating_suggestion", "review_preparation"],
        },
    }


def _merge_system_agent_metadata(current: dict[str, Any], defaults: dict[str, Any]) -> dict[str, Any]:
    merged = dict(current or {})
    for key, value in defaults.items():
        if isinstance(value, dict):
            nested = dict(merged.get(key) or {}) if isinstance(merged.get(key), dict) else {}
            nested.update(value)
            merged[key] = nested
        else:
            merged[key] = value
    return merged


def resolve_agent_avatar_file(filename: str) -> Path:
    safe_filename = agent_avatar_filename(str(AGENT_AVATAR_RELATIVE_DIR / str(filename or "")))
    if not safe_filename:
        raise FileNotFoundError("invalid Agent avatar image path")
    avatar_dir = (_project_root() / AGENT_AVATAR_RELATIVE_DIR).resolve()
    path = (avatar_dir / safe_filename).resolve()
    if avatar_dir != path.parent:
        raise FileNotFoundError("invalid Agent avatar image path")
    return path


def _agent_avatar_path_from_metadata(metadata: dict[str, Any]) -> str:
    avatar_path = str(
        metadata.get("avatarImagePath")
        or metadata.get("agentAvatarImagePath")
        or metadata.get("avatarPath")
        or ""
    ).strip()
    filename = agent_avatar_filename(avatar_path)
    return str(AGENT_AVATAR_RELATIVE_DIR / filename) if filename else ""


def _sanitize_avatar_stem(filename: str) -> str:
    raw_stem = Path(str(filename or "agent-avatar")).stem.lower()
    stem = re.sub(r"[^a-z0-9_-]+", "-", raw_stem).strip("-_")
    return stem[:40] or "agent-avatar"


def _decode_agent_avatar_payload(data_base64: str) -> bytes:
    try:
        payload = base64.b64decode(str(data_base64 or ""), validate=True)
    except (binascii.Error, ValueError) as exc:
        raise AgentDirectoryError("Agent avatar image data is not valid base64.") from exc
    if not payload:
        raise AgentDirectoryError("Agent avatar image cannot be empty.")
    if len(payload) > MAX_AGENT_AVATAR_IMAGE_BYTES:
        raise AgentDirectoryError("Agent avatar image cannot exceed 5MB.")
    return payload


def _validate_agent_avatar_signature(payload: bytes, content_type: str) -> None:
    if content_type == "image/png" and payload.startswith(b"\x89PNG\r\n\x1a\n"):
        return
    if content_type == "image/jpeg" and payload.startswith(b"\xff\xd8\xff"):
        return
    if content_type == "image/webp" and payload.startswith(b"RIFF") and payload[8:12] == b"WEBP":
        return
    raise AgentDirectoryError("Agent avatar image format does not match its content.")


def _ensure_agent_default_avatar(agent: dict[str, Any]) -> bool:
    metadata = dict(agent.get("metadata") or {})
    current_path = _agent_avatar_path_from_metadata(metadata)
    current_source = str(metadata.get("avatarImageSource") or metadata.get("agentAvatarImageSource") or "").strip()
    default_path = _default_agent_avatar_path(agent)
    if not default_path:
        return False
    if current_path and current_source != "default":
        return False
    if current_path == default_path and metadata.get("avatarImageSource") == "default":
        return False
    metadata["avatarImagePath"] = default_path
    metadata["avatarImageSource"] = "default"
    agent["metadata"] = metadata
    return True


def _default_agent_avatar_path(agent: dict[str, Any]) -> str:
    filename = _default_agent_avatar_filename(agent)
    return str(AGENT_AVATAR_RELATIVE_DIR / filename) if filename else ""


def _default_agent_avatar_filename(agent: dict[str, Any]) -> str:
    available = _available_agent_avatar_filenames()
    if not available:
        return ""
    key = _agent_avatar_match_key(agent)
    for tokens, filename in AGENT_AVATAR_ROLE_DEFAULTS:
        if filename not in available:
            continue
        if all(token in key for token in tokens):
            return filename
    fallback_pool = [filename for filename in AGENT_AVATAR_FILENAMES if filename in available]
    if not fallback_pool:
        fallback_pool = available
    stable_key = _normalize_agent_code(agent.get("agentCode")) or str(agent.get("agentId") or "")
    checksum = sum(ord(char) for char in stable_key)
    return fallback_pool[checksum % len(fallback_pool)]


def _available_agent_avatar_filenames() -> list[str]:
    avatar_dir = (_project_root() / AGENT_AVATAR_RELATIVE_DIR).resolve()
    if not avatar_dir.exists() or not avatar_dir.is_dir():
        return []
    existing = {
        item.name
        for item in avatar_dir.iterdir()
        if item.is_file() and agent_avatar_filename(str(AGENT_AVATAR_RELATIVE_DIR / item.name))
    }
    ordered = [filename for filename in AGENT_AVATAR_FILENAMES if filename in existing]
    extra = sorted(existing.difference(ordered))
    return ordered + extra


def _agent_avatar_match_key(agent: dict[str, Any]) -> str:
    metadata = agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}
    parts = [
        agent.get("primaryMode"),
        agent.get("roleKey"),
        agent.get("promptTemplateId"),
        metadata.get("functionalDisplayName"),
        metadata.get("researchAgentKey"),
        metadata.get("selfEvolutionRole"),
        metadata.get("supervisedRole"),
        metadata.get("systemRole"),
        metadata.get("researchOrgRole"),
    ]
    return " ".join(str(item or "").strip().lower() for item in parts if str(item or "").strip())


def _agent_to_api(agent: dict[str, Any], *, hydration: AgentApiHydrationContext | None = None) -> dict[str, Any]:
    workspace = str(agent.get("workspacePath") or "").strip()
    metadata = dict(agent.get("metadata") or {})
    avatar_path = _agent_avatar_path_from_metadata(metadata)
    profileless_session_agent = _is_profileless_session_agent({**agent, "metadata": metadata})
    if profileless_session_agent:
        metadata.pop("personaProfile", None)
        metadata.pop("taskProfile", None)
    persona_profile = {} if profileless_session_agent else _persona_profile_for_agent({**agent, "metadata": metadata})
    task_profile = {} if profileless_session_agent else _task_profile_for_agent({**agent, "metadata": metadata})
    agent_id = str(agent.get("agentId") or "").strip()
    return {
        "agentId": agent_id,
        "agentCode": _normalize_agent_code(agent.get("agentCode"))
        or _fallback_agent_code(agent.get("agentId")),
        "displayName": str(agent.get("displayName") or "").strip(),
        "kind": str(agent.get("kind") or DEFAULT_AGENT_KIND).strip() or DEFAULT_AGENT_KIND,
        "primaryMode": _normalize_primary_mode(agent.get("primaryMode") or _infer_agent_primary_mode(agent)),
        "roleKey": _normalize_role_key(agent.get("roleKey") or _infer_agent_role_key(agent)),
        "llmBindings": normalize_agent_llm_bindings(agent.get("llmBindings")),
        "promptTemplateId": _normalize_prompt_template_id(
            agent.get("promptTemplateId") or _infer_agent_prompt_template_id(agent)
        ),
        "directSessionId": str(agent.get("directSessionId") or "").strip(),
        "workspacePath": workspace,
        "workspaceTerritory": _agent_workspace_territory(agent),
        "toolPolicyId": str(agent.get("toolPolicyId") or DEFAULT_TOOL_POLICY_ID).strip() or DEFAULT_TOOL_POLICY_ID,
        "memoryPolicyId": str(agent.get("memoryPolicyId") or "").strip(),
        "avatarImagePath": avatar_path,
        "avatarImageUrl": agent_avatar_image_url(avatar_path),
        "personaProfile": persona_profile,
        "taskProfile": task_profile,
        "createdBy": str(agent.get("createdBy") or "").strip(),
        "status": str(agent.get("status") or "active").strip() or "active",
        "metadata": metadata,
        "createdAt": str(agent.get("createdAt") or "").strip(),
        "updatedAt": str(agent.get("updatedAt") or "").strip(),
        "memoryPolicy": _memory_policy_for_agent(agent, hydration=hydration),
        "toolPolicy": _tool_policy_for_agent(agent, hydration=hydration),
        "toolGovernanceRequests": _tool_governance_requests_for_agent(agent_id, hydration=hydration, limit=6),
        "groupContextEvents": _group_context_events_for_agent(agent, hydration=hydration, limit=8),
        "agentInboxMessages": _agent_inbox_messages_for_agent(agent, hydration=hydration, limit=8, status="pending"),
        "agentInboxPendingCount": _agent_inbox_pending_count_for_agent(agent, hydration=hydration, status="pending"),
    }


def _agent_to_api_summary(agent: dict[str, Any]) -> dict[str, Any]:
    workspace = str(agent.get("workspacePath") or "").strip()
    metadata = dict(agent.get("metadata") or {})
    avatar_path = _agent_avatar_path_from_metadata(metadata)
    profileless_session_agent = _is_profileless_session_agent({**agent, "metadata": metadata})
    if profileless_session_agent:
        metadata.pop("personaProfile", None)
        metadata.pop("taskProfile", None)
    agent_id = str(agent.get("agentId") or "").strip()
    return {
        "agentId": agent_id,
        "agentCode": _normalize_agent_code(agent.get("agentCode"))
        or _fallback_agent_code(agent.get("agentId")),
        "displayName": str(agent.get("displayName") or "").strip(),
        "kind": str(agent.get("kind") or DEFAULT_AGENT_KIND).strip() or DEFAULT_AGENT_KIND,
        "primaryMode": _normalize_primary_mode(agent.get("primaryMode") or _infer_agent_primary_mode(agent)),
        "roleKey": _normalize_role_key(agent.get("roleKey") or _infer_agent_role_key(agent)),
        "llmBindings": normalize_agent_llm_bindings(agent.get("llmBindings")),
        "promptTemplateId": _normalize_prompt_template_id(
            agent.get("promptTemplateId") or _infer_agent_prompt_template_id(agent)
        ),
        "directSessionId": str(agent.get("directSessionId") or "").strip(),
        "workspacePath": workspace,
        "workspaceTerritory": _agent_workspace_territory(agent),
        "toolPolicyId": str(agent.get("toolPolicyId") or DEFAULT_TOOL_POLICY_ID).strip() or DEFAULT_TOOL_POLICY_ID,
        "memoryPolicyId": str(agent.get("memoryPolicyId") or "").strip(),
        "avatarImagePath": avatar_path,
        "avatarImageUrl": agent_avatar_image_url(avatar_path),
        "personaProfile": {} if profileless_session_agent else _persona_profile_for_agent({**agent, "metadata": metadata}),
        "taskProfile": {} if profileless_session_agent else _task_profile_for_agent({**agent, "metadata": metadata}),
        "createdBy": str(agent.get("createdBy") or "").strip(),
        "status": str(agent.get("status") or "active").strip() or "active",
        "metadata": metadata,
        "createdAt": str(agent.get("createdAt") or "").strip(),
        "updatedAt": str(agent.get("updatedAt") or "").strip(),
    }


def _build_agent_api_hydration_context(
    state: dict[str, Any],
    agents: list[dict[str, Any]],
    *,
    timings: dict[str, float] | None = None,
) -> AgentApiHydrationContext:
    timings_ref = timings if timings is not None else {}
    started = time.perf_counter()
    tool_policies = _tool_policies(state)
    timings_ref["tool_policies"] = round((time.perf_counter() - started) * 1000, 1)
    started = time.perf_counter()
    memory_policies = _memory_policies(state)
    timings_ref["memory_policies"] = round((time.perf_counter() - started) * 1000, 1)
    started = time.perf_counter()
    tool_governance_requests_by_agent = _load_recent_tool_governance_requests_for_agents(agents, limit=6)
    timings_ref["tool_governance_requests"] = round((time.perf_counter() - started) * 1000, 1)
    started = time.perf_counter()
    group_context_events_by_agent: dict[str, list[dict[str, Any]]] = {}
    for agent in agents:
        agent_id = str(agent.get("agentId") or "").strip()
        if not agent_id:
            continue
        group_context_events_by_agent[agent_id] = _read_recent_jsonl(
            _resolve_project_path(str(agent.get("workspacePath") or "")) / "events" / "group_context_events.jsonl",
            limit=8,
        )
    timings_ref["group_context_events"] = round((time.perf_counter() - started) * 1000, 1)
    started = time.perf_counter()
    agent_inbox_messages_by_agent: dict[str, list[dict[str, Any]]] = {}
    agent_inbox_pending_count_by_agent: dict[str, int] = {}
    for agent in agents:
        agent_id = str(agent.get("agentId") or "").strip()
        if not agent_id:
            continue
        path = _agent_workspace_event_path(agent, "agent_inbox_messages.jsonl")
        agent_inbox_messages_by_agent[agent_id] = _read_recent_jsonl(
            path,
            limit=8,
            status="pending",
        )
        agent_inbox_pending_count_by_agent[agent_id] = _count_jsonl_matching_status(path, status="pending")
    timings_ref["agent_inbox_messages"] = round((time.perf_counter() - started) * 1000, 1)
    return AgentApiHydrationContext(
        state=state,
        tool_policies=tool_policies,
        memory_policies=memory_policies,
        tool_governance_requests_by_agent=tool_governance_requests_by_agent,
        group_context_events_by_agent=group_context_events_by_agent,
        agent_inbox_messages_by_agent=agent_inbox_messages_by_agent,
        agent_inbox_pending_count_by_agent=agent_inbox_pending_count_by_agent,
    )


def _memory_policy_for_agent(agent: dict[str, Any], *, hydration: AgentApiHydrationContext | None = None) -> dict[str, Any]:
    agent_id = str(agent.get("agentId") or "").strip()
    if hydration is None:
        return resolve_memory_policy_for_agent(agent_id)
    policy_id = str(agent.get("memoryPolicyId") or "").strip()
    policy = hydration.memory_policies.get(policy_id)
    workspace_path = str(agent.get("workspacePath") or _agent_workspace_relative_path(agent_id)).strip()
    if isinstance(policy, dict):
        return normalize_memory_policy(policy, policy_id, workspace_path)
    return default_memory_policy(policy_id or f"memory-{agent_id}", workspace_path)


def _tool_policy_for_agent(agent: dict[str, Any], *, hydration: AgentApiHydrationContext | None = None) -> dict[str, Any]:
    agent_id = str(agent.get("agentId") or "").strip()
    if hydration is None:
        return resolve_tool_policy_for_agent(agent_id)
    policy_id = str(agent.get("toolPolicyId") or DEFAULT_TOOL_POLICY_ID).strip() or DEFAULT_TOOL_POLICY_ID
    policy = hydration.tool_policies.get(policy_id) or default_tool_policy(policy_id)
    return normalize_tool_policy(policy, policy_id)


def _tool_governance_requests_for_agent(
    agent_id: str,
    *,
    hydration: AgentApiHydrationContext | None = None,
    limit: int = 6,
) -> list[dict[str, Any]]:
    if hydration is None:
        return _list_recent_tool_governance_requests_for_agent(agent_id, limit=limit)
    return list(hydration.tool_governance_requests_by_agent.get(agent_id) or [])[: max(1, int(limit or 1))]


def _group_context_events_for_agent(
    agent: dict[str, Any],
    *,
    hydration: AgentApiHydrationContext | None = None,
    limit: int = 8,
) -> list[dict[str, Any]]:
    agent_id = str(agent.get("agentId") or "").strip()
    if hydration is None:
        return list_group_context_events_for_agent(agent_id, limit=limit)
    events = list(hydration.group_context_events_by_agent.get(agent_id) or [])
    return events[-max(1, int(limit or 1)) :]


def _agent_inbox_messages_for_agent(
    agent: dict[str, Any],
    *,
    hydration: AgentApiHydrationContext | None = None,
    limit: int = 8,
    status: str = "pending",
) -> list[dict[str, Any]]:
    agent_id = str(agent.get("agentId") or "").strip()
    if hydration is None:
        return list_agent_inbox_messages_for_agent(agent_id, limit=limit, status=status)
    messages = list(hydration.agent_inbox_messages_by_agent.get(agent_id) or [])
    normalized_status = str(status or "").strip().lower()
    if normalized_status:
        messages = [
            item for item in messages
            if str(item.get("status") or "pending").strip().lower() == normalized_status
        ]
    return messages[-max(1, int(limit or 1)) :]


def _agent_inbox_pending_count_for_agent(
    agent: dict[str, Any],
    *,
    hydration: AgentApiHydrationContext | None = None,
    status: str = "pending",
) -> int:
    agent_id = str(agent.get("agentId") or "").strip()
    if hydration is None:
        return count_agent_inbox_messages_for_agent(agent_id, status=status)
    normalized_status = str(status or "").strip().lower()
    if normalized_status == "pending" and agent_id in hydration.agent_inbox_pending_count_by_agent:
        return hydration.agent_inbox_pending_count_by_agent[agent_id]
    messages = list(hydration.agent_inbox_messages_by_agent.get(agent_id) or [])
    if not normalized_status:
        return len(messages)
    count = sum(
        1
        for item in messages
        if str(item.get("status") or "pending").strip().lower() == normalized_status
    )
    if normalized_status == "pending":
        hydration.agent_inbox_pending_count_by_agent[agent_id] = count
    return count


def _load_recent_tool_governance_requests_for_agents(
    agents: list[dict[str, Any]],
    *,
    limit: int = 6,
) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {}
    for agent in agents:
        agent_id = str(agent.get("agentId") or "").strip()
        if not agent_id:
            continue
        try:
            requests = _read_tool_governance_requests_for_agent(agent, limit=limit)
        except Exception:
            requests = []
        requests.sort(
            key=lambda item: (
                str(item.get("createdAt") or ""),
                str(item.get("requestId") or item.get("eventId") or ""),
            ),
            reverse=True,
        )
        result[agent_id] = requests[: max(1, int(limit or 1))]
    return result


def _read_tool_governance_requests_for_agent(agent: dict[str, Any], *, limit: int | None = None) -> list[dict[str, Any]]:
    path = _resolve_project_path(str(agent.get("workspacePath") or "")) / "events" / "tool_governance_requests.jsonl"
    if limit is not None:
        return _read_recent_jsonl(path, limit=max(1, int(limit or 1)))
    return _read_jsonl(path)


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


def _list_recent_tool_governance_requests_for_agent(agent_id: str, *, limit: int = 6) -> list[dict[str, Any]]:
    try:
        from .agent_tool_governance_service import list_tool_governance_requests

        return list_tool_governance_requests(agent_id=agent_id, status="", limit=limit)
    except Exception:
        return []


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
    return bool(metadata.get("protected")) or system_role in {"ceo", "organization_advisor", KNOWLEDGE_STEWARD_ROLE_KEY}


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
    base = f"agent-{datetime.now().strftime('%Y%m%d-%H%M%S-%f')}"
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


def _clear_agent_runtime_state(agent: dict[str, Any]) -> dict[str, Any]:
    agent_id = str(agent.get("agentId") or "").strip()
    workspace_path = str(agent.get("workspacePath") or _agent_workspace_relative_path(agent_id)).strip()
    runtime_subdirs = ("inbox", "outbox", "events", "tmp", "logs", "runs", "scratch", "artifacts")
    if not agent_id or not workspace_path:
        return {"deletedPaths": [], "skippedPaths": [workspace_path or agent_id]}
    try:
        resolved = _resolve_project_path(workspace_path)
        expected_private = _resolve_project_path(_agent_workspace_relative_path(agent_id))
        agents_root = (_project_root() / "workspace" / "agents").resolve()
    except Exception:
        return {"deletedPaths": [], "skippedPaths": [workspace_path]}
    if resolved != expected_private:
        return {"deletedPaths": [], "skippedPaths": [_relative_project_path(resolved)]}
    try:
        if not resolved.is_relative_to(agents_root):
            return {"deletedPaths": [], "skippedPaths": [_relative_project_path(resolved)]}
    except ValueError:
        return {"deletedPaths": [], "skippedPaths": [_relative_project_path(resolved)]}

    resolved.mkdir(parents=True, exist_ok=True)
    deleted_paths: list[str] = []
    skipped_paths: list[str] = []
    for subdir in runtime_subdirs:
        target = (resolved / subdir).resolve()
        relative_path = _relative_project_path(target)
        try:
            if not target.is_relative_to(resolved):
                skipped_paths.append(relative_path)
                continue
        except ValueError:
            skipped_paths.append(relative_path)
            continue
        try:
            if target.exists():
                shutil.rmtree(target)
                deleted_paths.append(relative_path)
            target.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            skipped_paths.append(f"{relative_path} ({type(exc).__name__})")
    return {"deletedPaths": deleted_paths, "skippedPaths": skipped_paths}


def _reset_agent_direct_session(agent: dict[str, Any]) -> dict[str, Any]:
    session_id = str(agent.get("directSessionId") or "").strip()
    if not session_id:
        return {"resetDirectSession": False, "replacementDirectSessionId": "", "skippedPaths": []}
    try:
        from . import session_service

        result = session_service.delete_chat_session_lightweight(session_id, activate_replacement=True)
    except Exception as exc:
        return {
            "resetDirectSession": False,
            "replacementDirectSessionId": "",
            "skippedPaths": [f"direct_session:{session_id} ({type(exc).__name__})"],
        }
    replacement_direct_session_id = str(result.get("replacementDirectSessionId") or result.get("nextActiveSessionId") or "").strip()
    skipped_paths: list[str] = []
    if replacement_direct_session_id:
        try:
            update_agent_instance(
                str(agent.get("agentId") or "").strip(),
                direct_session_id=replacement_direct_session_id,
            )
        except Exception as exc:
            skipped_paths.append(f"direct_session_bind:{replacement_direct_session_id} ({type(exc).__name__})")
    return {
        "resetDirectSession": True,
        "replacementDirectSessionId": replacement_direct_session_id,
        "skippedPaths": skipped_paths,
    }


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


def _read_recent_jsonl(
    path: Path,
    *,
    limit: int,
    status: str = "",
    prompt_eligible_only: bool = False,
) -> list[dict[str, Any]]:
    """Read only the recent JSONL window needed for Agent Center previews."""

    normalized_limit = max(1, int(limit or 1))
    if not path.exists():
        return []
    normalized_status = str(status or "").strip().lower()
    cache_key = (*_jsonl_signature(path), normalized_limit, normalized_status, bool(prompt_eligible_only))
    cached = _JSONL_RECENT_CACHE.get(cache_key)
    if cached is not None:
        return [dict(item) for item in cached]
    events: list[dict[str, Any]] = []
    for line in _iter_text_lines_reverse(path):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue
        if normalized_status and str(payload.get("status") or "pending").strip().lower() != normalized_status:
            continue
        if prompt_eligible_only and not bool(payload.get("promptEligible", True)):
            continue
        events.append(payload)
        if len(events) >= normalized_limit:
            break
    result = list(reversed(events))
    _remember_jsonl_recent(cache_key, result)
    return [dict(item) for item in result]


def _iter_text_lines_reverse(path: Path) -> Iterable[str]:
    """Yield text lines from a file newest-first without reading it all."""

    chunk_size = 8192
    remainder = b""
    try:
        with path.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            position = handle.tell()
            while position > 0:
                read_size = min(chunk_size, position)
                position -= read_size
                handle.seek(position)
                data = handle.read(read_size) + remainder
                parts = data.split(b"\n")
                remainder = parts[0]
                for raw_line in reversed(parts[1:]):
                    if raw_line.endswith(b"\r"):
                        raw_line = raw_line[:-1]
                    line = raw_line.decode("utf-8", errors="ignore")
                    if line.strip():
                        yield line
            if remainder.strip():
                yield remainder.decode("utf-8", errors="ignore")
    except OSError:
        return


def _count_jsonl_matching_status(path: Path, *, status: str = "") -> int:
    normalized_status = str(status or "").strip().lower()
    if not path.exists():
        return 0
    cache_key = (*_jsonl_signature(path), normalized_status)
    cached = _JSONL_COUNT_CACHE.get(cache_key)
    if cached is not None:
        return cached
    count = 0
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(payload, dict):
                    continue
                if normalized_status and str(payload.get("status") or "pending").strip().lower() != normalized_status:
                    continue
                count += 1
    except OSError:
        return 0
    _remember_jsonl_count(cache_key, count)
    return count


def _jsonl_signature(path: Path) -> tuple[str, bool, int, int]:
    try:
        stat = path.stat()
    except OSError:
        return (str(path), False, 0, 0)
    return (str(path), True, int(stat.st_mtime_ns), int(stat.st_size))


def _remember_jsonl_recent(key: tuple[str, bool, int, int, int, str, bool], value: list[dict[str, Any]]) -> None:
    if len(_JSONL_RECENT_CACHE) > 512:
        _JSONL_RECENT_CACHE.clear()
    _JSONL_RECENT_CACHE[key] = [dict(item) for item in value if isinstance(item, dict)]


def _remember_jsonl_count(key: tuple[str, bool, int, int, str], value: int) -> None:
    if len(_JSONL_COUNT_CACHE) > 512:
        _JSONL_COUNT_CACHE.clear()
    _JSONL_COUNT_CACHE[key] = int(value or 0)


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
                "promptTemplateId": _normalize_prompt_template_id(agent.get("promptTemplateId")),
                "status": str(agent.get("status") or "").strip(),
            },
            lifecycle=lifecycle,
        )
    except Exception:
        return


def _record_agent_list_loaded(
    *,
    include_archived: bool,
    detail: str,
    raw_agent_count: int,
    returned_agent_count: int,
    timings: dict[str, float],
    hydration_timings: dict[str, float],
    repair_cache_hit: bool = False,
) -> None:
    total_ms = float(timings.get("total") or 0)
    lock_wait_ms = float(timings.get("lock_wait") or 0)
    if total_ms < 1000 and lock_wait_ms < 250:
        return
    try:
        record_runtime_scene_event(
            "agent_directory",
            "list_agents",
            "agent_directory.list_agents.slow",
            message="Agent directory list_agents was slow.",
            level="warning" if total_ms >= 3000 or lock_wait_ms >= 1000 else "info",
            outcome="observed",
            fields={
                "includeArchived": bool(include_archived),
                "detail": str(detail or "full"),
                "rawAgentCount": raw_agent_count,
                "returnedAgentCount": returned_agent_count,
                "repairCacheHit": bool(repair_cache_hit),
                "timingsMs": dict(timings),
                "hydrationTimingsMs": dict(hydration_timings),
                "slowestStage": _slowest_timing_stage(timings),
                "slowestHydrationStage": _slowest_timing_stage(hydration_timings),
            },
        )
    except Exception:
        return


def _slowest_timing_stage(timings: dict[str, float]) -> str:
    candidates = {
        str(key): float(value or 0)
        for key, value in dict(timings or {}).items()
        if str(key) != "total"
    }
    if not candidates:
        return ""
    return max(candidates.items(), key=lambda item: item[1])[0]


def _record_agent_avatar_defaults_event(agents: list[dict[str, Any]]) -> None:
    try:
        avatar_counts: dict[str, int] = {}
        for agent in agents:
            metadata = agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}
            avatar_path = _agent_avatar_path_from_metadata(metadata)
            if avatar_path:
                avatar_counts[avatar_path] = avatar_counts.get(avatar_path, 0) + 1
        record_runtime_scene_event(
            "agent_directory",
            "agent_avatar",
            "agent.avatar_defaults_assigned",
            message="Default Agent avatars were assigned from workspace/avatars.",
            level="info",
            outcome="repaired",
            fields={
                "assignedCount": len(agents),
                "avatarPaths": sorted(avatar_counts),
            },
            lifecycle=True,
        )
    except Exception:
        return


def _record_agent_avatar_updated_event(agent: dict[str, Any]) -> None:
    try:
        metadata = agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}
        record_runtime_scene_event(
            "agent_directory",
            "agent_avatar",
            "agent.avatar_updated",
            message="Agent avatar was updated.",
            level="info",
            outcome="updated",
            fields={
                "agentId": str(agent.get("agentId") or "").strip(),
                "agentCode": _normalize_agent_code(agent.get("agentCode")),
                "avatarImagePath": _agent_avatar_path_from_metadata(metadata),
                "avatarImageSource": str(metadata.get("avatarImageSource") or "").strip(),
            },
            lifecycle=True,
        )
    except Exception:
        return


def _record_agent_avatar_uploaded_event(agent: dict[str, Any], *, content_type: str, size_bytes: int) -> None:
    try:
        record_runtime_scene_event(
            "agent_directory",
            "agent_avatar",
            "agent.avatar_uploaded",
            message="Agent avatar image was uploaded.",
            level="info",
            outcome="uploaded",
            fields={
                "agentId": str(agent.get("agentId") or "").strip(),
                "agentCode": _normalize_agent_code(agent.get("agentCode")),
                "contentType": str(content_type or "").strip(),
                "sizeBytes": int(size_bytes or 0),
            },
            lifecycle=True,
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


def _record_agent_reset_event(agent: dict[str, Any], summary: dict[str, Any]) -> None:
    try:
        record_runtime_scene_event(
            "agent_directory",
            "reset",
            "agent.reset.completed",
            message="Agent debug reset completed.",
            level="info",
            outcome="reset",
            fields={
                "agentId": str(agent.get("agentId") or summary.get("agentId") or "").strip(),
                "agentCode": _normalize_agent_code(agent.get("agentCode")),
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
                "readKnowledgeBaseCount": len(list(policy.get("readKnowledgeBaseIds") or [])),
                "proposeKnowledgeBaseCount": len(list(policy.get("proposeKnowledgeBaseIds") or [])),
                "reviewKnowledgeBaseCount": len(list(policy.get("reviewKnowledgeBaseIds") or [])),
                "rateKnowledgeBaseCount": len(list(policy.get("rateKnowledgeBaseIds") or [])),
                "hasPrivateMemoryRoot": bool(str(policy.get("privateMemoryRoot") or "").strip()),
            },
            lifecycle=True,
        )
    except Exception:
        return


def _record_agent_llm_binding_migration_event(agents: list[dict[str, Any]]) -> None:
    try:
        migrated_count = sum(1 for item in agents if item.get("migrated"))
        unresolved = [
            str(item.get("agentId") or "").strip()
            for item in agents
            if not str(item.get("dialogueModelId") or "").strip()
        ][:20]
        record_runtime_scene_event(
            "agent_directory",
            "agent_llm_bindings",
            "agent.llm_bindings_migrated",
            message="Legacy Agent profile/template fields were migrated to llmBindings.",
            level="warning" if unresolved else "info",
            outcome="repaired" if not unresolved else "partial",
            fields={
                "agentCount": len(agents),
                "migratedCount": migrated_count,
                "unresolvedCount": len(unresolved),
                "unresolvedAgentIds": unresolved,
                "sample": agents[:12],
            },
        )
    except Exception:
        return


def _record_knowledge_steward_repaired_event(
    agent: dict[str, Any],
    *,
    created: bool = False,
    repaired_fields: list[str] | None = None,
) -> None:
    try:
        record_runtime_scene_event(
            "agent_directory",
            "agent",
            "agent.knowledge_steward.repaired",
            message="Knowledge Steward Agent was created or repaired.",
            level="info",
            outcome="created" if created else "repaired",
            fields={
                "agentId": str(agent.get("agentId") or "").strip(),
                "agentCode": _normalize_agent_code(agent.get("agentCode")),
                "roleKey": _normalize_role_key(agent.get("roleKey")),
                "toolPolicyId": str(agent.get("toolPolicyId") or "").strip(),
                "memoryPolicyId": str(agent.get("memoryPolicyId") or "").strip(),
                "directSessionId": str(agent.get("directSessionId") or "").strip(),
                "repairedFields": list(repaired_fields or []),
                "permissionBoundary": "proposal_and_rating_suggestion_only",
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


def _record_agent_persona_profile_event(agent: dict[str, Any], profile: dict[str, Any]) -> None:
    try:
        normalized = normalize_persona_profile(profile)
        record_runtime_scene_event(
            "agent_directory",
            "persona_profile",
            "agent.persona_profile.updated",
            message="Agent persona profile was updated.",
            level="info",
            outcome="updated",
            fields={
                "agentId": str(agent.get("agentId") or "").strip(),
                "agentCode": _normalize_agent_code(agent.get("agentCode")),
                "fieldCount": sum(1 for field in AGENT_PERSONA_PROFILE_FIELDS if normalized.get(field)),
                "expertiseCount": len(list(normalized.get("expertise") or [])),
                "hasGender": bool(str(normalized.get("gender") or "").strip()),
                "hasAge": bool(str(normalized.get("age") or "").strip()),
                "source": "AgentDirectory",
            },
            lifecycle=True,
        )
    except Exception:
        return


def _record_agent_task_profile_event(agent: dict[str, Any], profile: dict[str, Any]) -> None:
    try:
        normalized = normalize_task_profile(profile)
        record_runtime_scene_event(
            "agent_directory",
            "task_profile",
            "agent.task_profile.updated",
            message="Agent task profile was updated.",
            level="info",
            outcome="updated",
            fields={
                "agentId": str(agent.get("agentId") or "").strip(),
                "agentCode": _normalize_agent_code(agent.get("agentCode")),
                "fieldCount": sum(1 for field in AGENT_TASK_PROFILE_FIELDS if normalized.get(field)),
                "taskTypeCount": len(list(normalized.get("taskTypes") or [])),
                "hasMission": bool(str(normalized.get("mission") or "").strip()),
                "hasSuccessCriteria": bool(str(normalized.get("successCriteria") or "").strip()),
                "source": "AgentDirectory",
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
