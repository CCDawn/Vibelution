"""Persistent AgentInstance registry for chat-facing agents."""

from __future__ import annotations

import base64
import binascii
import json
import os
import re
import secrets
import shutil
import stat
import tempfile
import threading
import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Iterable
from urllib.parse import quote

from config.public_config import CONFIG_PATH as CONFIG_PATH
from core.chat.chat_task_types import trim_lines
from core.llm.agent_runtime import (
    AGENT_LLM_SLOTS,
    DEFAULT_AGENT_LLM_SLOT,
    agent_dialogue_model_id,
    agent_llm_model_id as agent_llm_model_id,
    normalize_agent_llm_bindings,
)
from core.logging import debug as _debug_logger
from core.ui.chat_state import load_chat_state

from . import agent_role_tool_profile_service
from .agent_config_authority import (
    DEFAULT_AGENT_CONTEXT_COMPRESSION_CREATION_POLICY,
)
from .runtime_scene_service import record_runtime_scene_event
from .supervised_runtime_contract import supervised_role_runtime_tools
from .agent_directory.profiles import (
    AGENT_PERSONA_PROFILE_FIELDS,
    AGENT_PERSONA_PROFILE_TEXT_FIELDS,
    AGENT_PERSONA_PROFILE_TEXT_LINE_LIMITS,
    AGENT_TASK_PROFILE_FIELDS,
    AGENT_TASK_PROFILE_TEXT_FIELDS,
    AGENT_TASK_PROFILE_TEXT_LINE_LIMITS,
    agent_persona_profile_has_content,
    agent_task_profile_has_content,
    normalize_persona_profile,
    normalize_task_profile,
    _persona_profile_has_content,
    _task_profile_has_content,
)
from .agent_directory.avatar_model_defaults import MODEL_AVATAR_FILENAMES
from .agent_directory.policies import (
    _context_compression_base_policy_for_agents,
    _context_compression_policy_from_config,
    _context_compression_ratio,
    _conversation_index_visibility_for_kind,
    _count_policy_refs,
    _default_tool_policy_for_agent,
    _default_tool_policy_id_for_agent,
    _direct_session_visibility,
    _effective_agent_tool_policy,
    _ensure_fixed_role_tool_policy,
    _ensure_session_agent_tool_policy,
    _fixed_role_tool_policy_kind,
    _has_context_compression_override,
    _knowledge_steward_memory_policy,
    _knowledge_steward_tool_policy,
    _memory_policy_for_agent,
    _normalize_context_compression_levels,
    _normalize_context_compression_preservation,
    _normalize_context_compression_summary_chars,
    _normalize_tool_policy_scopes,
    _positive_context_compression_int,
    _record_agent_delegation_policy_event,
    _record_agent_memory_policy_event,
    _record_agent_supervision_policy_event,
    _record_agent_tool_policy_event,
    _record_delegation_policy_block,
    _record_policy_block,
    _record_supervision_policy_block,
    _record_supervision_policy_observed,
    _tool_name_list,
    _tool_policies,
    _tool_policy_for_agent,
    _tool_policy_source_for_agent,
    _with_temporary_tool_grants,
    _without_subagent_delegation_tools,
    _workspace_path_for_policy,
    agent_conversation_index_visibility,
    build_agent_policy_options,
    compute_effective_tool_visibility,
    default_memory_policy,
    default_research_role_tool_policy,
    default_research_source_tool_policy,
    default_self_evolution_executable_tool_policy,
    default_session_agent_tool_policy,
    default_session_agent_tool_policy_v2,
    default_system_no_tool_policy,
    default_tool_policy,
    effective_agent_context_compression_policy,
    evaluate_current_delegation_policy,
    evaluate_current_supervision_policy,
    evaluate_current_tool_policy,
    evaluate_delegation_policy,
    evaluate_delegation_wake_policy,
    evaluate_supervision_policy,
    evaluate_tool_policy,
    normalize_agent_context_compression_policy,
    materialize_agent_context_compression_policy,
    normalize_conversation_index_visibility,
    normalize_delegation_policy,
    normalize_memory_policy,
    normalize_supervision_policy,
    normalize_tool_policy,
    record_supervision_policy_decision,
    resolve_delegation_policy_for_agent,
    resolve_memory_policy_for_agent,
    resolve_supervision_policy_for_agent,
    resolve_tool_policy_for_agent,
    session_agent_visibility,
    tool_policy_fingerprint,
)
from .agent_directory.lifecycle import (
    _agent_archive_protected,
    _archive_retired_self_evolution_agent,
    _delete_purged_agent_workspace,
    _record_agent_purged_event,
    _record_agent_reset_event,
    _reset_agent_direct_session,
    agent_archive_protected,
    archive_agent_instance,
    ensure_agent_archive_allowed,
    ensure_agent_purge_allowed,
    ensure_agent_purge_workspace_deletable,
    purge_archived_agent_instance,
    purge_system_team_agent_instance,
    reset_agent_instance,
)
from .agent_directory.projections import (
    build_agent_runtime_context_block,
    _agent_to_api,
    _build_agent_api_hydration_context,
    list_agents,
    _agent_to_api_summary,
    _build_agent_api_config_hydration_context,
    agent_conversation_index_classification,
    active_agent_runtime,
    _format_task_profile_context,
    _format_persona_profile_context,
    _agent_api_hydration_signature,
    _agent_api_config_hydration_signature,
    _remember_agent_api_hydration_cache,
    _get_agent_api_hydration_fast_cache,
    record_agent_api_hydration_event_file_changed,
    _agent_api_hydration_fast_signature,
    get_agent,
    _agent_api_hydration_cache_matches_mode,
    _refresh_agent_api_hydration_fast_cache,
    _get_agent_api_hydration_cache,
    _agent_api_hydration_event_version,
)
from .agent_directory.mutations import (
    update_agent_instance,
    create_agent_instance,
    _with_agent_creation_spec,
    store_agent_avatar_image,
    update_agent_avatar,
    replace_agent_llm_bindings_if_current,
    _default_agent_avatar_filename,
    _record_agent_task_profile_event,
    _record_agent_avatar_defaults_event,
    _record_agent_territory_event,
    _record_agent_persona_profile_event,
    _ensure_agent_default_avatar,
    resolve_agent_avatar_path_for_projection,
    _record_agent_event,
    _record_agent_avatar_updated_event,
    list_agent_avatar_options,
    _record_agent_avatar_uploaded_event,
    _record_agent_llm_binding_updated_event,
    _canonical_agent_avatar_metadata_path,
    agent_avatar_filename,
    _agent_avatar_match_key,
    _available_agent_avatar_filenames,
    _default_agent_avatar_path,
    _decode_agent_avatar_payload,
    resolve_agent_avatar_file,
    _validate_agent_avatar_signature,
    agent_avatar_image_url,
    _agent_avatar_image_version,
    _agent_avatar_path_from_metadata,
    record_agent_llm_binding_updated_event,
    _sanitize_avatar_stem,
)
from .agent_directory.repair_store import (
    _agent_creation_missing_fields,
    _agent_directory_storage_signature,
    _agent_public_display_name,
    _agent_workspace_relative_path,
    _atomic_write_json,
    _build_agent_registry_payload_for_storage,
    _challenge_cup_agent_profile_defaults,
    _clear_agent_runtime_state,
    _configured_model_library_ids,
    _count_jsonl_matching_status,
    _developer_sandbox_module,
    _display_name_needs_responsibility_repair,
    _ensure_agent_workspace,
    _ensure_fixed_role_profiles,
    _ensure_knowledge_steward_agent,
    _find_agent,
    _fixed_role_profile_defaults,
    _fixed_role_profile_key,
    _generic_research_agent_profile_defaults,
    _guard_against_suspicious_registry_shrink,
    _infer_agent_primary_mode,
    _infer_agent_prompt_template_id,
    _infer_agent_role_key,
    _invalidate_repaired_state_cache,
    _is_agent_private_workspace_path,
    _is_operation_chat_agent,
    _is_profileless_session_agent,
    _is_session_agent_primary_mode,
    _iter_text_lines_reverse,
    _jsonl_signature,
    _knowledge_steward_merged_metadata,
    _knowledge_steward_metadata,
    _load_existing_registry_payload_or_raise,
    _load_repaired_state_for_read,
    _mark_display_name_responsibility,
    _memory_policies,
    _merge_system_agent_metadata,
    _migrate_agent_llm_bindings_to_new_design,
    _next_agent_code,
    _normalize_agent_code,
    _normalize_agent_legacy_metadata_fields,
    _normalize_agent_record_for_storage,
    _normalize_primary_mode,
    _normalize_prompt_template_id,
    _normalize_role_key,
    _persona_profile_for_agent,
    _profile_id_to_model_id,
    _project_root,
    _prompt_template_id_for_role,
    _read_recent_jsonl,
    _read_recent_jsonl_with_count,
    _record_agent_llm_binding_migration_event,
    _record_agent_registry_load_failure,
    _record_knowledge_steward_repaired_event,
    _record_state_write_event,
    _refresh_agent_onboarding_metadata,
    _registry_state_signature,
    _relative_project_path,
    _remember_jsonl_count,
    _remember_jsonl_recent,
    _repair_agent_llm_binding_model_refs,
    _research_agent_profile_defaults,
    _research_org_profile_defaults,
    _resolve_legacy_agent_model_id,
    _resolve_project_path,
    _retired_self_evolution_role,
    _safe_fragment,
    _self_evolution_profile_defaults,
    _should_repair_agent_prompt_template_id,
    _should_repair_public_display_name,
    _should_replace_generic_challenge_cup_persona,
    _should_replace_generic_challenge_cup_task,
    _should_replace_incomplete_challenge_cup_task,
    _supervised_evolution_profile_defaults,
    _task_profile_for_agent,
    _unique_string_list,
    _with_functional_display_name,
    _workspace_path,
    default_state,
    load_state,
    repair_agent_directory,
    save_state,
)
from .agent_directory.ops_residual import (
    _active_agent_for_direct_session,
    _active_agent_prompt_template_id,
    _active_chat_session_id,
    _agent_context_window_limit,
    _agent_from_runtime_env,
    _agent_inbox_messages_for_agent,
    _agent_inbox_pending_count_for_agent,
    _agent_inbox_thread_id,
    _agent_llm_bindings_from_runtime_env,
    _agent_message_source_label,
    _agent_metadata_conversation_index_updates,
    _agent_metadata_prompt_template_id,
    _agent_prompt_template_binding,
    _agent_runtime_from_env,
    _agent_workspace_event_path,
    _agent_workspace_territory,
    _append_jsonl,
    _blocked_decision,
    _clamp_int,
    _count_pending_agent_inbox_messages_for_agents,
    _ensure_active_direct_session_available,
    _fallback_agent_code,
    _find_agent_by_direct_session,
    _get_config_value,
    _group_context_events_for_agent,
    _jsonl_file_has_records,
    _lexical_project_path,
    _list_recent_tool_governance_requests_for_agent,
    _load_recent_tool_governance_requests_for_agents,
    _model_context_window_limits_for_agents,
    _new_agent_id,
    _new_event_id,
    _path_has_reparse_component,
    _path_is_reparse_point,
    _path_is_within,
    _projection_edit_contract,
    _read_jsonl,
    _read_tool_governance_requests_for_agent,
    _record_agent_direct_session_collision_rejected,
    _record_agent_list_loaded,
    _record_agent_territory_write_blocked,
    _record_memory_event,
    _safe_metadata,
    _session_workspace_has_activity,
    _session_workspace_root_exists,
    _slowest_timing_stage,
    _source_authority_ref,
    _tool_governance_requests_for_agent,
    _with_runtime_tool_grants,
    _with_session_terminal_protocol_defaults,
    _without_disabled_agent_tools,
    _write_jsonl,
    consume_agent_inbox_message,
    consume_all_agent_inbox_messages,
    count_agent_inbox_messages_for_agent,
    current_agent_runtime,
    disable_group_context_events_for_room,
    effective_visible_tool_names_for_current_agent,
    ensure_agent_for_session,
    ensure_agent_shared_workspace,
    evaluate_agent_workspace_write,
    filter_llm_tools_for_current_agent,
    list_agent_inbox_messages_for_agent,
    list_agent_policy_options,
    list_group_context_events_for_agent,
    list_project_memory_update_proposals,
    next_wakeable_agent_inbox_message_for_agent,
    normalize_conversation_index_kind,
    reactivate_agent_instance,
    registry_path,
    resolve_agent_workspace_territory,
    resolve_project_memory_update_proposal,
    revoke_agent_inbox_message,
    scan_wakeable_agent_inbox_messages,
    utc_now_iso,
    write_agent_inbox_message,
    write_current_tool_observation,
    write_group_context_event,
    write_project_memory_update_proposal,
)
from .agent_directory.episodic_memory import (
    EPISODE_KINDS,
    PROMPT_LIST_LIMIT,
    REF_TYPES,
    append_episodic_event,
    list_current_episodic_events,
    supersede_episodic_event,
)


