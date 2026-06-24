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
from core.logging import debug as _debug_logger
from core.ui.chat_state import load_chat_state

from . import agent_role_tool_profile_service
from .runtime_scene_service import record_runtime_scene_event
from .supervised_runtime_contract import supervised_role_runtime_tools


PROJECT_ROOT = Path(__file__).resolve().parents[3]
AGENT_REGISTRY_VERSION = 1
SUSPICIOUS_REGISTRY_SHRINK_MIN_AGENTS = 8
SUSPICIOUS_REGISTRY_SHRINK_MIN_DIRECT_AGENTS = 3
DEFAULT_AGENT_KIND = "persistent"
DEFAULT_TOOL_POLICY_ID = "default"
DEFAULT_MEMORY_POLICY_ID = "private"
DEFAULT_AGENT_PRIMARY_MODE = "chat"
DEFAULT_SESSION_AGENT_ALLOWED_TOOLS = (
    "grep_search_tool",
    "glob_tool",
    "code_symbol_tool",
    "apply_diff_edit_tool",
    "apply_patch_tool",
    "write_file_tool",
    "python_lint_tool",
    "run_test_for_tool",
    "cli_tool",
    "agent_message_tool",
    "agent_tool_permission_request_tool",
    "get_core_context_tool",
    "get_current_goal_tool",
    "task_list_tool",
    "get_git_status_summary_tool",
    "get_recent_changes_tool",
    "explain_current_worktree_tool",
    "conversation_log_inspect_tool",
)
DEFAULT_SESSION_AGENT_PREFERRED_TOOLS = (
    "grep_search_tool",
    "code_symbol_tool",
    "apply_patch_tool",
    "run_test_for_tool",
    "cli_tool",
    "get_core_context_tool",
    "conversation_log_inspect_tool",
)
SUBAGENT_DELEGATION_TOOL_NAMES = {
    "cli_agent_run_tool",
    "create_child_session_tool",
    "list_child_sessions_tool",
    "spawn_agent_tool",
}
DISABLED_AGENT_DIRECT_READ_TOOL_NAMES = {
    "read_file_tool",
}
SESSION_AGENT_VISIBILITY_ACTIVE = "active_session"
SESSION_AGENT_VISIBILITY_PENDING = "pending_activity"
SESSION_AGENT_VISIBILITY_NONE = "none"
SESSION_AGENT_ACTIVITY_FILES = (
    "turn_journal.jsonl",
    "logs/conversation.jsonl",
    "events/visible_messages.jsonl",
)
MUTATING_AGENT_TOOL_NAMES = {
    "apply_patch_tool",
    "apply_diff_edit_tool",
    "write_file_tool",
    "cli_tool",
    "cli_agent_run_tool",
    "run_test_for_tool",
    "python_lint_tool",
}
SYSTEM_NO_TOOL_MODES = {"self_evolution", "supervised_evolution"}
SYSTEM_NO_TOOL_ROLES = {
    "self_evolution": {"executor", "reviewer", "summarizer"},
    "supervised_evolution": {"baseline", "candidate", "reviewer", "auditor", "judge"},
}
RESEARCH_SOURCE_ROLE_KEYS = {
    "ai_search_scope_lead",
    "global_primary_sources",
    "cn_primary_sources",
    "signal_quality_gate",
    "challenge_cup_data_discovery",
    "challenge_cup_source_acquisition",
    "challenge_cup_content_extraction",
    "challenge_cup_source_quality",
}
RESEARCH_SOURCE_ALLOWED_TOOLS = (
    "agent_message_tool",
    "research_knowledge_query_tool",
    "web_fetch_tool",
    "batch_web_search_tool",
    "paper_search_tool",
    "project_search_tool",
    "news_search_tool",
    "search_summarize_sources_tool",
    "search_memory_tool",
)
RESEARCH_SOURCE_PREFERRED_TOOLS = (
    "research_knowledge_query_tool",
    "batch_web_search_tool",
    "paper_search_tool",
    "search_summarize_sources_tool",
    "agent_message_tool",
)
RESEARCH_SOURCE_ROLE_TOOL_PROFILES = {
    "challenge_cup_data_discovery": {
        "allowedTools": (
            "agent_message_tool",
            "research_knowledge_query_tool",
            "source_collection_context_tool",
            "source_collection_stage_writeback_tool",
            "batch_web_search_tool",
            "paper_search_tool",
            "project_search_tool",
            "news_search_tool",
            "search_summarize_sources_tool",
        ),
        "preferredTools": (
            "source_collection_context_tool",
            "source_collection_stage_writeback_tool",
            "batch_web_search_tool",
            "paper_search_tool",
            "search_summarize_sources_tool",
            "research_knowledge_query_tool",
            "agent_message_tool",
        ),
    },
    "challenge_cup_source_acquisition": {
        "allowedTools": (
            "agent_message_tool",
            "research_knowledge_query_tool",
            "source_collection_context_tool",
            "source_collection_stage_writeback_tool",
            "web_fetch_tool",
            "batch_web_search_tool",
            "paper_search_tool",
            "project_search_tool",
            "search_summarize_sources_tool",
        ),
        "preferredTools": (
            "source_collection_context_tool",
            "source_collection_stage_writeback_tool",
            "web_fetch_tool",
            "batch_web_search_tool",
            "paper_search_tool",
            "search_summarize_sources_tool",
            "research_knowledge_query_tool",
            "agent_message_tool",
        ),
    },
    "challenge_cup_content_extraction": {
        "allowedTools": (
            "agent_message_tool",
            "research_knowledge_query_tool",
            "source_collection_context_tool",
            "source_collection_stage_writeback_tool",
            "web_fetch_tool",
            "search_summarize_sources_tool",
        ),
        "preferredTools": (
            "source_collection_context_tool",
            "source_collection_stage_writeback_tool",
            "web_fetch_tool",
            "search_summarize_sources_tool",
            "research_knowledge_query_tool",
            "agent_message_tool",
        ),
    },
    "challenge_cup_source_quality": {
        "allowedTools": (
            "agent_message_tool",
            "research_knowledge_query_tool",
            "source_collection_context_tool",
            "source_collection_stage_writeback_tool",
            "web_fetch_tool",
            "batch_web_search_tool",
            "paper_search_tool",
            "project_search_tool",
            "news_search_tool",
            "search_summarize_sources_tool",
        ),
        "preferredTools": (
            "source_collection_context_tool",
            "source_collection_stage_writeback_tool",
            "research_knowledge_query_tool",
            "web_fetch_tool",
            "search_summarize_sources_tool",
            "batch_web_search_tool",
            "paper_search_tool",
            "agent_message_tool",
        ),
    },
}
CHALLENGE_CUP_ROLE_PROMPT_TEMPLATE_IDS = {
    "challenge_cup_coordinator": "prompt-challenge-cup-coordinator",
    "challenge_cup_data_discovery": "prompt-challenge-cup-data-discovery",
    "challenge_cup_source_acquisition": "prompt-challenge-cup-source-acquisition",
    "challenge_cup_content_extraction": "prompt-challenge-cup-content-extraction",
    "challenge_cup_source_quality": "prompt-challenge-cup-source-quality",
}
RESEARCH_ROLE_TOOL_PROFILES = {
    "candidate_graph": {
        "allowedTools": (
            "agent_message_tool",
            "research_knowledge_query_tool",
            "source_collection_context_tool",
            "source_collection_stage_writeback_tool",
        ),
        "preferredTools": (
            "source_collection_context_tool",
            "source_collection_stage_writeback_tool",
            "research_knowledge_query_tool",
            "agent_message_tool",
        ),
    },
    "research_paper_reader": {
        "allowedTools": (
            "agent_message_tool",
            "research_knowledge_query_tool",
            "web_fetch_tool",
            "batch_web_search_tool",
            "paper_search_tool",
            "search_summarize_sources_tool",
        ),
        "preferredTools": (
            "research_knowledge_query_tool",
            "paper_search_tool",
            "web_fetch_tool",
            "search_summarize_sources_tool",
            "agent_message_tool",
        ),
    },
}
AGENT_LLM_BINDING_SLOTS = AGENT_LLM_SLOTS
LEGACY_AGENT_MODEL_ID_ALIASES = {
    "gpt_5_5_gpt_5_5": "relay_openai_gpt_5_5",
    "mimo_v2_5_pro": "xiaomi_mimo_v2_5_pro_token_plan",
}
LEGACY_AGENT_PRIMARY_MODEL_IDS = {"model-primary"}
KNOWLEDGE_STEWARD_AGENT_ID = "agent-knowledge-steward"
KNOWLEDGE_STEWARD_TOOL_POLICY_ID = "tool-knowledge-steward"
KNOWLEDGE_STEWARD_MEMORY_POLICY_ID = "memory-knowledge-steward"
KNOWLEDGE_STEWARD_ROLE_KEY = "knowledge_steward"
KNOWLEDGE_STEWARD_PROMPT_TEMPLATE_ID = "prompt-knowledge-steward"
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
    "10-anime-session-agent.png",
    "11-anime-deep-research-agent.png",
    "12-anime-tool-executor-agent.png",
    "13-anime-review-evaluator-agent.png",
    "14-anime-source-collector-agent.png",
    "15-anime-memory-steward-agent.png",
    "16-anime-self-evolution-agent.png",
    "17-anime-team-coordinator-agent.png",
    "18-anime-system-service-agent.png",
    "19-anime-creative-writer-agent.png",
    "image2-1779953260549-43de200a.png",
    "image2-1779954683508-9fcd1834.png",
)
AGENT_AVATAR_PRIMARY_DEFAULTS = (
    "01-session-agent.png",
    "02-diagnose-agent.png",
    "03-inspect-agent.png",
    "04-summarize-agent.png",
    "05-broad-explorer.png",
    "06-deep-investigator.png",
    "07-evidence-reviewer.png",
    "08-theme-synthesizer.png",
    "09-card-planner.png",
)
AGENT_AVATAR_GENERATED_FALLBACKS = (
    "10-anime-session-agent.png",
    "11-anime-deep-research-agent.png",
    "12-anime-tool-executor-agent.png",
    "13-anime-review-evaluator-agent.png",
    "14-anime-source-collector-agent.png",
    "15-anime-memory-steward-agent.png",
    "16-anime-self-evolution-agent.png",
    "17-anime-team-coordinator-agent.png",
    "18-anime-system-service-agent.png",
    "19-anime-creative-writer-agent.png",
)
AGENT_AVATAR_ROLE_DEFAULTS = (
    (("chat",), ("01-session-agent.png", "10-anime-session-agent.png")),
    (("general",), ("01-session-agent.png", "10-anime-session-agent.png")),
    (("source",), ("05-broad-explorer.png", "14-anime-source-collector-agent.png")),
    (("acquisition",), ("05-broad-explorer.png", "14-anime-source-collector-agent.png")),
    (("discovery",), ("05-broad-explorer.png", "14-anime-source-collector-agent.png")),
    (("content",), ("02-diagnose-agent.png", "12-anime-tool-executor-agent.png")),
    (("extraction",), ("02-diagnose-agent.png", "12-anime-tool-executor-agent.png")),
    (("memory",), ("04-summarize-agent.png", "15-anime-memory-steward-agent.png")),
    (("knowledge",), ("04-summarize-agent.png", "15-anime-memory-steward-agent.png")),
    (("steward",), ("04-summarize-agent.png", "15-anime-memory-steward-agent.png")),
    (("self_evolution",), ("03-inspect-agent.png", "16-anime-self-evolution-agent.png")),
    (("self-evolution",), ("03-inspect-agent.png", "16-anime-self-evolution-agent.png")),
    (("optimization",), ("03-inspect-agent.png", "16-anime-self-evolution-agent.png")),
    (("team",), ("09-card-planner.png", "17-anime-team-coordinator-agent.png")),
    (("coordinator",), ("09-card-planner.png", "17-anime-team-coordinator-agent.png")),
    (("orchestrat",), ("09-card-planner.png", "17-anime-team-coordinator-agent.png")),
    (("system",), ("03-inspect-agent.png", "18-anime-system-service-agent.png")),
    (("service",), ("03-inspect-agent.png", "18-anime-system-service-agent.png")),
    (("creative",), ("08-theme-synthesizer.png", "19-anime-creative-writer-agent.png")),
    (("writing",), ("08-theme-synthesizer.png", "19-anime-creative-writer-agent.png")),
    (("synthesis",), ("08-theme-synthesizer.png", "19-anime-creative-writer-agent.png")),
    (("research", "broad"), ("05-broad-explorer.png", "14-anime-source-collector-agent.png")),
    (("research", "deep"), ("06-deep-investigator.png", "11-anime-deep-research-agent.png")),
    (("research", "theme"), ("08-theme-synthesizer.png", "19-anime-creative-writer-agent.png")),
    (("research", "card"), ("09-card-planner.png", "19-anime-creative-writer-agent.png")),
    (("research", "planner"), ("09-card-planner.png", "17-anime-team-coordinator-agent.png")),
    (("summar",), ("04-summarize-agent.png", "19-anime-creative-writer-agent.png")),
    (("review",), ("07-evidence-reviewer.png", "13-anime-review-evaluator-agent.png")),
    (("evidence",), ("07-evidence-reviewer.png", "13-anime-review-evaluator-agent.png")),
    (("judge",), ("07-evidence-reviewer.png", "13-anime-review-evaluator-agent.png")),
    (("audit",), ("07-evidence-reviewer.png", "13-anime-review-evaluator-agent.png")),
    (("inspect",), ("03-inspect-agent.png", "13-anime-review-evaluator-agent.png")),
    (("diagnose",), ("02-diagnose-agent.png", "12-anime-tool-executor-agent.png")),
    (("debug",), ("02-diagnose-agent.png", "12-anime-tool-executor-agent.png")),
    (("tool",), ("02-diagnose-agent.png", "12-anime-tool-executor-agent.png")),
    (("execute",), ("02-diagnose-agent.png", "12-anime-tool-executor-agent.png")),
    (("baseline",), ("07-evidence-reviewer.png", "13-anime-review-evaluator-agent.png")),
    (("candidate",), ("02-diagnose-agent.png", "12-anime-tool-executor-agent.png")),
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
DEFAULT_AGENT_CONTEXT_COMPRESSION_POLICY = {
    "mode": "inherit",
}
DEFAULT_CONTEXT_COMPRESSION_LEVELS = {
    "light": 0.6,
    "standard": 0.8,
    "deep": 0.9,
    "emergency": 0.95,
}
DEFAULT_CONTEXT_COMPRESSION_SUMMARY_CHARS = {
    "light": 500,
    "standard": 1000,
    "deep": 2000,
    "emergency": 3000,
}
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
EXPLICIT_TOOL_POLICY_REQUIRED_TOOLS: set[str] = set()
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
_AGENT_API_HYDRATION_CACHE_LOCK = threading.RLock()
_AGENT_API_HYDRATION_CACHE_SIGNATURE: tuple[Any, ...] | None = None
_AGENT_API_HYDRATION_CACHE_FAST_SIGNATURE: tuple[Any, ...] | None = None
_AGENT_API_HYDRATION_CACHE_VALIDATED_AT = 0.0
_AGENT_API_HYDRATION_EVENT_VERSION = 0
_AGENT_API_HYDRATION_CACHE: AgentApiHydrationContext | None = None
_AGENT_API_HYDRATION_FAST_TTL_SECONDS = 15.0
_AGENT_API_HYDRATION_EVENT_FILENAMES = frozenset(
    {
        "tool_governance_requests.jsonl",
        "group_context_events.jsonl",
        "agent_inbox_messages.jsonl",
    }
)
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
    context_compression_base_policy: Any
    model_context_window_limits_by_model_id: dict[str, int]
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
    if normalized_detail not in {"full", "summary", "config"}:
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
    elif normalized_detail == "config":
        stage_started = time.perf_counter()
        hydration = _build_agent_api_config_hydration_context(state, raw_agents, timings=hydration_timings)
        timings["hydrate"] = round((time.perf_counter() - stage_started) * 1000, 1)
        hydration_timings["activity_hydration"] = 0.0
        stage_started = time.perf_counter()
        agents = [
            _agent_to_api(
                item,
                hydration=hydration,
                include_activity=False,
                include_tool_governance=True,
                include_inbox_pending_count=True,
            )
            for item in raw_agents
        ]
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
    context_compression_policy: dict[str, Any] | None = None,
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
        if not normalized_prompt_template_id:
            normalized_prompt_template_id = _prompt_template_id_for_role(normalized_role_key)
        normalized_context_compression_policy = normalize_agent_context_compression_policy(context_compression_policy)
        normalized_direct_session_id = str(direct_session_id or "").strip()
        _ensure_active_direct_session_available(
            state,
            normalized_direct_session_id,
            agent_id=agent_id,
        )
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
            "directSessionId": normalized_direct_session_id,
            "workspacePath": agent_workspace,
            "toolPolicyId": tool_policy_id,
            "memoryPolicyId": memory_policy_id,
            "contextCompressionPolicy": normalized_context_compression_policy,
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
            session_visibility = _direct_session_visibility(
                normalized_session_id,
                session_workspace_path=session_workspace_path,
            )
            created = create_agent_instance(
                display_name=display_name or normalized_session_id,
                llm_bindings=normalized_llm_bindings,
                primary_mode=primary_mode,
                role_key=role_key,
                prompt_template_id=prompt_template_id,
                direct_session_id=normalized_session_id,
                created_by=created_by,
                metadata={
                    "legacySessionWorkspacePath": str(session_workspace_path or "").strip(),
                    "directSessionVisibility": session_visibility,
                },
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
            _ensure_active_direct_session_available(
                state,
                normalized_session_id,
                agent_id=str(agent.get("agentId") or "").strip(),
            )
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
        session_visibility = _direct_session_visibility(
            normalized_session_id,
            session_workspace_path=str(metadata.get("legacySessionWorkspacePath") or legacy_path),
        )
        if session_visibility != str(metadata.get("directSessionVisibility") or "").strip():
            metadata["directSessionVisibility"] = session_visibility
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


def session_agent_visibility(agent: dict[str, Any] | None) -> str:
    """Return whether a direct chat Agent is backed by real session activity."""

    if not isinstance(agent, dict):
        return SESSION_AGENT_VISIBILITY_NONE
    primary_mode = _normalize_primary_mode(agent.get("primaryMode") or _infer_agent_primary_mode(agent))
    direct_session_id = str(agent.get("directSessionId") or "").strip()
    if primary_mode != "chat" or not direct_session_id:
        return SESSION_AGENT_VISIBILITY_NONE
    metadata = agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}
    legacy_workspace_path = str(metadata.get("legacySessionWorkspacePath") or "").strip()
    visibility = str(metadata.get("directSessionVisibility") or "").strip()
    if direct_session_id == _active_chat_session_id():
        return SESSION_AGENT_VISIBILITY_ACTIVE
    if visibility == SESSION_AGENT_VISIBILITY_ACTIVE:
        return SESSION_AGENT_VISIBILITY_ACTIVE
    if visibility == SESSION_AGENT_VISIBILITY_PENDING:
        if _session_workspace_has_activity(
            direct_session_id,
            session_workspace_path=legacy_workspace_path,
        ):
            return SESSION_AGENT_VISIBILITY_ACTIVE
        return SESSION_AGENT_VISIBILITY_PENDING
    session_root_exists = _session_workspace_root_exists(direct_session_id)
    if (
        not legacy_workspace_path
        and not direct_session_id.startswith("session-seed-")
        and direct_session_id != "session-coordinator"
        and not session_root_exists
    ):
        return SESSION_AGENT_VISIBILITY_ACTIVE
    return _direct_session_visibility(
        direct_session_id,
        session_workspace_path=legacy_workspace_path,
    )


def _active_chat_session_id() -> str:
    try:
        payload = load_chat_state(PROJECT_ROOT)
    except Exception:
        return ""
    if not isinstance(payload, dict):
        return ""
    return str(payload.get("active_conversation_id") or "").strip()


def _direct_session_visibility(
    session_id: str,
    *,
    session_workspace_path: str = "",
) -> str:
    normalized_session_id = str(session_id or "").strip()
    if not normalized_session_id:
        return SESSION_AGENT_VISIBILITY_NONE
    if _session_workspace_has_activity(normalized_session_id, session_workspace_path=session_workspace_path):
        return SESSION_AGENT_VISIBILITY_ACTIVE
    return SESSION_AGENT_VISIBILITY_PENDING


def _session_workspace_has_activity(session_id: str, *, session_workspace_path: str = "") -> bool:
    session_id = str(session_id or "").strip()
    candidates: list[Path] = []
    raw_workspace_path = str(session_workspace_path or "").strip()
    if raw_workspace_path:
        candidates.append(_resolve_project_path(raw_workspace_path))
    if session_id:
        candidates.append(_workspace_path("sessions", session_id, seed=False))

    seen: set[Path] = set()
    for session_root in candidates:
        resolved = Path(session_root).resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        for relative in SESSION_AGENT_ACTIVITY_FILES:
            if _jsonl_file_has_records(resolved / relative):
                return True
    return False


def _session_workspace_root_exists(session_id: str) -> bool:
    normalized_session_id = str(session_id or "").strip()
    if not normalized_session_id:
        return False
    try:
        return _workspace_path("sessions", normalized_session_id, seed=False).exists()
    except OSError:
        return False


def _jsonl_file_has_records(path: Path) -> bool:
    try:
        if not path.is_file() or path.stat().st_size <= 0:
            return False
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    return True
    except OSError:
        return False
    return False


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
    context_compression_policy: dict[str, Any] | None = None,
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
            normalized_direct_session_id = str(direct_session_id or "").strip()
            _ensure_active_direct_session_available(
                state,
                normalized_direct_session_id,
                agent_id=str(agent.get("agentId") or "").strip(),
            )
            agent["directSessionId"] = normalized_direct_session_id
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
        if context_compression_policy is not None:
            agent["contextCompressionPolicy"] = normalize_agent_context_compression_policy(context_compression_policy)
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
                if _persona_profile_has_content(updated_persona_profile):
                    metadata_payload.pop("personaProfileDefaultsDisabled", None)
                else:
                    metadata_payload["personaProfileDefaultsDisabled"] = True
            agent["metadata"] = metadata_payload
        if task_profile is not None:
            metadata_payload = dict(agent.get("metadata") or {})
            if _is_profileless_session_agent(agent):
                metadata_payload.pop("taskProfile", None)
            else:
                updated_task_profile = normalize_task_profile(task_profile)
                metadata_payload["taskProfile"] = updated_task_profile
                if _task_profile_has_content(updated_task_profile):
                    metadata_payload.pop("taskProfileDefaultsDisabled", None)
                else:
                    metadata_payload["taskProfileDefaultsDisabled"] = True
            agent["metadata"] = metadata_payload
        if (tool_policy_id is not None or primary_mode is not None) and _ensure_session_agent_tool_policy(state, agent):
            policy_id = str(agent.get("toolPolicyId") or DEFAULT_TOOL_POLICY_ID).strip() or DEFAULT_TOOL_POLICY_ID
            policies = _tool_policies(state)
            updated_tool_policy = normalize_tool_policy(policies.get(policy_id) or default_tool_policy(policy_id), policy_id)
            state["toolPolicies"] = policies
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


def purge_archived_agent_instance(agent_id: str, *, allow_active: bool = False) -> dict[str, Any]:
    """Physically remove an AgentInstance and its private workspace."""

    normalized_agent_id = str(agent_id or "").strip()
    if not normalized_agent_id:
        raise AgentDirectoryError("Agent id is required.")
    with _STATE_LOCK:
        state = load_state()
        agent = _find_agent(state, normalized_agent_id)
        if agent is None:
            raise AgentNotFoundError(f"Agent not found: {normalized_agent_id}")
        previous_status = str(agent.get("status") or "active").strip() or "active"
        if previous_status != "archived" and not allow_active:
            raise AgentDirectoryError("Only archived Agents can be permanently deleted.")
        if _agent_archive_protected(agent):
            raise AgentDirectoryError("Protected core Agent cannot be purged.")
        agent_snapshot = dict(agent)
        agent_snapshot["status"] = previous_status
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
        current_status = str(agent.get("status") or "active").strip() or "active"
        if current_status != "archived" and not allow_active:
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
    _record_agent_purged_event(agent_snapshot, result)
    return result


def ensure_agent_purge_workspace_deletable(agent: dict[str, Any]) -> dict[str, Any]:
    """Validate the purge workspace boundary before callers mutate external references."""

    agent_id = str(agent.get("agentId") or "").strip()
    workspace_path = str(agent.get("workspacePath") or _agent_workspace_relative_path(agent_id)).strip()
    if not agent_id or not workspace_path:
        return {"deletable": True, "workspacePath": workspace_path, "reason": "no_workspace_path"}
    try:
        resolved = _resolve_project_path(workspace_path)
        agents_root = _workspace_path("agents").resolve()
        expected_private = _resolve_project_path(_agent_workspace_relative_path(agent_id))
    except Exception as exc:
        raise AgentDirectoryError(f"Agent workspace path could not be resolved: {type(exc).__name__}") from exc
    if resolved != expected_private:
        raise AgentDirectoryError(f"Agent workspace path is not the expected private workspace: {_relative_project_path(resolved)}")
    try:
        if not resolved.is_relative_to(agents_root):
            raise AgentDirectoryError(f"Agent workspace path is outside the agents root: {_relative_project_path(resolved)}")
    except ValueError as exc:
        raise AgentDirectoryError(f"Agent workspace path is outside the agents root: {_relative_project_path(resolved)}") from exc
    if not resolved.exists():
        return {"deletable": True, "workspacePath": _relative_project_path(resolved), "reason": "workspace_absent"}
    if not resolved.is_dir():
        raise AgentDirectoryError(f"Agent workspace path is not a directory: {_relative_project_path(resolved)}")
    return {"deletable": True, "workspacePath": _relative_project_path(resolved), "reason": "workspace_present"}


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
                metadata["personaProfileDefaultsDisabled"] = True
                reset_summary["resetPersonaProfile"] = True
            agent["metadata"] = metadata
        if reset_task_profile:
            metadata = dict(agent.get("metadata") or {})
            if profileless_session_agent:
                metadata.pop("taskProfile", None)
            else:
                updated_task_profile = normalize_task_profile({})
                metadata["taskProfile"] = updated_task_profile
                metadata["taskProfileDefaultsDisabled"] = True
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
        if reset_summary["resetDirectSession"] and reset_summary["replacementDirectSessionId"]:
            with _STATE_LOCK:
                state = load_state()
                agent = _find_agent(state, normalized_agent_id)
                if agent is not None:
                    metadata = dict(agent.get("metadata") or {})
                    metadata["directSessionVisibility"] = SESSION_AGENT_VISIBILITY_ACTIVE
                    agent["metadata"] = metadata
                    agent["updatedAt"] = utc_now_iso()
                    save_state(state)

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
        state_signature = _agent_directory_storage_signature(state)
        changed = False
        knowledge_steward_result = _ensure_knowledge_steward_agent(state)
        if knowledge_steward_result.get("changed"):
            changed = True
        display_name_repaired_agents: list[dict[str, Any]] = []
        avatar_defaulted_agents: list[dict[str, Any]] = []
        territory_repaired_agents: list[dict[str, Any]] = []
        llm_binding_migrated_agents: list[dict[str, Any]] = []
        profile_repaired_agents: list[dict[str, Any]] = []
        tool_policy_repaired_agents: list[tuple[dict[str, Any], dict[str, Any]]] = []
        model_library_ids = _configured_model_library_ids()
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
            model_ref_repair = _repair_agent_llm_binding_model_refs(agent, model_library_ids=model_library_ids)
            if model_ref_repair.get("changed"):
                for item in list(model_ref_repair.get("repairs") or []):
                    llm_binding_migrated_agents.append(
                        {
                            "agentId": str(agent.get("agentId") or "").strip(),
                            "agentCode": _normalize_agent_code(agent.get("agentCode")),
                            "legacyModelId": str(item.get("legacyModelId") or "").strip(),
                            "dialogueModelId": str(agent_dialogue_model_id(agent) or "").strip(),
                            "canonicalModelId": str(item.get("canonicalModelId") or "").strip(),
                            "slot": str(item.get("slot") or "").strip(),
                            "migrated": True,
                            "repairKind": "legacy_model_id_alias",
                        }
                    )
                changed = True
            if _normalize_agent_legacy_metadata_fields(agent):
                changed = True
            if _ensure_fixed_role_profiles(agent):
                profile_repaired_agents.append(dict(agent))
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
            prompt_template_id = _infer_agent_prompt_template_id(agent)
            current_prompt_template_id = str(agent.get("promptTemplateId") or "").strip()
            if prompt_template_id and _should_repair_agent_prompt_template_id(current_prompt_template_id, prompt_template_id):
                agent["promptTemplateId"] = prompt_template_id
                changed = True
            elif current_prompt_template_id:
                normalized_prompt_template_id = _normalize_prompt_template_id(current_prompt_template_id)
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
            fixed_role_policy = _ensure_fixed_role_tool_policy(state, agent)
            if fixed_role_policy is not None:
                tool_policy_repaired_agents.append((dict(agent), dict(fixed_role_policy)))
                changed = True
            _refresh_agent_onboarding_metadata(state, agent)
        state["memoryPolicies"] = policies
        if changed and _agent_directory_storage_signature(state) != state_signature:
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
            for repaired_agent in profile_repaired_agents:
                _record_agent_event("agent.profile_repaired", repaired_agent)
            for repaired_agent, repaired_policy in tool_policy_repaired_agents:
                _record_agent_tool_policy_event(repaired_agent, repaired_policy)
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
    supervised_role = str(os.environ.get("VIBELUTION_SUPERVISED_ROLE") or "").strip()
    agent = _agent_from_runtime_env(agent_id)
    delegation_policy = resolve_delegation_policy_for_agent(agent_id)
    tool_policy = resolve_tool_policy_for_agent(agent_id, session_id=session_id)
    tool_policy = _with_runtime_tool_grants(
        tool_policy,
        supervised_role_runtime_tools(supervised_role),
        source="supervised_conversation_harness" if supervised_role else "",
    )
    tool_policy = _effective_agent_tool_policy(tool_policy, delegation_policy)
    return {
        "agentId": agent_id,
        "sessionId": session_id,
        "turnId": "",
        "roomId": "",
        "roundId": "",
        "supervisedRole": supervised_role,
        "agent": agent,
        "toolPolicy": tool_policy,
        "memoryPolicy": resolve_memory_policy_for_agent(agent_id),
        "delegationPolicy": delegation_policy,
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
    supervised_role: str = "",
    runtime_tool_grants: Iterable[Any] | None = None,
    runtime_tool_source: str = "",
):
    agent = get_agent(agent_id) if agent_id else None
    normalized_supervised_role = str(supervised_role or "").strip()
    grants = (
        _tool_name_list(runtime_tool_grants or [])
        if runtime_tool_grants is not None
        else supervised_role_runtime_tools(normalized_supervised_role)
    )
    delegation_policy = resolve_delegation_policy_for_agent(agent_id)
    tool_policy = resolve_tool_policy_for_agent(agent_id, session_id=session_id, turn_id=turn_id)
    tool_policy = _with_runtime_tool_grants(
        tool_policy,
        grants,
        source=str(runtime_tool_source or "").strip()
        or ("supervised_conversation_harness" if normalized_supervised_role else ""),
    )
    tool_policy = _effective_agent_tool_policy(tool_policy, delegation_policy)
    context = {
        "agentId": str(agent_id or "").strip(),
        "sessionId": str(session_id or "").strip(),
        "turnId": str(turn_id or "").strip(),
        "roomId": str(room_id or "").strip(),
        "roundId": str(round_id or "").strip(),
        "supervisedRole": normalized_supervised_role,
        "agent": agent or {},
        "toolPolicy": tool_policy,
        "memoryPolicy": resolve_memory_policy_for_agent(agent_id),
        "delegationPolicy": delegation_policy,
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


def _without_subagent_delegation_tools(policy: dict[str, Any], delegation_policy: dict[str, Any] | None) -> dict[str, Any]:
    normalized_policy = normalize_delegation_policy(delegation_policy)
    if bool(normalized_policy.get("allowSubagents", False)):
        return policy
    blocked_tools = SUBAGENT_DELEGATION_TOOL_NAMES
    allowed = [name for name in _tool_name_list(policy.get("allowedTools") or []) if name not in blocked_tools]
    preferred = [name for name in _tool_name_list(policy.get("preferredTools") or []) if name not in blocked_tools]
    if allowed == _tool_name_list(policy.get("allowedTools") or []) and preferred == _tool_name_list(
        policy.get("preferredTools") or []
    ):
        return policy
    return {
        **policy,
        "allowedTools": allowed,
        "preferredTools": preferred,
    }


def _without_disabled_agent_tools(policy: dict[str, Any]) -> dict[str, Any]:
    blocked_tools = DISABLED_AGENT_DIRECT_READ_TOOL_NAMES
    allowed = [name for name in _tool_name_list(policy.get("allowedTools") or []) if name not in blocked_tools]
    preferred = [name for name in _tool_name_list(policy.get("preferredTools") or []) if name not in blocked_tools]
    temporary_allowed = [
        name for name in _tool_name_list(policy.get("temporaryAllowedTools") or []) if name not in blocked_tools
    ]
    if (
        allowed == _tool_name_list(policy.get("allowedTools") or [])
        and preferred == _tool_name_list(policy.get("preferredTools") or [])
        and temporary_allowed == _tool_name_list(policy.get("temporaryAllowedTools") or [])
    ):
        return policy
    return {
        **policy,
        "allowedTools": allowed,
        "preferredTools": preferred,
        "temporaryAllowedTools": temporary_allowed,
    }


def _effective_agent_tool_policy(policy: dict[str, Any], delegation_policy: dict[str, Any] | None) -> dict[str, Any]:
    return _without_disabled_agent_tools(_without_subagent_delegation_tools(policy, delegation_policy))


def _with_runtime_tool_grants(
    policy: dict[str, Any],
    grants: Iterable[Any],
    *,
    source: str = "",
) -> dict[str, Any]:
    runtime_grants = _tool_name_list(grants or [])
    if not runtime_grants:
        return policy
    allowed = _tool_name_list(policy.get("allowedTools") or [])
    blocked = set(_tool_name_list(policy.get("blockedTools") or []))
    added: list[str] = []
    for tool in runtime_grants:
        if not tool or tool in blocked or tool in allowed:
            continue
        allowed.append(tool)
        added.append(tool)
    if not added:
        return policy
    return {
        **policy,
        "allowedTools": allowed,
        "temporaryAllowedTools": _tool_name_list(list(policy.get("temporaryAllowedTools") or []) + added),
        "runtimeToolSource": str(source or "").strip(),
    }


def compute_effective_tool_visibility(
    tools: Iterable[Any],
    *,
    policy: dict[str, Any] | None = None,
) -> EffectiveToolVisibility:
    normalized_policy = _without_disabled_agent_tools(policy if isinstance(policy, dict) else {})
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
    allowed_set = set(allowed)
    blocked_set = set(blocked)
    visible = tuple(
        name
        for name in tool_names
        if name in allowed_set and name not in blocked_set
    )
    visible_set = set(visible)
    preferred = tuple(
        name
        for name in _tool_name_list(normalized_policy.get("preferredTools") or [])
        if name in visible_set
    )
    hidden_restricted = tuple(
        name
        for name in tool_names
        if name not in visible_set
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
        blocked_tools=tuple(name for name in blocked if name in tool_name_set),
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
        except Exception as exc:
            _debug_logger.warning(
                f"Failed to build default LLM-facing tool list. Falling back to empty list. error={type(exc).__name__}: {exc}",
                tag="AGENT_TOOL_DIRECTORY",
            )
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


def resolve_tool_policy_for_agent(agent_id: str, *, session_id: str = "", turn_id: str = "") -> dict[str, Any]:
    agent = _find_agent(load_state(), agent_id)
    if agent is None:
        return default_tool_policy(DEFAULT_TOOL_POLICY_ID)
    state = load_state()
    policy_id = str(agent.get("toolPolicyId") or DEFAULT_TOOL_POLICY_ID).strip() or DEFAULT_TOOL_POLICY_ID
    policy = _tool_policies(state).get(policy_id) or default_tool_policy(policy_id)
    normalized = normalize_tool_policy(policy, policy_id)
    with_grants = _with_temporary_tool_grants(
        normalized,
        agent_id=agent_id,
        session_id=session_id,
        turn_id=turn_id,
    )
    metadata = agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}
    return _effective_agent_tool_policy(with_grants, metadata.get("delegationPolicy") if isinstance(metadata, dict) else {})


def _with_temporary_tool_grants(
    policy: dict[str, Any],
    *,
    agent_id: str,
    session_id: str = "",
    turn_id: str = "",
) -> dict[str, Any]:
    normalized_session_id = str(session_id or "").strip()
    if not normalized_session_id:
        return policy
    try:
        from core.web.services import agent_tool_governance_service

        temporary_grants = agent_tool_governance_service.temporary_granted_tools_for_agent(
            agent_id,
            session_id=normalized_session_id,
            turn_id=turn_id,
        )
    except Exception as exc:
        _debug_logger.warning(
            f"Failed to load temporary tool grants for agent={agent_id}, session_id={normalized_session_id}, turn_id={turn_id}. error={type(exc).__name__}: {exc}",
            tag="AGENT_TOOL_DIRECTORY",
        )
        return policy
    if not temporary_grants:
        return policy

    allowed = _tool_name_list(policy.get("allowedTools") or [])
    blocked = set(_tool_name_list(policy.get("blockedTools") or []))
    temporary_allowed: list[str] = []
    for tool in _tool_name_list(temporary_grants):
        if not tool or tool in blocked or tool in allowed:
            continue
        allowed.append(tool)
        temporary_allowed.append(tool)
    if not temporary_allowed:
        return policy
    return {
        **policy,
        "allowedTools": allowed,
        "temporaryAllowedTools": _tool_name_list(list(policy.get("temporaryAllowedTools") or []) + temporary_allowed),
    }


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
    shared_root = _workspace_path("shared").resolve()
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
    normalized_tool = str(tool_name or "").strip()
    delegation_policy = normalize_delegation_policy(runtime.get("delegationPolicy"))
    if normalized_tool in DISABLED_AGENT_DIRECT_READ_TOOL_NAMES:
        policy = runtime.get("toolPolicy") or {}
        policy_id = str(policy.get("policyId") or policy.get("id") or "").strip() or DEFAULT_TOOL_POLICY_ID
        decision = _blocked_decision(
            normalized_tool,
            "direct_read_tool_disabled",
            policy_id,
            agent_id,
            f"[工具策略提示] 当前 Agent 默认关闭 `{normalized_tool}`；请改用 `cli_tool` 执行 `rg` 与小范围命令读取。",
        )
        _record_policy_block(agent_id, policy, normalized_tool, tool_args, decision)
        return decision
    if normalized_tool in SUBAGENT_DELEGATION_TOOL_NAMES and not bool(
        delegation_policy.get("allowSubagents", False)
    ):
        policy = runtime.get("toolPolicy") or {}
        policy_id = str(policy.get("policyId") or policy.get("id") or "").strip() or DEFAULT_TOOL_POLICY_ID
        decision = _blocked_decision(
            normalized_tool,
            "subagent_delegation_disabled",
            policy_id,
            agent_id,
            f"[委托策略提示] 当前 Agent 默认关闭子 agent 派发权限，`{normalized_tool}` 已被拦截。",
        )
        _record_policy_block(agent_id, policy, normalized_tool, tool_args, decision)
        return decision
    policy = runtime.get("toolPolicy") or {}
    decision = evaluate_tool_policy(
        normalized_tool,
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
    if not normalized_tool:
        return _blocked_decision(
            normalized_tool,
            "missing_tool",
            policy_id,
            agent_id,
            "[工具策略提示] 当前工具调用缺少工具名称，已被 ToolPolicy 拦截。",
        )
    blocked = set(_tool_name_list(policy.get("blockedTools") or []))
    if normalized_tool in blocked:
        return _blocked_decision(
            normalized_tool,
            "blocked_tool",
            policy_id,
            agent_id,
            f"[工具策略提示] `{normalized_tool}` 已被该 Agent 的 ToolPolicy 禁用。",
        )
    allowed = set(_tool_name_list(policy.get("allowedTools") or []))
    if not allowed:
        return _blocked_decision(
            normalized_tool,
            "no_allowed_tools",
            policy_id,
            agent_id,
            "[工具策略提示] 当前 Agent 未配置可用工具，工具调用已被拦截。",
        )
    if normalized_tool not in allowed:
        return _blocked_decision(
            normalized_tool,
            "tool_not_allowed",
            policy_id,
            agent_id,
            f"[工具策略提示] `{normalized_tool}` 不在该 Agent 的可用工具策略中。",
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


def default_system_no_tool_policy(policy_id: str) -> dict[str, Any]:
    payload = default_tool_policy(policy_id)
    payload["networkAccess"] = "none"
    payload["mutationAccess"] = "none"
    return payload


def default_research_source_tool_policy(policy_id: str, *, role_key: str = "") -> dict[str, Any]:
    payload = default_tool_policy(policy_id)
    resolved = agent_role_tool_profile_service.resolve_role_tool_policy(
        role_key=role_key,
        primary_mode="research",
        policy_id=policy_id,
    )
    if resolved:
        payload.update(resolved)
    else:
        profile = RESEARCH_SOURCE_ROLE_TOOL_PROFILES.get(_normalize_role_key(role_key), {})
        payload["allowedTools"] = list(profile.get("allowedTools") or RESEARCH_SOURCE_ALLOWED_TOOLS)
        payload["preferredTools"] = list(profile.get("preferredTools") or RESEARCH_SOURCE_PREFERRED_TOOLS)
        payload["readScopes"] = ["private", "shared"]
        payload["writeScopes"] = []
        payload["networkAccess"] = "controlled"
        payload["mutationAccess"] = "none"
        payload["maxCallsPerTurn"] = 8
    return payload


def default_research_role_tool_policy(policy_id: str, *, role_key: str = "") -> dict[str, Any]:
    payload = default_tool_policy(policy_id)
    resolved = agent_role_tool_profile_service.resolve_role_tool_policy(
        role_key=role_key,
        primary_mode="research",
        policy_id=policy_id,
    )
    if resolved:
        payload.update(resolved)
    else:
        profile = RESEARCH_ROLE_TOOL_PROFILES.get(_normalize_role_key(role_key), {})
        payload["allowedTools"] = list(profile.get("allowedTools") or ("agent_message_tool", "research_knowledge_query_tool"))
        payload["preferredTools"] = list(profile.get("preferredTools") or payload["allowedTools"])
        payload["readScopes"] = ["private", "shared"]
        payload["writeScopes"] = []
        payload["networkAccess"] = "controlled"
        payload["mutationAccess"] = "none"
        payload["maxCallsPerTurn"] = 8
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
    policy_missing = current_policy_id not in policies
    if current_policy_id != DEFAULT_TOOL_POLICY_ID and not policy_missing:
        return False

    policy_id = current_policy_id if policy_missing and current_policy_id != DEFAULT_TOOL_POLICY_ID else f"tool-{agent_id}"
    policies[policy_id] = default_session_agent_tool_policy(policy_id)
    state["toolPolicies"] = policies
    agent["toolPolicyId"] = policy_id
    return True


def _ensure_fixed_role_tool_policy(state: dict[str, Any], agent: dict[str, Any]) -> dict[str, Any] | None:
    desired_kind = _fixed_role_tool_policy_kind(agent)
    if not desired_kind:
        return None
    agent_id = str(agent.get("agentId") or "").strip()
    if not agent_id:
        return None
    policy_id = f"tool-{agent_id}"
    policies = _tool_policies(state)
    if desired_kind == "research_source":
        desired_policy = default_research_source_tool_policy(policy_id, role_key=str(agent.get("roleKey") or ""))
    elif desired_kind == "research_role":
        desired_policy = default_research_role_tool_policy(policy_id, role_key=str(agent.get("roleKey") or ""))
    else:
        desired_policy = default_system_no_tool_policy(policy_id)
    current_policy_id = str(agent.get("toolPolicyId") or DEFAULT_TOOL_POLICY_ID).strip() or DEFAULT_TOOL_POLICY_ID
    current_policy = normalize_tool_policy(policies.get(current_policy_id) or default_tool_policy(current_policy_id), current_policy_id)
    next_policy = normalize_tool_policy(
        {
            **desired_policy,
            "perToolRules": dict(current_policy.get("perToolRules") or {}),
        },
        policy_id,
    )
    if current_policy_id == policy_id and policies.get(policy_id) == next_policy:
        return None
    previous_policy_id = current_policy_id
    policies[policy_id] = next_policy
    previous_policy_is_orphaned = (
        previous_policy_id != DEFAULT_TOOL_POLICY_ID
        and previous_policy_id != policy_id
        and _count_policy_refs(state.get("agents") or [], "toolPolicyId", previous_policy_id) == 1
    )
    if previous_policy_is_orphaned:
        policies.pop(previous_policy_id, None)
    state["toolPolicies"] = policies
    agent["toolPolicyId"] = policy_id
    return next_policy


def _fixed_role_tool_policy_kind(agent: dict[str, Any]) -> str:
    primary_mode = _normalize_primary_mode(agent.get("primaryMode") or _infer_agent_primary_mode(agent))
    role_key = _normalize_role_key(agent.get("roleKey") or _infer_agent_role_key(agent))
    metadata = agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}
    if primary_mode in SYSTEM_NO_TOOL_MODES:
        system_role = _normalize_role_key(metadata.get("selfEvolutionRole") or metadata.get("supervisedRole") or role_key)
        if system_role in SYSTEM_NO_TOOL_ROLES.get(primary_mode, set()):
            return "no_tools"
    if primary_mode == "research" and role_key in RESEARCH_SOURCE_ROLE_KEYS:
        return "research_source"
    if role_key in RESEARCH_ROLE_TOOL_PROFILES:
        return "research_role"
    return ""


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
    normalized["contextCompressionPolicy"] = normalize_agent_context_compression_policy(
        normalized.get("contextCompressionPolicy") if isinstance(normalized.get("contextCompressionPolicy"), dict) else None
    )
    metadata = dict(normalized.get("metadata") or {})
    avatar_path = _canonical_agent_avatar_metadata_path(metadata, normalized)
    for stale_key in (
        "agentAvatarImagePath",
        "agentAvatarImageUrl",
        "agentAvatarImageSource",
        "avatarPath",
        "avatarImageUrl",
    ):
        metadata.pop(stale_key, None)
    if avatar_path:
        metadata["avatarImagePath"] = avatar_path
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
    normalized.pop("avatarImagePath", None)
    normalized.pop("avatarImageUrl", None)
    normalized.pop("agentAvatarImagePath", None)
    normalized.pop("agentAvatarImageUrl", None)
    normalized.pop("avatarPath", None)
    return normalized


def _normalize_agent_legacy_metadata_fields(agent: dict[str, Any]) -> bool:
    before = json.dumps(agent, ensure_ascii=False, sort_keys=True)
    normalized = _normalize_agent_record_for_storage(agent)
    agent.clear()
    agent.update(normalized)
    after = json.dumps(agent, ensure_ascii=False, sort_keys=True)
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


def _configured_model_library_ids() -> set[str]:
    try:
        from config.settings import get_config

        model_library = getattr(get_config().llm, "model_library", {}) or {}
    except Exception:
        return set()
    if not isinstance(model_library, dict):
        return set()
    return {str(model_id or "").strip() for model_id in model_library if str(model_id or "").strip()}


def _resolve_legacy_agent_model_id(model_id: str, *, model_library_ids: set[str]) -> str:
    normalized = str(model_id or "").strip()
    if not normalized or normalized in model_library_ids:
        return normalized
    if normalized in LEGACY_AGENT_PRIMARY_MODEL_IDS:
        primary_model_id = _profile_id_to_model_id("primary")
        if primary_model_id and primary_model_id in model_library_ids:
            return primary_model_id
    alias_target = LEGACY_AGENT_MODEL_ID_ALIASES.get(normalized, "")
    if alias_target and alias_target in model_library_ids:
        return alias_target
    try:
        from config.settings import _compact_repeated_token_halves

        compacted = _compact_repeated_token_halves(normalized)
    except Exception:
        compacted = normalized
    if compacted and compacted != normalized and compacted in model_library_ids:
        return compacted
    return normalized


def _repair_agent_llm_binding_model_refs(agent: dict[str, Any], *, model_library_ids: set[str]) -> dict[str, Any]:
    if not model_library_ids:
        return {"changed": False}
    before = normalize_agent_llm_bindings(agent.get("llmBindings"))
    after = dict(before)
    repairs: list[dict[str, str]] = []
    for slot, binding in before.items():
        if not isinstance(binding, dict):
            continue
        model_id = str(binding.get("modelId") or "").strip()
        canonical_model_id = _resolve_legacy_agent_model_id(model_id, model_library_ids=model_library_ids)
        if canonical_model_id and canonical_model_id != model_id:
            updated_binding = dict(binding)
            updated_binding["modelId"] = canonical_model_id
            after[slot] = updated_binding
            repairs.append(
                {
                    "slot": str(slot or "").strip(),
                    "legacyModelId": model_id,
                    "canonicalModelId": canonical_model_id,
                }
            )
    if not repairs:
        return {"changed": False}

    metadata = dict(agent.get("metadata") or {})
    history = list(metadata.get("llmBindingModelIdRepairs") or [])
    now = utc_now_iso()
    for item in repairs:
        history.append(
            {
                "schemaVersion": 1,
                "source": "agent_registry_repair",
                "repairedAt": now,
                **item,
            }
        )
    metadata["llmBindingModelIdRepairs"] = history[-20:]
    agent["metadata"] = metadata
    agent["llmBindings"] = after
    agent["updatedAt"] = now
    return {"changed": True, "repairs": repairs}


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
    for key in ("allowedTools", "preferredTools"):
        payload[key] = [name for name in payload.get(key) or [] if name not in DISABLED_AGENT_DIRECT_READ_TOOL_NAMES]
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


def normalize_agent_context_compression_policy(policy: dict[str, Any] | None) -> dict[str, Any]:
    source = policy if isinstance(policy, dict) else {}
    mode = str(source.get("mode") or "").strip().lower()
    if mode not in {"inherit", "custom"}:
        mode = "custom" if _has_context_compression_override(source) else "inherit"
    if mode != "custom":
        return dict(DEFAULT_AGENT_CONTEXT_COMPRESSION_POLICY)

    payload: dict[str, Any] = {
        "mode": "custom",
        "enabled": bool(source.get("enabled", True)),
    }
    max_token_limit = _positive_context_compression_int(
        source.get("maxTokenLimit", source.get("max_token_limit")),
        default=0,
        maximum=2_000_000,
    )
    if max_token_limit > 0:
        payload["maxTokenLimit"] = max_token_limit
    payload["maxCompressionsPerSession"] = _positive_context_compression_int(
        source.get("maxCompressionsPerSession", source.get("max_compressions_per_session")),
        default=20,
        maximum=100,
    )
    payload["levels"] = _normalize_context_compression_levels(source.get("levels"))
    payload["summaryChars"] = _normalize_context_compression_summary_chars(
        source.get("summaryChars", source.get("summary_chars"))
    )
    payload["preservation"] = _normalize_context_compression_preservation(source.get("preservation"))
    return payload


def effective_agent_context_compression_policy(
    agent: dict[str, Any] | None,
    base_policy: Any = None,
    *,
    context_window_limit: int = 0,
) -> dict[str, Any]:
    base = _context_compression_policy_from_config(base_policy, context_window_limit=context_window_limit)
    raw_agent_policy = normalize_agent_context_compression_policy(
        (agent or {}).get("contextCompressionPolicy") if isinstance(agent, dict) else None
    )
    if raw_agent_policy.get("mode") != "custom":
        return {
            **base,
            "mode": "inherit",
            "source": "global",
            "agentPolicy": raw_agent_policy,
        }

    merged = {
        **base,
        "mode": "custom",
        "source": "agent_custom",
        "agentPolicy": raw_agent_policy,
        "enabled": bool(raw_agent_policy.get("enabled", base.get("enabled", True))),
        "maxCompressionsPerSession": _positive_context_compression_int(
            raw_agent_policy.get("maxCompressionsPerSession"),
            default=int(base.get("maxCompressionsPerSession") or 20),
            maximum=100,
        ),
        "levels": {
            **dict(base.get("levels") or {}),
            **dict(raw_agent_policy.get("levels") or {}),
        },
        "summaryChars": {
            **dict(base.get("summaryChars") or {}),
            **dict(raw_agent_policy.get("summaryChars") or {}),
        },
        "preservation": {
            **dict(base.get("preservation") or {}),
            **dict(raw_agent_policy.get("preservation") or {}),
        },
    }
    raw_limit = _positive_context_compression_int(raw_agent_policy.get("maxTokenLimit"), default=0, maximum=2_000_000)
    context_window = _positive_context_compression_int(context_window_limit, default=int(base.get("contextWindowLimit") or 0), maximum=2_000_000)
    if raw_limit > 0:
        merged["maxTokenLimit"] = raw_limit
        merged["effectiveTokenLimit"] = min(raw_limit, context_window) if context_window > 0 else raw_limit
    else:
        merged["maxTokenLimit"] = int(base.get("maxTokenLimit") or base.get("effectiveTokenLimit") or 0)
        merged["effectiveTokenLimit"] = int(base.get("effectiveTokenLimit") or merged["maxTokenLimit"])
    merged["compressionTriggerTokenLimit"] = int(merged.get("effectiveTokenLimit") or 0)
    merged["contextWindowLimit"] = context_window or int(merged.get("effectiveTokenLimit") or 0)
    merged["modelContextWindowLimit"] = int(merged.get("contextWindowLimit") or 0)
    return merged


def _agent_context_window_limit(
    agent: dict[str, Any] | None,
    *,
    hydration: AgentApiHydrationContext | None = None,
) -> int:
    model_id = agent_dialogue_model_id(agent) if isinstance(agent, dict) else ""
    if not model_id:
        return 0
    if hydration is not None:
        return int(hydration.model_context_window_limits_by_model_id.get(model_id) or 0)
    try:
        from config import get_config
        from config.public_config import resolve_llm_model_context_window

        config = get_config()
        model_library = getattr(config.llm, "model_library", {}) or {}
        entry = model_library.get(model_id) if isinstance(model_library, dict) else None
        if not isinstance(entry, dict):
            return 0
        provider = None
        provider_id = str(entry.get("provider_id") or "").strip()
        if provider_id:
            provider = config.llm.get_provider(provider_id)
        return resolve_llm_model_context_window(entry, provider)
    except Exception:
        return 0


def _model_context_window_limits_for_agents(agents: list[dict[str, Any]]) -> dict[str, int]:
    model_ids = sorted(
        {
            model_id
            for model_id in (agent_dialogue_model_id(agent) for agent in list(agents or []) if isinstance(agent, dict))
            if model_id
        }
    )
    if not model_ids:
        return {}
    try:
        from config import get_config
        from config.public_config import resolve_llm_model_context_window

        config = get_config()
        model_library = getattr(config.llm, "model_library", {}) or {}
        result: dict[str, int] = {}
        for model_id in model_ids:
            entry = model_library.get(model_id) if isinstance(model_library, dict) else None
            if not isinstance(entry, dict):
                result[model_id] = 0
                continue
            provider = None
            provider_id = str(entry.get("provider_id") or "").strip()
            if provider_id:
                provider = config.llm.get_provider(provider_id)
            try:
                result[model_id] = int(resolve_llm_model_context_window(entry, provider) or 0)
            except Exception:
                result[model_id] = 0
        return result
    except Exception:
        return {model_id: 0 for model_id in model_ids}


def _context_compression_base_policy_for_agents() -> Any:
    try:
        from config import get_config

        return get_config().context_compression
    except Exception:
        return {}


def _has_context_compression_override(source: dict[str, Any]) -> bool:
    return any(
        key in source
        for key in (
            "enabled",
            "maxTokenLimit",
            "max_token_limit",
            "maxCompressionsPerSession",
            "max_compressions_per_session",
            "levels",
            "summaryChars",
            "summary_chars",
            "preservation",
        )
    )


def _context_compression_policy_from_config(base_policy: Any, *, context_window_limit: int = 0) -> dict[str, Any]:
    if base_policy is None:
        try:
            from config import get_config

            base_policy = get_config().context_compression
        except Exception:
            base_policy = {}
    effective_limit = _positive_context_compression_int(
        _get_config_value(base_policy, "max_token_limit", "maxTokenLimit"),
        default=16_000,
        maximum=2_000_000,
    )
    context_window = _positive_context_compression_int(
        context_window_limit,
        default=effective_limit,
        maximum=2_000_000,
    )
    effective_token_limit = min(effective_limit, context_window) if context_window > 0 else effective_limit
    return {
        "mode": "inherit",
        "source": "global",
        "enabled": bool(_get_config_value(base_policy, "enabled", default=True)),
        "maxTokenLimit": effective_limit,
        "effectiveTokenLimit": effective_token_limit,
        "compressionTriggerTokenLimit": effective_token_limit,
        "contextWindowLimit": context_window,
        "modelContextWindowLimit": context_window,
        "maxCompressionsPerSession": _positive_context_compression_int(
            _get_config_value(base_policy, "max_compressions_per_session", "maxCompressionsPerSession"),
            default=20,
            maximum=100,
        ),
        "levels": _normalize_context_compression_levels(_get_config_value(base_policy, "levels", default={})),
        "summaryChars": _normalize_context_compression_summary_chars(
            _get_config_value(base_policy, "summary_chars", "summaryChars", default={})
        ),
        "preservation": _normalize_context_compression_preservation(
            _get_config_value(base_policy, "preservation", default={})
        ),
    }


def _normalize_context_compression_levels(levels: Any) -> dict[str, float]:
    raw = levels if levels is not None else {}
    return {
        "light": _context_compression_ratio(_get_config_value(raw, "light"), DEFAULT_CONTEXT_COMPRESSION_LEVELS["light"]),
        "standard": _context_compression_ratio(_get_config_value(raw, "standard"), DEFAULT_CONTEXT_COMPRESSION_LEVELS["standard"]),
        "deep": _context_compression_ratio(_get_config_value(raw, "deep"), DEFAULT_CONTEXT_COMPRESSION_LEVELS["deep"]),
        "emergency": _context_compression_ratio(_get_config_value(raw, "emergency"), DEFAULT_CONTEXT_COMPRESSION_LEVELS["emergency"]),
    }


def _normalize_context_compression_summary_chars(summary_chars: Any) -> dict[str, int]:
    raw = summary_chars if summary_chars is not None else {}
    return {
        "light": _positive_context_compression_int(_get_config_value(raw, "light"), default=DEFAULT_CONTEXT_COMPRESSION_SUMMARY_CHARS["light"], maximum=20_000),
        "standard": _positive_context_compression_int(_get_config_value(raw, "standard"), default=DEFAULT_CONTEXT_COMPRESSION_SUMMARY_CHARS["standard"], maximum=20_000),
        "deep": _positive_context_compression_int(_get_config_value(raw, "deep"), default=DEFAULT_CONTEXT_COMPRESSION_SUMMARY_CHARS["deep"], maximum=20_000),
        "emergency": _positive_context_compression_int(_get_config_value(raw, "emergency"), default=DEFAULT_CONTEXT_COMPRESSION_SUMMARY_CHARS["emergency"], maximum=20_000),
    }


def _normalize_context_compression_preservation(preservation: Any) -> dict[str, Any]:
    raw = preservation if preservation is not None else {}
    return {
        "keepAiMessages": _positive_context_compression_int(
            _get_config_value(raw, "keepAiMessages", "keep_ai_messages"),
            default=5,
            maximum=50,
        ),
        "preserveErrors": bool(_get_config_value(raw, "preserveErrors", "preserve_errors", default=True)),
        "extractKeyDecisions": bool(_get_config_value(raw, "extractKeyDecisions", "extract_key_decisions", default=True)),
    }


def _context_compression_ratio(value: Any, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = default
    return max(0.0, min(1.0, parsed))


def _positive_context_compression_int(value: Any, *, default: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(0, min(maximum, parsed))


def _get_config_value(source: Any, *keys: str, default: Any = None) -> Any:
    for key in keys:
        if isinstance(source, dict) and key in source:
            return source.get(key)
        if hasattr(source, key):
            return getattr(source, key)
    return default


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
        payload = _build_agent_registry_payload_for_storage(state)
        _guard_against_suspicious_registry_shrink(payload)
        _atomic_write_json(registry_path(), payload)
        _invalidate_repaired_state_cache()
        return payload


def _guard_against_suspicious_registry_shrink(next_payload: dict[str, Any]) -> None:
    path = registry_path()
    if not path.exists():
        return
    try:
        previous_payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    if not isinstance(previous_payload, dict):
        return
    previous_agents = [item for item in previous_payload.get("agents") or [] if isinstance(item, dict)]
    next_agents = [item for item in next_payload.get("agents") or [] if isinstance(item, dict)]
    previous_count = len(previous_agents)
    next_count = len(next_agents)
    if previous_count < SUSPICIOUS_REGISTRY_SHRINK_MIN_AGENTS:
        return
    if next_count > max(2, previous_count // 4):
        return
    next_agent_ids = {str(item.get("agentId") or "").strip() for item in next_agents}
    previous_direct_agents = [
        item
        for item in previous_agents
        if str(item.get("agentId") or "").strip()
        and str(item.get("directSessionId") or "").strip()
        and str(item.get("status") or "active").strip().lower() != "archived"
    ]
    removed_direct_agents = [
        item for item in previous_direct_agents if str(item.get("agentId") or "").strip() not in next_agent_ids
    ]
    if len(removed_direct_agents) < SUSPICIOUS_REGISTRY_SHRINK_MIN_DIRECT_AGENTS:
        return
    if len(removed_direct_agents) < max(SUSPICIOUS_REGISTRY_SHRINK_MIN_DIRECT_AGENTS, len(previous_direct_agents) // 2):
        return
    fields = {
        "previousAgentCount": previous_count,
        "nextAgentCount": next_count,
        "previousDirectSessionAgentCount": len(previous_direct_agents),
        "removedDirectSessionAgentCount": len(removed_direct_agents),
        "sampleRemovedAgentIds": [
            str(item.get("agentId") or "").strip()
            for item in removed_direct_agents[:8]
        ],
        "pathName": path.name,
    }
    _record_state_write_event(
        "agent_directory.state_write_rejected_suspicious_shrink",
        level="error",
        outcome="blocked",
        fields=fields,
    )
    raise AgentDirectoryError(
        "Refused suspicious Agent registry shrink: "
        f"{previous_count} agents would become {next_count}, "
        f"removing {len(removed_direct_agents)} active direct-session Agents."
    )


def _build_agent_registry_payload_for_storage(state: dict[str, Any]) -> dict[str, Any]:
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
    return payload


def _agent_directory_storage_signature(state: dict[str, Any]) -> str:
    payload = _build_agent_registry_payload_for_storage(state)
    payload.pop("updatedAt", None)
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def registry_path() -> Path:
    return _workspace_path("agents", "agents.json")


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

    avatar_dir = _workspace_path("avatars").resolve()
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
            "promptTemplateId": KNOWLEDGE_STEWARD_PROMPT_TEMPLATE_ID,
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
        "promptTemplateId": KNOWLEDGE_STEWARD_PROMPT_TEMPLATE_ID,
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
                "source_collection_context_tool",
                "source_collection_stage_writeback_tool",
                "skill_library_search_tool",
                "unified_memory_search_tool",
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
                "source_collection_context_tool",
                "source_collection_stage_writeback_tool",
                "knowledge_governance_tasks_tool",
                "knowledge_operations_health_tool",
                "knowledge_governance_plan_tool",
                "knowledge_steward_workbench_tool",
                "knowledge_steward_recommendations_tool",
                "skill_library_search_tool",
                "unified_memory_search_tool",
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
            "constraints": "阶段私聊任务先用 source_collection_context_tool 读取资料上下文，完成、阻塞或失败都用 source_collection_stage_writeback_tool 回写；该回写只更新阶段任务状态，不等于正式 KnowledgeItem 落盘，正式入库仍必须由具备审核权限的角色或用户确认。",
            "handoffNotes": "需要最终审核时交给 Team owner/lead/steward/coordinator 或用户。",
            "taskTypes": ["knowledge_governance", "source_ingestion", "rating_suggestion", "review_preparation"],
        },
    }


def _ensure_fixed_role_profiles(agent: dict[str, Any]) -> bool:
    metadata = dict(agent.get("metadata") or {})
    defaults = _fixed_role_profile_defaults(agent, metadata)
    if not defaults:
        return False

    changed = False
    persona = normalize_persona_profile(metadata.get("personaProfile") if isinstance(metadata.get("personaProfile"), dict) else {})
    persona_defaults_disabled = bool(metadata.get("personaProfileDefaultsDisabled"))
    replace_generic_persona = _should_replace_generic_challenge_cup_persona(agent, metadata, persona)
    if not persona_defaults_disabled and (not _persona_profile_has_content(persona) or replace_generic_persona):
        default_persona = normalize_persona_profile(defaults.get("personaProfile"))
        if _persona_profile_has_content(default_persona):
            metadata["personaProfile"] = default_persona
            changed = True

    task = normalize_task_profile(metadata.get("taskProfile") if isinstance(metadata.get("taskProfile"), dict) else {})
    task_defaults_disabled = bool(metadata.get("taskProfileDefaultsDisabled"))
    replace_challenge_cup_task = (
        _should_replace_generic_challenge_cup_task(agent, metadata, task)
        or _should_replace_incomplete_challenge_cup_task(agent, metadata, task)
    )
    if not task_defaults_disabled and (not _task_profile_has_content(task) or replace_challenge_cup_task):
        default_task = normalize_task_profile(defaults.get("taskProfile"))
        if _task_profile_has_content(default_task):
            metadata["taskProfile"] = default_task
            changed = True

    if changed:
        agent["metadata"] = metadata
    return changed


def _should_replace_generic_challenge_cup_persona(
    agent: dict[str, Any],
    metadata: dict[str, Any],
    profile: dict[str, Any],
) -> bool:
    role_key = _normalize_role_key(agent.get("roleKey") or metadata.get("researchAgentKey") or "")
    if role_key not in CHALLENGE_CUP_ROLE_PROMPT_TEMPLATE_IDS:
        return False
    return (
        str(profile.get("personality") or "").strip() == "细致、证据优先，避免把未验证来源当成结论。"
        and str(profile.get("communicationStyle") or "").strip() == "先列可用证据和不确定性，再给研究建议。"
        and str(profile.get("collaborationPreference") or "").strip() == "围绕来源、证据、引用和结论边界与研究团队协作。"
    )


def _should_replace_generic_challenge_cup_task(
    agent: dict[str, Any],
    metadata: dict[str, Any],
    profile: dict[str, Any],
) -> bool:
    role_key = _normalize_role_key(agent.get("roleKey") or metadata.get("researchAgentKey") or "")
    if role_key not in CHALLENGE_CUP_ROLE_PROMPT_TEMPLATE_IDS:
        return False
    return (
        str(profile.get("responsibilities") or "").strip()
        == "阅读资料；提取关键证据；标注来源质量；把发现交给研究组织或团队成员复核。"
        and str(profile.get("preferredTasks") or "").strip() == "文献阅读、来源比对、证据摘录和研究问题拆解。"
        and str(profile.get("constraints") or "").strip() == "保留来源边界，遵守研究工具和知识库权限。"
    )


def _should_replace_incomplete_challenge_cup_task(
    agent: dict[str, Any],
    metadata: dict[str, Any],
    profile: dict[str, Any],
) -> bool:
    role_key = _normalize_role_key(agent.get("roleKey") or metadata.get("researchAgentKey") or "")
    if role_key not in CHALLENGE_CUP_ROLE_PROMPT_TEMPLATE_IDS:
        return False
    return not any(str(profile.get(field) or "").strip() for field in AGENT_TASK_PROFILE_TEXT_FIELDS)


def _fixed_role_profile_defaults(agent: dict[str, Any], metadata: dict[str, Any]) -> dict[str, Any]:
    role = _fixed_role_profile_key(agent, metadata)
    if not role:
        return {}

    functional_name = str(
        metadata.get("functionalDisplayName")
        or metadata.get("selfEvolutionRoleLabel")
        or metadata.get("supervisedRoleLabel")
        or agent.get("displayName")
        or role
    ).strip()
    responsibilities = _unique_string_list(metadata.get("responsibilities"))

    if role.startswith("self_evolution:"):
        return _self_evolution_profile_defaults(role.split(":", 1)[1], functional_name)
    if role.startswith("supervised_evolution:"):
        return _supervised_evolution_profile_defaults(role.split(":", 1)[1], functional_name)
    if role.startswith("research_org:"):
        return _research_org_profile_defaults(role.split(":", 1)[1], functional_name, responsibilities)
    if role.startswith("challenge_cup:"):
        return _challenge_cup_agent_profile_defaults(role.split(":", 1)[1], functional_name)
    if role.startswith("research_agent:"):
        return _research_agent_profile_defaults(role.split(":", 1)[1], functional_name)
    return {}


def _fixed_role_profile_key(agent: dict[str, Any], metadata: dict[str, Any]) -> str:
    primary_mode = _normalize_primary_mode(agent.get("primaryMode") or _infer_agent_primary_mode(agent))
    self_role = _normalize_role_key(metadata.get("selfEvolutionRole") or "")
    if primary_mode == "self_evolution" or self_role:
        return f"self_evolution:{self_role or _normalize_role_key(agent.get('roleKey')) or 'member'}"

    supervised_role = _normalize_role_key(metadata.get("supervisedRole") or "")
    if primary_mode == "supervised_evolution" or supervised_role:
        return f"supervised_evolution:{supervised_role or _normalize_role_key(agent.get('roleKey')) or 'member'}"

    research_org_role = _normalize_role_key(metadata.get("researchOrgRole") or metadata.get("systemRole") or "")
    if research_org_role in {"ceo", "organization_advisor", "capability_steward"}:
        return f"research_org:{research_org_role}"

    research_agent_key = _normalize_role_key(metadata.get("researchAgentKey") or "")
    role_key = _normalize_role_key(agent.get("roleKey") or "")
    if role_key in CHALLENGE_CUP_ROLE_PROMPT_TEMPLATE_IDS:
        return f"challenge_cup:{role_key}"
    if research_agent_key or role_key.startswith("research_") or primary_mode == "research":
        return f"research_agent:{research_agent_key or role_key}"

    return ""


def _self_evolution_profile_defaults(role: str, functional_name: str) -> dict[str, Any]:
    labels = {
        "executor": ("执行候选改进", "实现、验证和记录自进化候选变更。", "实现、测试、回滚准备"),
        "reviewer": ("评审候选变更", "从证据、风险和可回滚性角度审查自进化候选。", "代码评审、风险评估、证据复核"),
        "summarizer": ("总结进化证据", "压缩自进化运行证据，输出可追踪摘要和后续建议。", "运行摘要、证据整理、结论归档"),
    }
    mission, responsibilities, expertise = labels.get(
        role,
        ("维护自进化流程", "按固定角色职责处理自进化运行中的分工。", "自进化协作"),
    )
    return {
        "personaProfile": {
            "personality": "审慎、可复核，优先保护主线稳定。",
            "communicationStyle": "先给结论，再列证据、风险和下一步。",
            "background": f"{functional_name} 是 Vibelution 自进化流程中的固定系统角色。",
            "collaborationPreference": "围绕候选变更、验证证据和回滚边界与其他系统 Agent 协作。",
            "expertise": ["自进化", expertise, "运行证据"],
        },
        "taskProfile": {
            "mission": mission,
            "responsibilities": responsibilities,
            "preferredTasks": "边界清晰、可验证、可回滚的自进化子任务。",
            "avoidTasks": "不要绕过监督门禁、不要直接发布远端变更、不要处理缺少证据的破坏性操作。",
            "successCriteria": "输出包含行为变化、证据、风险和回滚条件的可审查结果。",
            "deliverables": "候选实现、评审意见、运行摘要或证据索引。",
            "constraints": "遵守自进化事务边界和主线稳定要求。",
            "handoffNotes": "高风险或需发布的动作交给监督/用户确认。",
            "taskTypes": ["self_evolution", role],
        },
    }


def _supervised_evolution_profile_defaults(role: str, functional_name: str) -> dict[str, Any]:
    return {
        "personaProfile": {
            "personality": "严谨、保守，重视对照实验和可复现证据。",
            "communicationStyle": "用明确判定说明通过、失败、风险和证据缺口。",
            "background": f"{functional_name} 是监督进化评测和晋升流程中的固定系统角色。",
            "collaborationPreference": "围绕基线、候选、评审、审计和判定证据协作。",
            "expertise": ["监督进化", "评测证据", role],
        },
        "taskProfile": {
            "mission": "支撑监督进化的候选比较、风险评审和晋升判定。",
            "responsibilities": "收集评测证据；比较候选与基线；标注风险、退化和晋升条件。",
            "preferredTasks": "候选评测、审计、对照比较和晋升门禁判断。",
            "avoidTasks": "不要绕过用户门禁或把未验证候选提升为稳定行为。",
            "successCriteria": "每个判定都能追溯到测试、日志或人工评审证据。",
            "deliverables": "评测结论、风险说明、晋升或回滚建议。",
            "constraints": "SemVer、回滚和证据链要求必须保留。",
            "handoffNotes": "需要合入或发布时交给主线集成流程。",
            "taskTypes": ["supervised_evolution", role],
        },
    }


def _research_org_profile_defaults(role: str, functional_name: str, responsibilities: list[str]) -> dict[str, Any]:
    role_labels = {
        "ceo": ("把研究目标转成组织任务", "研究组织决策、任务分派、用户沟通"),
        "organization_advisor": ("设计和维护临时研究组织", "组织结构设计、权限建议、成员治理"),
        "capability_steward": ("维护 Agent 能力和权限边界", "能力审计、工具策略、记忆策略"),
    }
    mission, expertise = role_labels.get(role, ("维护研究组织运行", "研究组织治理"))
    responsibility_text = "；".join(responsibilities) if responsibilities else f"{functional_name} 负责{mission}。"
    return {
        "personaProfile": {
            "personality": "冷静、结构化，优先保持研究组织边界清晰。",
            "communicationStyle": "先给组织判断，再列依据、风险和需要用户确认的动作。",
            "background": f"{functional_name} 是研究组织中的受保护治理角色。",
            "collaborationPreference": "通过提案、审核和显式用户门禁推进高风险组织变更。",
            "expertise": ["研究组织", expertise, "Agent 治理"],
        },
        "taskProfile": {
            "mission": mission,
            "responsibilities": responsibility_text,
            "preferredTasks": "研究任务拆解、组织调度、能力边界审查和治理建议。",
            "avoidTasks": "不要擅自删除核心 Agent、绕过权限审批或直接执行高风险工具变更。",
            "successCriteria": "组织建议可审查、可回滚，且每个高风险动作都有明确用户门禁。",
            "deliverables": "组织方案、能力审计、权限建议、协作边界说明。",
            "constraints": "保持研究组织图、Agent Directory 和 mode binding 一致。",
            "handoffNotes": "需要执行破坏性或权限升级动作时交给用户或主线治理流程确认。",
            "taskTypes": ["research_organization", role],
        },
    }


def _research_agent_profile_defaults(role: str, functional_name: str) -> dict[str, Any]:
    if role in CHALLENGE_CUP_ROLE_PROMPT_TEMPLATE_IDS:
        return _challenge_cup_agent_profile_defaults(role, functional_name)
    return _generic_research_agent_profile_defaults(role, functional_name)


def _challenge_cup_agent_profile_defaults(role: str, functional_name: str) -> dict[str, Any]:
    profiles = {
        "challenge_cup_coordinator": {
            "personaProfile": {
                "personality": "清醒、克制，擅长把挑战杯科研流程压缩成下一步行动。",
                "communicationStyle": "先给阶段判断，再列证据位置、角色分工和用户下一步。",
                "background": f"{functional_name} 是挑战杯 ai 科研团队的协调 Agent，负责读状态和组织交接，不直接执行资料搜集。",
                "collaborationPreference": "把执行任务交给资料发现、资料获取、资料提炼、资料审查和 Knowledge Steward，不越权声称已执行。",
                "expertise": ["挑战杯科研流程", "阶段协调", "任务交接"],
            },
            "taskProfile": {
                "mission": "协调挑战杯知识搜集阶段，整理当前状态、角色交接和用户下一步。",
                "responsibilities": "读取项目/会话上下文、任务状态和最近变更；判断阶段位置；把输入输出交接给对应执行 Agent。",
                "preferredTasks": "阶段判断、交接清单、阻塞归因、用户确认项整理。",
                "avoidTasks": "不要声称已启动资料搜集、联网搜索、提炼、审查或入库；不要执行 Shell/Git/正式知识写入。",
                "successCriteria": "用户能清楚看到当前阶段、证据位置、哪个 Agent 该做什么、下一步点击或确认什么。",
                "deliverables": "Stage Status、Agent Handoff、User Next Step、Boundaries。",
                "constraints": "只基于可读上下文和已有状态协调；执行动作交给具备对应工具和权限的 Agent 或 UI/API。",
                "handoffNotes": "需要真实资料处理时交给 challenge_cup_data_discovery/source_acquisition/content_extraction/source_quality。",
                "taskTypes": ["challenge_cup", "coordination", "stage_status"],
            },
        },
        "challenge_cup_data_discovery": {
            "personaProfile": {
                "personality": "敏锐、证据优先，擅长把赛题和 query seeds 展开成可追踪资料线索。",
                "communicationStyle": "先给检索框架，再列候选线索、价值、缺口和交接优先级。",
                "background": f"{functional_name} 是挑战杯资料发现 Agent，负责发现公开资料线索，不负责打开全文或入库。",
                "collaborationPreference": "把 DOI/URL/检索式交给资料获取 Agent，遇到弱来源或重复线索时标注风险。",
                "expertise": ["挑战杯资料发现", "公开资料检索", "检索式设计"],
            },
            "taskProfile": {
                "mission": "围绕挑战杯赛题和知识搜集目标发现高价值资料线索。",
                "responsibilities": "生成检索方向；使用公开搜索发现论文、综述、数据集、政策/标准和赛题线索；记录 locator 缺口。",
                "preferredTasks": "query seeds 扩展、候选来源发现、检索优先级排序。",
                "avoidTasks": "不要抓取全文、不要提炼正文、不要写正式知识、不要把搜索摘要当成事实结论。",
                "successCriteria": "每条线索都有标题、来源类型、关键词、URL/DOI 线索、价值说明和不确定性。",
                "deliverables": "Search Frame、Candidate Leads、Acquisition Handoff、Blockers。",
                "constraints": "阶段私聊任务先用 source_collection_context_tool 读取平台资料上下文，完成、阻塞或失败都用 source_collection_stage_writeback_tool 回写；该回写只更新阶段任务状态，不等于正式知识写入。",
                "handoffNotes": "把可打开来源交给 challenge_cup_source_acquisition。",
                "taskTypes": ["challenge_cup", "data_discovery", "source_leads"],
            },
        },
        "challenge_cup_source_acquisition": {
            "personaProfile": {
                "personality": "耐心、严谨，重视 locator、访问状态和来源元数据一致性。",
                "communicationStyle": "先汇总获取结果，再逐条列来源元数据、访问状态和失败原因。",
                "background": f"{functional_name} 是挑战杯资料获取 Agent，负责把 DOI/URL/检索式转成可验证来源记录。",
                "collaborationPreference": "向资料提炼 Agent 提交可读来源和注意事项；无法访问时退回明确原因。",
                "expertise": ["来源获取", "DOI/URL 校验", "元数据登记"],
            },
            "taskProfile": {
                "mission": "把资料发现线索转成可复核的挑战杯来源记录。",
                "responsibilities": "搜索和打开公开网页；记录题名、作者/机构、年份、DOI/URL、来源类型、访问状态和证据片段。",
                "preferredTasks": "DOI/URL 校验、网页访问、来源元数据整理、重复来源识别。",
                "avoidTasks": "不要下载或改写本地文件、不要写正式知识、不要把无法访问来源标为已获取。",
                "successCriteria": "每条来源都有可追踪 locator、访问状态、最小元数据和提炼注意事项。",
                "deliverables": "Acquisition Summary、Source Records、Extraction Handoff、Gaps。",
                "constraints": "阶段私聊任务先用 source_collection_context_tool 读取平台资料上下文，完成、阻塞或失败都用 source_collection_stage_writeback_tool 回写；该回写只更新阶段任务状态，不写文件或正式知识。",
                "handoffNotes": "把已获取可读来源交给 challenge_cup_content_extraction。",
                "taskTypes": ["challenge_cup", "source_acquisition", "source_metadata"],
            },
        },
        "challenge_cup_content_extraction": {
            "personaProfile": {
                "personality": "细致、克制，擅长把资料内容提炼为可审查证据而不夸大结论。",
                "communicationStyle": "先说明提炼范围，再列证据片段、来源锚点、可信度和退回原因。",
                "background": f"{functional_name} 是挑战杯资料提炼 Agent，负责从已获取来源中提炼 source_manifest 候选摘要。",
                "collaborationPreference": "把提炼结果交给资料审查 Agent；需要新来源时退回资料发现/获取链路。",
                "expertise": ["证据摘录", "来源锚点", "source_manifest 提炼"],
            },
            "taskProfile": {
                "mission": "从已获取来源中提炼与挑战杯赛题、机制、实验、数据和交付相关的证据。",
                "responsibilities": "阅读公开网页或候选资料；提取证据片段、锚点、主题标签、可信度和不确定性。",
                "preferredTasks": "证据摘录、主题标签、source_manifest 摘要、退回原因整理。",
                "avoidTasks": "不要发现新检索方向、不要写最终结论、不要写正式知识或 official graph。",
                "successCriteria": "每条提炼结果都有来源锚点、证据类型、适用主题、可信度和待审查边界。",
                "deliverables": "Extraction Scope、Evidence Items、Candidate Manifest、Return Reasons。",
                "constraints": "阶段私聊任务先用 source_collection_context_tool 读取平台资料上下文，完成、阻塞或失败都用 source_collection_stage_writeback_tool 回写；web_fetch_tool 只用于公开 URL 补查，不读取 file:// 或 localhost。",
                "handoffNotes": "把候选摘要交给 challenge_cup_source_quality 审查。",
                "taskTypes": ["challenge_cup", "content_extraction", "evidence_manifest"],
            },
        },
        "challenge_cup_source_quality": {
            "personaProfile": {
                "personality": "审慎、挑剔，优先发现来源缺口、重复和证据风险。",
                "communicationStyle": "先给审查分布，再逐条列通过/退回/拒绝/人工确认的依据。",
                "background": f"{functional_name} 是挑战杯资料审查 Agent，负责 source_manifest 入库前审查。",
                "collaborationPreference": "把通过项交给资料入库/Knowledge Steward，把缺口退回资料发现、获取或提炼 Agent。",
                "expertise": ["来源质量评估", "证据审查", "入库前审"],
            },
            "taskProfile": {
                "mission": "审查挑战杯候选资料是否可进入入库前审。",
                "responsibilities": "核对来源可追溯性、证据质量、赛题相关性、重复/冲突和可入库风险。",
                "preferredTasks": "候选资料审查、退回补资料、人工确认项整理、Steward 交接。",
                "avoidTasks": "不要直接写正式 Team Knowledge/RAG/official graph，不替 Knowledge Steward 做正式治理或 ACL 变更。",
                "successCriteria": "每条候选都有清晰决定、证据、风险、补齐要求或 Steward 交接理由。",
                "deliverables": "Review Summary、Candidate Decisions、Steward Handoff、Human Gate。",
                "constraints": "阶段私聊任务先用 source_collection_context_tool 读取平台资料上下文，完成、阻塞或失败都用 source_collection_stage_writeback_tool 回写；仍可使用 research/web/search 工具补充公开来源审查，不读取 file:// 或 localhost。",
                "handoffNotes": "通过项交给 Knowledge Steward 或资料入库步骤，退回项交给对应执行 Agent。",
                "taskTypes": ["challenge_cup", "source_quality", "pre_ingestion_review"],
            },
        },
    }
    return profiles.get(role, _generic_research_agent_profile_defaults(role, functional_name))


def _generic_research_agent_profile_defaults(role: str, functional_name: str) -> dict[str, Any]:
    role_label = role.replace("_", " ").strip() or "research agent"
    return {
        "personaProfile": {
            "personality": "细致、证据优先，避免把未验证来源当成结论。",
            "communicationStyle": "先列可用证据和不确定性，再给研究建议。",
            "background": f"{functional_name} 是研究流程中的功能型 Agent。",
            "collaborationPreference": "围绕来源、证据、引用和结论边界与研究团队协作。",
            "expertise": ["研究检索", "证据整理", role_label],
        },
        "taskProfile": {
            "mission": f"承担 {functional_name} 的研究分工，输出可追溯证据。",
            "responsibilities": "阅读资料；提取关键证据；标注来源质量；把发现交给研究组织或团队成员复核。",
            "preferredTasks": "文献阅读、来源比对、证据摘录和研究问题拆解。",
            "avoidTasks": "不要编造来源、不要把未经复核的发现写成确定结论。",
            "successCriteria": "输出包含来源、证据片段、可信度和待复核问题。",
            "deliverables": "资料摘要、证据清单、引用线索和复核建议。",
            "constraints": "保留来源边界，遵守研究工具和知识库权限。",
            "handoffNotes": "结论性判断交给研究负责人或评审 Agent 复核。",
            "taskTypes": ["research", role],
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
    avatar_dir = _workspace_path("avatars").resolve()
    path = (avatar_dir / safe_filename).resolve()
    if avatar_dir != path.parent:
        raise FileNotFoundError("invalid Agent avatar image path")
    return path


def _canonical_agent_avatar_metadata_path(
    metadata: dict[str, Any],
    agent: dict[str, Any] | None = None,
) -> str:
    agent_payload = agent if isinstance(agent, dict) else {}
    raw_path = str(
        metadata.get("avatarImagePath")
        or metadata.get("agentAvatarImagePath")
        or metadata.get("avatarPath")
        or agent_payload.get("avatarImagePath")
        or agent_payload.get("agentAvatarImagePath")
        or agent_payload.get("avatarPath")
        or ""
    ).strip()
    filename = agent_avatar_filename(raw_path)
    return str(AGENT_AVATAR_RELATIVE_DIR / filename) if filename else ""


def _agent_avatar_path_from_metadata(metadata: dict[str, Any]) -> str:
    avatar_path = str(metadata.get("avatarImagePath") or "").strip()
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
    for tokens, filenames in AGENT_AVATAR_ROLE_DEFAULTS:
        if all(token in key for token in tokens):
            for filename in filenames:
                if filename in available:
                    return filename
    fallback_pool = [filename for filename in AGENT_AVATAR_PRIMARY_DEFAULTS if filename in available]
    if not fallback_pool:
        fallback_pool = [filename for filename in AGENT_AVATAR_GENERATED_FALLBACKS if filename in available]
    if not fallback_pool:
        fallback_pool = [filename for filename in AGENT_AVATAR_FILENAMES if filename in available]
    if not fallback_pool:
        fallback_pool = available
    stable_key = _normalize_agent_code(agent.get("agentCode")) or str(agent.get("agentId") or "")
    checksum = sum(ord(char) for char in stable_key)
    return fallback_pool[checksum % len(fallback_pool)]


def _available_agent_avatar_filenames() -> list[str]:
    avatar_dir = _workspace_path("avatars").resolve()
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


def _agent_to_api(
    agent: dict[str, Any],
    *,
    hydration: AgentApiHydrationContext | None = None,
    include_activity: bool = True,
    include_tool_governance: bool = False,
    include_inbox_pending_count: bool = False,
) -> dict[str, Any]:
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
    tool_policy = _tool_policy_for_agent(agent, hydration=hydration)
    agent_source_ref = _source_authority_ref("agent", agent_id)
    agent_projection_edit = _projection_edit_contract("agent", agent_id)
    return {
        "agentId": agent_id,
        "agentCode": _normalize_agent_code(agent.get("agentCode"))
        or _fallback_agent_code(agent.get("agentId")),
        "displayName": str(agent.get("displayName") or "").strip(),
        "kind": str(agent.get("kind") or DEFAULT_AGENT_KIND).strip() or DEFAULT_AGENT_KIND,
        "primaryMode": _normalize_primary_mode(agent.get("primaryMode") or _infer_agent_primary_mode(agent)),
        "roleKey": _normalize_role_key(agent.get("roleKey") or _infer_agent_role_key(agent)),
        "llmBindings": normalize_agent_llm_bindings(agent.get("llmBindings")),
        "contextCompressionPolicy": normalize_agent_context_compression_policy(
            agent.get("contextCompressionPolicy") if isinstance(agent.get("contextCompressionPolicy"), dict) else None
        ),
        "contextCompressionEffectivePolicy": effective_agent_context_compression_policy(
            agent,
            hydration.context_compression_base_policy if hydration is not None else None,
            context_window_limit=_agent_context_window_limit(agent, hydration=hydration),
        ),
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
        "toolPolicy": tool_policy,
        "toolPolicySource": _tool_policy_source_for_agent(agent, tool_policy),
        "toolGovernanceRequests": (
            _tool_governance_requests_for_agent(agent_id, hydration=hydration, limit=6)
            if include_activity or include_tool_governance
            else []
        ),
        "groupContextEvents": _group_context_events_for_agent(agent, hydration=hydration, limit=8) if include_activity else [],
        "agentInboxMessages": (
            _agent_inbox_messages_for_agent(agent, hydration=hydration, limit=8, status="pending") if include_activity else []
        ),
        "agentInboxPendingCount": (
            _agent_inbox_pending_count_for_agent(agent, hydration=hydration, status="pending")
            if include_activity or include_inbox_pending_count
            else 0
        ),
        "sourceRef": agent_source_ref,
        "projectionEdit": agent_projection_edit,
        "activityHydration": (
            "full"
            if include_activity
            else ("config" if include_tool_governance or include_inbox_pending_count else "deferred")
        ),
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
    agent_source_ref = _source_authority_ref("agent", agent_id)
    agent_projection_edit = _projection_edit_contract("agent", agent_id)
    return {
        "agentId": agent_id,
        "agentCode": _normalize_agent_code(agent.get("agentCode"))
        or _fallback_agent_code(agent.get("agentId")),
        "displayName": str(agent.get("displayName") or "").strip(),
        "kind": str(agent.get("kind") or DEFAULT_AGENT_KIND).strip() or DEFAULT_AGENT_KIND,
        "primaryMode": _normalize_primary_mode(agent.get("primaryMode") or _infer_agent_primary_mode(agent)),
        "roleKey": _normalize_role_key(agent.get("roleKey") or _infer_agent_role_key(agent)),
        "llmBindings": normalize_agent_llm_bindings(agent.get("llmBindings")),
        "contextCompressionPolicy": normalize_agent_context_compression_policy(
            agent.get("contextCompressionPolicy") if isinstance(agent.get("contextCompressionPolicy"), dict) else None
        ),
        "contextCompressionEffectivePolicy": effective_agent_context_compression_policy(
            agent,
            context_window_limit=_agent_context_window_limit(agent),
        ),
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
        "sourceRef": agent_source_ref,
        "projectionEdit": agent_projection_edit,
    }


def _source_authority_ref(kind: str, source_id: str, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    from core.agent_kernel.source_authority import source_ref

    return source_ref(kind, source_id, metadata)


def _projection_edit_contract(kind: str, source_id: str, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    from core.agent_kernel.source_authority import projection_edit_contract

    return projection_edit_contract(kind, source_id, metadata)


def _build_agent_api_hydration_context(
    state: dict[str, Any],
    agents: list[dict[str, Any]],
    *,
    timings: dict[str, float] | None = None,
) -> AgentApiHydrationContext:
    timings_ref = timings if timings is not None else {}
    started = time.perf_counter()
    fast_signature = ("full", _agent_api_hydration_fast_signature(agents))
    cached = _get_agent_api_hydration_fast_cache(fast_signature, now=started)
    if cached is not None:
        timings_ref["cache_lookup"] = round((time.perf_counter() - started) * 1000, 1)
        timings_ref["cache_hit"] = 1.0
        timings_ref["cache_fast_hit"] = 1.0
        return cached
    signature: tuple[Any, ...] | None = None
    if _agent_api_hydration_cache_matches_mode("full"):
        signature = ("full", _agent_api_hydration_signature(agents))
        cached = _get_agent_api_hydration_cache(signature)
        timings_ref["cache_lookup"] = round((time.perf_counter() - started) * 1000, 1)
        if cached is not None:
            timings_ref["cache_hit"] = 1.0
            timings_ref["cache_fast_hit"] = 0.0
            _refresh_agent_api_hydration_fast_cache(fast_signature)
            return cached
    else:
        timings_ref["cache_lookup"] = round((time.perf_counter() - started) * 1000, 1)
    timings_ref["cache_hit"] = 0.0
    timings_ref["cache_fast_hit"] = 0.0
    started = time.perf_counter()
    tool_policies = _tool_policies(state)
    timings_ref["tool_policies"] = round((time.perf_counter() - started) * 1000, 1)
    started = time.perf_counter()
    memory_policies = _memory_policies(state)
    timings_ref["memory_policies"] = round((time.perf_counter() - started) * 1000, 1)
    started = time.perf_counter()
    context_compression_base_policy = _context_compression_base_policy_for_agents()
    timings_ref["context_compression_policy"] = round((time.perf_counter() - started) * 1000, 1)
    started = time.perf_counter()
    model_context_window_limits = _model_context_window_limits_for_agents(agents)
    timings_ref["model_context_windows"] = round((time.perf_counter() - started) * 1000, 1)
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
    context = AgentApiHydrationContext(
        state=state,
        tool_policies=tool_policies,
        memory_policies=memory_policies,
        context_compression_base_policy=context_compression_base_policy,
        model_context_window_limits_by_model_id=model_context_window_limits,
        tool_governance_requests_by_agent=tool_governance_requests_by_agent,
        group_context_events_by_agent=group_context_events_by_agent,
        agent_inbox_messages_by_agent=agent_inbox_messages_by_agent,
        agent_inbox_pending_count_by_agent=agent_inbox_pending_count_by_agent,
    )
    _remember_agent_api_hydration_cache(signature, fast_signature, context)
    return context


def _build_agent_api_config_hydration_context(
    state: dict[str, Any],
    agents: list[dict[str, Any]],
    *,
    timings: dict[str, float] | None = None,
) -> AgentApiHydrationContext:
    timings_ref = timings if timings is not None else {}
    started = time.perf_counter()
    fast_signature = ("config", _agent_api_hydration_fast_signature(agents))
    cached = _get_agent_api_hydration_fast_cache(fast_signature, now=started)
    if cached is not None:
        timings_ref["cache_lookup"] = round((time.perf_counter() - started) * 1000, 1)
        timings_ref["cache_hit"] = 1.0
        timings_ref["cache_fast_hit"] = 1.0
        return cached
    signature: tuple[Any, ...] | None = None
    if _agent_api_hydration_cache_matches_mode("config"):
        signature = ("config", _agent_api_config_hydration_signature(agents))
        cached = _get_agent_api_hydration_cache(signature)
        timings_ref["cache_lookup"] = round((time.perf_counter() - started) * 1000, 1)
        if cached is not None:
            timings_ref["cache_hit"] = 1.0
            timings_ref["cache_fast_hit"] = 0.0
            _refresh_agent_api_hydration_fast_cache(fast_signature)
            return cached
    else:
        timings_ref["cache_lookup"] = round((time.perf_counter() - started) * 1000, 1)
    timings_ref["cache_hit"] = 0.0
    timings_ref["cache_fast_hit"] = 0.0
    started = time.perf_counter()
    tool_policies = _tool_policies(state)
    timings_ref["tool_policies"] = round((time.perf_counter() - started) * 1000, 1)
    started = time.perf_counter()
    memory_policies = _memory_policies(state)
    timings_ref["memory_policies"] = round((time.perf_counter() - started) * 1000, 1)
    started = time.perf_counter()
    context_compression_base_policy = _context_compression_base_policy_for_agents()
    timings_ref["context_compression_policy"] = round((time.perf_counter() - started) * 1000, 1)
    started = time.perf_counter()
    model_context_window_limits = _model_context_window_limits_for_agents(agents)
    timings_ref["model_context_windows"] = round((time.perf_counter() - started) * 1000, 1)
    started = time.perf_counter()
    tool_governance_requests_by_agent = _load_recent_tool_governance_requests_for_agents(agents, limit=6)
    timings_ref["tool_governance_requests"] = round((time.perf_counter() - started) * 1000, 1)
    started = time.perf_counter()
    agent_inbox_pending_count_by_agent = _count_pending_agent_inbox_messages_for_agents(agents)
    timings_ref["agent_inbox_pending_counts"] = round((time.perf_counter() - started) * 1000, 1)
    timings_ref["group_context_events"] = 0.0
    timings_ref["agent_inbox_messages"] = 0.0
    context = AgentApiHydrationContext(
        state=state,
        tool_policies=tool_policies,
        memory_policies=memory_policies,
        context_compression_base_policy=context_compression_base_policy,
        model_context_window_limits_by_model_id=model_context_window_limits,
        tool_governance_requests_by_agent=tool_governance_requests_by_agent,
        group_context_events_by_agent={},
        agent_inbox_messages_by_agent={},
        agent_inbox_pending_count_by_agent=agent_inbox_pending_count_by_agent,
    )
    _remember_agent_api_hydration_cache(signature, fast_signature, context)
    return context


def _agent_api_hydration_fast_signature(agents: list[dict[str, Any]]) -> tuple[Any, ...]:
    agent_keys: list[tuple[str, str]] = []
    for agent in agents:
        if not isinstance(agent, dict):
            continue
        agent_keys.append(
            (
                str(agent.get("agentId") or "").strip(),
                str(agent.get("workspacePath") or "").strip(),
            )
        )
    return (_registry_state_signature(), _agent_api_hydration_event_version(), tuple(agent_keys))


def _agent_api_hydration_signature(agents: list[dict[str, Any]]) -> tuple[Any, ...]:
    agent_signatures: list[tuple[Any, ...]] = []
    for agent in agents:
        if not isinstance(agent, dict):
            continue
        agent_id = str(agent.get("agentId") or "").strip()
        workspace = str(agent.get("workspacePath") or "").strip()
        agent_signatures.append(
            (
                agent_id,
                workspace,
                _jsonl_signature(_agent_workspace_event_path(agent, "tool_governance_requests.jsonl")),
                _jsonl_signature(_agent_workspace_event_path(agent, "group_context_events.jsonl")),
                _jsonl_signature(_agent_workspace_event_path(agent, "agent_inbox_messages.jsonl")),
            )
        )
    return (_registry_state_signature(), _agent_api_hydration_event_version(), tuple(agent_signatures))


def _agent_api_config_hydration_signature(agents: list[dict[str, Any]]) -> tuple[Any, ...]:
    agent_signatures: list[tuple[Any, ...]] = []
    for agent in agents:
        if not isinstance(agent, dict):
            continue
        agent_id = str(agent.get("agentId") or "").strip()
        workspace = str(agent.get("workspacePath") or "").strip()
        agent_signatures.append(
            (
                agent_id,
                workspace,
                _jsonl_signature(_agent_workspace_event_path(agent, "tool_governance_requests.jsonl")),
                _jsonl_signature(_agent_workspace_event_path(agent, "agent_inbox_messages.jsonl")),
            )
        )
    return (_registry_state_signature(), _agent_api_hydration_event_version(), tuple(agent_signatures))


def _agent_api_hydration_event_version() -> int:
    with _AGENT_API_HYDRATION_CACHE_LOCK:
        return _AGENT_API_HYDRATION_EVENT_VERSION


def record_agent_api_hydration_event_file_changed(path: Path | str) -> None:
    """Invalidate the fast Agent API hydration cache when Agent event logs change."""

    global _AGENT_API_HYDRATION_EVENT_VERSION
    try:
        filename = Path(path).name
    except TypeError:
        filename = ""
    if filename not in _AGENT_API_HYDRATION_EVENT_FILENAMES:
        return
    with _AGENT_API_HYDRATION_CACHE_LOCK:
        _AGENT_API_HYDRATION_EVENT_VERSION += 1


def _get_agent_api_hydration_fast_cache(
    fast_signature: tuple[Any, ...],
    *,
    now: float,
) -> AgentApiHydrationContext | None:
    with _AGENT_API_HYDRATION_CACHE_LOCK:
        if _AGENT_API_HYDRATION_CACHE is None:
            return None
        if _AGENT_API_HYDRATION_CACHE_FAST_SIGNATURE != fast_signature:
            return None
        if now - _AGENT_API_HYDRATION_CACHE_VALIDATED_AT > _AGENT_API_HYDRATION_FAST_TTL_SECONDS:
            return None
        return _AGENT_API_HYDRATION_CACHE


def _get_agent_api_hydration_cache(signature: tuple[Any, ...]) -> AgentApiHydrationContext | None:
    with _AGENT_API_HYDRATION_CACHE_LOCK:
        if _AGENT_API_HYDRATION_CACHE_SIGNATURE == signature:
            return _AGENT_API_HYDRATION_CACHE
    return None


def _agent_api_hydration_cache_matches_mode(mode: str) -> bool:
    normalized_mode = str(mode or "").strip()
    if not normalized_mode:
        return False
    with _AGENT_API_HYDRATION_CACHE_LOCK:
        for signature in (_AGENT_API_HYDRATION_CACHE_FAST_SIGNATURE, _AGENT_API_HYDRATION_CACHE_SIGNATURE):
            if isinstance(signature, tuple) and signature and signature[0] == normalized_mode:
                return True
    return False


def _refresh_agent_api_hydration_fast_cache(fast_signature: tuple[Any, ...]) -> None:
    global _AGENT_API_HYDRATION_CACHE_FAST_SIGNATURE
    global _AGENT_API_HYDRATION_CACHE_VALIDATED_AT
    with _AGENT_API_HYDRATION_CACHE_LOCK:
        _AGENT_API_HYDRATION_CACHE_FAST_SIGNATURE = fast_signature
        _AGENT_API_HYDRATION_CACHE_VALIDATED_AT = time.perf_counter()


def _remember_agent_api_hydration_cache(
    signature: tuple[Any, ...] | None,
    fast_signature: tuple[Any, ...],
    context: AgentApiHydrationContext,
) -> None:
    global _AGENT_API_HYDRATION_CACHE_SIGNATURE
    global _AGENT_API_HYDRATION_CACHE_FAST_SIGNATURE
    global _AGENT_API_HYDRATION_CACHE_VALIDATED_AT
    global _AGENT_API_HYDRATION_CACHE
    with _AGENT_API_HYDRATION_CACHE_LOCK:
        _AGENT_API_HYDRATION_CACHE_SIGNATURE = signature
        _AGENT_API_HYDRATION_CACHE_FAST_SIGNATURE = fast_signature
        _AGENT_API_HYDRATION_CACHE_VALIDATED_AT = time.perf_counter()
        _AGENT_API_HYDRATION_CACHE = context


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
    metadata = agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}
    return _effective_agent_tool_policy(
        normalize_tool_policy(policy, policy_id),
        metadata.get("delegationPolicy") if isinstance(metadata, dict) else {},
    )


def _tool_policy_source_for_agent(agent: dict[str, Any], policy: dict[str, Any] | None) -> dict[str, Any]:
    agent_id = str(agent.get("agentId") or "").strip()
    policy_id = str(agent.get("toolPolicyId") or DEFAULT_TOOL_POLICY_ID).strip() or DEFAULT_TOOL_POLICY_ID
    normalized_policy = normalize_tool_policy(policy if isinstance(policy, dict) else {}, policy_id)
    allowed_tools = _tool_name_list(normalized_policy.get("allowedTools") or [])
    preferred_tools = _tool_name_list(normalized_policy.get("preferredTools") or [])
    mutating_tools = sorted({tool for tool in allowed_tools if tool in MUTATING_AGENT_TOOL_NAMES})
    is_session_agent = _is_session_agent_primary_mode(str(agent.get("primaryMode") or _infer_agent_primary_mode(agent)))
    is_private_policy = bool(agent_id and policy_id == f"tool-{agent_id}")
    fixed_kind = _fixed_role_tool_policy_kind(agent)
    default_allowed = list(DEFAULT_SESSION_AGENT_ALLOWED_TOOLS)
    default_preferred = list(DEFAULT_SESSION_AGENT_PREFERRED_TOOLS)
    if fixed_kind == "no_tools":
        kind = "system_no_tools"
        label = "系统固定无工具"
        description = "该系统角色由运行时固定为无工具策略，避免误删或误授权影响核心流程。"
    elif fixed_kind in {"research_source", "research_role"}:
        kind = "fixed_role_policy"
        label = "角色固定工具"
        description = "该科研角色使用固定工具包，系统会按职责保持只读/受控权限。"
    elif policy_id == DEFAULT_TOOL_POLICY_ID:
        kind = "empty_default_policy"
        label = "空默认包"
        description = "当前引用全局空默认包；没有显式允许工具。"
    elif is_session_agent and is_private_policy and allowed_tools == default_allowed and preferred_tools == default_preferred:
        kind = "session_default_private"
        label = "会话默认包"
        description = "当前会话 Agent 使用自己的默认工具包；保存后不会被其他共享包覆盖。"
    elif is_session_agent and len(allowed_tools) > len(default_allowed) and mutating_tools:
        kind = "legacy_wide_private_override"
        label = "历史宽权限覆盖"
        description = "该会话 Agent 保留了旧的私有宽权限配置；系统不会静默收窄，请在工具页手动替换为目标工具包。"
    elif is_private_policy:
        kind = "agent_private_override"
        label = "Agent 私有覆盖"
        description = "该 Agent 使用自己的私有 ToolPolicy；重置/替换只影响当前 Agent。"
    else:
        kind = "shared_policy"
        label = "共享工具包"
        description = "该 Agent 引用共享 ToolPolicy；修改共享包可能影响其他 Agent。"
    return {
        "kind": kind,
        "label": label,
        "description": description,
        "policyId": policy_id,
        "isPrivate": is_private_policy,
        "isLegacyWide": kind == "legacy_wide_private_override",
        "allowedToolCount": len(allowed_tools),
        "preferredToolCount": len(preferred_tools),
        "mutatingToolCount": len(mutating_tools),
        "mutatingTools": mutating_tools,
    }


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
        except Exception as exc:
            _debug_logger.warning(
                f"Failed to read tool governance requests for agent={agent_id}, limit={limit}. error={type(exc).__name__}: {exc}",
                tag="AGENT_TOOL_DIRECTORY",
            )
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


def _count_pending_agent_inbox_messages_for_agents(agents: list[dict[str, Any]]) -> dict[str, int]:
    result: dict[str, int] = {}
    for agent in agents:
        agent_id = str(agent.get("agentId") or "").strip()
        if not agent_id:
            continue
        try:
            result[agent_id] = _count_jsonl_matching_status(
                _agent_workspace_event_path(agent, "agent_inbox_messages.jsonl"),
                status="pending",
            )
        except Exception as exc:
            _debug_logger.warning(
                f"Failed to count pending inbox messages for agent={agent_id}. error={type(exc).__name__}: {exc}",
                tag="AGENT_TOOL_DIRECTORY",
            )
            result[agent_id] = 0
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
    except Exception as exc:
        _debug_logger.warning(
            f"Failed to list recent tool governance requests for agent={agent_id}, limit={limit}. error={type(exc).__name__}: {exc}",
            tag="AGENT_TOOL_DIRECTORY",
        )
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
    return research_org_role in {"ceo", "organization_advisor", "capability_steward", KNOWLEDGE_STEWARD_ROLE_KEY}


def agent_archive_protected(agent: dict[str, Any]) -> bool:
    return _agent_archive_protected(agent)


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


def _active_agent_for_direct_session(
    state: dict[str, Any],
    session_id: str,
    *,
    exclude_agent_id: str = "",
) -> dict[str, Any] | None:
    normalized = str(session_id or "").strip()
    excluded = str(exclude_agent_id or "").strip()
    if not normalized:
        return None
    for item in state.get("agents") or []:
        if not isinstance(item, dict):
            continue
        agent_id = str(item.get("agentId") or "").strip()
        if excluded and agent_id == excluded:
            continue
        if str(item.get("status") or "active").strip().lower() == "archived":
            continue
        if str(item.get("directSessionId") or "").strip() == normalized:
            return item
    return None


def _ensure_active_direct_session_available(
    state: dict[str, Any],
    session_id: str,
    *,
    agent_id: str,
) -> None:
    normalized = str(session_id or "").strip()
    if not normalized:
        return
    existing = _active_agent_for_direct_session(state, normalized, exclude_agent_id=agent_id)
    if existing is None:
        return
    _record_agent_direct_session_collision_rejected(
        session_id=normalized,
        agent_id=str(agent_id or "").strip(),
        existing_agent=existing,
    )
    existing_agent_id = str(existing.get("agentId") or "").strip()
    raise AgentDirectoryError(f"Agent direct session is already bound to another active Agent: {existing_agent_id}")


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


def _prompt_template_id_for_role(role_key: Any) -> str:
    return CHALLENGE_CUP_ROLE_PROMPT_TEMPLATE_IDS.get(_normalize_role_key(role_key), "")


def _should_repair_agent_prompt_template_id(current: str, expected: str) -> bool:
    normalized_current = _normalize_prompt_template_id(current)
    normalized_expected = _normalize_prompt_template_id(expected)
    if not normalized_expected:
        return False
    return not normalized_current or normalized_current == "prompt-chat-default"


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
    role_prompt_template_id = _prompt_template_id_for_role(agent.get("roleKey"))
    if role_prompt_template_id:
        return role_prompt_template_id
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
    normalized_agent_id = str(agent_id or "").strip()
    if not normalized_agent_id:
        return False
    normalized_path = str(path_value or "").strip().replace("\\", "/").strip("/")
    expected_path = _agent_workspace_relative_path(normalized_agent_id).strip("/")
    if normalized_path == expected_path:
        return True
    try:
        actual = _resolve_project_path(path_value)
        expected = _resolve_project_path(expected_path)
    except Exception:
        return False
    return actual == expected


def _ensure_agent_workspace(path_value: str) -> Path:
    path = _resolve_project_path(path_value)
    agents_root = _workspace_path("agents").resolve()
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
        agents_root = _workspace_path("agents").resolve()
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
        agents_root = _workspace_path("agents").resolve()
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

        result = session_service.reset_agent_direct_session_lightweight(
            session_id,
            agent_id=str(agent.get("agentId") or "").strip(),
            title=str(agent.get("displayName") or "").strip(),
        )
    except Exception as exc:
        raise AgentDirectoryError(f"Agent direct session reset failed: {type(exc).__name__}: {exc}") from exc
    replacement_direct_session_id = str(result.get("replacementDirectSessionId") or result.get("nextActiveSessionId") or "").strip()
    return {
        "resetDirectSession": True,
        "replacementDirectSessionId": replacement_direct_session_id,
        "skippedPaths": [],
    }


def _resolve_project_path(path_value: str) -> Path:
    raw = str(path_value or "").strip()
    path = Path(raw)
    if path.parts and path.parts[0].lower() == "workspace":
        return _workspace_path(*path.parts[1:]).resolve()
    if not path.is_absolute():
        path = _project_root() / path
    return path.resolve()


def _relative_project_path(path: Path) -> str:
    resolved = Path(path).resolve()
    workspace_root = _workspace_path().resolve()
    try:
        return f"workspace/{resolved.relative_to(workspace_root).as_posix()}"
    except ValueError:
        pass
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


def _developer_sandbox_module():
    from core.infrastructure import developer_sandbox

    return developer_sandbox


def _workspace_path(*parts: str, intent: str = "state", seed: bool = True) -> Path:
    return _developer_sandbox_module().route_workspace_path(
        _project_root(),
        "agent_directory",
        *parts,
        intent=intent,
        seed=seed,
    )


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
    record_agent_api_hydration_event_file_changed(path)


def _write_jsonl(path: Path, payloads: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        json.dumps(item, ensure_ascii=False, sort_keys=True)
        for item in list(payloads or [])
        if isinstance(item, dict)
    ]
    path.write_text(("\n".join(lines) + "\n") if lines else "", encoding="utf-8", newline="\n")
    record_agent_api_hydration_event_file_changed(path)


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


def _record_agent_direct_session_collision_rejected(
    *,
    session_id: str,
    agent_id: str,
    existing_agent: dict[str, Any],
) -> None:
    try:
        record_runtime_scene_event(
            "agent_directory",
            "agent_direct_session_collision",
            "agent.direct_session_collision.rejected",
            message="Agent directSessionId collision was rejected before saving.",
            level="warning",
            outcome="rejected",
            fields={
                "sessionId": str(session_id or "").strip(),
                "agentId": str(agent_id or "").strip(),
                "existingAgentId": str(existing_agent.get("agentId") or "").strip(),
                "existingAgentCode": _normalize_agent_code(existing_agent.get("agentCode")),
                "existingStatus": str(existing_agent.get("status") or "active").strip() or "active",
            },
            lifecycle=True,
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
            message="Agent llmBindings were migrated or repaired.",
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
