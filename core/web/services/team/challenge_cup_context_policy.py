"""Versioned context-compression policy contract for the six Challenge Cup roles.

Policy history:
    v1  inherit (unmaterialized; resolved to ``migration_required``/disabled)
    v2  ad-hoc custom policies with drifted limits (disabled / 1,000,000 /
        262,144 residue)
    v3  explicit, versioned custom policies aligned to the AutoDL
        GLM-5.3-flash window contract (this module)

Budget contract (first-round frozen values, configurable via operator config):

    effective_input_hard_limit = context_window - reserved_max_output - reserve
    compression_trigger        = effective_input_hard_limit - 16,384
    post_compression_target    = effective_input_hard_limit * 2 / 3

With ``context_window=262,144``, ``reserved_max_output=32,768`` and
``protocol_and_safety_reserve=8,192`` this yields the frozen plan values
221,184 / 204,800 / 147,456. The protocol reserve is a conservative
first-round value and must only change through this versioned contract.
"""

from __future__ import annotations

import copy
from datetime import datetime, timezone
from typing import Any

CHALLENGE_CUP_CONTEXT_POLICY_VERSION = 3

# Frozen first-round budget values (plan CC-AGENT-CONVERSATION-REPAIR §5.4).
CONTEXT_WINDOW_TOKENS = 262_144
RESERVED_MAX_OUTPUT_TOKENS = 32_768
PROTOCOL_AND_SAFETY_RESERVE_TOKENS = 8_192
TRIGGER_SAFETY_MARGIN_TOKENS = 16_384
POST_COMPRESSION_TARGET_RATIO = 2 / 3

# Shared compression retention contract (must survive every compression).
SHARED_RETENTION_FOCUS: tuple[str, ...] = (
    "scope",
    "task_contract",
    "unresolved_tool_call",
    "evidence_locator",
    "writeback_contract",
    "compression_generation",
    "iteration_attempt",
)

# Per-role retention focus (plan §6.7 table).
CHALLENGE_CUP_ROLE_RETENTION_FOCUS: dict[str, tuple[str, ...]] = {
    "challenge_cup_search": ("retrieval_constraints", "source_citations"),
    "challenge_cup_extractor": ("evidence_digest", "counter_evidence_and_gaps"),
    "challenge_cup_knowledge_manager": ("claim_identity", "version_lineage"),
    "challenge_cup_evaluator": ("scoring_rubric", "candidates", "open_objections"),
    "challenge_cup_experiment_revision": (
        "experiment_versions",
        "variables_and_failures",
        "revision_rationale",
    ),
    "challenge_cup_execution_steward": (
        "execution_contract",
        "tool_state",
        "artifact_refs",
    ),
}

CHALLENGE_CUP_CONTEXT_POLICY_ROLES: tuple[str, ...] = tuple(
    CHALLENGE_CUP_ROLE_RETENTION_FOCUS
)

_SNAPSHOT_SCHEMA_VERSION = 1


def _config_context_compression() -> Any:
    try:
        from config import get_config

        return get_config().context_compression
    except Exception:
        return None


def _config_int(cc: Any, key: str) -> int:
    try:
        return int(getattr(cc, key))
    except (TypeError, ValueError, AttributeError):
        return 0


