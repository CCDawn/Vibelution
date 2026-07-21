"""Agent directory policy normalize / evaluate / resolve helpers.

Claim scope: tool, memory, delegation, supervision, visibility, and
context-compression policy contracts. Registry IO stays on the facade.

Late-bound facade keeps monkeypatches stable.
"""

from __future__ import annotations

from typing import Any, Iterable

# Local default for signature evaluation (facade remains SSOT).
DEFAULT_TOOL_POLICY_ID = "default"


def _service():
    from core.web.services import agent_directory_service

    return agent_directory_service


def _context_compression_base_policy_for_agents() -> Any:
    s = _service()
    try:
        from config import get_config

        return get_config().context_compression
    except Exception:
        return {}


def _context_compression_policy_from_config(base_policy: Any, *, context_window_limit: int = 0) -> dict[str, Any]:
    s = _service()
    if base_policy is None:
        try:
            from config import get_config

            base_policy = get_config().context_compression
        except Exception:
            base_policy = {}
    effective_limit = s._positive_context_compression_int(
        s._get_config_value(base_policy, "max_token_limit", "maxTokenLimit"),
        default=16_000,
        maximum=2_000_000,
    )
    context_window = s._positive_context_compression_int(
        context_window_limit,
        default=effective_limit,
        maximum=2_000_000,
    )
    effective_token_limit = min(effective_limit, context_window) if context_window > 0 else effective_limit
    return {
        "mode": "inherit",
        "source": "global",
        "enabled": bool(s._get_config_value(base_policy, "enabled", default=True)),
        "maxTokenLimit": effective_limit,
        "effectiveTokenLimit": effective_token_limit,
        "compressionTriggerTokenLimit": effective_token_limit,
        "contextWindowLimit": context_window,
        "modelContextWindowLimit": context_window,
        "maxCompressionsPerSession": s._positive_context_compression_int(
            s._get_config_value(base_policy, "max_compressions_per_session", "maxCompressionsPerSession"),
            default=20,
            maximum=100,
        ),
        "levels": s._normalize_context_compression_levels(s._get_config_value(base_policy, "levels", default={})),
        "summaryChars": s._normalize_context_compression_summary_chars(
            s._get_config_value(base_policy, "summary_chars", "summaryChars", default={})
        ),
        "preservation": s._normalize_context_compression_preservation(
            s._get_config_value(base_policy, "preservation", default={})
        ),
    }


def _context_compression_ratio(value: Any, default: float) -> float:
    s = _service()
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = default
    return max(0.0, min(1.0, parsed))


def _conversation_index_visibility_for_kind(kind: str) -> str:
    s = _service()
    if kind == s.CONVERSATION_INDEX_KIND_TEAM_AGENT:
        return s.CONVERSATION_INDEX_VISIBILITY_TEAM_PRIVATE
    if kind == s.CONVERSATION_INDEX_KIND_HIDDEN:
        return s.CONVERSATION_INDEX_VISIBILITY_HIDDEN
    return s.CONVERSATION_INDEX_VISIBILITY_USER_VISIBLE


def _count_policy_refs(agents: list[dict[str, Any]], field: str, policy_id: str) -> int:
    s = _service()
    return sum(1 for agent in agents if str(agent.get(field) or "").strip() == policy_id)


def _default_tool_policy_for_agent(policy_id: str, primary_mode: str, *, role_key: str = "") -> dict[str, Any]:
    s = _service()
    normalized_mode = s._normalize_primary_mode(primary_mode)
    if s._is_session_agent_primary_mode(normalized_mode):
        return s.default_session_agent_tool_policy(policy_id)
    if normalized_mode == "research":
        return s.default_research_role_tool_policy(policy_id, role_key=role_key)
    return s.default_tool_policy(policy_id)


def _default_tool_policy_id_for_agent(agent_id: str, primary_mode: str) -> str:
    s = _service()
    normalized_mode = s._normalize_primary_mode(primary_mode)
    if s._is_session_agent_primary_mode(normalized_mode) or normalized_mode == "research":
        return f"tool-{agent_id}"
    return s.DEFAULT_TOOL_POLICY_ID


def _direct_session_visibility(
    session_id: str,
    *,
    session_workspace_path: str = "",
) -> str:
    s = _service()
    normalized_session_id = str(session_id or "").strip()
    if not normalized_session_id:
        return s.SESSION_AGENT_VISIBILITY_NONE
    if s._session_workspace_has_activity(normalized_session_id, session_workspace_path=session_workspace_path):
        return s.SESSION_AGENT_VISIBILITY_ACTIVE
    return s.SESSION_AGENT_VISIBILITY_PENDING


def _effective_agent_tool_policy(policy: dict[str, Any], delegation_policy: dict[str, Any] | None) -> dict[str, Any]:
    s = _service()
    return s._without_disabled_agent_tools(s._without_subagent_delegation_tools(policy, delegation_policy))


def _ensure_fixed_role_tool_policy(
    state: dict[str, Any],
    agent: dict[str, Any],
    *,
    normalized_tool_policies: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    s = _service()
    desired_kind = s._fixed_role_tool_policy_kind(agent)
    if not desired_kind:
        return None
    agent_id = str(agent.get("agentId") or "").strip()
    if not agent_id:
        return None
    role_key = s._normalize_role_key(agent.get("roleKey") or s._infer_agent_role_key(agent))
    if agent_id == s.KNOWLEDGE_STEWARD_AGENT_ID or role_key == s.KNOWLEDGE_STEWARD_ROLE_KEY:
        policy_id = s.KNOWLEDGE_STEWARD_TOOL_POLICY_ID
    else:
        policy_id = f"tool-{agent_id}"
    policies = normalized_tool_policies if normalized_tool_policies is not None else s._tool_policies(state)
    if desired_kind == "research_source":
        desired_policy = s.default_research_source_tool_policy(policy_id, role_key=str(agent.get("roleKey") or ""))
    elif desired_kind == "research_role":
        desired_policy = s.default_research_role_tool_policy(policy_id, role_key=str(agent.get("roleKey") or ""))
    elif desired_kind == "self_evolution_executable":
        desired_policy = s.default_self_evolution_executable_tool_policy(policy_id)
    elif desired_kind == "role_profile":
        metadata = agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}
        desired_policy = s.agent_role_tool_profile_service.resolve_role_tool_policy(
            role_key=str(agent.get("roleKey") or ""),
            primary_mode=str(agent.get("primaryMode") or ""),
            metadata=metadata,
            policy_id=policy_id,
        ) or s.default_research_role_tool_policy(policy_id, role_key=str(agent.get("roleKey") or ""))
    else:
        desired_policy = s.default_system_no_tool_policy(policy_id)
    current_policy_id = str(agent.get("toolPolicyId") or s.DEFAULT_TOOL_POLICY_ID).strip() or s.DEFAULT_TOOL_POLICY_ID
    current_policy = s.normalize_tool_policy(policies.get(current_policy_id) or s.default_tool_policy(current_policy_id), current_policy_id)
    versioned_runtime_overrides: dict[str, Any] = {}
    if int(current_policy.get("policyVersion") or 1) > int(desired_policy.get("policyVersion") or 1):
        versioned_runtime_overrides = {
            "maxCallsPerTurn": int(current_policy.get("maxCallsPerTurn") or 0),
            "policyVersion": int(current_policy.get("policyVersion") or 1),
        }
    next_policy = s.normalize_tool_policy(
        {
            **desired_policy,
            **versioned_runtime_overrides,
            "perToolRules": dict(current_policy.get("perToolRules") or {}),
        },
        policy_id,
    )
    if current_policy_id == policy_id and policies.get(policy_id) == next_policy:
        return None
    previous_policy_id = current_policy_id
    policies[policy_id] = next_policy
    previous_policy_is_orphaned = (
        previous_policy_id != s.DEFAULT_TOOL_POLICY_ID
        and previous_policy_id != policy_id
        and s._count_policy_refs(state.get("agents") or [], "toolPolicyId", previous_policy_id) == 1
    )
    if previous_policy_is_orphaned:
        policies.pop(previous_policy_id, None)
    state["toolPolicies"] = policies
    agent["toolPolicyId"] = policy_id
    return next_policy


