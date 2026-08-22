"""Real 125-question batch execution contract for Challenge Cup.

Pure contract layer: no routes, no storage, no network. It reuses the existing
``CatalogExecutionState`` state machine and binds real-run planning to the
frozen full-catalog execution policy (batch size, concurrency caps, circuit
breaker). It never launches anything itself; the service layer owns run
creation, command dispatch and harvesting.

Real plans unlock progressively (G1 -> G5 -> G12 -> G125). The previous gate's
batch must be fully succeeded before the next plan may start, and concurrency
above the frozen default additionally requires completed G12 evidence.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from core.research.competition.catalog_execution import (
    CatalogExecutionPlan,
    CatalogExecutionState,
    QuestionStatus,
    _validate_checkpoint_envelope,
    build_result_set,
    catalog_plan,
)
from core.research.competition.resources import (
    CompetitionResourceError,
    load_full_catalog_execution_core,
)
from core.research.competition.result_set import CatalogScope

REAL_PLAN_GATES: dict[str, str] = {
    "real-1": "G1",
    "real-5": "G5",
    "real-12": "G12",
    "real-125": "G125",
}
ALLOWED_REAL_BATCH_PLAN_IDS: tuple[str, ...] = tuple(REAL_PLAN_GATES)
GATE_ORDER: tuple[str, ...] = ("G1", "G5", "G12", "G125")
PREVIOUS_GATE: dict[str, str] = {
    "G5": "G1",
    "G12": "G5",
    "G125": "G12",
}
PREVIOUS_GATE_PLAN_ID: dict[str, str] = {
    "G5": "real-1",
    "G12": "real-5",
    "G125": "real-12",
}
DEFAULT_REAL_FAILURE_BUDGET = 3
MAX_REAL_START_ATTEMPTS = 3
REAL_BATCH_PROJECTION_SCHEMA_VERSION = 1

_TERMINAL_STATUSES = {
    QuestionStatus.SUCCEEDED,
    QuestionStatus.FAILED,
    QuestionStatus.BLOCKED,
}


class RealBatchError(ValueError):
    """A real catalog batch contract was violated."""


def validate_real_batch_plan(plan_id: str) -> str:
    """Validate a real batch plan id; unknown plans fail closed."""
    normalized = str(plan_id or "").strip()
    if normalized not in ALLOWED_REAL_BATCH_PLAN_IDS:
        raise RealBatchError(
            f"Unknown real batch plan: {plan_id!r}. Allowed: {ALLOWED_REAL_BATCH_PLAN_IDS}."
        )
    return normalized


def real_plan(plan_id: str) -> CatalogExecutionPlan:
    """Build the real execution plan bound to one progressive gate."""
    normalized = validate_real_batch_plan(plan_id)
    return catalog_plan(normalized, REAL_PLAN_GATES[normalized])


def new_real_batch_state(plan_id: str) -> CatalogExecutionState:
    """Create a fresh real batch state for one gate plan."""
    return CatalogExecutionState(
        plan=real_plan(plan_id),
        scope=CatalogScope.from_tracked_resources(),
    )


def frozen_execution_policy() -> dict[str, Any]:
    """Return the frozen execution policy; drift fails closed."""
    try:
        core = load_full_catalog_execution_core()
    except CompetitionResourceError as exc:
        raise RealBatchError(
            f"The frozen full-catalog execution policy is unavailable: {exc}"
        ) from exc
    policy = core.get("executionPolicy")
    if not isinstance(policy, dict):
        raise RealBatchError("The frozen execution policy is missing executionPolicy.")
    return dict(policy)


def _policy_int(policy: dict[str, Any], key: str) -> int:
    value = policy.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise RealBatchError(f"The frozen execution policy has an invalid {key}.")
    return value


def validate_real_concurrency(value: Any, *, above_default_allowed: bool) -> int:
    """Bound concurrency to the frozen policy: default cap unless G12 evidence."""
    policy = frozen_execution_policy()
    default_cap = _policy_int(policy, "defaultMaxConcurrentQuestionRuns")
    hard_cap = _policy_int(policy, "hardMaxConcurrentQuestionRuns")
    if hard_cap < default_cap:
        raise RealBatchError("The frozen execution policy has inverted concurrency caps.")
    try:
        normalized = int(value)
    except (TypeError, ValueError) as exc:
        raise RealBatchError("concurrency must be an integer.") from exc
    if normalized < 1 or normalized > hard_cap:
        raise RealBatchError(
            f"concurrency must be between 1 and the frozen hard cap {hard_cap}."
        )
    if normalized > default_cap and not above_default_allowed:
        raise RealBatchError(
            "concurrency above the frozen default requires completed G12 evidence."
        )
    return normalized


def validate_real_failure_budget(value: Any) -> int:
    try:
        normalized = int(value)
    except (TypeError, ValueError) as exc:
        raise RealBatchError("failureBudget must be an integer.") from exc
    if normalized < 1:
        raise RealBatchError("failureBudget must be at least 1.")
    return normalized


def circuit_breaker_tripped(consecutive_failures: int, *, failure_budget: int) -> bool:
    """Stop launching new questions once failures exceed the budget."""
    return int(consecutive_failures) >= int(failure_budget)


def count_consecutive_failures(outcomes: Sequence[dict[str, Any]]) -> int:
    """Count trailing failed items, stopping at the latest success/blocked."""
    streak = 0
    for item in reversed(list(outcomes)):
        if str(item.get("outcome") or "") == "failed":
            streak += 1
        else:
            break
    return streak


def project_real_batch_state(
    state: CatalogExecutionState,
    *,
    updated_at: str,
    run_refs: dict[str, dict[str, Any]] | None = None,
    awaiting_approval: dict[str, dict[str, Any]] | None = None,
    consecutive_failures: int = 0,
    failure_budget: int = DEFAULT_REAL_FAILURE_BUDGET,
    cancelled: bool = False,
) -> dict[str, Any]:
    """Project the real batch state into the typed public camelCase shape."""
    summary = state.outcome_summary()
    refs = dict(run_refs or {})
    awaiting = dict(awaiting_approval or {})
    completed_ids = [
        question_id
        for question_id in state.plan.question_ids
        if state.status(question_id) in _TERMINAL_STATUSES
    ]
    # Real runs stay RUNNING between calls, so the launchable backlog is the
    # untouched PENDING set; the shared pending view also lists in-flight items.
    pending_ids = [
        question_id
        for question_id in state.plan.question_ids
        if state.status(question_id) is QuestionStatus.PENDING
    ]
    checkpoint = state.to_checkpoint()
    checkpoint_sha256 = (
        str(checkpoint["checkpoint_sha256"]).strip().upper()
        if _validate_checkpoint_envelope(checkpoint)
        else ""
    )
    result_manifest = build_result_set(state).manifest()
    return {
        "schemaVersion": REAL_BATCH_PROJECTION_SCHEMA_VERSION,
        "planId": state.plan.plan_id,
        "gateId": state.plan.gate_id,
        "questionCount": len(state.plan.question_ids),
        "statusSummary": {
            "pending": summary["pending"],
            "running": summary["running"],
            "succeeded": summary["succeeded"],
            "failed": summary["failed"],
            "blocked": summary["blocked"],
        },
        "pendingCount": len(pending_ids),
        "succeededCount": summary["succeeded"],
        "failedCount": summary["failed"],
        "blockedCount": summary["blocked"],
        "totalAttempts": summary["total_attempts"],
        "completedQuestionIds": completed_ids,
        "pendingQuestionIds": pending_ids,
        "runRefs": {
            question_id: {
                "runId": str(entry.get("runId") or ""),
                "attempt": int(entry.get("attempt") or 0),
            }
            for question_id, entry in refs.items()
            if isinstance(entry, dict)
        },
        "awaitingApprovalQuestionIds": sorted(awaiting),
        "consecutiveFailures": int(consecutive_failures),
        "failureBudget": int(failure_budget),
        "circuitBreakerOpen": circuit_breaker_tripped(
            consecutive_failures, failure_budget=failure_budget
        ),
        "cancelled": bool(cancelled),
        "gateComplete": summary["succeeded"] == len(state.plan.question_ids),
        "checkpointSha256": checkpoint_sha256,
        "resultManifestSha256": result_manifest["manifest_sha256"],
        "packageQualitySummary": state.package_quality_summary(),
        "lastUpdatedAt": updated_at,
        "canResume": bool(pending_ids or awaiting) and not cancelled,
    }
