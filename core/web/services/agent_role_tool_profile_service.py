"""Single source of truth for fixed-role Agent tool profiles."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any


ROLE_TOOL_PROFILE_VERSION = 1

FORMAL_KNOWLEDGE_WRITE_TOOLS = (
    "knowledge_proposal_tool",
    "knowledge_ingestion_tool",
)
KNOWLEDGE_GOVERNANCE_TOOLS = (
    "knowledge_governance_tasks_tool",
    "knowledge_operations_health_tool",
    "knowledge_governance_plan_tool",
    "knowledge_steward_recommendations_tool",
    "knowledge_steward_workbench_tool",
    "knowledge_rating_suggestion_tool",
)
KNOWLEDGE_STEWARD_TOOLS = FORMAL_KNOWLEDGE_WRITE_TOOLS + KNOWLEDGE_GOVERNANCE_TOOLS
SEARCH_DISABLED_TOOLS = ("web_search_tool",)
CODE_MUTATION_TOOLS = (
    "cli_tool",
    "cli_agent_run_tool",
    "apply_patch_tool",
    "write_file_tool",
    "run_test_for_tool",
    "commit_changes_tool",
)
RESEARCH_FORBIDDEN_TOOLS = KNOWLEDGE_STEWARD_TOOLS

RESEARCH_STAGE_TOOLS = (
    "agent_message_tool",
    "research_knowledge_query_tool",
    "task_create_tool",
    "task_update_tool",
    "source_collection_context_tool",
    "source_collection_stage_writeback_tool",
)
SEARCH_TOOLS = (
    "batch_web_search_tool",
    "paper_search_tool",
    "project_search_tool",
    "news_search_tool",
    "search_summarize_sources_tool",
)
FETCH_TOOLS = ("web_fetch_tool",)
RESEARCH_GOVERNANCE_TOOLS = (
    "agent_message_tool",
    "research_agent_creation_proposal_tool",
    "research_communication_edge_proposal_tool",
    "research_proposal_apply_tool",
)
CHALLENGE_CUP_EXPERIMENT_TOOLS = (
    "agent_message_tool",
    "research_knowledge_query_tool",
    "challenge_cup_experiment_context_tool",
    "challenge_cup_experiment_writeback_tool",
)
CHALLENGE_CUP_ITERATION_TOOLS = (
    "agent_message_tool",
    "research_knowledge_query_tool",
    "challenge_cup_iteration_context_tool",
    "challenge_cup_iteration_writeback_tool",
)
CHALLENGE_CUP_VERSIONING_TOOLS = (
    "agent_message_tool",
    "research_knowledge_query_tool",
    "challenge_cup_versioning_context_tool",
    "challenge_cup_versioning_writeback_tool",
)
CHALLENGE_CUP_OPERATION_FORBIDDEN_TOOLS = (
    *RESEARCH_FORBIDDEN_TOOLS,
    *SEARCH_DISABLED_TOOLS,
    *CODE_MUTATION_TOOLS,
    *SEARCH_TOOLS,
    *FETCH_TOOLS,
)


def _unique(values: Any) -> tuple[str, ...]:
    result: list[str] = []
    seen: set[str] = set()
    raw_values = [values] if isinstance(values, str) else list(values or [])
    for item in raw_values:
        value = str(item or "").strip()
        if not value or value in seen:
            continue
        result.append(value)
        seen.add(value)
    return tuple(result)


def role_tool_profile_fingerprint(profile: dict[str, Any]) -> str:
    relevant = {
        key: profile.get(key)
        for key in (
            "profileId",
            "profileVersion",
            "allowedTools",
            "preferredTools",
            "forbiddenTools",
            "readScopes",
            "writeScopes",
            "networkAccess",
            "mutationAccess",
            "maxCallsPerTurn",
        )
    }
    data = json.dumps(relevant, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(data.encode("utf-8")).hexdigest()[:16]


def _profile(
    profile_id: str,
    *,
    allowed_tools: Any,
    preferred_tools: Any | None = None,
    forbidden_tools: Any = (),
    read_scopes: Any = ("private", "shared"),
    write_scopes: Any = (),
    network_access: str = "controlled",
    mutation_access: str = "none",
    max_calls_per_turn: int = 8,
    role_family: str = "research",
    description: str = "",
) -> dict[str, Any]:
    allowed = _unique(allowed_tools)
    preferred = tuple(tool for tool in _unique(preferred_tools or allowed) if tool in allowed)
    payload = {
        "profileId": str(profile_id or "").strip(),
        "profileVersion": ROLE_TOOL_PROFILE_VERSION,
        "roleFamily": str(role_family or "").strip(),
        "description": str(description or "").strip(),
        "allowedTools": list(allowed),
        "preferredTools": list(preferred),
        "forbiddenTools": list(_unique(forbidden_tools)),
        "readScopes": list(_unique(read_scopes)),
        "writeScopes": list(_unique(write_scopes)),
        "networkAccess": str(network_access or "inherit").strip(),
        "mutationAccess": str(mutation_access or "inherit").strip(),
        "maxCallsPerTurn": max(0, int(max_calls_per_turn or 0)),
    }
    payload["profileFingerprint"] = role_tool_profile_fingerprint(payload)
    return payload


ROLE_TOOL_PROFILES: dict[str, dict[str, Any]] = {
    "ai_search_scope_lead": _profile(
        "ai_search_scope_lead",
        allowed_tools=(
            "agent_message_tool",
            "research_knowledge_query_tool",
            "batch_web_search_tool",
            "paper_search_tool",
            "project_search_tool",
            "news_search_tool",
            "search_summarize_sources_tool",
            "search_memory_tool",
        ),
        preferred_tools=(
            "research_knowledge_query_tool",
            "batch_web_search_tool",
            "paper_search_tool",
            "search_summarize_sources_tool",
            "agent_message_tool",
        ),
        forbidden_tools=(*RESEARCH_FORBIDDEN_TOOLS, *SEARCH_DISABLED_TOOLS),
        description="Coordinate AI search source scope and quality gates without code or knowledge writes.",
    ),
    "global_primary_sources": _profile(
        "global_primary_sources",
        allowed_tools=(
            "agent_message_tool",
            "research_knowledge_query_tool",
            "web_fetch_tool",
            "batch_web_search_tool",
            "paper_search_tool",
            "project_search_tool",
            "search_summarize_sources_tool",
            "search_memory_tool",
        ),
        preferred_tools=(
            "research_knowledge_query_tool",
            "batch_web_search_tool",
            "paper_search_tool",
            "web_fetch_tool",
            "search_summarize_sources_tool",
            "agent_message_tool",
        ),
        forbidden_tools=(*RESEARCH_FORBIDDEN_TOOLS, *SEARCH_DISABLED_TOOLS),
        description="Find global first-party AI sources and verify primary evidence.",
    ),
    "cn_primary_sources": _profile(
        "cn_primary_sources",
        allowed_tools=(
            "agent_message_tool",
            "research_knowledge_query_tool",
            "web_fetch_tool",
            "batch_web_search_tool",
            "project_search_tool",
            "news_search_tool",
            "search_summarize_sources_tool",
            "search_memory_tool",
        ),
        preferred_tools=(
            "research_knowledge_query_tool",
            "batch_web_search_tool",
            "news_search_tool",
            "web_fetch_tool",
            "search_summarize_sources_tool",
            "agent_message_tool",
        ),
        forbidden_tools=(*RESEARCH_FORBIDDEN_TOOLS, *SEARCH_DISABLED_TOOLS),
        description="Find Chinese first-party AI sources and verify entity/source ownership.",
    ),
    "signal_quality_gate": _profile(
        "signal_quality_gate",
        allowed_tools=(
            "agent_message_tool",
            "research_knowledge_query_tool",
            "web_fetch_tool",
            "batch_web_search_tool",
            "paper_search_tool",
            "project_search_tool",
            "news_search_tool",
            "search_summarize_sources_tool",
            "search_memory_tool",
        ),
        preferred_tools=(
            "research_knowledge_query_tool",
            "web_fetch_tool",
            "search_summarize_sources_tool",
            "batch_web_search_tool",
            "agent_message_tool",
        ),
        forbidden_tools=(*RESEARCH_FORBIDDEN_TOOLS, *SEARCH_DISABLED_TOOLS),
        description="Review AI search signals and reject low-quality or non-primary evidence.",
    ),
    "research_source_default": _profile(
        "research_source_default",
        allowed_tools=(
            "agent_message_tool",
            "research_knowledge_query_tool",
            "web_fetch_tool",
            *SEARCH_TOOLS,
            "search_memory_tool",
        ),
        preferred_tools=(
            "research_knowledge_query_tool",
            "batch_web_search_tool",
            "paper_search_tool",
            "search_summarize_sources_tool",
            "agent_message_tool",
        ),
        forbidden_tools=(*RESEARCH_FORBIDDEN_TOOLS, *SEARCH_DISABLED_TOOLS),
    ),
    "research_role_default": _profile(
        "research_role_default",
        allowed_tools=(
            "agent_message_tool",
            "research_knowledge_query_tool",
            "batch_web_search_tool",
            "paper_search_tool",
            "web_fetch_tool",
            "search_summarize_sources_tool",
        ),
        preferred_tools=(
            "agent_message_tool",
            "batch_web_search_tool",
            "paper_search_tool",
            "web_fetch_tool",
            "research_knowledge_query_tool",
        ),
        forbidden_tools=(*RESEARCH_FORBIDDEN_TOOLS, *SEARCH_DISABLED_TOOLS),
    ),
    "source_finder": _profile(
        "source_finder",
        allowed_tools=(*RESEARCH_STAGE_TOOLS, *SEARCH_TOOLS, *FETCH_TOOLS),
        preferred_tools=(
            "source_collection_context_tool",
            "source_collection_stage_writeback_tool",
            "batch_web_search_tool",
            "paper_search_tool",
            "project_search_tool",
            "search_summarize_sources_tool",
            "web_fetch_tool",
            "agent_message_tool",
        ),
        forbidden_tools=(*RESEARCH_FORBIDDEN_TOOLS, *SEARCH_DISABLED_TOOLS),
        description="Find, fetch, download, and register traceable source records for a source collection run.",
    ),
    "source_extractor": _profile(
        "source_extractor",
        allowed_tools=(*RESEARCH_STAGE_TOOLS, *FETCH_TOOLS, "search_summarize_sources_tool"),
        preferred_tools=(
            "source_collection_context_tool",
            "source_collection_stage_writeback_tool",
            "web_fetch_tool",
            "search_summarize_sources_tool",
            "research_knowledge_query_tool",
            "agent_message_tool",
        ),
        forbidden_tools=(
            *RESEARCH_FORBIDDEN_TOOLS,
            "batch_web_search_tool",
            "paper_search_tool",
            "project_search_tool",
            "news_search_tool",
            *SEARCH_DISABLED_TOOLS,
        ),
        description="Extract useful source content and make source-quality decisions in one pass.",
    ),
    "source_relation_mapper": _profile(
        "source_relation_mapper",
        allowed_tools=RESEARCH_STAGE_TOOLS,
        preferred_tools=(
            "source_collection_context_tool",
            "source_collection_stage_writeback_tool",
            "research_knowledge_query_tool",
            "agent_message_tool",
        ),
        forbidden_tools=(*RESEARCH_FORBIDDEN_TOOLS, *SEARCH_TOOLS, *FETCH_TOOLS, *SEARCH_DISABLED_TOOLS),
        network_access="none",
        description="Build candidate-only topic, source, and evidence relationships without writing the official graph.",
    ),
    "source_ingestor": _profile(
        "source_ingestor",
        allowed_tools=(
            "agent_message_tool",
            "task_create_tool",
            "task_update_tool",
            "source_collection_context_tool",
            "source_collection_stage_writeback_tool",
            *KNOWLEDGE_STEWARD_TOOLS,
        ),
        preferred_tools=(
            "task_create_tool",
            "task_update_tool",
            "source_collection_context_tool",
            "source_collection_stage_writeback_tool",
            "knowledge_governance_tasks_tool",
            "knowledge_operations_health_tool",
            "knowledge_governance_plan_tool",
            "knowledge_proposal_tool",
            "knowledge_ingestion_tool",
        ),
        forbidden_tools=(*SEARCH_TOOLS, *FETCH_TOOLS, *SEARCH_DISABLED_TOOLS),
        write_scopes=("private",),
        network_access="none",
        mutation_access="restricted",
        max_calls_per_turn=12,
        role_family="knowledge",
        description="Perform governed final source review and formal Team Knowledge ingestion.",
    ),
    "challenge_cup_coordinator": _profile(
        "challenge_cup_coordinator",
        allowed_tools=(
            "agent_message_tool",
            "research_knowledge_query_tool",
            "source_collection_context_tool",
            "challenge_cup_experiment_context_tool",
            "challenge_cup_iteration_context_tool",
            "challenge_cup_versioning_context_tool",
        ),
        preferred_tools=(
            "agent_message_tool",
            "research_knowledge_query_tool",
            "source_collection_context_tool",
            "challenge_cup_experiment_context_tool",
            "challenge_cup_iteration_context_tool",
            "challenge_cup_versioning_context_tool",
        ),
        forbidden_tools=CHALLENGE_CUP_OPERATION_FORBIDDEN_TOOLS,
        network_access="none",
        mutation_access="none",
        description="Coordinate Challenge Cup stages with read-only context tools and Agent messaging.",
    ),
    "challenge_cup_experiment_planner": _profile(
        "challenge_cup_experiment_planner",
        allowed_tools=CHALLENGE_CUP_EXPERIMENT_TOOLS,
        preferred_tools=(
            "challenge_cup_experiment_context_tool",
            "challenge_cup_experiment_writeback_tool",
            "research_knowledge_query_tool",
            "agent_message_tool",
        ),
        forbidden_tools=CHALLENGE_CUP_OPERATION_FORBIDDEN_TOOLS,
        write_scopes=("team_workflow_ledger",),
        network_access="none",
        mutation_access="restricted",
        max_calls_per_turn=8,
    ),
    "challenge_cup_experiment_ledger": _profile(
        "challenge_cup_experiment_ledger",
        allowed_tools=CHALLENGE_CUP_EXPERIMENT_TOOLS,
        preferred_tools=(
            "challenge_cup_experiment_context_tool",
            "challenge_cup_experiment_writeback_tool",
            "research_knowledge_query_tool",
            "agent_message_tool",
        ),
        forbidden_tools=CHALLENGE_CUP_OPERATION_FORBIDDEN_TOOLS,
        write_scopes=("team_workflow_ledger",),
        network_access="none",
        mutation_access="restricted",
        max_calls_per_turn=8,
    ),
    "challenge_cup_iteration_planner": _profile(
        "challenge_cup_iteration_planner",
        allowed_tools=(*CHALLENGE_CUP_ITERATION_TOOLS, "challenge_cup_experiment_context_tool"),
        preferred_tools=(
            "challenge_cup_iteration_context_tool",
            "challenge_cup_iteration_writeback_tool",
            "challenge_cup_experiment_context_tool",
            "research_knowledge_query_tool",
            "agent_message_tool",
        ),
        forbidden_tools=CHALLENGE_CUP_OPERATION_FORBIDDEN_TOOLS,
        write_scopes=("team_workflow_ledger",),
        network_access="none",
        mutation_access="restricted",
        max_calls_per_turn=8,
    ),
    "challenge_cup_versioning": _profile(
        "challenge_cup_versioning",
        allowed_tools=(*CHALLENGE_CUP_VERSIONING_TOOLS, "challenge_cup_iteration_context_tool"),
        preferred_tools=(
            "challenge_cup_versioning_context_tool",
            "challenge_cup_versioning_writeback_tool",
            "challenge_cup_iteration_context_tool",
            "research_knowledge_query_tool",
            "agent_message_tool",
        ),
        forbidden_tools=CHALLENGE_CUP_OPERATION_FORBIDDEN_TOOLS,
        write_scopes=("team_workflow_ledger",),
        network_access="none",
        mutation_access="restricted",
        max_calls_per_turn=8,
    ),
    "research_paper_reader": _profile(
        "research_paper_reader",
        allowed_tools=(
            "agent_message_tool",
            "research_knowledge_query_tool",
            "web_fetch_tool",
            "batch_web_search_tool",
            "paper_search_tool",
            "search_summarize_sources_tool",
        ),
        preferred_tools=(
            "research_knowledge_query_tool",
            "paper_search_tool",
            "web_fetch_tool",
            "search_summarize_sources_tool",
            "agent_message_tool",
        ),
        forbidden_tools=(*RESEARCH_FORBIDDEN_TOOLS, *SEARCH_DISABLED_TOOLS),
    ),
    "knowledge_steward": _profile(
        "knowledge_steward",
        allowed_tools=(
            "agent_message_tool",
            "source_collection_context_tool",
            "source_collection_stage_writeback_tool",
            "skill_library_search_tool",
            "unified_memory_search_tool",
            *KNOWLEDGE_STEWARD_TOOLS,
        ),
        preferred_tools=(
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
        ),
        forbidden_tools=SEARCH_DISABLED_TOOLS,
        write_scopes=("private",),
        network_access="none",
        mutation_access="restricted",
        max_calls_per_turn=12,
        role_family="knowledge",
    ),
    "research_org_ceo": _profile(
        "research_org_ceo",
        allowed_tools=(*RESEARCH_GOVERNANCE_TOOLS, "batch_web_search_tool", "paper_search_tool", "web_fetch_tool"),
        preferred_tools=("agent_message_tool", "research_agent_creation_proposal_tool", "research_proposal_apply_tool"),
        forbidden_tools=(*FORMAL_KNOWLEDGE_WRITE_TOOLS, *SEARCH_DISABLED_TOOLS),
        mutation_access="restricted",
        role_family="research_governance",
    ),
    "research_org_organization_advisor": _profile(
        "research_org_organization_advisor",
        allowed_tools=(
            "agent_message_tool",
            "agent_tool_permission_request_tool",
            "research_agent_creation_proposal_tool",
            "research_communication_edge_proposal_tool",
            "research_proposal_apply_tool",
            "batch_web_search_tool",
            "paper_search_tool",
            "web_fetch_tool",
        ),
        preferred_tools=("agent_message_tool", "research_agent_creation_proposal_tool", "research_communication_edge_proposal_tool"),
        forbidden_tools=(*FORMAL_KNOWLEDGE_WRITE_TOOLS, *SEARCH_DISABLED_TOOLS),
        mutation_access="restricted",
        role_family="research_governance",
    ),
    "research_org_capability_steward": _profile(
        "research_org_capability_steward",
        allowed_tools=(
            "agent_message_tool",
            "agent_tool_permission_request_tool",
            "research_agent_creation_proposal_tool",
            "research_communication_edge_proposal_tool",
            "research_proposal_apply_tool",
            "batch_web_search_tool",
            "paper_search_tool",
            "web_fetch_tool",
            "read_memory_tool",
            "get_memory_summary_tool",
            "search_memory_tool",
            "read_dynamic_prompt_tool",
            "research_knowledge_query_tool",
        ),
        preferred_tools=("agent_message_tool", "agent_tool_permission_request_tool", "research_knowledge_query_tool"),
        forbidden_tools=(*FORMAL_KNOWLEDGE_WRITE_TOOLS, *SEARCH_DISABLED_TOOLS),
        mutation_access="restricted",
        role_family="research_governance",
    ),
}

RESEARCH_SOURCE_ROLE_KEYS = {
    "source_finder",
    "source_extractor",
    "source_relation_mapper",
    "source_ingestor",
}
RETIRED_SOURCE_COLLECTION_ROLE_KEYS = {
    "data_discovery",
    "source_acquisition",
    "source_intake",
    "content_extraction",
    "source_quality",
    "candidate_graph",
    "challenge_cup_data_discovery",
    "challenge_cup_source_acquisition",
    "challenge_cup_content_extraction",
    "challenge_cup_source_quality",
    "knowledge_expansion_source_intake",
    "knowledge_expansion_content_extraction",
    "knowledge_expansion_source_quality",
    "knowledge_expansion_candidate_graph",
}

def normalize_role_key(value: Any) -> str:
    return re.sub(r"[^a-z0-9_]+", "_", str(value or "").strip().lower()).strip("_")


def get_role_tool_profile(profile_id: str) -> dict[str, Any] | None:
    profile = ROLE_TOOL_PROFILES.get(str(profile_id or "").strip())
    return dict(profile) if isinstance(profile, dict) else None


def role_tool_profile_for_role(role_key: str, *, primary_mode: str = "", metadata: dict[str, Any] | None = None) -> dict[str, Any] | None:
    normalized_role = normalize_role_key(role_key)
    normalized_mode = normalize_role_key(primary_mode)
    raw_metadata = metadata if isinstance(metadata, dict) else {}
    research_org_role = normalize_role_key(raw_metadata.get("researchOrgRole") or raw_metadata.get("systemRole") or "")
    if normalized_role in RETIRED_SOURCE_COLLECTION_ROLE_KEYS:
        return None
    if normalized_role == "knowledge_steward" or research_org_role == "knowledge_steward":
        return get_role_tool_profile("knowledge_steward")
    if research_org_role in {"ceo", "organization_advisor", "capability_steward"}:
        return get_role_tool_profile(f"research_org_{research_org_role}")
    if normalized_role in ROLE_TOOL_PROFILES:
        return get_role_tool_profile(normalized_role)
    if normalized_mode == "research" and normalized_role in RESEARCH_SOURCE_ROLE_KEYS:
        return get_role_tool_profile("research_source_default")
    if normalized_mode == "research":
        return get_role_tool_profile("research_role_default")
    return None


def build_policy_from_role_profile(profile: dict[str, Any], policy_id: str) -> dict[str, Any]:
    return {
        "policyId": str(policy_id or "").strip(),
        "allowedTools": list(profile.get("allowedTools") or []),
        "preferredTools": list(profile.get("preferredTools") or []),
        "blockedTools": [],
        "readScopes": list(profile.get("readScopes") or []),
        "writeScopes": list(profile.get("writeScopes") or []),
        "allowedCommandKinds": [],
        "blockedCommandPatterns": [],
        "networkAccess": str(profile.get("networkAccess") or "inherit"),
        "mutationAccess": str(profile.get("mutationAccess") or "inherit"),
        "maxCallsPerTurn": max(0, int(profile.get("maxCallsPerTurn") or 0)),
        "perToolRules": {},
        "roleToolProfileId": str(profile.get("profileId") or "").strip(),
        "roleToolProfileVersion": int(profile.get("profileVersion") or ROLE_TOOL_PROFILE_VERSION),
        "roleToolProfileFingerprint": str(profile.get("profileFingerprint") or role_tool_profile_fingerprint(profile)),
    }


def resolve_role_tool_policy(
    *,
    role_key: str,
    primary_mode: str = "",
    metadata: dict[str, Any] | None = None,
    policy_id: str,
) -> dict[str, Any] | None:
    profile = role_tool_profile_for_role(role_key, primary_mode=primary_mode, metadata=metadata)
    if not profile:
        return None
    return build_policy_from_role_profile(profile, policy_id)


def forbidden_tools_for_role(
    role_key: str,
    *,
    primary_mode: str = "",
    metadata: dict[str, Any] | None = None,
) -> list[str]:
    profile = role_tool_profile_for_role(role_key, primary_mode=primary_mode, metadata=metadata)
    if not profile:
        return []
    return list(profile.get("forbiddenTools") or [])


def role_forbids_tool(
    role_key: str,
    tool_name: str,
    *,
    primary_mode: str = "",
    metadata: dict[str, Any] | None = None,
) -> bool:
    normalized_tool = str(tool_name or "").strip()
    if not normalized_tool:
        return False
    return normalized_tool in set(forbidden_tools_for_role(role_key, primary_mode=primary_mode, metadata=metadata))