def _ensure_session_agent_tool_policy(
    state: dict[str, Any],
    agent: dict[str, Any],
    *,
    normalized_tool_policies: dict[str, Any] | None = None,
) -> bool:
    s = _service()
    if not s._is_session_agent_primary_mode(str(agent.get("primaryMode") or "")):
        return False
    agent_id = str(agent.get("agentId") or "").strip()
    if not agent_id:
        return False
    policies = normalized_tool_policies if normalized_tool_policies is not None else s._tool_policies(state)
    current_policy_id = str(agent.get("toolPolicyId") or s.DEFAULT_TOOL_POLICY_ID).strip() or s.DEFAULT_TOOL_POLICY_ID
    policy_missing = current_policy_id not in policies
    if current_policy_id != s.DEFAULT_TOOL_POLICY_ID and not policy_missing:
        return False

    policy_id = current_policy_id if policy_missing and current_policy_id != s.DEFAULT_TOOL_POLICY_ID else f"tool-{agent_id}"
    policies[policy_id] = s.default_session_agent_tool_policy(policy_id)
    state["toolPolicies"] = policies
    agent["toolPolicyId"] = policy_id
    return True


def _fixed_role_tool_policy_kind(agent: dict[str, Any]) -> str:
    s = _service()
    primary_mode = s._normalize_primary_mode(agent.get("primaryMode") or s._infer_agent_primary_mode(agent))
    role_key = s._normalize_role_key(agent.get("roleKey") or s._infer_agent_role_key(agent))
    metadata = agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}
    if primary_mode in s.SYSTEM_NO_TOOL_MODES:
        system_role = s._normalize_role_key(metadata.get("selfEvolutionRole") or metadata.get("supervisedRole") or role_key)
        if primary_mode == "self_evolution" and system_role in s.SELF_EVOLUTION_EXECUTABLE_ROLES:
            return "self_evolution_executable"
        if system_role in s.SYSTEM_NO_TOOL_ROLES.get(primary_mode, set()):
            return "no_tools"
    if s.agent_role_tool_profile_service.role_has_explicit_tool_profile(role_key, primary_mode=primary_mode, metadata=metadata):
        return "role_profile"
    return ""


def _has_context_compression_override(source: dict[str, Any]) -> bool:
    s = _service()
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


def _knowledge_steward_memory_policy(workspace_path: str) -> dict[str, Any]:
    s = _service()
    return s.normalize_memory_policy(
        {
            **s.default_memory_policy(s.KNOWLEDGE_STEWARD_MEMORY_POLICY_ID, workspace_path),
            "readSharedGroups": ["project"],
            "writeSharedGroups": [],
            "readKnowledgeBaseIds": [],
            "proposeKnowledgeBaseIds": [],
            "reviewKnowledgeBaseIds": [],
            "rateKnowledgeBaseIds": [],
        },
        s.KNOWLEDGE_STEWARD_MEMORY_POLICY_ID,
        workspace_path,
    )


