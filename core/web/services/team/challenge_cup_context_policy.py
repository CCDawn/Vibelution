"""Versioned context-compression policy contract for the six Challenge Cup roles.

Policy history:
    v1  inherit (unmaterialized; resolved to ``migration_required``/disabled)
    v2  ad-hoc custom policies with drifted limits (disabled / 1,000,000 /
        262,144 residue)
    v3  explicit, versioned custom policies aligned to the AutoDL
        GLM-5.3-flash window contract (conservative first round:
        window - 32,768 output - 8,192 protocol reserve, -16,384 trigger pad)
    v4  industry-shaped budget (current contract, this module). Same shape as
        the Claude Code / ZCode auto-compact policy
        (``zai-org/ZCode`` ``apps/zcode-cli/packages/core/src/compact/policy.ts``,
        Apache-2.0, design borrowed not code): reserve the model's own output
        cap only, keep a fixed 13,000-token trigger pad, and target two
        thirds of the remaining input budget.

Budget contract (frozen values, configurable via operator config):

    applied_output_reserve     = min(model_max_output | operator knob | 20,480, 20,480)
    effective_input_hard_limit = context_window - applied_output_reserve
    compression_trigger        = effective_input_hard_limit - 13,000
    post_compression_target    = effective_input_hard_limit * 2 / 3

With ``context_window=262,144`` and the capped/default output reserve of
20,480 this yields the frozen values 241,664 / 228,664 / 161,109.

Deliberately not conservative (operator decision 2026-09-21): the model's
own output reservation is the only structural deduction — the v3 protocol
reserve layer (−8,192) and the deeper trigger pad (−16,384) are retired, and
no path may fall back to a half-window derivation. The budget only changes
through this versioned contract; the version bump is what makes the
version-gated migration re-materialize already-deployed v3 roles onto the
new budget.
"""

from __future__ import annotations

import copy
from datetime import datetime, timezone
from typing import Any

CHALLENGE_CUP_CONTEXT_POLICY_VERSION = 4

