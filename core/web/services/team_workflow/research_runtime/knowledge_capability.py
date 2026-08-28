"""Workflow-owned capability policy for knowledge sideflow stage actions.

The knowledge-collection child run executes its five stage nodes without a
human in the loop, yet every action it takes must remain inside a
server-granted envelope (plan §4.6).  The command service (the single write
entry) issues **restricted capabilities**: each capability is bound to one
child run + node lineage, a whitelist of managed source roots, a budget
(action / retry counters plus an absolute expiry) and the policy matrix
below.  ``authorize_stage_action`` is the fail-closed gate every stage
action must pass; ``record_stage_action`` is the only way to consume
budget, and capabilities are immutable so consumption always produces a new
record.

Hard boundaries:

- A capability authorizes STAGE actions only.  The ad-hoc Agent tool path
  (``tool_catalog`` / ``tool_approvals``) never consults capabilities and
  never shares the action vocabulary, so a capability can never be replayed
  as a tool approval — knowledge collection/request tools stay HIGH-tier
  fail-closed for ad-hoc use.
- ``operator_only`` actions are denied at this entry unconditionally; they
  remain reachable exclusively through the workflow command service's
  operator authorization.
- ``human_gate`` actions are denied unless the caller presents a durable
  human-gate receipt id (an accepted human task), matching the
  knowledge-package handoff semantics.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, replace
from enum import Enum
from typing import Any, Mapping


def _new_capability_id() -> str:
    """Capability ids are capability-namespace scoped; they deliberately do
    not extend the ledger's fixed ``new_id`` prefix registry (spec 5.6)."""
    return f"kcap-{uuid.uuid4().hex}"


class CapabilityPolicyClass(str, Enum):
    AUTO_ALLOWED = "auto_allowed"
    HUMAN_GATE = "human_gate"
    OPERATOR_ONLY = "operator_only"
    BLOCKED = "blocked"


# ------------------------------------------------------------- action names

# auto_allowed: safe reads inside registered roots, allowed type resolution,
# controlled retrieval, staging DataRecords, in-budget retries.
READ_MANAGED_ROOT = "read_managed_root"
RESOLVE_EVIDENCE_TYPE = "resolve_evidence_type"
CONTROLLED_SEARCH = "controlled_search"
STAGE_DATA_RECORD = "stage_data_record"
RETRY_WITHIN_BUDGET = "retry_within_budget"

# human_gate: package handoff, adding a managed root, source policy upgrade,
# over-budget retries — a human decision is required first.
KNOWLEDGE_HANDOFF = "knowledge_handoff"
ADD_MANAGED_ROOT = "add_managed_root"
UPGRADE_SOURCE_POLICY = "upgrade_source_policy"
RETRY_OVER_BUDGET = "retry_over_budget"

# operator_only: only the operator command path may perform these.
CANCEL_RUN = "cancel_run"
ARCHIVE_RUN = "archive_run"
FORCE_RECONCILIATION = "force_reconciliation"
DEFINE_MIGRATION = "define_migration"
CHANGE_PERMISSIONS = "change_permissions"

# blocked: never grantable, never executable inside the sideflow.
RUN_MACRO = "run_macro"
RUN_OLE = "run_ole"
RUN_ACTIVEX = "run_activex"
RUN_EXECUTABLE = "run_executable"
PATH_ESCAPE = "path_escape"
ZIP_BOMB = "zip_bomb"
HASH_MISMATCH = "hash_mismatch"
DEFINITION_MISMATCH = "definition_mismatch"

AUTO_ALLOWED_ACTIONS: frozenset[str] = frozenset(
    {
        READ_MANAGED_ROOT,
        RESOLVE_EVIDENCE_TYPE,
        CONTROLLED_SEARCH,
        STAGE_DATA_RECORD,
        RETRY_WITHIN_BUDGET,
    }
)
HUMAN_GATE_ACTIONS: frozenset[str] = frozenset(
    {
        KNOWLEDGE_HANDOFF,
        ADD_MANAGED_ROOT,
        UPGRADE_SOURCE_POLICY,
        RETRY_OVER_BUDGET,
    }
)
OPERATOR_ONLY_ACTIONS: frozenset[str] = frozenset(
    {
        CANCEL_RUN,
        ARCHIVE_RUN,
        FORCE_RECONCILIATION,
        DEFINE_MIGRATION,
        CHANGE_PERMISSIONS,
    }
)
BLOCKED_ACTIONS: frozenset[str] = frozenset(
    {
        RUN_MACRO,
        RUN_OLE,
        RUN_ACTIVEX,
        RUN_EXECUTABLE,
        PATH_ESCAPE,
        ZIP_BOMB,
        HASH_MISMATCH,
        DEFINITION_MISMATCH,
    }
)

