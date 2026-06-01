"""Shared tool catalog metadata for registry, policy UI, and governance."""

from __future__ import annotations

from typing import Any


LOW_PERMISSION_TIER = "low"
MEDIUM_PERMISSION_TIER = "medium"
HIGH_PERMISSION_TIER = "high"
GENERATED_PERMISSION_TIER = "generated"
EXPLICIT_ALLOW_TOOLS = {
    "research_knowledge_query_tool",
    "research_agent_creation_proposal_tool",
    "research_communication_edge_proposal_tool",
    "knowledge_query_tool",
    "knowledge_proposal_tool",
    "knowledge_ingestion_tool",
    "knowledge_governance_tasks_tool",
    "knowledge_operations_health_tool",
    "knowledge_governance_plan_tool",
    "knowledge_steward_recommendations_tool",
    "knowledge_steward_workbench_tool",
    "knowledge_rating_suggestion_tool",
}

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
        "riskTags": [],
        "permissionTier": LOW_PERMISSION_TIER,
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
        "capabilityTags": ["symbol_index", "code_navigation"],
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
    "commit_compressed_memory_tool": {
        "category": "memory_context",
        "capabilityTags": ["memory_write", "context"],
        "riskTags": ["memory_write"],
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
        "category": "self_model",
        "capabilityTags": ["restart", "runtime_control"],
        "riskTags": ["runtime_restart"],
        "permissionTier": HIGH_PERMISSION_TIER,
    },
    "image2_generate_tool": {
        "category": "media_research",
        "capabilityTags": ["image_generation", "artifact"],
        "riskTags": ["model_cost", "artifact_write"],
        "permissionTier": HIGH_PERMISSION_TIER,
    },
    "research_knowledge_query_tool": {
        "category": "media_research",
        "capabilityTags": ["research_database", "read_only"],
        "riskTags": ["research_database_access"],
        "permissionTier": HIGH_PERMISSION_TIER,
    },
    "knowledge_query_tool": {
        "category": "memory_context",
        "capabilityTags": ["team_knowledge", "read_only"],
        "riskTags": ["team_knowledge_access"],
        "permissionTier": HIGH_PERMISSION_TIER,
    },
    "knowledge_proposal_tool": {
        "category": "memory_context",
        "capabilityTags": ["team_knowledge", "proposal_write", "source_registration"],
        "riskTags": ["team_knowledge_proposal"],
        "permissionTier": HIGH_PERMISSION_TIER,
    },
    "knowledge_ingestion_tool": {
        "category": "memory_context",
        "capabilityTags": ["team_knowledge", "ingestion_package", "source_registration"],
        "riskTags": ["team_knowledge_proposal"],
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
}