def challenge_cup_context_budget(
    *,
    context_window: int = CONTEXT_WINDOW_TOKENS,
    reserved_max_output_tokens: int | None = None,
    protocol_and_safety_reserve_tokens: int | None = None,
) -> dict[str, int]:
    """Compute the versioned context budget for one model window.

    ``reserved_max_output_tokens`` / ``protocol_and_safety_reserve_tokens``
    fall back to the frozen contract values; the protocol reserve may be
    overridden by the operator config knob
    ``context_compression.protocol_and_safety_reserve_tokens``.
    """

    if int(context_window or 0) <= 0:
        raise ValueError("context_window must be a positive token count")
    cc = _config_context_compression()
    reserved_output = (
        int(reserved_max_output_tokens)
        if reserved_max_output_tokens is not None
        else _config_int(cc, "reserved_max_output_tokens") or RESERVED_MAX_OUTPUT_TOKENS
    )
    reserve = (
        int(protocol_and_safety_reserve_tokens)
        if protocol_and_safety_reserve_tokens is not None
        else _config_int(cc, "protocol_and_safety_reserve_tokens") or PROTOCOL_AND_SAFETY_RESERVE_TOKENS
    )
    reserved_output = max(0, int(reserved_output))
    reserve = max(0, int(reserve))
    hard_limit = int(context_window) - reserved_output - reserve
    if hard_limit <= 0:
        raise ValueError(
            "context budget is non-positive: window minus reservations must stay positive"
        )
    trigger = hard_limit - TRIGGER_SAFETY_MARGIN_TOKENS
    if trigger <= 0:
        raise ValueError("compression trigger must stay positive below the hard limit")
    target = int(hard_limit * POST_COMPRESSION_TARGET_RATIO)
    return {
        "contextWindow": int(context_window),
        "reservedMaxOutputTokens": reserved_output,
        "protocolAndSafetyReserveTokens": reserve,
        "effectiveInputHardLimit": hard_limit,
        "compressionTriggerTokenLimit": trigger,
        "postCompressionTargetTokenLimit": target,
    }


def _role_policy_payload(role_key: str) -> dict[str, Any] | None:
    focus = CHALLENGE_CUP_ROLE_RETENTION_FOCUS.get(str(role_key or "").strip())
    if focus is None:
        return None
    budget = challenge_cup_context_budget()
    retention_focus = list(SHARED_RETENTION_FOCUS) + list(focus)
    return {
        "mode": "custom",
        "enabled": True,
        "policyVersion": CHALLENGE_CUP_CONTEXT_POLICY_VERSION,
        "maxTokenLimit": budget["effectiveInputHardLimit"],
        "compressionTriggerTokenLimit": budget["compressionTriggerTokenLimit"],
        "postCompressionTargetTokenLimit": budget["postCompressionTargetTokenLimit"],
        "maxCompressionsPerSession": 20,
        "levels": {
            "light": 0.6,
            "standard": 0.8,
            "deep": 0.9,
            "emergency": 0.95,
        },
        "summaryChars": {
            "light": 500,
            "standard": 1_000,
            "deep": 2_000,
            "emergency": 3_000,
        },
        "preservation": {
            "keepAiMessages": 5,
            "preserveErrors": True,
            "extractKeyDecisions": True,
            "retentionFocus": retention_focus,
        },
    }


def challenge_cup_role_context_policy(role_key: str) -> dict[str, Any] | None:
    """Return the explicit versioned custom policy for one Challenge Cup role.

    Non-Challenge-Cup roles return ``None`` so the global default stays
    untouched.
    """

    payload = _role_policy_payload(role_key)
    return copy.deepcopy(payload) if payload is not None else None


def _challenge_cup_role_agents() -> list[tuple[str, dict[str, Any]]]:
    """List (role_key, agent) pairs for the managed Challenge Cup team agents."""

    from core.web.services import agent_directory_service, team_service

    team_id = str(getattr(team_service, "CHALLENGE_CUP_RESEARCH_TEAM_ID", "") or "").strip()
    if not team_id:
        return []
    agents: list[tuple[str, dict[str, Any]]] = []
    for agent in agent_directory_service.list_agents(include_archived=True, detail="summary"):
        if not isinstance(agent, dict):
            continue
        metadata = agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}
        if str(metadata.get("challengeCupTeamId") or "").strip() != team_id:
            continue
        role_key = str(metadata.get("challengeCupTeamRole") or "").strip()
        if role_key not in CHALLENGE_CUP_ROLE_RETENTION_FOCUS:
            continue
        agents.append((role_key, agent))
    agents.sort(key=lambda item: item[0])
    return agents