CAPABILITY_ACTION_POLICY: dict[str, CapabilityPolicyClass] = {
    **{action: CapabilityPolicyClass.AUTO_ALLOWED for action in AUTO_ALLOWED_ACTIONS},
    **{action: CapabilityPolicyClass.HUMAN_GATE for action in HUMAN_GATE_ACTIONS},
    **{action: CapabilityPolicyClass.OPERATOR_ONLY for action in OPERATOR_ONLY_ACTIONS},
    **{action: CapabilityPolicyClass.BLOCKED for action in BLOCKED_ACTIONS},
}

# Actions that touch managed-root content must name a whitelisted root.
ROOT_SCOPED_ACTIONS: frozenset[str] = frozenset({READ_MANAGED_ROOT, STAGE_DATA_RECORD})

DEFAULT_STAGE_BUDGET_MAX_ACTIONS = 64
DEFAULT_STAGE_BUDGET_MAX_RETRIES = 2
DEFAULT_STAGE_BUDGET_TTL_MS = 24 * 60 * 60 * 1000


# ------------------------------------------------------------- capability


@dataclass(frozen=True, slots=True)
class KnowledgeCapabilityBudget:
    max_actions: int
    actions_used: int = 0
    max_retries: int = DEFAULT_STAGE_BUDGET_MAX_RETRIES
    retries_used: int = 0
    expires_at_ms: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "maxActions": self.max_actions,
            "actionsUsed": self.actions_used,
            "maxRetries": self.max_retries,
            "retriesUsed": self.retries_used,
            "expiresAtMs": self.expires_at_ms,
        }


@dataclass(frozen=True, slots=True)
class KnowledgeCapability:
    """A restricted, server-owned grant for one sideflow stage lineage."""

    capability_id: str
    run_id: str
    node_id: str
    actions: frozenset[str]
    allowed_root_ids: frozenset[str]
    budget: KnowledgeCapabilityBudget
    issued_by: str = "knowledge-command-service"
    audience: str = "workflow_stage"
    issued_at_ms: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "capabilityId": self.capability_id,
            "runId": self.run_id,
            "nodeId": self.node_id,
            "actions": sorted(self.actions),
            "allowedRootIds": sorted(self.allowed_root_ids),
            "budget": self.budget.to_dict(),
            "issuedBy": self.issued_by,
            "audience": self.audience,
            "issuedAtMs": self.issued_at_ms,
        }


def issue_knowledge_capability(
    *,
    run_id: str,
    node_id: str,
    root_ids: Mapping[str, Any] | list[Any] | tuple[Any, ...] | None = None,
    actions: frozenset[str] | None = None,
    max_actions: int = DEFAULT_STAGE_BUDGET_MAX_ACTIONS,
    max_retries: int = DEFAULT_STAGE_BUDGET_MAX_RETRIES,
    issued_at_ms: int = 0,
    ttl_ms: int = DEFAULT_STAGE_BUDGET_TTL_MS,
    capability_id: str | None = None,
) -> KnowledgeCapability:
    """Server-owned issuance.  Grantable actions are restricted to the
    ``auto_allowed`` set — human-gate / operator-only / blocked actions can
    never appear on an issued capability."""
    grantable = tuple(
        sorted(
            action
            for action in (actions or AUTO_ALLOWED_ACTIONS)
            if CAPABILITY_ACTION_POLICY.get(action) is CapabilityPolicyClass.AUTO_ALLOWED
        )
    )
    unknown = sorted(
        action
        for action in (actions or ())
        if CAPABILITY_ACTION_POLICY.get(action) is not CapabilityPolicyClass.AUTO_ALLOWED
    )
    if unknown:
        raise ValueError(
            f"actions are not grantable via capability: {unknown}"
        )
    if not grantable:
        raise ValueError("capability must grant at least one auto_allowed action")
    expires_at = (
        int(issued_at_ms) + int(ttl_ms)
        if ttl_ms and ttl_ms > 0
        else None
    )
    return KnowledgeCapability(
        capability_id=capability_id or _new_capability_id(),
        run_id=str(run_id or ""),
        node_id=str(node_id or ""),
        actions=frozenset(grantable),
        allowed_root_ids=frozenset(normalize_root_ids(root_ids)),
        budget=KnowledgeCapabilityBudget(
            max_actions=max(int(max_actions), 1),
            max_retries=max(int(max_retries), 0),
            expires_at_ms=expires_at,
        ),
        issued_at_ms=int(issued_at_ms),
    )


def normalize_root_ids(raw: Any) -> list[str]:
    """Lower-cased, trimmed, de-duplicated root ids (mirrors the managed-root
    request normalization so a capability whitelist can never disagree with
    the registry selection format)."""
    if isinstance(raw, Mapping):
        raw = raw.get("rootIds")
    if not isinstance(raw, (list, tuple, set, frozenset)):
        return []
    normalized: list[str] = []
    for item in list(raw)[:32]:
        if not isinstance(item, str):
            continue
        root_id = item.strip().lower()[:64]
        if root_id and root_id not in normalized:
            normalized.append(root_id)
    return normalized


# ------------------------------------------------------------- authorization


