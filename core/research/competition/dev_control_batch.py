"""DEV fixture batch execution and checkpoint projection for Challenge Cup.

Pure contract layer: no routes, no storage, no network. It reuses the existing
``CatalogExecutionState`` state machine and the existing ``challenge_cup_dispatcher``
fixture adapters. It never invokes real Qwen, CUDA/GPU, DANDI or a formal
submission, and it rejects dev-12 / dev-125 and formal/real scopes fail-closed.
"""

from __future__ import annotations

from typing import Any, Callable

from core.research.competition.catalog_execution import (
    CatalogExecutionError,
    CatalogExecutionState,
    QuestionStatus,
    dev_plan,
    run_pending_batch,
)
from core.research.competition.result_set import CatalogScope, QuestionResult
from core.research.experiment_adapters import (
    ControlledLocator,
    ExperimentContract,
    ExperimentOutcome,
    challenge_cup_dispatcher,
)
from core.research.workflow.contracts import ResearchScopeEnvelope, scope_hash_for

ALLOWED_DEV_BATCH_PLAN_IDS: tuple[str, ...] = ("dev-1", "dev-5")
FORBIDDEN_DEV_BATCH_PLAN_IDS: tuple[str, ...] = ("dev-12", "dev-125")
MAX_DEV_BATCH_MAX_ITEMS = 5
BATCH_PROJECTION_SCHEMA_VERSION = 1

DEV_PROGRAM_ID = "XH-202619"
DEV_AGENT_ID = "agent-dev-platform"
GPU_ADAPTER = "gpu_operator_benchmark"
NEURAL_ADAPTER = "neural_spike_coding"
FASHION_ADAPTER = "fashion_mnist_predictive_coding_multi_seed"

_TERMINAL_STATUSES = {
    QuestionStatus.SUCCEEDED,
    QuestionStatus.FAILED,
    QuestionStatus.BLOCKED,
}


class DevBatchError(ValueError):
    """A Challenge Cup DEV batch contract was violated."""


def validate_dev_batch_plan(plan_id: str) -> str:
    """Validate a DEV fixture plan id; dev-12/dev-125 and unknown plans fail closed."""
    normalized = str(plan_id or "").strip()
    if normalized in FORBIDDEN_DEV_BATCH_PLAN_IDS:
        raise DevBatchError(
            f"DEV batch plan {normalized} is not authorized on the DEV platform."
        )
    if normalized not in ALLOWED_DEV_BATCH_PLAN_IDS:
        raise DevBatchError(f"Unknown DEV batch plan: {plan_id!r}.")
    return normalized


def validate_dev_batch_max_items(max_items: int | None) -> int | None:
    """Bound maxItems to the DEV batch cap; None means run all remaining items."""
    if max_items is None:
        return None
    try:
        value = int(max_items)
    except (TypeError, ValueError) as exc:
        raise DevBatchError("maxItems must be an integer.") from exc
    if value < 0 or value > MAX_DEV_BATCH_MAX_ITEMS:
        raise DevBatchError(f"maxItems must be between 0 and {MAX_DEV_BATCH_MAX_ITEMS}.")
    return value


def new_dev_batch_state(plan_id: str) -> CatalogExecutionState:
    """Create a fresh DEV fixture batch state for one authorized plan."""
    return CatalogExecutionState(
        plan=dev_plan(plan_id),
        scope=CatalogScope.from_tracked_resources(),
    )


def _fixture_identity(question_id: str) -> dict[str, str]:
    if question_id == "SCI-091":
        return {
            "theme": "cc-gpu-operator-001",
            "campaign": "cc-campaign-gpu-operator-001",
            "question": "SCI-091",
            "adapter": GPU_ADAPTER,
            "method": "computational_kernel_benchmark",
        }
    if question_id == "SCI-096":
        return {
            "theme": "cc-neural-information-001",
            "campaign": "cc-campaign-neural-spike-001",
            "question": "SCI-096",
            "adapter": NEURAL_ADAPTER,
            "method": "dataset_analysis_benchmark",
        }
    return {
        "theme": "cc-neural-information-001",
        "campaign": "cc-campaign-neural-spike-001",
        "question": question_id,
        "adapter": FASHION_ADAPTER,
        "method": "model_training_inference",
    }


def _fixture_scope(question_id: str) -> ResearchScopeEnvelope:
    identity = _fixture_identity(question_id)
    digest = scope_hash_for(
        program=DEV_PROGRAM_ID,
        theme=identity["theme"],
        campaign=identity["campaign"],
        question=identity["question"],
        branch="main",
        workflow="hypothesis_and_plan",
        agent_id=DEV_AGENT_ID,
        mode="dev",
    )
    return ResearchScopeEnvelope.from_dict(
        {
            "program": DEV_PROGRAM_ID,
            "theme": identity["theme"],
            "campaign": identity["campaign"],
            "question": identity["question"],
            "branch": "main",
            "workflow": "hypothesis_and_plan",
            "agentId": DEV_AGENT_ID,
            "mode": "dev",
            "scopeHash": digest,
            "artifactLocator": f"research-artifact://{DEV_PROGRAM_ID}/{digest}",
            "ledgerRoot": f"research-ledger://{DEV_PROGRAM_ID}/{digest}",
            "cacheKey": f"scope:{digest}:main:{DEV_AGENT_ID}",
        }
    )