def export_challenge_cup_context_policy_snapshot() -> dict[str, Any]:
    """Export a secret-free snapshot of the six role compression policies."""

    entries: list[dict[str, Any]] = []
    for role_key, agent in _challenge_cup_role_agents():
        policy = agent.get("contextCompressionPolicy")
        entries.append(
            {
                "agentId": str(agent.get("agentId") or "").strip(),
                "role": role_key,
                "policy": copy.deepcopy(policy) if isinstance(policy, dict) else None,
            }
        )
    return {
        "schemaVersion": _SNAPSHOT_SCHEMA_VERSION,
        "policyVersion": CHALLENGE_CUP_CONTEXT_POLICY_VERSION,
        "exportedAt": datetime.now(timezone.utc).isoformat(),
        "agents": entries,
    }


def apply_challenge_cup_context_policies(
    *,
    snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Migrate the six roles onto the explicit versioned custom policies.

    Returns the applied snapshot and the number of roles actually changed.
    """

    from core.web.services import agent_directory_service

    safe_snapshot = snapshot or export_challenge_cup_context_policy_snapshot()
    changed_roles: list[str] = []
    unchanged_roles: list[str] = []
    for role_key, agent in _challenge_cup_role_agents():
        target = challenge_cup_role_context_policy(role_key)
        if target is None:
            continue
        agent_id = str(agent.get("agentId") or "").strip()
        if not agent_id:
            continue
        current = agent.get("contextCompressionPolicy")
        normalized_current = agent_directory_service.normalize_agent_context_compression_policy(
            current if isinstance(current, dict) else {}
        )
        normalized_target = agent_directory_service.normalize_agent_context_compression_policy(target)
        if normalized_current == normalized_target:
            unchanged_roles.append(role_key)
            continue
        agent_directory_service.update_agent_instance(
            agent_id,
            context_compression_policy=copy.deepcopy(target),
        )
        changed_roles.append(role_key)
    return {
        "snapshot": safe_snapshot,
        "policyVersion": CHALLENGE_CUP_CONTEXT_POLICY_VERSION,
        "changedRoles": changed_roles,
        "unchangedRoles": unchanged_roles,
        "changedRoleCount": len(changed_roles),
    }


def rollback_challenge_cup_context_policies(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Restore the pre-migration policies captured in ``snapshot``.

    Rollback never restores ``inherit``: a prior policy that was
    ``inherit``/unmaterialized falls back to the canonical versioned custom
    policy so the role stays explicitly configured.
    """

    from core.web.services import agent_directory_service

    known_roles = set(CHALLENGE_CUP_ROLE_RETENTION_FOCUS)
    restored: list[str] = []
    skipped: list[dict[str, str]] = []
    for entry in list((snapshot or {}).get("agents") or []):
        if not isinstance(entry, dict):
            continue
        agent_id = str(entry.get("agentId") or "").strip()
        if not agent_id:
            continue
        agent = agent_directory_service.get_agent(agent_id, include_archived=True)
        if not isinstance(agent, dict) or not agent:
            skipped.append({"agentId": agent_id, "reason": "agent_not_found"})
            continue
        metadata = agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}
        role_key = str(
            entry.get("role") or metadata.get("challengeCupTeamRole") or ""
        ).strip()
        if role_key not in known_roles:
            skipped.append({"agentId": agent_id, "reason": "not_challenge_cup_role"})
            continue
        prior = entry.get("policy")
        normalized_prior = agent_directory_service.normalize_agent_context_compression_policy(
            prior if isinstance(prior, dict) else {}
        )
        if normalized_prior.get("mode") == "custom":
            restore = normalized_prior
        else:
            canonical = challenge_cup_role_context_policy(role_key)
            if canonical is None:
                skipped.append({"agentId": agent_id, "reason": "missing_canonical_policy"})
                continue
            restore = canonical
        agent_directory_service.update_agent_instance(
            agent_id,
            context_compression_policy=copy.deepcopy(restore),
        )
        restored.append(role_key)
    return {
        "restoredRoles": restored,
        "restoredCount": len(restored),
        "skipped": skipped,
    }