# Contract reference window and budget constants (v4).
CONTEXT_WINDOW_TOKENS = 262_144
# Output reserve cap AND default: when the model's configured max output is
# unknown the budget still reserves the industry-standard 20,480.
MAX_OUTPUT_RESERVE_TOKENS = 20_480
TRIGGER_SAFETY_MARGIN_TOKENS = 13_000
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
) -> dict[str, int]:
    """Compute the versioned context budget for one model window.

    ``reserved_max_output_tokens`` is the model's configured max output (or
    an explicit override). It is capped at ``MAX_OUTPUT_RESERVE_TOKENS``;
    when unset it falls back to the operator knob
    ``context_compression.reserved_max_output_tokens`` and then to the same
    20,480 default, so an unconfigured model keeps a real output reservation.
    """

    if int(context_window or 0) <= 0:
        raise ValueError("context_window must be a positive token count")
    cc = _config_context_compression()
    if reserved_max_output_tokens is not None:
        requested_reserve = max(0, int(reserved_max_output_tokens))
    else:
        requested_reserve = max(0, _config_int(cc, "reserved_max_output_tokens"))
    applied_reserve = min(
        requested_reserve or MAX_OUTPUT_RESERVE_TOKENS,
        MAX_OUTPUT_RESERVE_TOKENS,
    )
    hard_limit = int(context_window) - applied_reserve
    if hard_limit <= 0:
        raise ValueError(
            "context budget is non-positive: window minus the output reserve must stay positive"
        )
    trigger = hard_limit - TRIGGER_SAFETY_MARGIN_TOKENS
    if trigger <= 0:
        raise ValueError("compression trigger must stay positive below the hard limit")
    target = int(hard_limit * POST_COMPRESSION_TARGET_RATIO)
    return {
        "contextWindow": int(context_window),
        "reservedMaxOutputTokens": applied_reserve,
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


def _policy_version(policy: Any) -> int:
    """Return the declared policy version, or 0 for legacy/unversioned data."""

    if not isinstance(policy, dict):
        return 0
    try:
        return max(0, int(policy.get("policyVersion") or 0))
    except (TypeError, ValueError):
        return 0


def challenge_cup_context_policies_outdated() -> bool:
    """Return whether any managed role still runs below the contract version.

    Registry read failures propagate to the caller on purpose: the bootstrap
    hook owns the fail-soft decision so a broken registry can never be
    mistaken for "already migrated".
    """

    for _role_key, agent in _challenge_cup_role_agents():
        version = _policy_version(agent.get("contextCompressionPolicy"))
        if version < CHALLENGE_CUP_CONTEXT_POLICY_VERSION:
            return True
    return False


def apply_challenge_cup_context_policies(
    *,
    snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """One-time version-gated migration onto the explicit v3 policies.

    Only roles whose current policy has no ``policyVersion`` or a version
    below ``CHALLENGE_CUP_CONTEXT_POLICY_VERSION`` are migrated to the
    canonical contract. Roles already at the current version are never
    overwritten: an exact canonical match is reported as ``skipped_current``
    while any other current-version policy is treated as a deliberate
    operator customization (``skipped_custom``). The pre-change snapshot is
    exported before the first actual write so rollback can restore the
    explicit prior policies.
    """

    from core.web.services import agent_directory_service

    plans: list[tuple[str, str, dict[str, Any]]] = []
    skipped_current: list[str] = []
    skipped_custom: list[str] = []
    for role_key, agent in _challenge_cup_role_agents():
        target = challenge_cup_role_context_policy(role_key)
        if target is None:
            continue
        agent_id = str(agent.get("agentId") or "").strip()
        if not agent_id:
            continue
        current = agent.get("contextCompressionPolicy")
        if _policy_version(current) >= CHALLENGE_CUP_CONTEXT_POLICY_VERSION:
            normalized_current = agent_directory_service.normalize_agent_context_compression_policy(
                current if isinstance(current, dict) else {}
            )
            normalized_target = agent_directory_service.normalize_agent_context_compression_policy(target)
            if normalized_current == normalized_target:
                skipped_current.append(role_key)
            else:
                skipped_custom.append(role_key)
            continue
        plans.append((role_key, agent_id, target))

    result: dict[str, Any] = {
        "policyVersion": CHALLENGE_CUP_CONTEXT_POLICY_VERSION,
        "migratedRoles": [],
        "skippedCurrentRoles": skipped_current,
        "skippedCustomRoles": skipped_custom,
        "migratedCount": 0,
        "snapshotExported": False,
    }
    if snapshot is not None:
        result["snapshot"] = snapshot
    if not plans:
        return result
    safe_snapshot = snapshot or export_challenge_cup_context_policy_snapshot()
    migrated_roles: list[str] = []
    for role_key, agent_id, target in plans:
        agent_directory_service.update_agent_instance(
            agent_id,
            context_compression_policy=copy.deepcopy(target),
        )
        migrated_roles.append(role_key)
    result.update(
        {
            "snapshot": safe_snapshot,
            "snapshotExported": snapshot is None,
            "migratedRoles": migrated_roles,
            "migratedCount": len(migrated_roles),
        }
    )
    return result


def rollback_challenge_cup_context_policies(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Restore the pre-migration policies captured in ``snapshot``.

    Rollback never restores ``inherit``: a prior policy that was
    ``inherit``/unmaterialized falls back to the canonical versioned custom
    policy so the role stays explicitly configured. A restored prior custom
    policy is stamped with the current contract version (when older) so the
    version gate treats it as a deliberate choice and never re-migrates the
    rolled-back role on the next bootstrap.
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
            prior_version = _policy_version(restore)
            if prior_version < CHALLENGE_CUP_CONTEXT_POLICY_VERSION:
                restore["policyVersion"] = CHALLENGE_CUP_CONTEXT_POLICY_VERSION
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