def _fixture_contract(*, plan_id: str, method: str, question: str) -> ExperimentContract:
    return ExperimentContract.from_payload(
        {
            "schemaVersion": 2,
            "planId": plan_id,
            "teamId": "dev-platform",
            "experimentMethod": method,
            "researchQuestion": f"{question} DEV fixture",
            "methodConfig": {"runMode": "dev_fixture", "dataset": "synthetic"},
            "metricContract": {
                "primaryMetric": "fixture_score",
                "metrics": [{"name": "fixture_score"}],
            },
        }
    )


def _fixture_locator(plan_id: str, question_id: str) -> ControlledLocator:
    return ControlledLocator(
        kind="offline",
        relativePath=f"offline/challenge-cup-dev/{plan_id}/{question_id}",
    )


def execute_dev_fixture_question(
    state: CatalogExecutionState,
    question_id: str,
) -> QuestionResult:
    """Run one question through the challenge_cup_dispatcher DEV fixture adapters.

    A non-fixture outcome fails closed so the state machine records the item as
    failed instead of polluting neighbors. DEV results are never
    submission-eligible.
    """
    identity = _fixture_identity(question_id)
    result = challenge_cup_dispatcher().dispatch(
        scope=_fixture_scope(question_id),
        contract=_fixture_contract(
            plan_id=state.plan.plan_id,
            method=identity["method"],
            question=identity["question"],
        ),
        locator=_fixture_locator(state.plan.plan_id, question_id),
        adapter_id=identity["adapter"],
    )
    if result.outcome not in (ExperimentOutcome.COMPLETED, ExperimentOutcome.PARTIAL):
        raise CatalogExecutionError(
            f"{question_id}: fixture outcome={result.outcome.value}: {result.message}"
        )
    return QuestionResult.create(
        scope=state.scope,
        question_id=question_id,
        model_receipt_locator=f"model-receipt://dev/{result.adapterId}/{result.resultId}",
        knowledge_locator=f"knowledge://dev/{question_id}",
        status="dev_fixture",
        submission_eligible=False,
    )


def run_dev_fixture_batch(
    state: CatalogExecutionState,
    *,
    max_items: int | None = None,
    on_item: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Run a bounded DEV fixture batch, one item at a time.

    ``on_item`` is invoked after every completed/failed item so the caller can
    persist the serialized checkpoint before the next item starts. Succeeded
    items are never re-run on resume because ``pending_question_ids`` excludes
    them.
    """
    bounded = validate_dev_batch_max_items(max_items)
    if bounded == 0:
        return {"attempted": [], "outcomes": [], "summary": state.outcome_summary()}
    attempted: list[str] = []
    outcomes: list[dict[str, Any]] = []
    while bounded is None or len(outcomes) < bounded:
        batch = run_pending_batch(
            state,
            lambda question_id: execute_dev_fixture_question(state, question_id),
            max_items=1,
        )
        if not batch["outcomes"]:
            break
        attempted.extend(batch["attempted"])
        item = batch["outcomes"][0]
        outcomes.append(item)
        if on_item is not None:
            on_item(item)
    return {"attempted": attempted, "outcomes": outcomes, "summary": state.outcome_summary()}


def project_dev_batch_state(
    state: CatalogExecutionState,
    *,
    updated_at: str,
) -> dict[str, Any]:
    summary = state.outcome_summary()
    completed_ids = [
        question_id
        for question_id in state.plan.question_ids
        if state.status(question_id) in _TERMINAL_STATUSES
    ]
    return {
        "schemaVersion": BATCH_PROJECTION_SCHEMA_VERSION,
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
        "pendingCount": len(state.pending_question_ids()),
        "succeededCount": summary["succeeded"],
        "failedCount": summary["failed"],
        "blockedCount": summary["blocked"],
        "totalAttempts": summary["total_attempts"],
        "completedQuestionIds": completed_ids,
        "pendingQuestionIds": list(state.pending_question_ids()),
        "lastUpdatedAt": updated_at,
        "canResume": bool(state.pending_question_ids()),
    }


def project_dev_batch_checkpoint(
    checkpoint: dict[str, Any],
    *,
    updated_at: str,
) -> dict[str, Any]:
    state = CatalogExecutionState.from_checkpoint(checkpoint)
    return project_dev_batch_state(state, updated_at=updated_at)