PROJECT_ROOT = Path(__file__).resolve().parents[3]
AGENT_REGISTRY_VERSION = 1
SUSPICIOUS_REGISTRY_SHRINK_MIN_AGENTS = 8
SUSPICIOUS_REGISTRY_SHRINK_MIN_DIRECT_AGENTS = 3
DEFAULT_AGENT_KIND = "persistent"
DEFAULT_TOOL_POLICY_ID = "default"
DEFAULT_MEMORY_POLICY_ID = "private"
DEFAULT_AGENT_PRIMARY_MODE = "chat"
_LEGACY_SESSION_AGENT_ALLOWED_TOOLS = (
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
    "user_action_telemetry_query_tool",
)
_LEGACY_SESSION_AGENT_PREFERRED_TOOLS = (
    "grep_search_tool",
    "code_symbol_tool",
    "apply_patch_tool",
    "run_test_for_tool",
    "cli_tool",
    "get_core_context_tool",
    "conversation_log_inspect_tool",
)
SESSION_PROTOCOL_ALLOWED_TOOLS = (
    *_LEGACY_SESSION_AGENT_ALLOWED_TOOLS[:8],
    "exec_command",
    "write_stdin",
    *_LEGACY_SESSION_AGENT_ALLOWED_TOOLS[8:],
)
SESSION_PROTOCOL_PREFERRED_TOOLS = (
    "exec_command",
    "write_stdin",
    *_LEGACY_SESSION_AGENT_PREFERRED_TOOLS,
)
PERSONAL_MEMORY_APPEND_TOOL_NAME = "append_personal_memory_tool"
PERSONAL_MEMORY_SUPERSEDE_TOOL_NAME = "supersede_personal_memory_tool"
PERSONAL_EPISODE_TOOL_NAME = PERSONAL_MEMORY_APPEND_TOOL_NAME
PERSONAL_EPISODE_SUPERSEDE_TOOL_NAME = PERSONAL_MEMORY_SUPERSEDE_TOOL_NAME
LEGACY_PERSONAL_MEMORY_TOOL_RENAMES = {
    "append_episodic_memory_tool": PERSONAL_MEMORY_APPEND_TOOL_NAME,
    "supersede_episodic_memory_tool": PERSONAL_MEMORY_SUPERSEDE_TOOL_NAME,
}
GENERATION_HANDOFF_MEMORY_TOOLS = (
    "get_core_context_tool",
    "get_current_goal_tool",
    "commit_compressed_memory_tool",
)
# Historical persisted defaults keep the old episodic tool names as literals.
_EPISODE_ERA_SESSION_AGENT_ALLOWED_TOOLS = (
    *SESSION_PROTOCOL_ALLOWED_TOOLS,
    "append_episodic_memory_tool",
)
_NARROW_HANDOFF_SESSION_AGENT_ALLOWED_TOOLS = tuple(
    name
    for name in _EPISODE_ERA_SESSION_AGENT_ALLOWED_TOOLS
    if name not in GENERATION_HANDOFF_MEMORY_TOOLS
)
_EPISODIC_NAMED_SESSION_AGENT_ALLOWED_TOOLS = (
    *_NARROW_HANDOFF_SESSION_AGENT_ALLOWED_TOOLS,
    "supersede_episodic_memory_tool",
)
PROJECT_OPERATION_TOOL_NAMES = (
    "agent_create_tool",
    "agent_update_tool",
    "agent_archive_tool",
    "agent_reset_tool",
    "session_create_tool",
    "session_update_tool",
    "session_stop_tool",
    "session_delete_tool",
    "agent_inbox_list_tool",
    "agent_message_consume_tool",
    "agent_messages_consume_all_tool",
    "knowledge_base_acl_grant_tool",
)
DEFAULT_SESSION_AGENT_ALLOWED_TOOLS = tuple(
    [
        *[
            name
            for name in _NARROW_HANDOFF_SESSION_AGENT_ALLOWED_TOOLS
            if name not in LEGACY_PERSONAL_MEMORY_TOOL_RENAMES
        ],
        PERSONAL_MEMORY_APPEND_TOOL_NAME,
        PERSONAL_MEMORY_SUPERSEDE_TOOL_NAME,
        *PROJECT_OPERATION_TOOL_NAMES,
        "github_project_library_search_tool",
        "github_project_library_clone_tool",
    ]
)
_DEFAULT_SESSION_AGENT_PREFERRED_BASE = tuple(
    name
    for name in SESSION_PROTOCOL_PREFERRED_TOOLS
    if name not in GENERATION_HANDOFF_MEMORY_TOOLS
)
_DEFAULT_SESSION_REUSE_RESEARCH_INDEX = _DEFAULT_SESSION_AGENT_PREFERRED_BASE.index(
    "apply_patch_tool"
)
DEFAULT_SESSION_AGENT_PREFERRED_TOOLS = (
    *_DEFAULT_SESSION_AGENT_PREFERRED_BASE[:_DEFAULT_SESSION_REUSE_RESEARCH_INDEX],
    "github_project_library_search_tool",
    *_DEFAULT_SESSION_AGENT_PREFERRED_BASE[_DEFAULT_SESSION_REUSE_RESEARCH_INDEX:],
)