def _knowledge_steward_tool_policy() -> dict[str, Any]:
    s = _service()
    profile_policy = s.agent_role_tool_profile_service.resolve_role_tool_policy(
        role_key=s.KNOWLEDGE_STEWARD_ROLE_KEY,
        primary_mode="general",
        metadata={"systemRole": s.KNOWLEDGE_STEWARD_ROLE_KEY},
        policy_id=s.KNOWLEDGE_STEWARD_TOOL_POLICY_ID,
    )
    if profile_policy:
        return s.normalize_tool_policy(profile_policy, s.KNOWLEDGE_STEWARD_TOOL_POLICY_ID)
    return s.normalize_tool_policy(
        {
            **s.default_tool_policy(s.KNOWLEDGE_STEWARD_TOOL_POLICY_ID),
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
        s.KNOWLEDGE_STEWARD_TOOL_POLICY_ID,
    )


def _memory_policy_for_agent(agent: dict[str, Any], *, hydration: Any | None = None) -> dict[str, Any]:
    s = _service()
    agent_id = str(agent.get("agentId") or "").strip()
    if hydration is None:
        return s.resolve_memory_policy_for_agent(agent_id)
    policy_id = str(agent.get("memoryPolicyId") or "").strip()
    policy = hydration.memory_policies.get(policy_id)
    workspace_path = str(agent.get("workspacePath") or s._agent_workspace_relative_path(agent_id)).strip()
    if isinstance(policy, dict):
        return s.normalize_memory_policy(policy, policy_id, workspace_path)
    return s.default_memory_policy(policy_id or f"memory-{agent_id}", workspace_path)


def _normalize_context_compression_levels(levels: Any) -> dict[str, float]:
    s = _service()
    raw = levels if levels is not None else {}
    return {
        "light": s._context_compression_ratio(s._get_config_value(raw, "light"), s.DEFAULT_CONTEXT_COMPRESSION_LEVELS["light"]),
        "standard": s._context_compression_ratio(s._get_config_value(raw, "standard"), s.DEFAULT_CONTEXT_COMPRESSION_LEVELS["standard"]),
        "deep": s._context_compression_ratio(s._get_config_value(raw, "deep"), s.DEFAULT_CONTEXT_COMPRESSION_LEVELS["deep"]),
        "emergency": s._context_compression_ratio(s._get_config_value(raw, "emergency"), s.DEFAULT_CONTEXT_COMPRESSION_LEVELS["emergency"]),
    }


def _normalize_context_compression_preservation(preservation: Any) -> dict[str, Any]:
    s = _service()
    raw = preservation if preservation is not None else {}
    return {
        "keepAiMessages": s._positive_context_compression_int(
            s._get_config_value(raw, "keepAiMessages", "keep_ai_messages"),
            default=5,
            maximum=50,
        ),
        "preserveErrors": bool(s._get_config_value(raw, "preserveErrors", "preserve_errors", default=True)),
        "extractKeyDecisions": bool(s._get_config_value(raw, "extractKeyDecisions", "extract_key_decisions", default=True)),
    }


def _normalize_context_compression_summary_chars(summary_chars: Any) -> dict[str, int]:
    s = _service()
    raw = summary_chars if summary_chars is not None else {}
    return {
        "light": s._positive_context_compression_int(s._get_config_value(raw, "light"), default=s.DEFAULT_CONTEXT_COMPRESSION_SUMMARY_CHARS["light"], maximum=20_000),
        "standard": s._positive_context_compression_int(s._get_config_value(raw, "standard"), default=s.DEFAULT_CONTEXT_COMPRESSION_SUMMARY_CHARS["standard"], maximum=20_000),
        "deep": s._positive_context_compression_int(s._get_config_value(raw, "deep"), default=s.DEFAULT_CONTEXT_COMPRESSION_SUMMARY_CHARS["deep"], maximum=20_000),
        "emergency": s._positive_context_compression_int(s._get_config_value(raw, "emergency"), default=s.DEFAULT_CONTEXT_COMPRESSION_SUMMARY_CHARS["emergency"], maximum=20_000),
    }


def _normalize_tool_policy_scopes(scopes: Any) -> list[str]:
    s = _service()
    normalized: list[str] = []
    raw_scopes = [scopes] if isinstance(scopes, str) else list(scopes or [])
    for item in raw_scopes:
        scope = str(item or "").strip().lower()
        if scope not in s.TOOL_POLICY_WORKSPACE_SCOPES or scope in normalized:
            continue
        normalized.append(scope)
    return normalized


def _positive_context_compression_int(value: Any, *, default: int, maximum: int) -> int:
    s = _service()
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(0, min(maximum, parsed))


def _record_agent_delegation_policy_event(agent: dict[str, Any], policy: dict[str, Any]) -> None:
    s = _service()
    try:
        s.record_runtime_scene_event(
            "agent_directory",
            "delegation_policy",
            "agent.delegation_policy.updated",
            message="agent.delegation_policy.updated",
            level="info",
            outcome="observed",
            fields={
                "agentId": str(agent.get("agentId") or "").strip(),
                "agentCode": s._normalize_agent_code(agent.get("agentCode")),
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


def _record_agent_memory_policy_event(agent: dict[str, Any], policy: dict[str, Any]) -> None:
    s = _service()
    try:
        s.record_runtime_scene_event(
            "agent_directory",
            "memory_policy",
            "agent.memory_policy.updated",
            message="agent.memory_policy.updated",
            level="info",
            outcome="observed",
            fields={
                "agentId": str(agent.get("agentId") or "").strip(),
                "agentCode": s._normalize_agent_code(agent.get("agentCode")),
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


def _record_agent_supervision_policy_event(agent: dict[str, Any], policy: dict[str, Any]) -> None:
    s = _service()
    try:
        s.record_runtime_scene_event(
            "agent_directory",
            "supervision_policy",
            "agent.supervision_policy.updated",
            message="agent.supervision_policy.updated",
            level="info",
            outcome="observed",
            fields={
                "agentId": str(agent.get("agentId") or "").strip(),
                "agentCode": s._normalize_agent_code(agent.get("agentCode")),
                "supervisionEnabled": bool(policy.get("supervisionEnabled", False)),
                "requiresReview": bool(policy.get("requiresReview", False)),
                "reviewMode": str(policy.get("reviewMode") or "").strip(),
                "evidenceLevel": str(policy.get("evidenceLevel") or "").strip(),
            },
            lifecycle=True,
        )
    except Exception:
        return


def _record_agent_tool_policy_event(agent: dict[str, Any], policy: dict[str, Any]) -> None:
    s = _service()
    try:
        s.record_runtime_scene_event(
            "agent_directory",
            "tool_policy",
            "agent.tool_policy.updated",
            message="agent.tool_policy.updated",
            level="info",
            outcome="observed",
            fields={
                "agentId": str(agent.get("agentId") or "").strip(),
                "agentCode": s._normalize_agent_code(agent.get("agentCode")),
                "toolPolicyId": str(policy.get("policyId") or agent.get("toolPolicyId") or "").strip(),
                "allowedToolCount": len(list(policy.get("allowedTools") or [])),
                "blockedToolCount": len(list(policy.get("blockedTools") or [])),
                "preferredToolCount": len(list(policy.get("preferredTools") or [])),
                "readScopeCount": len(list(policy.get("readScopes") or [])),
                "writeScopeCount": len(list(policy.get("writeScopes") or [])),
                "sharedWriteEnabled": "shared" in set(s._normalize_tool_policy_scopes(policy.get("writeScopes"))),
            },
            lifecycle=True,
        )
    except Exception:
        return


def _record_delegation_policy_block(
    agent_id: str,
    policy: dict[str, Any],
    decision: Any,
) -> None:
    s = _service()
    try:
        s.record_runtime_scene_event(
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


def _record_policy_block(
    agent_id: str,
    policy: dict[str, Any],
    tool_name: str,
    tool_args: dict[str, Any],
    decision: Any,
) -> None:
    s = _service()
    try:
        s.record_runtime_scene_event(
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


def _record_supervision_policy_block(decision: Any) -> None:
    s = _service()
    try:
        s.record_runtime_scene_event(
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


def _record_supervision_policy_observed(decision: Any) -> None:
    s = _service()
    try:
        s.record_runtime_scene_event(
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


def _tool_name_list(tools: Iterable[Any]) -> list[str]:
    s = _service()
    names: list[str] = []
    seen: set[str] = set()
    for tool in list(tools or []):
        name = str(getattr(tool, "name", "") or tool or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        names.append(name)
    return names


def _tool_policies(state: dict[str, Any]) -> dict[str, Any]:
    s = _service()
    raw = state.get("toolPolicies")
    policies = dict(raw) if isinstance(raw, dict) else {}
    policies.setdefault(s.DEFAULT_TOOL_POLICY_ID, s.default_tool_policy(s.DEFAULT_TOOL_POLICY_ID))
    return {
        str(policy_id): s.normalize_tool_policy(policy if isinstance(policy, dict) else {}, str(policy_id))
        for policy_id, policy in policies.items()
    }


def _tool_policy_for_agent(agent: dict[str, Any], *, hydration: Any | None = None) -> dict[str, Any]:
    s = _service()
    agent_id = str(agent.get("agentId") or "").strip()
    if hydration is None:
        return s.resolve_tool_policy_for_agent(agent_id)
    policy_id = str(agent.get("toolPolicyId") or s.DEFAULT_TOOL_POLICY_ID).strip() or s.DEFAULT_TOOL_POLICY_ID
    policy = hydration.tool_policies.get(policy_id) or s.default_tool_policy(policy_id)
    metadata = agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}
    return s._effective_agent_tool_policy(
        s._with_session_terminal_protocol_defaults(agent, s.normalize_tool_policy(policy, policy_id)),
        metadata.get("delegationPolicy") if isinstance(metadata, dict) else {},
    )


def _tool_policy_source_for_agent(agent: dict[str, Any], policy: dict[str, Any] | None) -> dict[str, Any]:
    s = _service()
    agent_id = str(agent.get("agentId") or "").strip()
    policy_id = str(agent.get("toolPolicyId") or s.DEFAULT_TOOL_POLICY_ID).strip() or s.DEFAULT_TOOL_POLICY_ID
    normalized_policy = s.normalize_tool_policy(policy if isinstance(policy, dict) else {}, policy_id)
    allowed_tools = s._tool_name_list(normalized_policy.get("allowedTools") or [])
    preferred_tools = s._tool_name_list(normalized_policy.get("preferredTools") or [])
    mutating_tools = sorted({tool for tool in allowed_tools if tool in s.MUTATING_AGENT_TOOL_NAMES})
    is_session_agent = s._is_session_agent_primary_mode(str(agent.get("primaryMode") or s._infer_agent_primary_mode(agent)))
    is_private_policy = bool(agent_id and policy_id == f"tool-{agent_id}")
    fixed_kind = s._fixed_role_tool_policy_kind(agent)
    default_allowed = list(s.DEFAULT_SESSION_AGENT_ALLOWED_TOOLS)
    default_preferred = list(s.DEFAULT_SESSION_AGENT_PREFERRED_TOOLS)
    if fixed_kind == "no_tools":
        kind = "system_no_tools"
        label = "系统固定无工具"
        description = "该系统角色由运行时固定为无工具策略，避免误删或误授权影响核心流程。"
    elif fixed_kind in {"research_source", "research_role"}:
        kind = "fixed_role_policy"
        label = "角色固定工具"
        description = "该科研角色使用固定工具包，系统会按职责保持只读/受控权限。"
    elif policy_id == s.DEFAULT_TOOL_POLICY_ID:
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


def _with_temporary_tool_grants(
    policy: dict[str, Any],
    *,
    agent_id: str,
    session_id: str = "",
    turn_id: str = "",
) -> dict[str, Any]:
    s = _service()
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
        s._debug_logger.warning(
            f"Failed to load temporary tool grants for agent={agent_id}, session_id={normalized_session_id}, turn_id={turn_id}. error={type(exc).__name__}: {exc}",
            tag="AGENT_TOOL_DIRECTORY",
        )
        return policy
    if not temporary_grants:
        return policy

    allowed = s._tool_name_list(policy.get("allowedTools") or [])
    blocked = set(s._tool_name_list(policy.get("blockedTools") or []))
    temporary_allowed: list[str] = []
    for tool in s._tool_name_list(temporary_grants):
        if not tool or tool in blocked or tool in allowed:
            continue
        allowed.append(tool)
        temporary_allowed.append(tool)
    if not temporary_allowed:
        return policy
    return {
        **policy,
        "allowedTools": allowed,
        "temporaryAllowedTools": s._tool_name_list(list(policy.get("temporaryAllowedTools") or []) + temporary_allowed),
    }


def _without_subagent_delegation_tools(policy: dict[str, Any], delegation_policy: dict[str, Any] | None) -> dict[str, Any]:
    s = _service()
    normalized_policy = s.normalize_delegation_policy(delegation_policy)
    if bool(normalized_policy.get("allowSubagents", False)):
        return policy
    blocked_tools = s.SUBAGENT_DELEGATION_TOOL_NAMES
    allowed = [name for name in s._tool_name_list(policy.get("allowedTools") or []) if name not in blocked_tools]
    preferred = [name for name in s._tool_name_list(policy.get("preferredTools") or []) if name not in blocked_tools]
    if allowed == s._tool_name_list(policy.get("allowedTools") or []) and preferred == s._tool_name_list(
        policy.get("preferredTools") or []
    ):
        return policy
    return {
        **policy,
        "allowedTools": allowed,
        "preferredTools": preferred,
    }


def _workspace_path_for_policy(agent_workspace_path: str, existing_private_root: str = "") -> str:
    s = _service()
    workspace_path = str(agent_workspace_path or "").strip()
    if workspace_path:
        return workspace_path
    private_root = str(existing_private_root or "").strip().replace("\\", "/")
    suffix = "/memory"
    if private_root.endswith(suffix):
        return private_root[: -len(suffix)]
    return ""


def agent_conversation_index_visibility(
    agent: dict[str, Any] | None,
    *,
    hidden_team_member_agent_ids: set[str] | None = None,
) -> str:
    """Return how an Agent direct session may appear in the ordinary chat index."""
    s = _service()

    if not isinstance(agent, dict):
        return s.CONVERSATION_INDEX_VISIBILITY_HIDDEN
    if str(agent.get("kind") or s.DEFAULT_AGENT_KIND).strip() != s.DEFAULT_AGENT_KIND:
        return s.CONVERSATION_INDEX_VISIBILITY_HIDDEN
    if str(agent.get("status") or "active").strip().lower() == "archived":
        return s.CONVERSATION_INDEX_VISIBILITY_HIDDEN
    agent_id = str(agent.get("agentId") or "").strip()
    direct_session_id = str(agent.get("directSessionId") or "").strip()
    if not agent_id or not direct_session_id:
        return s.CONVERSATION_INDEX_VISIBILITY_HIDDEN
    classification = s.agent_conversation_index_classification(
        agent,
        hidden_team_member_agent_ids=hidden_team_member_agent_ids,
    )
    kind = str(classification.get("kind") or "").strip()
    if kind == s.CONVERSATION_INDEX_KIND_TEAM_AGENT:
        return s.CONVERSATION_INDEX_VISIBILITY_TEAM_PRIVATE
    if kind in {s.CONVERSATION_INDEX_KIND_PERSONAL_AGENT, s.CONVERSATION_INDEX_KIND_USER_CHAT, s.CONVERSATION_INDEX_KIND_SYSTEM_ENTRY}:
        return s.CONVERSATION_INDEX_VISIBILITY_USER_VISIBLE
    return s.CONVERSATION_INDEX_VISIBILITY_HIDDEN


def build_agent_policy_options(
    *,
    state: dict[str, Any] | None = None,
    agents: list[dict[str, Any]] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Build lightweight policy options from an already-loaded Agent registry snapshot."""
    s = _service()

    source_state = state if isinstance(state, dict) else s.load_state()
    source_agents = list(agents or [])
    if not source_agents:
        source_agents = [item for item in source_state.get("agents") or [] if isinstance(item, dict)]
    tool_policies = s._tool_policies(source_state)
    memory_policies = s._memory_policies(source_state)
    return {
        "toolPolicies": [
            {
                "policyId": policy_id,
                "agentCount": s._count_policy_refs(agents, "toolPolicyId", policy_id),
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
                "agentCount": s._count_policy_refs(agents, "memoryPolicyId", policy_id),
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


def compute_effective_tool_visibility(
    tools: Iterable[Any],
    *,
    policy: dict[str, Any] | None = None,
) -> Any:
    s = _service()
    normalized_policy = s._without_disabled_agent_tools(policy if isinstance(policy, dict) else {})
    policy_id = str(normalized_policy.get("policyId") or normalized_policy.get("id") or s.DEFAULT_TOOL_POLICY_ID).strip()
    policy_id = policy_id or s.DEFAULT_TOOL_POLICY_ID
    tool_names = s._tool_name_list(tools)
    tool_name_set = set(tool_names)
    allowed = tuple(
        name
        for name in s._tool_name_list(normalized_policy.get("allowedTools") or [])
        if name
    )
    blocked = tuple(
        name
        for name in s._tool_name_list(normalized_policy.get("blockedTools") or [])
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
        for name in s._tool_name_list(normalized_policy.get("preferredTools") or [])
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
    return s.EffectiveToolVisibility(
        policy_id=policy_id,
        visible_tools=visible,
        configured_unavailable_tools=configured_unavailable,
        blocked_tools=tuple(name for name in blocked if name in tool_name_set),
        hidden_restricted_tools=hidden_restricted,
        preferred_tools=preferred,
        write_scopes=tuple(s._normalize_tool_policy_scopes(normalized_policy.get("writeScopes"))),
    )


def default_memory_policy(policy_id: str, agent_workspace_path: str) -> dict[str, Any]:
    s = _service()
    workspace_path = s._workspace_path_for_policy(str(agent_workspace_path or "").strip(), "")
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


def default_research_role_tool_policy(policy_id: str, *, role_key: str = "") -> dict[str, Any]:
    s = _service()
    payload = s.default_tool_policy(policy_id)
    resolved = s.agent_role_tool_profile_service.resolve_role_tool_policy(
        role_key=role_key,
        primary_mode="research",
        policy_id=policy_id,
    )
    if resolved:
        payload.update(resolved)
    else:
        profile = s._RESEARCH_ROLE_DEFAULT_PROFILE
        payload["allowedTools"] = list(profile.get("allowedTools") or ("agent_message_tool", "research_knowledge_query_tool"))
        payload["preferredTools"] = list(profile.get("preferredTools") or payload["allowedTools"])
        payload["readScopes"] = ["private", "shared"]
        payload["writeScopes"] = []
        payload["networkAccess"] = "controlled"
        payload["mutationAccess"] = "none"
        payload["maxCallsPerTurn"] = 8
    return payload


def default_research_source_tool_policy(policy_id: str, *, role_key: str = "") -> dict[str, Any]:
    s = _service()
    payload = s.default_tool_policy(policy_id)
    resolved = s.agent_role_tool_profile_service.resolve_role_tool_policy(
        role_key=role_key,
        primary_mode="research",
        policy_id=policy_id,
    )
    if resolved and str(resolved.get("roleToolProfileId") or "").strip() != "research_role_default":
        payload.update(resolved)
    else:
        profile = s._RESEARCH_SOURCE_DEFAULT_PROFILE
        if profile:
            payload.update(s.agent_role_tool_profile_service.build_policy_from_role_profile(profile, policy_id))
        else:
            payload["allowedTools"] = list(s.RESEARCH_SOURCE_ALLOWED_TOOLS)
            payload["preferredTools"] = list(s.RESEARCH_SOURCE_PREFERRED_TOOLS)
            payload["readScopes"] = ["private", "shared"]
            payload["writeScopes"] = []
            payload["networkAccess"] = "controlled"
            payload["mutationAccess"] = "none"
            payload["maxCallsPerTurn"] = 8
    return payload


def default_self_evolution_executable_tool_policy(policy_id: str) -> dict[str, Any]:
    s = _service()
    payload = s.default_tool_policy(policy_id)
    payload["allowedTools"] = list(s.SELF_EVOLUTION_EXECUTABLE_AGENT_ALLOWED_TOOLS)
    payload["preferredTools"] = list(s.SELF_EVOLUTION_EXECUTABLE_AGENT_PREFERRED_TOOLS)
    payload["readScopes"] = ["private", "shared", "repo"]
    payload["writeScopes"] = ["repo"]
    payload["networkAccess"] = "none"
    payload["mutationAccess"] = "restricted"
    payload["maxCallsPerTurn"] = 12
    return payload


def default_session_agent_tool_policy(policy_id: str) -> dict[str, Any]:
    s = _service()
    payload = s.default_tool_policy(policy_id)
    payload["allowedTools"] = list(s.DEFAULT_SESSION_AGENT_ALLOWED_TOOLS)
    payload["preferredTools"] = list(s.DEFAULT_SESSION_AGENT_PREFERRED_TOOLS)
    payload["readScopes"] = ["private", "shared"]
    payload["writeScopes"] = ["private"]
    return payload


def default_session_agent_tool_policy_v2(policy_id: str, *, registered_tool_names: Iterable[str]):
    """Project the existing default session assignment into immutable ToolPolicyV2."""
    s = _service()

    from core.authorization.tool_policy_evaluator import normalize_legacy_tool_policy

    return normalize_legacy_tool_policy(
        s.default_session_agent_tool_policy(policy_id),
        registered_tool_names=registered_tool_names,
        policy_id=policy_id,
    )


def default_system_no_tool_policy(policy_id: str) -> dict[str, Any]:
    s = _service()
    payload = s.default_tool_policy(policy_id)
    payload["networkAccess"] = "none"
    payload["mutationAccess"] = "none"
    return payload


def default_tool_policy(policy_id: str = DEFAULT_TOOL_POLICY_ID) -> dict[str, Any]:
    s = _service()
    return {
        "policyId": str(policy_id or s.DEFAULT_TOOL_POLICY_ID),
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


def effective_agent_context_compression_policy(
    agent: dict[str, Any] | None,
    base_policy: Any = None,
    *,
    context_window_limit: int = 0,
) -> dict[str, Any]:
    s = _service()
    base = s._context_compression_policy_from_config(base_policy, context_window_limit=context_window_limit)
    raw_agent_policy = s.normalize_agent_context_compression_policy(
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
        "maxCompressionsPerSession": s._positive_context_compression_int(
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
    raw_limit = s._positive_context_compression_int(raw_agent_policy.get("maxTokenLimit"), default=0, maximum=2_000_000)
    context_window = s._positive_context_compression_int(context_window_limit, default=int(base.get("contextWindowLimit") or 0), maximum=2_000_000)
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


def evaluate_current_delegation_policy(
    *,
    context_mode: str = "isolated",
    requested_depth: int | None = None,
    wake_message: bool = False,
) -> Any:
    s = _service()
    runtime = s.current_agent_runtime()
    agent_id = str(runtime.get("agentId") or "").strip()
    if not agent_id:
        return s.DelegationPolicyDecision(True, context_mode=str(context_mode or "isolated").strip() or "isolated")
    policy = runtime.get("delegationPolicy") or s.resolve_delegation_policy_for_agent(agent_id)
    decision = s.evaluate_delegation_policy(
        policy,
        agent_id=agent_id,
        context_mode=context_mode,
        requested_depth=requested_depth,
        wake_message=wake_message,
    )
    if not decision.allowed:
        s._record_delegation_policy_block(agent_id, policy, decision)
    return decision


def evaluate_current_supervision_policy(
    *,
    action: str,
    human_override: bool = False,
    user_initiated: bool = False,
) -> Any:
    s = _service()
    runtime = s.current_agent_runtime()
    agent_id = str(runtime.get("agentId") or "").strip()
    if not agent_id:
        return s.SupervisionPolicyDecision(True, action=str(action or "").strip())
    policy = runtime.get("supervisionPolicy") or s.resolve_supervision_policy_for_agent(agent_id)
    decision = s.evaluate_supervision_policy(
        policy,
        agent_id=agent_id,
        action=action,
        human_override=human_override,
        user_initiated=user_initiated,
    )
    s.record_supervision_policy_decision(decision)
    return decision


def evaluate_current_tool_policy(tool_name: str, tool_args: dict[str, Any]) -> Any:
    s = _service()
    runtime = s.current_agent_runtime()
    agent_id = str(runtime.get("agentId") or "").strip()
    if not agent_id:
        return s.ToolPolicyDecision(True)
    normalized_tool = str(tool_name or "").strip()
    delegation_policy = s.normalize_delegation_policy(runtime.get("delegationPolicy"))
    if normalized_tool in s.DISABLED_AGENT_DIRECT_READ_TOOL_NAMES:
        policy = runtime.get("toolPolicy") or {}
        policy_id = str(policy.get("policyId") or policy.get("id") or "").strip() or s.DEFAULT_TOOL_POLICY_ID
        decision = s._blocked_decision(
            normalized_tool,
            "direct_read_tool_disabled",
            policy_id,
            agent_id,
            f"[工具策略提示] 当前 Agent 默认关闭 `{normalized_tool}`；请改用 `cli_tool` 执行 `rg` 与小范围命令读取。",
        )
        s._record_policy_block(agent_id, policy, normalized_tool, tool_args, decision)
        return decision
    if normalized_tool in s.SUBAGENT_DELEGATION_TOOL_NAMES and not bool(
        delegation_policy.get("allowSubagents", False)
    ):
        policy = runtime.get("toolPolicy") or {}
        policy_id = str(policy.get("policyId") or policy.get("id") or "").strip() or s.DEFAULT_TOOL_POLICY_ID
        decision = s._blocked_decision(
            normalized_tool,
            "subagent_delegation_disabled",
            policy_id,
            agent_id,
            f"[委托策略提示] 当前 Agent 默认关闭子 agent 派发权限，`{normalized_tool}` 已被拦截。",
        )
        s._record_policy_block(agent_id, policy, normalized_tool, tool_args, decision)
        return decision
    policy = runtime.get("toolPolicy") or {}
    decision = s.evaluate_tool_policy(
        normalized_tool,
        tool_args,
        policy=policy,
        agent_id=agent_id,
    )
    if not decision.allowed:
        s._record_policy_block(agent_id, policy, tool_name, tool_args, decision)
    return decision


def evaluate_delegation_policy(
    policy: dict[str, Any],
    *,
    agent_id: str = "",
    context_mode: str = "isolated",
    requested_depth: int | None = None,
    wake_message: bool = False,
) -> Any:
    s = _service()
    normalized_policy = s.normalize_delegation_policy(policy)
    normalized_mode = str(context_mode or "isolated").strip().lower() or "isolated"
    max_depth = int(normalized_policy.get("maxDepth") or 0)
    max_concurrent = int(normalized_policy.get("maxConcurrent") or 0)
    if wake_message and not bool(normalized_policy.get("allowWakeMessages", True)):
        return s.DelegationPolicyDecision(
            False,
            message="[委托策略提示] 目标 Agent 的唤醒消息已关闭，消息会留在 inbox 中等待后续处理。",
            reason="wake_messages_disabled",
            agent_id=agent_id,
            max_depth=max_depth,
            max_concurrent=max_concurrent,
            context_mode=normalized_mode,
        )
    if not bool(normalized_policy.get("allowSubagents", False)):
        return s.DelegationPolicyDecision(
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
        return s.DelegationPolicyDecision(
            False,
            message=f"[委托策略提示] 当前 Agent 不允许 `{normalized_mode}` 子 Agent 上下文模式。",
            reason="context_mode_not_allowed",
            agent_id=agent_id,
            max_depth=max_depth,
            max_concurrent=max_concurrent,
            context_mode=normalized_mode,
        )
    depth = s._clamp_int(requested_depth, minimum=0, maximum=99, default=0) if requested_depth is not None else 0
    if max_depth <= 0 or depth > max_depth:
        return s.DelegationPolicyDecision(
            False,
            message="[委托策略提示] 当前 Agent 的子 Agent 深度上限不允许本次派发。",
            reason="max_depth_exceeded",
            agent_id=agent_id,
            max_depth=max_depth,
            max_concurrent=max_concurrent,
            context_mode=normalized_mode,
        )
    return s.DelegationPolicyDecision(
        True,
        agent_id=agent_id,
        max_depth=max_depth,
        max_concurrent=max_concurrent,
        context_mode=normalized_mode,
    )


def evaluate_delegation_wake_policy(policy: dict[str, Any], *, agent_id: str = "") -> Any:
    s = _service()
    normalized_policy = s.normalize_delegation_policy(policy)
    if bool(normalized_policy.get("allowWakeMessages", True)):
        return s.DelegationPolicyDecision(
            True,
            agent_id=agent_id,
            max_depth=int(normalized_policy.get("maxDepth") or 0),
            max_concurrent=int(normalized_policy.get("maxConcurrent") or 0),
            context_mode="agent_inbox",
        )
    return s.DelegationPolicyDecision(
        False,
        message="[委托策略提示] 目标 Agent 的唤醒消息已关闭，消息会留在 inbox 中等待后续处理。",
        reason="wake_messages_disabled",
        agent_id=agent_id,
        max_depth=int(normalized_policy.get("maxDepth") or 0),
        max_concurrent=int(normalized_policy.get("maxConcurrent") or 0),
        context_mode="agent_inbox",
    )


def evaluate_supervision_policy(
    policy: dict[str, Any],
    *,
    agent_id: str = "",
    action: str,
    human_override: bool = False,
    user_initiated: bool = False,
) -> Any:
    s = _service()
    normalized_policy = s.normalize_supervision_policy(policy)
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
        return s.SupervisionPolicyDecision(True, reason="human_override", **base)
    if not supervision_enabled:
        return s.SupervisionPolicyDecision(True, reason="supervision_disabled", **base)
    if review_mode == "disabled":
        return s.SupervisionPolicyDecision(True, reason="review_disabled", **base)
    if review_mode == "required" or requires_review:
        return s.SupervisionPolicyDecision(
            False,
            message="[监督策略提示] 当前 Agent 的自主动作需要先完成复核，本次动作已被阻止。",
            reason="supervision_review_required",
            **base,
        )
    return s.SupervisionPolicyDecision(True, reason="supervision_advisory", **base)


def evaluate_tool_policy(
    tool_name: str,
    tool_args: dict[str, Any],
    *,
    policy: dict[str, Any],
    agent_id: str = "",
) -> Any:
    s = _service()
    normalized_tool = str(tool_name or "").strip()
    policy_id = str(policy.get("policyId") or policy.get("id") or "").strip() or s.DEFAULT_TOOL_POLICY_ID
    if not normalized_tool:
        return s._blocked_decision(
            normalized_tool,
            "missing_tool",
            policy_id,
            agent_id,
            "[工具策略提示] 当前工具调用缺少工具名称，已被 ToolPolicy 拦截。",
        )
    blocked = set(s._tool_name_list(policy.get("blockedTools") or []))
    if normalized_tool in blocked:
        return s._blocked_decision(
            normalized_tool,
            "blocked_tool",
            policy_id,
            agent_id,
            f"[工具策略提示] `{normalized_tool}` 已被该 Agent 的 ToolPolicy 禁用。",
        )
    allowed = set(s._tool_name_list(policy.get("allowedTools") or []))
    if not allowed:
        return s._blocked_decision(
            normalized_tool,
            "no_allowed_tools",
            policy_id,
            agent_id,
            "[工具策略提示] 当前 Agent 未配置可用工具，工具调用已被拦截。",
        )
    if normalized_tool not in allowed:
        return s._blocked_decision(
            normalized_tool,
            "tool_not_allowed",
            policy_id,
            agent_id,
            f"[工具策略提示] `{normalized_tool}` 不在该 Agent 的可用工具策略中。",
        )
    return s.ToolPolicyDecision(True, policy_id=policy_id, agent_id=agent_id)


def normalize_agent_context_compression_policy(policy: dict[str, Any] | None) -> dict[str, Any]:
    s = _service()
    source = policy if isinstance(policy, dict) else {}
    mode = str(source.get("mode") or "").strip().lower()
    if mode not in {"inherit", "custom"}:
        mode = "custom" if s._has_context_compression_override(source) else "inherit"
    if mode != "custom":
        return dict(s.DEFAULT_AGENT_CONTEXT_COMPRESSION_POLICY)

    payload: dict[str, Any] = {
        "mode": "custom",
        "enabled": bool(source.get("enabled", True)),
    }
    max_token_limit = s._positive_context_compression_int(
        source.get("maxTokenLimit", source.get("max_token_limit")),
        default=0,
        maximum=2_000_000,
    )
    if max_token_limit > 0:
        payload["maxTokenLimit"] = max_token_limit
    payload["maxCompressionsPerSession"] = s._positive_context_compression_int(
        source.get("maxCompressionsPerSession", source.get("max_compressions_per_session")),
        default=20,
        maximum=100,
    )
    payload["levels"] = s._normalize_context_compression_levels(source.get("levels"))
    payload["summaryChars"] = s._normalize_context_compression_summary_chars(
        source.get("summaryChars", source.get("summary_chars"))
    )
    payload["preservation"] = s._normalize_context_compression_preservation(source.get("preservation"))
    return payload


def normalize_conversation_index_visibility(value: Any) -> str:
    s = _service()
    visibility = str(value or "").strip()
    if visibility in s.CONVERSATION_INDEX_VISIBILITIES:
        return visibility
    return ""


def normalize_delegation_policy(policy: dict[str, Any] | None) -> dict[str, Any]:
    s = _service()
    source = policy if isinstance(policy, dict) else {}
    allowed_modes = [
        mode
        for mode in s._unique_string_list(source.get("allowedContextModes"))
        if mode in {"isolated", "fork"}
    ]
    if not allowed_modes:
        allowed_modes = ["isolated"]
    return {
        "allowSubagents": bool(source.get("allowSubagents", False)),
        "maxConcurrent": s._clamp_int(source.get("maxConcurrent"), minimum=0, maximum=8, default=0),
        "maxDepth": s._clamp_int(source.get("maxDepth"), minimum=0, maximum=4, default=0),
        "allowWakeMessages": bool(source.get("allowWakeMessages", True)),
        "allowedContextModes": allowed_modes,
    }


def normalize_memory_policy(policy: dict[str, Any], policy_id: str, agent_workspace_path: str) -> dict[str, Any]:
    s = _service()
    payload = s.default_memory_policy(policy_id, agent_workspace_path)
    payload.update(policy if isinstance(policy, dict) else {})
    payload["policyId"] = str(policy_id or payload.get("policyId") or "").strip()
    workspace_path = s._workspace_path_for_policy(str(agent_workspace_path or "").strip(), str(payload.get("privateMemoryRoot") or ""))
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
        payload[key] = s._unique_string_list(payload.get(key))
    return payload


def normalize_supervision_policy(policy: dict[str, Any] | None) -> dict[str, Any]:
    s = _service()
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


def normalize_tool_policy(policy: dict[str, Any], policy_id: str = "") -> dict[str, Any]:
    s = _service()
    raw_policy = policy if isinstance(policy, dict) else {}
    payload = s.default_tool_policy(policy_id or str(raw_policy.get("policyId") or raw_policy.get("id") or s.DEFAULT_TOOL_POLICY_ID))
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
        payload[key] = [name for name in payload.get(key) or [] if name not in s.DISABLED_AGENT_DIRECT_READ_TOOL_NAMES]
    payload["readScopes"] = s._normalize_tool_policy_scopes(payload.get("readScopes"))
    payload["writeScopes"] = s._normalize_tool_policy_scopes(payload.get("writeScopes"))
    payload["perToolRules"] = dict(payload.get("perToolRules") or {})
    try:
        payload["maxCallsPerTurn"] = max(0, int(payload.get("maxCallsPerTurn") or 0))
    except (TypeError, ValueError):
        payload["maxCallsPerTurn"] = 0
    try:
        payload["policyVersion"] = max(1, int(payload.get("policyVersion") or 1))
    except (TypeError, ValueError):
        payload["policyVersion"] = 1
    return payload


def record_supervision_policy_decision(decision: Any) -> None:
    s = _service()
    if not decision.agent_id or not decision.supervision_enabled:
        return
    if decision.reason in {"human_override", "review_disabled", "supervision_disabled"}:
        return
    if not decision.allowed:
        s._record_supervision_policy_block(decision)
        return
    if decision.review_mode == "advisory":
        s._record_supervision_policy_observed(decision)


def resolve_delegation_policy_for_agent(agent_id: str) -> dict[str, Any]:
    s = _service()
    state = s.load_state()
    agent = s._find_agent(state, agent_id)
    if agent is None:
        return s.normalize_delegation_policy({})
    metadata = agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}
    return s.normalize_delegation_policy(metadata.get("delegationPolicy") if isinstance(metadata, dict) else {})


def resolve_memory_policy_for_agent(agent_id: str) -> dict[str, Any]:
    s = _service()
    state = s.load_state()
    agent = s._find_agent(state, agent_id)
    if agent is None:
        return {}
    policy_id = str(agent.get("memoryPolicyId") or "").strip()
    policy = s._memory_policies(state).get(policy_id)
    workspace_path = str(agent.get("workspacePath") or s._agent_workspace_relative_path(agent_id)).strip()
    if isinstance(policy, dict):
        return s.normalize_memory_policy(policy, policy_id, workspace_path)
    return s.default_memory_policy(policy_id or f"memory-{agent_id}", workspace_path)


def resolve_supervision_policy_for_agent(agent_id: str) -> dict[str, Any]:
    s = _service()
    state = s.load_state()
    agent = s._find_agent(state, agent_id)
    if agent is None:
        return s.normalize_supervision_policy({})
    metadata = agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}
    return s.normalize_supervision_policy(metadata.get("supervisionPolicy") if isinstance(metadata, dict) else {})


def resolve_tool_policy_for_agent(agent_id: str, *, session_id: str = "", turn_id: str = "") -> dict[str, Any]:
    s = _service()
    agent = s._find_agent(s.load_state(), agent_id)
    if agent is None:
        return s.default_tool_policy(s.DEFAULT_TOOL_POLICY_ID)
    state = s.load_state()
    policy_id = str(agent.get("toolPolicyId") or s.DEFAULT_TOOL_POLICY_ID).strip() or s.DEFAULT_TOOL_POLICY_ID
    policy = s._tool_policies(state).get(policy_id) or s.default_tool_policy(policy_id)
    normalized = s._with_session_terminal_protocol_defaults(agent, s.normalize_tool_policy(policy, policy_id))
    with_grants = s._with_temporary_tool_grants(
        normalized,
        agent_id=agent_id,
        session_id=session_id,
        turn_id=turn_id,
    )
    metadata = agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}
    return s._effective_agent_tool_policy(with_grants, metadata.get("delegationPolicy") if isinstance(metadata, dict) else {})


def session_agent_visibility(agent: dict[str, Any] | None) -> str:
    """Return whether a direct chat Agent is backed by real session activity."""
    s = _service()

    if not isinstance(agent, dict):
        return s.SESSION_AGENT_VISIBILITY_NONE
    primary_mode = s._normalize_primary_mode(agent.get("primaryMode") or s._infer_agent_primary_mode(agent))
    direct_session_id = str(agent.get("directSessionId") or "").strip()
    if primary_mode != "chat" or not direct_session_id:
        return s.SESSION_AGENT_VISIBILITY_NONE
    metadata = agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}
    legacy_workspace_path = str(metadata.get("legacySessionWorkspacePath") or "").strip()
    visibility = str(metadata.get("directSessionVisibility") or "").strip()
    if direct_session_id == s._active_chat_session_id():
        return s.SESSION_AGENT_VISIBILITY_ACTIVE
    if visibility == s.SESSION_AGENT_VISIBILITY_ACTIVE:
        return s.SESSION_AGENT_VISIBILITY_ACTIVE
    if visibility == s.SESSION_AGENT_VISIBILITY_PENDING:
        if s._session_workspace_has_activity(
            direct_session_id,
            session_workspace_path=legacy_workspace_path,
        ):
            return s.SESSION_AGENT_VISIBILITY_ACTIVE
        return s.SESSION_AGENT_VISIBILITY_PENDING
    session_root_exists = s._session_workspace_root_exists(direct_session_id)
    if (
        not legacy_workspace_path
        and not direct_session_id.startswith("session-seed-")
        and direct_session_id != "session-coordinator"
        and not session_root_exists
    ):
        return s.SESSION_AGENT_VISIBILITY_ACTIVE
    return s._direct_session_visibility(
        direct_session_id,
        session_workspace_path=legacy_workspace_path,
    )


def tool_policy_fingerprint(policy: dict[str, Any]) -> str:
    s = _service()
    import hashlib
    import json

    normalized = s.normalize_tool_policy(policy, str((policy or {}).get("policyId") or ""))
    encoded = json.dumps(normalized, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