@dataclass(frozen=True, slots=True)
class StageActionContext:
    """Server-side facts about one attempted stage action."""

    run_id: str
    node_id: str
    now_ms: int = 0
    root_id: str = ""
    human_gate_receipt_id: str = ""


@dataclass(frozen=True, slots=True)
class CapabilityDecision:
    allowed: bool
    code: str
    detail: str
    policy_class: CapabilityPolicyClass | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "code": self.code,
            "detail": self.detail,
            "policyClass": (
                self.policy_class.value if self.policy_class is not None else None
            ),
        }


_DENY = CapabilityDecision  # readability alias


def authorize_stage_action(
    capability: KnowledgeCapability,
    action: str,
    context: StageActionContext,
) -> CapabilityDecision:
    """Fail-closed gate for one sideflow stage action.

    Denial order: unknown action -> policy blocked -> operator-only ->
    human gate -> run/node binding -> expiry -> budget -> root whitelist.
    A capability never grants anything outside its own run/node/roots/
    budget/expiry envelope, and it can never authorize ad-hoc tool calls
    (they are not stage actions).
    """
    action_key = str(action or "").strip()
    policy_class = CAPABILITY_ACTION_POLICY.get(action_key)
    if policy_class is None:
        return _DENY(
            allowed=False,
            code="unknown_action",
            detail=f"action {action_key!r} is not a workflow stage action",
        )
    if policy_class is CapabilityPolicyClass.BLOCKED:
        return _DENY(
            allowed=False,
            code="policy_blocked",
            detail=f"action {action_key!r} is blocked by the capability policy matrix",
            policy_class=policy_class,
        )
    if policy_class is CapabilityPolicyClass.OPERATOR_ONLY:
        return _DENY(
            allowed=False,
            code="operator_command_required",
            detail=(
                f"action {action_key!r} requires the operator command path; "
                "capabilities never authorize it"
            ),
            policy_class=policy_class,
        )
    if policy_class is CapabilityPolicyClass.HUMAN_GATE:
        receipt_id = str(context.human_gate_receipt_id or "").strip()
        if not receipt_id:
            return _DENY(
                allowed=False,
                code="human_gate_required",
                detail=(
                    f"action {action_key!r} requires an accepted human gate "
                    "receipt; capabilities alone never satisfy it"
                ),
                policy_class=policy_class,
            )
    if str(context.run_id or "") != str(capability.run_id or ""):
        return _DENY(
            allowed=False,
            code="run_binding_mismatch",
            detail="capability is bound to a different run",
        )
    if str(context.node_id or "") != str(capability.node_id or ""):
        return _DENY(
            allowed=False,
            code="node_binding_mismatch",
            detail="capability is bound to a different node",
        )
    if action_key not in capability.actions:
        return _DENY(
            allowed=False,
            code="action_not_granted",
            detail=f"capability does not grant {action_key!r}",
        )
    expires_at = capability.budget.expires_at_ms
    if expires_at is not None and int(context.now_ms or 0) >= int(expires_at):
        return _DENY(
            allowed=False,
            code="capability_expired",
            detail=f"capability expired at {expires_at}",
        )
    if capability.budget.actions_used >= capability.budget.max_actions:
        return _DENY(
            allowed=False,
            code="budget_exhausted",
            detail=(
                f"action budget exhausted "
                f"({capability.budget.actions_used}/{capability.budget.max_actions})"
            ),
        )
    if action_key in ROOT_SCOPED_ACTIONS:
        root_id = str(context.root_id or "").strip().lower()
        if not root_id:
            return _DENY(
                allowed=False,
                code="root_not_specified",
                detail=f"action {action_key!r} requires a managed root id",
            )
        if root_id not in capability.allowed_root_ids:
            return _DENY(
                allowed=False,
                code="root_outside_allowlist",
                detail=f"managed root {root_id!r} is not in the capability whitelist",
            )
    return CapabilityDecision(
        allowed=True,
        code="allowed",
        detail="authorized by workflow-owned capability",
        policy_class=policy_class,
    )


def record_stage_action(
    capability: KnowledgeCapability,
    action: str,
    *,
    retry: bool = False,
) -> KnowledgeCapability:
    """Consume budget for an executed stage action (fail-closed on overrun).

    Returns a NEW immutable capability; the caller must persist/use the
    returned record for subsequent authorizations.
    """
    action_key = str(action or "").strip()
    if action_key not in capability.actions:
        raise ValueError(
            f"action {action_key!r} was not granted on this capability"
        )
    budget = capability.budget
    if budget.actions_used >= budget.max_actions:
        raise ValueError("action budget exhausted")
    if retry and budget.retries_used >= budget.max_retries:
        raise ValueError("retry budget exhausted")
    return replace(
        capability,
        budget=replace(
            budget,
            actions_used=budget.actions_used + 1,
            retries_used=budget.retries_used + (1 if retry else 0),
        ),
    )


def capability_summary(capability: KnowledgeCapability) -> dict[str, Any]:
    """Snapshot for receipts / inspection payloads."""
    return capability.to_dict()