def _rewrite_legacy_personal_memory_tool_names(names: list[str]) -> list[str]:
    rewritten: list[str] = []
    seen: set[str] = set()
    for name in names:
        mapped = LEGACY_PERSONAL_MEMORY_TOOL_RENAMES.get(name, name)
        if mapped in seen:
            continue
        seen.add(mapped)
        rewritten.append(mapped)
    return rewritten


# The persistent stdin protocol belongs to ordinary conversation Agents.  Keep
# self-evolution role policy unchanged until its own execution contract opts in.
SELF_EVOLUTION_EXECUTABLE_AGENT_ALLOWED_TOOLS = tuple(
    dict.fromkeys((*_LEGACY_SESSION_AGENT_ALLOWED_TOOLS, *GENERATION_HANDOFF_MEMORY_TOOLS))
)
SELF_EVOLUTION_EXECUTABLE_AGENT_PREFERRED_TOOLS = tuple(_LEGACY_SESSION_AGENT_PREFERRED_TOOLS)
SELF_EVOLUTION_EXECUTABLE_ROLES = {"executor", "reviewer"}
SELF_EVOLUTION_OBSERVER_ROLES = {"observer"}
SELF_EVOLUTION_ACTIVE_ROLES = SELF_EVOLUTION_EXECUTABLE_ROLES | SELF_EVOLUTION_OBSERVER_ROLES
SELF_EVOLUTION_RETIRED_ROLES = {"summarizer"}
SELF_EVOLUTION_RETIRED_PROMPT_TEMPLATE_IDS = {"prompt-self-summarizer"}
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
CONVERSATION_INDEX_VISIBILITY_USER_VISIBLE = "user_visible"
CONVERSATION_INDEX_VISIBILITY_TEAM_PRIVATE = "team_private"
CONVERSATION_INDEX_VISIBILITY_INTERNAL_RECOVERY = "internal_recovery"
CONVERSATION_INDEX_VISIBILITY_HIDDEN = "hidden"
CONVERSATION_INDEX_VISIBILITIES = {
    CONVERSATION_INDEX_VISIBILITY_USER_VISIBLE,
    CONVERSATION_INDEX_VISIBILITY_TEAM_PRIVATE,
    CONVERSATION_INDEX_VISIBILITY_INTERNAL_RECOVERY,
    CONVERSATION_INDEX_VISIBILITY_HIDDEN,
}
CONVERSATION_INDEX_KIND_USER_CHAT = "user_chat"
CONVERSATION_INDEX_KIND_PERSONAL_AGENT = "personal_agent"
CONVERSATION_INDEX_KIND_TEAM_AGENT = "team_agent"
CONVERSATION_INDEX_KIND_SYSTEM_ENTRY = "system_entry"
CONVERSATION_INDEX_KIND_HIDDEN = "hidden"
CONVERSATION_INDEX_KIND_INVALID = "invalid"
CONVERSATION_INDEX_KINDS = {
    CONVERSATION_INDEX_KIND_USER_CHAT,
    CONVERSATION_INDEX_KIND_PERSONAL_AGENT,
    CONVERSATION_INDEX_KIND_TEAM_AGENT,
    CONVERSATION_INDEX_KIND_SYSTEM_ENTRY,
    CONVERSATION_INDEX_KIND_HIDDEN,
    CONVERSATION_INDEX_KIND_INVALID,
}
TEAM_PRIVATE_DIRECT_SESSION_CREATED_BY = {
    "ai_search_team",
    "challenge_cup_team",
    "knowledge_expansion_team",
}
INTERNAL_RECOVERY_DIRECT_SESSION_CREATED_BY = {
    "research_organization",
    "self_evolution",
    "supervised_evolution",
    "system_repair",
}
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
    "self_evolution": SELF_EVOLUTION_OBSERVER_ROLES,
    "supervised_evolution": {"baseline", "candidate", "reviewer", "auditor", "judge"},
}
RESEARCH_SOURCE_ROLE_KEYS = set(agent_role_tool_profile_service.RESEARCH_SOURCE_ROLE_KEYS)
_RESEARCH_SOURCE_DEFAULT_PROFILE = agent_role_tool_profile_service.get_role_tool_profile("research_source_default") or {}
_RESEARCH_ROLE_DEFAULT_PROFILE = agent_role_tool_profile_service.get_role_tool_profile("research_role_default") or {}
RESEARCH_SOURCE_ALLOWED_TOOLS = tuple(_RESEARCH_SOURCE_DEFAULT_PROFILE.get("allowedTools") or ())
RESEARCH_SOURCE_PREFERRED_TOOLS = tuple(_RESEARCH_SOURCE_DEFAULT_PROFILE.get("preferredTools") or ())
CHALLENGE_CUP_ROLE_PROMPT_TEMPLATE_IDS = agent_role_tool_profile_service.CHALLENGE_CUP_ROLE_PROMPT_TEMPLATE_IDS
AI_SEARCH_ROLE_PROMPT_TEMPLATE_IDS = agent_role_tool_profile_service.AI_SEARCH_ROLE_PROMPT_TEMPLATE_IDS
KNOWLEDGE_EXPANSION_ROLE_PROMPT_TEMPLATE_IDS = agent_role_tool_profile_service.KNOWLEDGE_EXPANSION_ROLE_PROMPT_TEMPLATE_IDS
AGENT_LLM_BINDING_SLOTS = AGENT_LLM_SLOTS
LEGACY_AGENT_MODEL_ID_ALIASES = {
    "relay_openai_gpt_5_5": "relay_gpt_5_6_luna",
    "gpt_5_5_gpt_5_5": "relay_gpt_5_6_luna",
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
CODE_DELIVERY_AUDIT_AGENT_ID = "agent-code-delivery-audit"
CODE_DELIVERY_AUDIT_ROLE_KEY = "code_delivery_audit"
CODE_DELIVERY_AUDIT_DIRECT_SESSION_ID = "agent-code-delivery-audit-direct"
AGENT_CODE_PREFIX = "A"
AGENT_SHARED_WORKSPACE_PATH = "workspace/shared"
AGENT_AVATAR_RELATIVE_DIR = PurePosixPath("workspace/avatars")
AGENT_AVATAR_ASSET_DIR_NAME = "agent-avatars"
AGENT_AVATAR_CONFIG_DIR_NAME = "avatars"
AGENT_AVATAR_CONFIG_AGENT_DIR_NAME = "agents"
AGENT_AVATAR_MODEL_FILENAMES = MODEL_AVATAR_FILENAMES
AGENT_AVATAR_FILENAMES = (
    *AGENT_AVATAR_MODEL_FILENAMES,
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
# Specific role/token rules first; broad primaryMode tokens last so they never
# steal faces from knowledge_steward / self_evolution executor / supervised judge, etc.
AGENT_AVATAR_ROLE_DEFAULTS = (
    # --- product fixed roles (exact-ish tokens in match key) ---
    (("knowledge_steward",), ("15-anime-memory-steward-agent.png", "04-summarize-agent.png")),
    (("capability",), ("18-anime-system-service-agent.png", "09-card-planner.png")),
    (("能力管家",), ("18-anime-system-service-agent.png", "09-card-planner.png")),
    # supervised evolution sub-roles (distinguish faces)
    (("baseline",), ("03-inspect-agent.png", "07-evidence-reviewer.png")),
    (("candidate",), ("12-anime-tool-executor-agent.png", "02-diagnose-agent.png")),
    (("auditor",), ("07-evidence-reviewer.png", "13-anime-review-evaluator-agent.png")),
    (("judge",), ("09-card-planner.png", "18-anime-system-service-agent.png")),
    # self-evolution sub-roles before broad self_evolution mode
    (("observer",), ("16-anime-self-evolution-agent.png", "03-inspect-agent.png")),
    (("executor",), ("12-anime-tool-executor-agent.png", "02-diagnose-agent.png")),
    # research org / coordination
    (("org_advisor",), ("17-anime-team-coordinator-agent.png", "09-card-planner.png")),
    (("组织顾问",), ("17-anime-team-coordinator-agent.png", "09-card-planner.png")),
    (("ceo",), ("09-card-planner.png", "17-anime-team-coordinator-agent.png")),
    # memory / knowledge (substring, after knowledge_steward exact)
    (("memory",), ("04-summarize-agent.png", "15-anime-memory-steward-agent.png")),
    (("knowledge",), ("04-summarize-agent.png", "15-anime-memory-steward-agent.png")),
    (("steward",), ("04-summarize-agent.png", "15-anime-memory-steward-agent.png")),
    # research specialty pairs
    (("research", "broad"), ("05-broad-explorer.png", "14-anime-source-collector-agent.png")),
    (("research", "deep"), ("06-deep-investigator.png", "11-anime-deep-research-agent.png")),
    (("research", "theme"), ("08-theme-synthesizer.png", "19-anime-creative-writer-agent.png")),
    (("research", "card"), ("09-card-planner.png", "19-anime-creative-writer-agent.png")),
    (("research", "planner"), ("09-card-planner.png", "17-anime-team-coordinator-agent.png")),
    # generic function tokens
    (("source",), ("05-broad-explorer.png", "14-anime-source-collector-agent.png")),
    (("acquisition",), ("05-broad-explorer.png", "14-anime-source-collector-agent.png")),
    (("discovery",), ("05-broad-explorer.png", "14-anime-source-collector-agent.png")),
    (("content",), ("02-diagnose-agent.png", "12-anime-tool-executor-agent.png")),
    (("extraction",), ("02-diagnose-agent.png", "12-anime-tool-executor-agent.png")),
    (("optimization",), ("03-inspect-agent.png", "16-anime-self-evolution-agent.png")),
    (("coordinator",), ("09-card-planner.png", "17-anime-team-coordinator-agent.png")),
    (("orchestrat",), ("09-card-planner.png", "17-anime-team-coordinator-agent.png")),
    (("team",), ("09-card-planner.png", "17-anime-team-coordinator-agent.png")),
    (("creative",), ("08-theme-synthesizer.png", "19-anime-creative-writer-agent.png")),
    (("writing",), ("08-theme-synthesizer.png", "19-anime-creative-writer-agent.png")),
    (("synthesis",), ("08-theme-synthesizer.png", "19-anime-creative-writer-agent.png")),
    (("summar",), ("04-summarize-agent.png", "19-anime-creative-writer-agent.png")),
    (("review",), ("13-anime-review-evaluator-agent.png", "07-evidence-reviewer.png")),
    (("evidence",), ("07-evidence-reviewer.png", "13-anime-review-evaluator-agent.png")),
    (("audit",), ("07-evidence-reviewer.png", "13-anime-review-evaluator-agent.png")),
    (("inspect",), ("03-inspect-agent.png", "13-anime-review-evaluator-agent.png")),
    (("diagnose",), ("02-diagnose-agent.png", "12-anime-tool-executor-agent.png")),
    (("debug",), ("02-diagnose-agent.png", "12-anime-tool-executor-agent.png")),
    (("tool",), ("02-diagnose-agent.png", "12-anime-tool-executor-agent.png")),
    (("execute",), ("02-diagnose-agent.png", "12-anime-tool-executor-agent.png")),
    (("system",), ("18-anime-system-service-agent.png", "03-inspect-agent.png")),
    (("service",), ("18-anime-system-service-agent.png", "03-inspect-agent.png")),
    # --- broad primaryMode last ---
    (("self_evolution",), ("16-anime-self-evolution-agent.png", "03-inspect-agent.png")),
    (("self-evolution",), ("16-anime-self-evolution-agent.png", "03-inspect-agent.png")),
    (("supervised_evolution",), ("07-evidence-reviewer.png", "13-anime-review-evaluator-agent.png")),
    (("research",), ("05-broad-explorer.png", "11-anime-deep-research-agent.png")),
    (("chat",), ("01-session-agent.png", "10-anime-session-agent.png")),
    (("general",), ("01-session-agent.png", "10-anime-session-agent.png")),
)
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
TOOL_POLICY_WORKSPACE_SCOPES = ("private", "shared", "team_workflow_ledger")
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
_STATE_LOCK = threading.RLock()
_AGENT_SESSION_LIFECYCLE_LOCK = threading.RLock()
# 显式 project_root 的调用栈内传播：list_agents/get_agent/registry_path 接收
# 显式参数后通过 scoped context 生效，包内唯一的根读取口（_active_project_root）
# 优先取该值，否则回落模块级 PROJECT_ROOT。只在单次公开调用栈内 set/reset，
# 线程与 async 任务之间互不可见，取代旧的跨线程 save-swap-restore。
_SCOPED_PROJECT_ROOT: ContextVar[Path | None] = ContextVar(
    "vibelution_agent_directory_scoped_project_root",
    default=None,
)


@contextmanager
def scoped_project_root(project_root: Path | str | None):
    """Scope explicit ``project_root`` reads for one public API call."""

    if project_root is None:
        yield None
        return
    normalized = Path(project_root)
    token = _SCOPED_PROJECT_ROOT.set(normalized)
    try:
        yield normalized
    finally:
        _SCOPED_PROJECT_ROOT.reset(token)


def _active_project_root() -> Path:
    scoped = _SCOPED_PROJECT_ROOT.get()
    return scoped if scoped is not None else PROJECT_ROOT


_REPAIRED_STATE_CACHE_SIGNATURE: tuple[str, bool, int, int] | None = None
_REPAIRED_STATE_CACHE: dict[str, Any] | None = None
_JSONL_RECENT_CACHE: dict[tuple[str, bool, int, int, int, str, bool], list[dict[str, Any]]] = {}
_JSONL_COUNT_CACHE: dict[tuple[str, bool, int, int, str], int] = {}
_JSONL_RECENT_COUNT_CACHE: dict[tuple[str, bool, int, int, int, str], tuple[list[dict[str, Any]], int]] = {}
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


class AgentStateConflictError(AgentDirectoryError):
    """Raised when an Agent changes during a compare-and-swap update."""


class AgentArchivedError(AgentDirectoryError):
    """Raised when an archived AgentInstance would be silently reactivated."""


class AgentMessageNotFoundError(AgentDirectoryError):
    """Raised when an Agent inbox message does not exist."""


class AgentMemoryProposalNotFoundError(AgentDirectoryError):
    """Raised when an Agent project-memory proposal does not exist."""


class AgentEpisodicEventNotFoundError(AgentDirectoryError):
    """Raised when an Agent episodic event does not exist."""


def agent_session_lifecycle_serialized(
    callback: Callable[..., Any],
) -> Callable[..., Any]:
    """Serialize Agent registry mutations with bound-session lifecycle work."""

    @wraps(callback)
    def wrapped(*args: Any, **kwargs: Any) -> Any:
        with agent_session_lifecycle_transaction():
            return callback(*args, **kwargs)

    return wrapped


def agent_session_lifecycle_with_chat_serialized(
    callback: Callable[..., Any],
) -> Callable[..., Any]:
    """Serialize Agent work that also mutates bound chat-session state."""

    @wraps(callback)
    def wrapped(*args: Any, **kwargs: Any) -> Any:
        from . import session_service

        with session_service.session_agent_lifecycle_transaction():
            return callback(*args, **kwargs)

    return wrapped



# Lifecycle pack bodies; serializer wrappers stay on this facade.
archive_agent_instance = agent_session_lifecycle_serialized(archive_agent_instance)
purge_archived_agent_instance = agent_session_lifecycle_serialized(purge_archived_agent_instance)
reset_agent_instance = agent_session_lifecycle_with_chat_serialized(reset_agent_instance)

# Mutation pack bodies; serializer wrappers stay on this facade.
create_agent_instance = agent_session_lifecycle_serialized(create_agent_instance)
update_agent_instance = agent_session_lifecycle_serialized(update_agent_instance)

# Ops residual bodies; serializer wrappers stay on this facade.
ensure_agent_for_session = agent_session_lifecycle_serialized(ensure_agent_for_session)
reactivate_agent_instance = agent_session_lifecycle_serialized(reactivate_agent_instance)
@contextmanager
def agent_session_lifecycle_transaction():
    """Hold the cross-store Agent/session lifecycle serialization lock."""

    with _AGENT_SESSION_LIFECYCLE_LOCK:
        yield


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