TOOL_BUNDLE_DEFINITIONS: tuple[dict[str, Any], ...] = (
    {
        "bundleId": "core",
        "label": "Core tools",
        "description": "Essential low-risk tools for reading workspace context, tracking goals, and inspecting current state.",
        "category": "core",
        "toolNames": [
            "grep_search_tool",
            "glob_tool",
            "read_file_tool",
            "get_core_context_tool",
            "get_current_goal_tool",
            "task_list_tool",
            "get_git_status_summary_tool",
            "get_recent_changes_tool",
        ],
        "preferredToolNames": [
            "grep_search_tool",
            "read_file_tool",
            "get_core_context_tool",
        ],
    },
    {
        "bundleId": "research",
        "label": "Research toolkit",
        "description": "Tools for web research, evidence lookup, research knowledge access, and research-oriented workspace reading.",
        "category": "research",
        "toolNames": [
            "grep_search_tool",
            "glob_tool",
            "read_file_tool",
            "web_search_tool",
            "web_fetch_tool",
            "research_knowledge_query_tool",
            "knowledge_query_tool",
            "knowledge_proposal_tool",
            "knowledge_ingestion_tool",
            "knowledge_governance_tasks_tool",
            "knowledge_steward_recommendations_tool",
            "knowledge_steward_workbench_tool",
            "knowledge_rating_suggestion_tool",
            "get_session_files_tool",
        ],
        "preferredToolNames": [
            "web_search_tool",
            "web_fetch_tool",
            "research_knowledge_query_tool",
            "knowledge_query_tool",
            "knowledge_governance_tasks_tool",
            "knowledge_steward_recommendations_tool",
            "knowledge_steward_workbench_tool",
            "knowledge_rating_suggestion_tool",
        ],
    },
    {
        "bundleId": "coding",
        "label": "Coding toolkit",
        "description": "Tools for code navigation, editing, linting, testing, and Git state inspection.",
        "category": "coding",
        "toolNames": [
            "grep_search_tool",
            "glob_tool",
            "read_file_tool",
            "code_symbol_tool",
            "apply_diff_edit_tool",
            "apply_patch_tool",
            "python_lint_tool",
            "run_test_for_tool",
            "get_git_status_summary_tool",
            "get_recent_changes_tool",
            "explain_current_worktree_tool",
        ],
        "preferredToolNames": [
            "grep_search_tool",
            "read_file_tool",
            "apply_patch_tool",
            "run_test_for_tool",
        ],
    },
    {
        "bundleId": "collaboration",
        "label": "Collaboration toolkit",
        "description": "Tools for Agent-to-Agent messaging, delegation, and controlled organization governance requests.",
        "category": "collaboration",
        "toolNames": [
            "agent_message_tool",
            "spawn_agent_tool",
            "agent_tool_permission_request_tool",
            "research_agent_creation_proposal_tool",
            "research_communication_edge_proposal_tool",
            "get_core_context_tool",
            "task_list_tool",
        ],
        "preferredToolNames": [
            "agent_message_tool",
            "research_agent_creation_proposal_tool",
            "agent_tool_permission_request_tool",
            "research_communication_edge_proposal_tool",
        ],
    },
    {
        "bundleId": "memory_context",
        "label": "Memory and context toolkit",
        "description": "Tools for reading context, searching memory, compacting context, and recording durable learning.",
        "category": "memory",
        "toolNames": [
            "get_core_context_tool",
            "get_current_goal_tool",
            "search_memory_tool",
            "search_error_archive_tool",
            "commit_compressed_memory_tool",
            "record_learning_tool",
            "compress_context_tool",
        ],
        "preferredToolNames": [
            "get_core_context_tool",
            "search_memory_tool",
        ],
    },
    {
        "bundleId": "media",
        "label": "Media toolkit",
        "description": "Tools for generated images and media-oriented research artifacts.",
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
        "label": "Operations toolkit",
        "description": "High-impact runtime, shell, cleanup, task control, evolution, and self-model mutation tools.",
        "category": "operations",
        "toolNames": [
            "cli_tool",
            "clean_workspace_debris_tool",
            "list_workspace_debris_tool",
            "task_list_tool",
            "task_create_tool",
            "task_update_tool",
            "task_start_tool",
            "task_output_tool",
            "task_stop_tool",
            "plan_update_tool",
            "open_evolution_transaction_tool",
            "close_evolution_transaction_tool",
            "update_diagnosis_rules_tool",
            "update_self_model_tool",
            "record_evolution_tool",
            "trigger_self_restart_tool",
        ],
        "preferredToolNames": [
            "task_list_tool",
            "task_output_tool",
        ],
    },
)


def list_tool_bundles(*, available_tool_names: set[str] | None = None) -> list[dict[str, Any]]:
    """Return stable tool-package presets for configuring Agent ToolPolicy quickly."""

    available = set(available_tool_names or TOOL_CATALOG.keys())
    bundles: list[dict[str, Any]] = []
    for definition in TOOL_BUNDLE_DEFINITIONS:
        tool_names = _unique_existing_tool_names(definition.get("toolNames"), available)
        preferred_tool_names = [
            item for item in _unique_existing_tool_names(definition.get("preferredToolNames"), available) if item in tool_names
        ]
        risk_tags = sorted({tag for tool_name in tool_names for tag in risk_tags_for_tool(tool_name)})
        permission_tiers = [permission_tier_for_tool(tool_name) for tool_name in tool_names]
        high_risk_count = sum(1 for tier in permission_tiers if tier == HIGH_PERMISSION_TIER)
        explicit_allow_count = sum(1 for tool_name in tool_names if tool_name in EXPLICIT_ALLOW_TOOLS)
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
    return [bundle for bundle in bundles if bundle["bundleId"] and bundle["toolNames"]]


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
    }


def permission_tier_for_tool(tool_name: str) -> str:
    return str(metadata_for_tool(tool_name).get("permissionTier") or MEDIUM_PERMISSION_TIER)


def risk_tags_for_tool(tool_name: str) -> list[str]:
    return list(metadata_for_tool(tool_name).get("riskTags") or [])
