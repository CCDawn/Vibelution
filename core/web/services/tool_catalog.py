"""Shared tool catalog metadata for registry, policy UI, and governance."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import re
from typing import Any, Literal, Sequence


ToolCapability = str
ToolRisk = Literal["read", "write", "execute", "network", "destructive"]
ToolConcurrency = Literal["safe", "serialized"]
ToolApproval = Literal["never", "on_request", "always"]

TOOL_DESCRIPTOR_SCHEMA_VERSION = 1
# Monotonic contract revision. Bump only when descriptor semantics change.
TOOL_REGISTRY_VERSION = 1

_TOOL_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]{2,63}$")
_CAPABILITY_PATTERN = re.compile(r"^[a-z][a-z0-9_]{1,63}$")
_VALID_RISKS = {"read", "write", "execute", "network", "destructive"}
_VALID_CONCURRENCY = {"safe", "serialized"}
_VALID_APPROVAL = {"never", "on_request", "always"}
_CATEGORY_SCOPES = {
    "workspace_read": ("workspace",),
    "workspace_write": ("workspace",),
    "code_quality": ("workspace",),
    "web_research": ("network",),
    "git_evolution": ("workspace",),
    "task_runtime": ("runtime",),
    "agent_collaboration": ("agent",),
    "memory_context": ("memory",),
    "conversation_history": ("session",),
    "self_model": ("self_model",),
    "runtime_control": ("runtime",),
    "media_research": ("media",),
    "custom_generated": ("custom",),
    "virtual_life": ("agent",),
}
_DESTRUCTIVE_RISK_TAGS = {"delete_or_cleanup", "project_rollback"}
_EXECUTE_RISK_TAGS = {
    "background_agent",
    "background_task",
    "command_execution",
    "computer_control",
    "external_agent",
    "external_automation",
    "runtime_restart",
    "test_execution",
}
_NETWORK_RISK_TAGS = {"model_cost", "network_access"}
_WRITE_RISK_TAGS = {
    "agent_creation",
    "artifact_write",
    "can_modify_workspace",
    "can_start_agent",
    "can_wake_agent",
    "context_mutation",
    "cross_agent_message",
    "file_write",
    "formal_knowledge_mutation",
    "memory_write",
    "organization_policy_change",
    "permission_management",
    "runtime_governance",
    "self_model_write",
    "session_state_write",
    "session_wake",
    "task_state_write",
    "team_knowledge_proposal",
    "team_knowledge_rating",
    "team_knowledge_write",
    "team_workflow_state_write",
}


class ToolDescriptorError(ValueError):
    """Raised when canonical tool metadata is incomplete or ambiguous."""


@dataclass(frozen=True, slots=True)
class ToolAvailability:
    platforms: tuple[str, ...] = ()
    required_config: tuple[str, ...] = ()

    def public_projection(self) -> dict[str, list[str]]:
        """Return configuration names only; never include values or secrets."""

        return {
            "platforms": list(self.platforms),
            "requiredConfig": list(self.required_config),
        }


@dataclass(frozen=True, slots=True)
class ToolDescriptor:
    name: str
    schema_version: int
    schema_hash: str
    enabled: bool
    capabilities: tuple[ToolCapability, ...]
    risk: ToolRisk
    concurrency: ToolConcurrency
    scopes: tuple[str, ...]
    approval: ToolApproval
    aliases: tuple[str, ...] = ()
    availability: ToolAvailability = ToolAvailability()

    def public_projection(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "schemaVersion": self.schema_version,
            "schemaHash": self.schema_hash,
            "enabled": self.enabled,
            "capabilities": list(self.capabilities),
            "risk": self.risk,
            "concurrency": self.concurrency,
            "scopes": list(self.scopes),
            "approval": self.approval,
            "aliases": list(self.aliases),
            "availability": self.availability.public_projection(),
        }


LOW_PERMISSION_TIER = "low"
MEDIUM_PERMISSION_TIER = "medium"
HIGH_PERMISSION_TIER = "high"
GENERATED_PERMISSION_TIER = "generated"
EXPLICIT_ALLOW_TOOLS = {
    "cli_agent_run_tool",
    "computer_use_session_tool",
    "computer_use_task_tool",
    "read_file_tool",
    "research_knowledge_query_tool",
    "research_agent_creation_proposal_tool",
    "research_communication_edge_proposal_tool",
    "research_proposal_apply_tool",
    "unified_memory_search_tool",
    "knowledge_proposal_tool",
    "knowledge_ingestion_tool",
    "knowledge_governance_tasks_tool",
    "knowledge_operations_health_tool",
    "knowledge_governance_plan_tool",
    "knowledge_steward_recommendations_tool",
    "knowledge_steward_workbench_tool",
    "knowledge_rating_suggestion_tool",
    "research_knowledge_collection_tool",
    "research_knowledge_request_tool",
}


def explicit_allow_tool_names() -> set[str]:
    """Return tools that still require ToolPolicy explicit allow."""

    return set(EXPLICIT_ALLOW_TOOLS)

CATEGORY_LABELS = {
    "workspace_read": "Workspace read",
    "workspace_write": "Workspace write",
    "code_quality": "Code quality",
    "web_research": "Web and research",
    "git_evolution": "Git and evolution",
    "task_runtime": "Task runtime",
    "agent_collaboration": "Agent collaboration",
    "memory_context": "Memory and context",
    "self_model": "Self model",
    "media_research": "Media and knowledge",
    "custom_generated": "Custom generated",
    "virtual_life": "Virtual human life",
    "uncategorized": "Uncategorized",
}

TOOL_CATALOG: dict[str, dict[str, Any]] = {
    "grep_search_tool": {
        "category": "workspace_read",
        "capabilityTags": ["search", "codebase", "read_only"],
        "riskTags": [],
        "permissionTier": LOW_PERMISSION_TIER,
    },
    "glob_tool": {
        "category": "workspace_read",
        "capabilityTags": ["file_discovery", "read_only"],
        "riskTags": [],
        "permissionTier": LOW_PERMISSION_TIER,
    },
    "read_file_tool": {
        "category": "workspace_read",
        "capabilityTags": ["file_read", "read_only"],
        "riskTags": ["workspace_file_read"],
        "permissionTier": MEDIUM_PERMISSION_TIER,
    },
    "get_session_files_tool": {
        "category": "workspace_read",
        "capabilityTags": ["session_artifacts", "read_only"],
        "riskTags": ["session_data_access"],
        "permissionTier": MEDIUM_PERMISSION_TIER,
    },
    "apply_diff_edit_tool": {
        "category": "workspace_write",
        "capabilityTags": ["file_edit", "patch"],
        "riskTags": ["file_write"],
        "permissionTier": HIGH_PERMISSION_TIER,
    },
    "apply_patch_tool": {
        "category": "workspace_write",
        "capabilityTags": ["file_edit", "patch"],
        "riskTags": ["file_write"],
        "permissionTier": HIGH_PERMISSION_TIER,
    },
    "write_file_tool": {
        "category": "workspace_write",
        "capabilityTags": ["file_write"],
        "riskTags": ["file_write"],
        "permissionTier": HIGH_PERMISSION_TIER,
    },
    "clean_workspace_debris_tool": {
        "category": "workspace_write",
        "capabilityTags": ["cleanup", "delete"],
        "riskTags": ["delete_or_cleanup"],
        "permissionTier": HIGH_PERMISSION_TIER,
    },
    "list_workspace_debris_tool": {
        "category": "workspace_read",
        "capabilityTags": ["cleanup_planning", "read_only"],
        "riskTags": [],
        "permissionTier": MEDIUM_PERMISSION_TIER,
    },
    "code_symbol_tool": {
        "category": "code_quality",
        "capabilityTags": ["code_context_graph", "project_index", "code_navigation", "impact_analysis", "affected_tests"],
        "riskTags": [],
        "permissionTier": MEDIUM_PERMISSION_TIER,
    },
    "python_lint_tool": {
        "category": "code_quality",
        "capabilityTags": ["lint", "python"],
        "riskTags": ["static_analysis"],
        "permissionTier": MEDIUM_PERMISSION_TIER,
    },
    "run_test_for_tool": {
        "category": "code_quality",
        "capabilityTags": ["test", "validation"],
        "riskTags": ["test_execution"],
        "permissionTier": MEDIUM_PERMISSION_TIER,
    },
    "web_search_tool": {
        "category": "web_research",
        "capabilityTags": ["web_search", "network"],
        "riskTags": ["network_access"],
        "permissionTier": HIGH_PERMISSION_TIER,
    },
    "web_fetch_tool": {
        "category": "web_research",
        "capabilityTags": ["web_fetch", "network"],
        "riskTags": ["network_access"],
        "permissionTier": HIGH_PERMISSION_TIER,
    },
    "batch_web_search_tool": {
        "category": "web_research",
        "capabilityTags": ["web_search", "batch", "network", "no_quota_api"],
        "riskTags": ["network_access"],
        "permissionTier": HIGH_PERMISSION_TIER,
    },
    "paper_search_tool": {
        "category": "web_research",
        "capabilityTags": ["web_search", "paper_search", "research_sources", "network", "no_quota_api"],
        "riskTags": ["network_access"],
        "permissionTier": HIGH_PERMISSION_TIER,
    },
    "project_search_tool": {
        "category": "web_research",
        "capabilityTags": ["web_search", "project_search", "repositories", "network", "no_quota_api"],
        "riskTags": ["network_access"],
        "permissionTier": HIGH_PERMISSION_TIER,
    },
    "news_search_tool": {
        "category": "web_research",
        "capabilityTags": ["web_search", "news_search", "network", "no_quota_api"],
        "riskTags": ["network_access"],
        "permissionTier": HIGH_PERMISSION_TIER,
    },
    "search_summarize_sources_tool": {
        "category": "web_research",
        "capabilityTags": ["source_deduplication", "citation_cleanup", "read_only"],
        "riskTags": [],
        "permissionTier": LOW_PERMISSION_TIER,
    },
    "source_collection_context_tool": {
        "category": "media_research",
        "capabilityTags": ["source_collection", "stage_context", "read_only", "no_quota_api"],
        "riskTags": ["team_workflow_access"],
        "permissionTier": MEDIUM_PERMISSION_TIER,
    },
    "source_collection_stage_writeback_tool": {
        "category": "media_research",
        "capabilityTags": ["source_collection", "stage_task_writeback", "structured_result"],
        "riskTags": ["team_workflow_state_write"],
        "permissionTier": HIGH_PERMISSION_TIER,
    },
    "challenge_cup_experiment_context_tool": {
        "category": "media_research",
        "capabilityTags": ["challenge_cup", "experiment_ledger", "read_only", "no_quota_api"],
        "riskTags": ["team_workflow_access"],
        "permissionTier": MEDIUM_PERMISSION_TIER,
    },
    "challenge_cup_experiment_writeback_tool": {
        "category": "media_research",
        "capabilityTags": ["challenge_cup", "experiment_ledger", "structured_result"],
        "riskTags": ["team_workflow_state_write"],
        "permissionTier": HIGH_PERMISSION_TIER,
    },
    "challenge_cup_iteration_context_tool": {
        "category": "media_research",
        "capabilityTags": ["challenge_cup", "research_loop", "read_only", "no_quota_api"],
        "riskTags": ["team_workflow_access"],
        "permissionTier": MEDIUM_PERMISSION_TIER,
    },
    "challenge_cup_iteration_writeback_tool": {
        "category": "media_research",
        "capabilityTags": ["challenge_cup", "research_loop", "structured_result"],
        "riskTags": ["team_workflow_state_write"],
        "permissionTier": HIGH_PERMISSION_TIER,
    },
    "challenge_cup_versioning_context_tool": {
        "category": "media_research",
        "capabilityTags": ["challenge_cup", "candidate_versioning", "read_only", "no_quota_api"],
        "riskTags": ["team_workflow_access"],
        "permissionTier": MEDIUM_PERMISSION_TIER,
    },
    "challenge_cup_versioning_writeback_tool": {
        "category": "media_research",
        "capabilityTags": ["challenge_cup", "candidate_versioning", "structured_result"],
        "riskTags": ["team_workflow_state_write"],
        "permissionTier": HIGH_PERMISSION_TIER,
    },
    "research_knowledge_collection_tool": {
        "category": "media_research",
        "capabilityTags": ["challenge_cup", "knowledge_collection_facade", "source_collection", "scope_envelope", "structured_result", "no_quota_api"],
        "riskTags": ["team_workflow_state_write"],
        "permissionTier": HIGH_PERMISSION_TIER,
    },
    "research_knowledge_request_tool": {
        "category": "media_research",
        "capabilityTags": ["challenge_cup", "hypothesis_knowledge_request", "advisory_preview", "scope_envelope", "structured_result", "no_quota_api"],
        "riskTags": ["team_workflow_state_write"],
        "permissionTier": HIGH_PERMISSION_TIER,
    },
    "get_git_status_summary_tool": {
        "category": "git_evolution",
        "capabilityTags": ["git", "status", "read_only"],
        "riskTags": [],
        "permissionTier": LOW_PERMISSION_TIER,
    },
    "get_recent_changes_tool": {
        "category": "git_evolution",
        "capabilityTags": ["git", "diff_summary", "read_only"],
        "riskTags": [],
        "permissionTier": LOW_PERMISSION_TIER,
    },
    "get_entity_history_tool": {
        "category": "git_evolution",
        "capabilityTags": ["git", "history", "read_only"],
        "riskTags": [],
        "permissionTier": LOW_PERMISSION_TIER,
    },
    "explain_current_worktree_tool": {
        "category": "git_evolution",
        "capabilityTags": ["git", "worktree", "read_only"],
        "riskTags": [],
        "permissionTier": LOW_PERMISSION_TIER,
    },
    "conversation_log_inspect_tool": {
        "category": "workspace_read",
        "capabilityTags": ["conversation_logs", "diagnostics", "read_only"],
        "riskTags": ["session_data_access"],
        "permissionTier": LOW_PERMISSION_TIER,
    },
    "user_action_telemetry_query_tool": {
        "category": "workspace_read",
        "capabilityTags": ["runtime_scenes", "user_action_telemetry", "diagnostics", "read_only"],
        "riskTags": ["session_data_access"],
        "permissionTier": LOW_PERMISSION_TIER,
    },
    "history_search_tool": {
        "category": "conversation_history",
        "capabilityTags": ["conversation_history", "search", "read_only"],
        "riskTags": ["session_data_access"],
        "permissionTier": LOW_PERMISSION_TIER,
    },
    "history_fetch_tool": {
        "category": "conversation_history",
        "capabilityTags": ["conversation_history", "fetch", "read_only"],
        "riskTags": ["session_data_access"],
        "permissionTier": LOW_PERMISSION_TIER,
    },
    "history_timeline_tool": {
        "category": "conversation_history",
        "capabilityTags": ["conversation_history", "timeline", "read_only"],
        "riskTags": ["session_data_access"],
        "permissionTier": LOW_PERMISSION_TIER,
    },
    "history_checkpoint_tool": {
        "category": "conversation_history",
        "capabilityTags": ["conversation_history", "checkpoint", "read_only"],
        "riskTags": ["session_data_access"],
        "permissionTier": LOW_PERMISSION_TIER,
    },
    "open_evolution_transaction_tool": {
        "category": "git_evolution",
        "capabilityTags": ["transaction", "evolution"],
        "riskTags": ["runtime_governance"],
        "permissionTier": HIGH_PERMISSION_TIER,
    },
    "close_evolution_transaction_tool": {
        "category": "git_evolution",
        "capabilityTags": ["transaction", "evolution"],
        "riskTags": ["runtime_governance"],
        "permissionTier": HIGH_PERMISSION_TIER,
    },
    "get_evolution_fitness_tool": {
        "category": "git_evolution",
        "capabilityTags": ["fitness", "read_only"],
        "riskTags": [],
        "permissionTier": LOW_PERMISSION_TIER,
    },
    "cli_tool": {
        "category": "task_runtime",
        "capabilityTags": ["command", "shell"],
        "riskTags": ["command_execution"],
        "permissionTier": HIGH_PERMISSION_TIER,
    },
    "exec_command": {
        "category": "task_runtime",
        "capabilityTags": ["command", "shell", "terminal_session"],
        "riskTags": ["command_execution"],
        "permissionTier": HIGH_PERMISSION_TIER,
    },
    "write_stdin": {
        "category": "task_runtime",
        "capabilityTags": ["command", "terminal_session", "stdin"],
        "riskTags": ["command_execution"],
        "permissionTier": HIGH_PERMISSION_TIER,
    },
    "cli_agent_run_tool": {
        "category": "agent_collaboration",
        "capabilityTags": ["external_agent", "cli_agent", "command", "worktree"],
        "riskTags": ["command_execution", "external_agent", "can_modify_workspace"],
        "permissionTier": HIGH_PERMISSION_TIER,
    },
    "task_create_tool": {
        "category": "task_runtime",
        "capabilityTags": ["task_state", "write"],
        "riskTags": ["task_state_write"],
        "permissionTier": HIGH_PERMISSION_TIER,
    },
    "task_update_tool": {
        "category": "task_runtime",
        "capabilityTags": ["task_state", "write"],
        "riskTags": ["task_state_write"],
        "permissionTier": HIGH_PERMISSION_TIER,
    },
    "task_list_tool": {
        "category": "task_runtime",
        "capabilityTags": ["task_state", "read_only"],
        "riskTags": [],
        "permissionTier": LOW_PERMISSION_TIER,
    },
    "plan_update_tool": {
        "category": "task_runtime",
        "capabilityTags": ["plan", "state_write"],
        "riskTags": ["task_state_write"],
        "permissionTier": HIGH_PERMISSION_TIER,
    },
    "task_start_tool": {
        "category": "task_runtime",
        "capabilityTags": ["background_task", "command"],
        "riskTags": ["background_task"],
        "permissionTier": HIGH_PERMISSION_TIER,
    },
    "task_output_tool": {
        "category": "task_runtime",
        "capabilityTags": ["background_task", "read_only"],
        "riskTags": ["background_task"],
        "permissionTier": MEDIUM_PERMISSION_TIER,
    },
    "task_stop_tool": {
        "category": "task_runtime",
        "capabilityTags": ["background_task", "control"],
        "riskTags": ["background_task"],
        "permissionTier": HIGH_PERMISSION_TIER,
    },
    "spawn_agent_tool": {
        "category": "agent_collaboration",
        "capabilityTags": ["subagent", "delegation"],
        "riskTags": ["background_agent"],
        "permissionTier": HIGH_PERMISSION_TIER,
    },
    "agent_message_tool": {
        "category": "agent_collaboration",
        "capabilityTags": ["agent_message", "wake"],
        "riskTags": ["cross_agent_message", "can_wake_agent"],
        "permissionTier": HIGH_PERMISSION_TIER,
    },
    "create_child_session_tool": {
        "category": "agent_collaboration",
        "capabilityTags": ["child_session", "conversation_split", "task_routing"],
        "riskTags": ["session_state_write", "can_start_agent"],
        "permissionTier": HIGH_PERMISSION_TIER,
    },
    "list_child_sessions_tool": {
        "category": "agent_collaboration",
        "capabilityTags": ["child_session", "conversation_index", "read_only"],
        "riskTags": ["session_data_access"],
        "permissionTier": MEDIUM_PERMISSION_TIER,
    },
    "agent_create_tool": {
        "category": "agent_collaboration",
        "capabilityTags": ["agent_creation", "lifecycle", "governed_write"],
        "riskTags": ["agent_creation"],
        "permissionTier": HIGH_PERMISSION_TIER,
    },
    "agent_update_tool": {
        "category": "agent_collaboration",
        "capabilityTags": ["agent_configuration", "governed_write"],
        "riskTags": ["permission_management", "runtime_governance"],
        "permissionTier": HIGH_PERMISSION_TIER,
    },
    "agent_archive_tool": {
        "category": "agent_collaboration",
        "capabilityTags": ["agent_archive", "lifecycle", "governed_write"],
        "riskTags": ["delete_or_cleanup"],
        "permissionTier": HIGH_PERMISSION_TIER,
    },
    "agent_reset_tool": {
        "category": "agent_collaboration",
        "capabilityTags": ["agent_reset", "lifecycle", "governed_write"],
        "riskTags": ["delete_or_cleanup"],
        "permissionTier": HIGH_PERMISSION_TIER,
    },
    "session_create_tool": {
        "category": "agent_collaboration",
        "capabilityTags": ["session_create", "lifecycle", "governed_write"],
        "riskTags": ["session_state_write"],
        "permissionTier": HIGH_PERMISSION_TIER,
    },
    "session_update_tool": {
        "category": "agent_collaboration",
        "capabilityTags": ["session_update", "lifecycle", "governed_write"],
        "riskTags": ["session_state_write"],
        "permissionTier": HIGH_PERMISSION_TIER,
    },
    "session_stop_tool": {
        "category": "agent_collaboration",
        "capabilityTags": ["session_stop", "lifecycle", "governed_write"],
        "riskTags": ["session_state_write"],
        "permissionTier": HIGH_PERMISSION_TIER,
    },
    "session_delete_tool": {
        "category": "agent_collaboration",
        "capabilityTags": ["session_delete", "lifecycle", "governed_write"],
        "riskTags": ["delete_or_cleanup"],
        "permissionTier": HIGH_PERMISSION_TIER,
    },
    "agent_inbox_list_tool": {
        "category": "agent_collaboration",
        "capabilityTags": ["agent_inbox", "message_list", "read_only"],
        "riskTags": ["session_data_access"],
        "permissionTier": MEDIUM_PERMISSION_TIER,
    },
    "agent_message_consume_tool": {
        "category": "agent_collaboration",
        "capabilityTags": ["agent_inbox", "message_consume", "governed_write"],
        "riskTags": ["session_state_write"],
        "permissionTier": HIGH_PERMISSION_TIER,
    },
    "agent_messages_consume_all_tool": {
        "category": "agent_collaboration",
        "capabilityTags": ["agent_inbox", "message_consume_all", "governed_write"],
        "riskTags": ["session_state_write"],
        "permissionTier": HIGH_PERMISSION_TIER,
    },
    "knowledge_base_acl_grant_tool": {
        "category": "memory_context",
        "capabilityTags": ["team_knowledge", "knowledge_base_acl", "permission_management"],
        "riskTags": ["permission_management", "team_knowledge_write"],
        "permissionTier": HIGH_PERMISSION_TIER,
    },
    "agent_tool_permission_request_tool": {
        "category": "agent_collaboration",
        "capabilityTags": ["permission_management", "governance"],
        "riskTags": ["permission_management"],
        "permissionTier": HIGH_PERMISSION_TIER,
    },
    "research_agent_creation_proposal_tool": {
        "category": "agent_collaboration",
        "capabilityTags": ["agent_creation", "organization_governance", "proposal"],
        "riskTags": ["organization_policy_change", "agent_creation"],
        "permissionTier": HIGH_PERMISSION_TIER,
    },
    "research_communication_edge_proposal_tool": {
        "category": "agent_collaboration",
        "capabilityTags": ["communication_edge", "organization_governance", "proposal"],
        "riskTags": ["organization_policy_change", "cross_agent_message"],
        "permissionTier": HIGH_PERMISSION_TIER,
    },
    "research_proposal_apply_tool": {
        "category": "agent_collaboration",
        "capabilityTags": ["organization_governance", "proposal_apply", "agent_creation"],
        "riskTags": ["organization_policy_change", "agent_creation"],
        "permissionTier": HIGH_PERMISSION_TIER,
    },
    "commit_compressed_memory_tool": {
        "category": "memory_context",
        "capabilityTags": ["memory_write", "context"],
        "riskTags": ["memory_write"],
        "permissionTier": HIGH_PERMISSION_TIER,
    },
    "read_memory_tool": {
        "category": "memory_context",
        "capabilityTags": ["memory_read", "context", "read_only"],
        "riskTags": ["memory_access"],
        "permissionTier": MEDIUM_PERMISSION_TIER,
    },
    "get_memory_summary_tool": {
        "category": "memory_context",
        "capabilityTags": ["memory_summary", "context", "read_only"],
        "riskTags": ["memory_access"],
        "permissionTier": MEDIUM_PERMISSION_TIER,
    },
    "session_reference_query_tool": {
        "category": "memory_context",
        "capabilityTags": ["conversation_reference", "session_history", "read_only"],
        "riskTags": ["session_data_access"],
        "permissionTier": MEDIUM_PERMISSION_TIER,
    },
    "skill_library_search_tool": {
        "category": "memory_context",
        "capabilityTags": ["skill_library", "skill_search", "read_only"],
        "riskTags": ["memory_access"],
        "permissionTier": MEDIUM_PERMISSION_TIER,
    },
    "github_project_library_search_tool": {
        "category": "memory_context",
        "capabilityTags": ["github_project_library", "read_only"],
        "riskTags": ["memory_access"],
        "permissionTier": MEDIUM_PERMISSION_TIER,
    },
    "github_project_library_clone_tool": {
        "category": "memory_context",
        "capabilityTags": ["github_project_library", "memory_write", "network_access"],
        "riskTags": ["memory_write", "network_access"],
        "permissionTier": HIGH_PERMISSION_TIER,
    },
    "get_core_context_tool": {
        "category": "memory_context",
        "capabilityTags": ["context", "read_only"],
        "riskTags": [],
        "permissionTier": LOW_PERMISSION_TIER,
    },
    "get_current_goal_tool": {
        "category": "memory_context",
        "capabilityTags": ["goal", "read_only"],
        "riskTags": [],
        "permissionTier": LOW_PERMISSION_TIER,
    },
    "record_learning_tool": {
        "category": "memory_context",
        "capabilityTags": ["memory_write", "learning"],
        "riskTags": ["memory_write"],
        "permissionTier": HIGH_PERMISSION_TIER,
    },
    "append_personal_memory_tool": {
        "category": "memory_context",
        "capabilityTags": ["memory_write", "private_episode"],
        "riskTags": ["memory_write"],
        "permissionTier": MEDIUM_PERMISSION_TIER,
    },
    "supersede_personal_memory_tool": {
        "category": "memory_context",
        "capabilityTags": ["memory_write", "private_episode"],
        "riskTags": ["memory_write"],
        "permissionTier": MEDIUM_PERMISSION_TIER,
    },
    "append_episodic_memory_tool": {
        "category": "memory_context",
        "capabilityTags": ["memory_write", "private_episode"],
        "riskTags": ["memory_write"],
        "permissionTier": MEDIUM_PERMISSION_TIER,
    },
    "supersede_episodic_memory_tool": {
        "category": "memory_context",
        "capabilityTags": ["memory_write", "private_episode"],
        "riskTags": ["memory_write"],
        "permissionTier": MEDIUM_PERMISSION_TIER,
    },
    "search_memory_tool": {
        "category": "memory_context",
        "capabilityTags": ["memory_search", "read_only"],
        "riskTags": ["memory_access"],
        "permissionTier": HIGH_PERMISSION_TIER,
    },
    "search_error_archive_tool": {
        "category": "memory_context",
        "capabilityTags": ["error_archive", "read_only"],
        "riskTags": ["memory_access"],
        "permissionTier": HIGH_PERMISSION_TIER,
    },
    "compress_context_tool": {
        "category": "memory_context",
        "capabilityTags": ["context", "compaction"],
        "riskTags": ["context_mutation"],
        "permissionTier": HIGH_PERMISSION_TIER,
    },
    "get_mental_state_tool": {
        "category": "self_model",
        "capabilityTags": ["mental_state", "read_only"],
        "riskTags": [],
        "permissionTier": LOW_PERMISSION_TIER,
    },
    "update_diagnosis_rules_tool": {
        "category": "self_model",
        "capabilityTags": ["diagnosis_rules", "write"],
        "riskTags": ["self_model_write"],
        "permissionTier": HIGH_PERMISSION_TIER,
    },
    "update_self_model_tool": {
        "category": "self_model",
        "capabilityTags": ["self_model", "write"],
        "riskTags": ["self_model_write"],
        "permissionTier": HIGH_PERMISSION_TIER,
    },
    "get_self_model_tool": {
        "category": "self_model",
        "capabilityTags": ["self_model", "read_only"],
        "riskTags": ["self_model_access"],
        "permissionTier": MEDIUM_PERMISSION_TIER,
    },
    "record_evolution_tool": {
        "category": "self_model",
        "capabilityTags": ["evolution_record", "write"],
        "riskTags": ["self_model_write"],
        "permissionTier": HIGH_PERMISSION_TIER,
    },
    "trigger_self_restart_tool": {
        "category": "runtime_control",
        "capabilityTags": ["hot_restart", "launcher_lifecycle", "runtime_control", "rollback"],
        "riskTags": ["runtime_restart", "project_rollback", "session_wake"],
        "permissionTier": HIGH_PERMISSION_TIER,
    },
    "image2_generate_tool": {
        "category": "media_research",
        "capabilityTags": ["image_generation", "artifact"],
        "riskTags": ["model_cost", "artifact_write"],
        "permissionTier": HIGH_PERMISSION_TIER,
    },
    "computer_use_task_tool": {
        "category": "task_runtime",
        "capabilityTags": ["computer_use", "sandbox_browser", "automation"],
        "riskTags": ["computer_control", "network_access", "external_automation"],
        "permissionTier": HIGH_PERMISSION_TIER,
    },
    "computer_use_session_tool": {
        "category": "task_runtime",
        "capabilityTags": ["computer_use", "sandbox_browser", "session_control"],
        "riskTags": ["computer_control", "external_automation", "session_state_write"],
        "permissionTier": HIGH_PERMISSION_TIER,
    },
    "research_knowledge_query_tool": {
        "category": "media_research",
        "capabilityTags": ["research_database", "read_only"],
        "riskTags": ["research_database_access"],
        "permissionTier": HIGH_PERMISSION_TIER,
    },
    "unified_memory_search_tool": {
        "category": "memory_context",
        "capabilityTags": ["agent_memory", "team_knowledge", "unified_search", "rag_retrieval", "citations", "read_only"],
        "riskTags": ["team_knowledge_access", "prompt_context_candidate"],
        "permissionTier": HIGH_PERMISSION_TIER,
        "argDescriptors": [
            {
                "name": "include_user_content",
                "type": "boolean",
                "required": False,
                "description": "Include imported user Markdown Space pages as read-only reference results.",
            },
            {
                "name": "user_content_space_ids",
                "type": "string",
                "required": False,
                "description": "Comma-separated imported user Markdown Space ids to search when include_user_content is true.",
            },
        ],
    },
    "knowledge_proposal_tool": {
        "category": "memory_context",
        "capabilityTags": ["team_knowledge", "proposal_write", "central_source_attachment"],
        "riskTags": ["team_knowledge_proposal"],
        "permissionTier": HIGH_PERMISSION_TIER,
    },
    "knowledge_ingestion_tool": {
        "category": "memory_context",
        "capabilityTags": ["team_knowledge", "source_review", "direct_ingestion", "knowledge_item_write", "central_source_attachment"],
        "riskTags": ["team_knowledge_write", "formal_knowledge_mutation"],
        "permissionTier": HIGH_PERMISSION_TIER,
    },
    "knowledge_governance_tasks_tool": {
        "category": "memory_context",
        "capabilityTags": ["team_knowledge", "governance_queue", "read_only"],
        "riskTags": ["team_knowledge_access"],
        "permissionTier": HIGH_PERMISSION_TIER,
    },
    "knowledge_operations_health_tool": {
        "category": "memory_context",
        "capabilityTags": ["team_knowledge", "operations_health", "read_only"],
        "riskTags": ["team_knowledge_access"],
        "permissionTier": HIGH_PERMISSION_TIER,
    },
    "knowledge_governance_plan_tool": {
        "category": "memory_context",
        "capabilityTags": ["team_knowledge", "governance_plan", "read_only"],
        "riskTags": ["team_knowledge_access"],
        "permissionTier": HIGH_PERMISSION_TIER,
    },
    "knowledge_steward_recommendations_tool": {
        "category": "memory_context",
        "capabilityTags": ["team_knowledge", "steward_recommendations", "governance", "read_only"],
        "riskTags": ["team_knowledge_access"],
        "permissionTier": HIGH_PERMISSION_TIER,
    },
    "knowledge_steward_workbench_tool": {
        "category": "memory_context",
        "capabilityTags": ["team_knowledge", "steward_workbench", "governance", "read_only"],
        "riskTags": ["team_knowledge_access"],
        "permissionTier": HIGH_PERMISSION_TIER,
    },
    "knowledge_rating_suggestion_tool": {
        "category": "memory_context",
        "capabilityTags": ["team_knowledge", "rating_suggestion", "governance"],
        "riskTags": ["team_knowledge_rating"],
        "permissionTier": HIGH_PERMISSION_TIER,
    },
    "virtual_human_status_tool": {
        "category": "virtual_life",
        "capabilityTags": ["virtual_life", "life_state", "read_only"],
        "riskTags": [],
        "permissionTier": LOW_PERMISSION_TIER,
    },
    "virtual_human_schedule_tool": {
        "category": "virtual_life",
        "capabilityTags": ["virtual_life", "life_schedule", "read_only"],
        "riskTags": [],
        "permissionTier": LOW_PERMISSION_TIER,
    },
    "virtual_human_activity_tool": {
        "category": "virtual_life",
        "capabilityTags": ["virtual_life", "life_activity", "structured_result"],
        "riskTags": ["session_state_write"],
        "permissionTier": MEDIUM_PERMISSION_TIER,
    },
    "virtual_human_diary_tool": {
        "category": "virtual_life",
        "capabilityTags": ["virtual_life", "life_diary", "structured_result"],
        "riskTags": ["memory_write"],
        "permissionTier": MEDIUM_PERMISSION_TIER,
    },
    "virtual_human_relationship_tool": {
        "category": "virtual_life",
        "capabilityTags": ["virtual_life", "life_relationship", "structured_result"],
        "riskTags": ["memory_write"],
        "permissionTier": MEDIUM_PERMISSION_TIER,
    },
    "virtual_human_reflection_tool": {
        "category": "virtual_life",
        "capabilityTags": ["virtual_life", "life_reflection", "proposal_write", "structured_result"],
        "riskTags": ["memory_proposal"],
        "permissionTier": MEDIUM_PERMISSION_TIER,
    },
    "virtual_human_proactive_message_tool": {
        "category": "virtual_life",
        "capabilityTags": ["virtual_life", "proactive_message", "structured_result"],
        "riskTags": ["session_state_write", "session_wake"],
        "permissionTier": MEDIUM_PERMISSION_TIER,
    },
    "virtual_human_dialogue_decision_v2_tool": {
        "category": "virtual_life",
        "capabilityTags": ["virtual_life", "dialogue_decision", "structured_result"],
        "riskTags": ["session_state_write"],
        "permissionTier": MEDIUM_PERMISSION_TIER,
    },
}

TOOL_BUNDLE_DEFINITIONS: tuple[dict[str, Any], ...] = (
    {
        "bundleId": "virtual_human_life",
        "label": "虚拟人生活工具包",
        "description": "仅对已启用插件的 Agent 生效：查询和推进自己的生活、日记、关系与受控主动消息。",
        "category": "virtual_life",
        "toolNames": [
            "virtual_human_status_tool",
            "virtual_human_schedule_tool",
            "virtual_human_activity_tool",
            "virtual_human_diary_tool",
            "virtual_human_relationship_tool",
            "virtual_human_reflection_tool",
            "virtual_human_proactive_message_tool",
            "virtual_human_dialogue_decision_v2_tool",
        ],
        "preferredToolNames": [
            "virtual_human_status_tool",
            "virtual_human_schedule_tool",
            "virtual_human_activity_tool",
            "virtual_human_diary_tool",
            "virtual_human_relationship_tool",
            "virtual_human_reflection_tool",
            "virtual_human_proactive_message_tool",
            "virtual_human_dialogue_decision_v2_tool",
        ],
    },
    {
        "bundleId": "pure_chat",
        "label": "纯聊天 / 无工具",
        "description": "关闭该 Agent 的全部工具调用，只保留模型对话能力；适合需要彻底禁用默认工具的会话 Agent。",
        "category": "core",
        "toolNames": [],
        "preferredToolNames": [],
    },
    {
        "bundleId": "core",
        "label": "会话 Agent 基础包",
        "description": "适合会话 Agent 默认启用：检索代码、查看任务和当前工作状态。世代交接脑留给自进化角色。",
        "category": "core",
        "toolNames": [
            "grep_search_tool",
            "glob_tool",
            "task_list_tool",
            "get_git_status_summary_tool",
            "get_recent_changes_tool",
            "conversation_log_inspect_tool",
        ],
        "preferredToolNames": [
            "grep_search_tool",
            "conversation_log_inspect_tool",
        ],
    },
    {
        "bundleId": "research",
        "label": "科研工具包",
        "description": "适合科研资料检索和证据整理：联网搜索、读取科研知识库和整理来源线索，不包含正式知识入库工具。",
        "category": "research",
        "toolNames": [
            "grep_search_tool",
            "glob_tool",
            "web_fetch_tool",
            "batch_web_search_tool",
            "paper_search_tool",
            "project_search_tool",
            "news_search_tool",
            "search_summarize_sources_tool",
            "research_knowledge_query_tool",
            "unified_memory_search_tool",
            "get_session_files_tool",
        ],
        "preferredToolNames": [
            "batch_web_search_tool",
            "paper_search_tool",
            "web_fetch_tool",
            "search_summarize_sources_tool",
            "research_knowledge_query_tool",
            "unified_memory_search_tool",
        ],
    },
    {
        "bundleId": "source_collection_stage",
        "label": "资料搜集阶段包",
        "description": "适合挑战杯资料搜集阶段私聊任务：读取阶段上下文并回写阶段任务结果，不等同正式知识入库。",
        "category": "research",
        "toolNames": [
            "task_list_tool",
            "task_create_tool",
            "task_update_tool",
            "source_collection_context_tool",
            "source_collection_stage_writeback_tool",
            "research_knowledge_query_tool",
            "batch_web_search_tool",
            "paper_search_tool",
            "project_search_tool",
            "news_search_tool",
            "search_summarize_sources_tool",
            "web_fetch_tool",
            "agent_message_tool",
        ],
        "preferredToolNames": [
            "task_list_tool",
            "task_create_tool",
            "task_update_tool",
            "source_collection_context_tool",
            "source_collection_stage_writeback_tool",
            "batch_web_search_tool",
            "paper_search_tool",
            "search_summarize_sources_tool",
            "research_knowledge_query_tool",
        ],
    },
    {
        "bundleId": "challenge_cup_experiment",
        "label": "挑战杯实验账本包",
        "description": "适合挑战杯实验规划和证据登记：读写实验计划、baseline、smoke/full-run 结果和入库申请，不执行训练。",
        "category": "research",
        "toolNames": [
            "challenge_cup_experiment_context_tool",
            "challenge_cup_experiment_writeback_tool",
            "research_knowledge_query_tool",
            "agent_message_tool",
            "user_action_telemetry_query_tool",
        ],
        "preferredToolNames": [
            "challenge_cup_experiment_context_tool",
            "challenge_cup_experiment_writeback_tool",
            "research_knowledge_query_tool",
        ],
    },
    {
        "bundleId": "challenge_cup_iteration",
        "label": "挑战杯迭代账本包",
        "description": "适合挑战杯实验迭代与候选版本治理：读写 Research Loop、证据决策、版本历史和拒绝归档，不自动 apply。",
        "category": "research",
        "toolNames": [
            "challenge_cup_iteration_context_tool",
            "challenge_cup_iteration_writeback_tool",
            "challenge_cup_versioning_context_tool",
            "challenge_cup_versioning_writeback_tool",
            "challenge_cup_experiment_context_tool",
            "research_knowledge_query_tool",
            "agent_message_tool",
            "user_action_telemetry_query_tool",
        ],
        "preferredToolNames": [
            "challenge_cup_iteration_context_tool",
            "challenge_cup_iteration_writeback_tool",
            "challenge_cup_versioning_context_tool",
            "challenge_cup_versioning_writeback_tool",
        ],
    },
    {
        "bundleId": "knowledge_steward",
        "label": "知识库管理员审核包",
        "description": "适合知识库管理员入库审核：提交摄取包、知识提案、治理队列和评级建议。",
        "category": "memory",
        "toolNames": [
            "source_collection_context_tool",
            "source_collection_stage_writeback_tool",
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
        "preferredToolNames": [
            "source_collection_context_tool",
            "source_collection_stage_writeback_tool",
            "knowledge_governance_tasks_tool",
            "knowledge_operations_health_tool",
            "knowledge_governance_plan_tool",
            "knowledge_steward_recommendations_tool",
            "knowledge_steward_workbench_tool",
            "knowledge_rating_suggestion_tool",
        ],
    },
    {
        "bundleId": "coding",
        "label": "代码修改包",
        "description": "适合项目开发工作：代码定位、文件修改、静态检查、测试运行和 Git 状态检查。",
        "category": "coding",
        "toolNames": [
            "grep_search_tool",
            "glob_tool",
            "code_symbol_tool",
            "apply_diff_edit_tool",
            "apply_patch_tool",
            "python_lint_tool",
            "run_test_for_tool",
            "get_git_status_summary_tool",
            "get_recent_changes_tool",
            "explain_current_worktree_tool",
            "github_project_library_search_tool",
            "github_project_library_clone_tool",
        ],
        "preferredToolNames": [
            "grep_search_tool",
            "apply_patch_tool",
            "run_test_for_tool",
            "github_project_library_search_tool",
        ],
    },
    {
        "bundleId": "collaboration",
        "label": "团队协作工具包",
        "description": "适合多 Agent 协作：Agent 私聊/广播、派发子 Agent、提出组织结构和沟通关系调整。",
        "category": "collaboration",
        "toolNames": [
            "agent_message_tool",
            "create_child_session_tool",
            "list_child_sessions_tool",
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
            "spawn_agent_tool",
            "agent_tool_permission_request_tool",
            "research_agent_creation_proposal_tool",
            "research_communication_edge_proposal_tool",
            "research_proposal_apply_tool",
            "get_core_context_tool",
            "task_list_tool",
        ],
        "preferredToolNames": [
            "agent_message_tool",
            "create_child_session_tool",
            "list_child_sessions_tool",
            "research_agent_creation_proposal_tool",
            "agent_tool_permission_request_tool",
            "research_communication_edge_proposal_tool",
            "research_proposal_apply_tool",
        ],
    },
    {
        "bundleId": "memory_context",
        "label": "记忆平台工具包",
        "description": "适合管理长期上下文：读取核心上下文、检索记忆、压缩上下文和记录稳定经验。",
        "category": "memory",
        "toolNames": [
            "get_core_context_tool",
            "get_current_goal_tool",
            "search_memory_tool",
            "search_error_archive_tool",
            "history_search_tool",
            "history_fetch_tool",
            "history_timeline_tool",
            "history_checkpoint_tool",
            "unified_memory_search_tool",
            "skill_library_search_tool",
            "github_project_library_search_tool",
            "github_project_library_clone_tool",
            "commit_compressed_memory_tool",
            "record_learning_tool",
            "compress_context_tool",
        ],
        "preferredToolNames": [
            "get_core_context_tool",
            "unified_memory_search_tool",
            "skill_library_search_tool",
            "github_project_library_search_tool",
            "history_search_tool",
            "search_memory_tool",
        ],
    },
    {
        "bundleId": "media",
        "label": "媒体生成工具包",
        "description": "适合生成图片和媒体类产物，通常会产生模型调用成本或写入产物。",
        "category": "media",
        "toolNames": [
            "image2_generate_tool",
        ],
        "preferredToolNames": [
            "image2_generate_tool",
        ],
    },
    {
        "bundleId": "operations",
        "label": "运维诊断工具包",
        "description": "高影响工具集合：命令执行、清理、后台任务控制、进化事务和自我模型修改，需谨慎授权。",
        "category": "operations",
        "toolNames": [
            "cli_tool",
            "exec_command",
            "write_stdin",
            "cli_agent_run_tool",
            "clean_workspace_debris_tool",
            "list_workspace_debris_tool",
            "task_list_tool",
            "task_create_tool",
            "task_update_tool",
            "task_start_tool",
            "task_output_tool",
            "task_stop_tool",
            "computer_use_task_tool",
            "computer_use_session_tool",
            "plan_update_tool",
            "open_evolution_transaction_tool",
            "close_evolution_transaction_tool",
            "get_evolution_fitness_tool",
            "update_diagnosis_rules_tool",
            "update_self_model_tool",
            "record_evolution_tool",
            "trigger_self_restart_tool",
        ],
        "preferredToolNames": [
            "task_list_tool",
            "task_output_tool",
            "computer_use_task_tool",
            "computer_use_session_tool",
        ],
    },
)


def bundle_ids_for_tool(tool_name: str, *, available_tool_names: set[str] | None = None) -> list[str]:
    """Return package ids that include a tool without duplicating tool metadata."""

    normalized = str(tool_name or "").strip()
    if not normalized:
        return []
    available = set(available_tool_names or TOOL_CATALOG.keys())
    result: list[str] = []
    for bundle in list_tool_bundles(available_tool_names=available):
        if normalized in bundle["toolNames"]:
            result.append(str(bundle["bundleId"]))
    return result


def list_tool_bundles(*, available_tool_names: set[str] | None = None) -> list[dict[str, Any]]:
    """Return stable tool-package presets for configuring Agent ToolPolicy quickly."""

    available = set(available_tool_names or TOOL_CATALOG.keys())
    bundles: list[dict[str, Any]] = []
    explicit_allow_tools = explicit_allow_tool_names()
    for definition in TOOL_BUNDLE_DEFINITIONS:
        tool_names = _unique_existing_tool_names(definition.get("toolNames"), available)
        preferred_tool_names = [
            item for item in _unique_existing_tool_names(definition.get("preferredToolNames"), available) if item in tool_names
        ]
        risk_tags = sorted({tag for tool_name in tool_names for tag in risk_tags_for_tool(tool_name)})
        permission_tiers = [permission_tier_for_tool(tool_name) for tool_name in tool_names]
        high_risk_count = sum(1 for tier in permission_tiers if tier == HIGH_PERMISSION_TIER)
        explicit_allow_count = sum(1 for tool_name in tool_names if tool_name in explicit_allow_tools)
        bundles.append(
            {
                "bundleId": str(definition.get("bundleId") or "").strip(),
                "label": str(definition.get("label") or "").strip(),
                "description": str(definition.get("description") or "").strip(),
                "category": str(definition.get("category") or "").strip(),
                "toolNames": tool_names,
                "preferredToolNames": preferred_tool_names,
                "toolCount": len(tool_names),
                "preferredToolCount": len(preferred_tool_names),
                "highRiskToolCount": high_risk_count,
                "explicitAllowToolCount": explicit_allow_count,
                "riskTags": risk_tags,
            }
        )
    return [bundle for bundle in bundles if bundle["bundleId"]]


def _unique_existing_tool_names(values: Any, available: set[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for item in list(values or []):
        value = str(item or "").strip()
        if not value or value in seen or value not in available:
            continue
        result.append(value)
        seen.add(value)
    return result


def metadata_for_tool(tool_name: str, *, source: str = "built_in") -> dict[str, Any]:
    name = str(tool_name or "").strip()
    if str(source or "").strip() == "generated":
        return {
            "category": "custom_generated",
            "categoryLabel": CATEGORY_LABELS["custom_generated"],
            "capabilityTags": ["custom", "manifest"],
            "riskTags": ["custom_tool"],
            "permissionTier": GENERATED_PERMISSION_TIER,
        }
    metadata = dict(TOOL_CATALOG.get(name) or {})
    category = str(metadata.get("category") or "uncategorized")
    return {
        "category": category,
        "categoryLabel": CATEGORY_LABELS.get(category, CATEGORY_LABELS["uncategorized"]),
        "capabilityTags": list(metadata.get("capabilityTags") or []),
        "riskTags": list(metadata.get("riskTags") or []),
        "permissionTier": str(metadata.get("permissionTier") or MEDIUM_PERMISSION_TIER),
        "argDescriptors": list(metadata.get("argDescriptors") or []),
    }


def permission_tier_for_tool(tool_name: str) -> str:
    return str(metadata_for_tool(tool_name).get("permissionTier") or MEDIUM_PERMISSION_TIER)


def risk_tags_for_tool(tool_name: str) -> list[str]:
    return list(metadata_for_tool(tool_name).get("riskTags") or [])


def build_tool_descriptor(
    tool_name: str,
    *,
    args_schema: dict[str, Any],
    source: str = "built_in",
    enabled: bool = True,
    aliases: Sequence[str] = (),
    platforms: Sequence[str] = (),
    required_config: Sequence[str] = (),
) -> ToolDescriptor:
    """Build one immutable descriptor from Registry-owned catalog facts."""

    name = str(tool_name or "").strip()
    normalized_source = str(source or "").strip() or "built_in"
    if not _TOOL_ID_PATTERN.fullmatch(name):
        raise ToolDescriptorError(f"Invalid canonical tool name: {name or '<empty>'}")
    if normalized_source == "built_in" and name not in TOOL_CATALOG:
        raise ToolDescriptorError(f"Built-in tool has no catalog metadata: {name}")

    metadata = metadata_for_tool(name, source=normalized_source)
    capabilities = _normalized_descriptor_tokens(metadata.get("capabilityTags"), field="capability")
    if not capabilities:
        raise ToolDescriptorError(f"Tool descriptor has no capabilities: {name}")
    normalized_aliases = _normalized_descriptor_tokens(aliases, field="alias", pattern=_TOOL_ID_PATTERN)
    normalized_platforms = _normalized_descriptor_tokens(platforms, field="platform")
    normalized_required_config = _normalized_descriptor_tokens(required_config, field="required config")
    risk = _descriptor_risk(metadata)
    scopes = _CATEGORY_SCOPES.get(str(metadata.get("category") or ""), ("uncategorized",))
    approval: ToolApproval = "always" if risk == "destructive" else (
        "on_request" if str(metadata.get("permissionTier") or "") == HIGH_PERMISSION_TIER else "never"
    )
    concurrency: ToolConcurrency = "serialized" if risk in {"write", "execute", "destructive"} else "safe"
    descriptor = ToolDescriptor(
        name=name,
        schema_version=TOOL_DESCRIPTOR_SCHEMA_VERSION,
        schema_hash=_schema_hash(args_schema),
        enabled=bool(enabled),
        capabilities=capabilities,
        risk=risk,
        concurrency=concurrency,
        scopes=tuple(scopes),
        approval=approval,
        aliases=normalized_aliases,
        availability=ToolAvailability(
            platforms=normalized_platforms,
            required_config=normalized_required_config,
        ),
    )
    validate_tool_descriptors((descriptor,))
    return descriptor


def validate_tool_descriptors(descriptors: Sequence[ToolDescriptor]) -> tuple[ToolDescriptor, ...]:
    """Validate canonical names, aliases, capabilities, and descriptor facts."""

    ordered = tuple(sorted(descriptors, key=lambda item: item.name))
    canonical_names: set[str] = set()
    aliases: dict[str, str] = {}
    for descriptor in ordered:
        if not _TOOL_ID_PATTERN.fullmatch(descriptor.name):
            raise ToolDescriptorError(f"Invalid canonical tool name: {descriptor.name or '<empty>'}")
        if descriptor.name in canonical_names:
            raise ToolDescriptorError(f"Duplicate canonical tool name: {descriptor.name}")
        canonical_names.add(descriptor.name)
        if descriptor.schema_version != TOOL_DESCRIPTOR_SCHEMA_VERSION:
            raise ToolDescriptorError(f"Unsupported descriptor schema version for {descriptor.name}")
        if not re.fullmatch(r"[0-9a-f]{64}", descriptor.schema_hash):
            raise ToolDescriptorError(f"Invalid schema hash for {descriptor.name}")
        if not descriptor.capabilities:
            raise ToolDescriptorError(f"Tool descriptor has no capabilities: {descriptor.name}")
        for capability in descriptor.capabilities:
            if not _CAPABILITY_PATTERN.fullmatch(capability):
                raise ToolDescriptorError(f"Invalid capability `{capability}` for {descriptor.name}")
        if descriptor.risk not in _VALID_RISKS:
            raise ToolDescriptorError(f"Invalid risk classification for {descriptor.name}")
        if descriptor.concurrency not in _VALID_CONCURRENCY:
            raise ToolDescriptorError(f"Invalid concurrency classification for {descriptor.name}")
        if descriptor.approval not in _VALID_APPROVAL:
            raise ToolDescriptorError(f"Invalid approval mode for {descriptor.name}")
        if not descriptor.scopes:
            raise ToolDescriptorError(f"Tool descriptor has no scopes: {descriptor.name}")
        for alias in descriptor.aliases:
            previous = aliases.get(alias)
            if previous is not None:
                raise ToolDescriptorError(f"Duplicate tool alias `{alias}`: {previous}, {descriptor.name}")
            aliases[alias] = descriptor.name

    collisions = sorted(canonical_names.intersection(aliases))
    if collisions:
        alias = collisions[0]
        raise ToolDescriptorError(f"Tool alias collides with canonical name: {alias}")
    return ordered


def registry_descriptor_fingerprint(descriptors: Sequence[ToolDescriptor]) -> str:
    """Return a deterministic fingerprint for one validated Registry snapshot."""

    ordered = validate_tool_descriptors(descriptors)
    payload = [descriptor.public_projection() for descriptor in ordered]
    return sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _descriptor_risk(metadata: dict[str, Any]) -> ToolRisk:
    tags = {str(item or "").strip() for item in metadata.get("riskTags") or [] if str(item or "").strip()}
    if tags.intersection(_DESTRUCTIVE_RISK_TAGS):
        return "destructive"
    if tags.intersection(_EXECUTE_RISK_TAGS):
        return "execute"
    if tags.intersection(_NETWORK_RISK_TAGS):
        return "network"
    if tags.intersection(_WRITE_RISK_TAGS):
        return "write"
    return "read"


def _schema_hash(args_schema: dict[str, Any]) -> str:
    schema = args_schema if isinstance(args_schema, dict) else {}
    return sha256(_canonical_json(schema).encode("utf-8")).hexdigest()


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True)


def _normalized_descriptor_tokens(
    values: Any,
    *,
    field: str,
    pattern: re.Pattern[str] = _CAPABILITY_PATTERN,
) -> tuple[str, ...]:
    normalized = tuple(sorted({str(item or "").strip() for item in values or [] if str(item or "").strip()}))
    for value in normalized:
        if not pattern.fullmatch(value):
            raise ToolDescriptorError(f"Invalid {field}: {value}")
    return normalized
