"""Structured decision contract for the post-evidence operator loop."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Literal

from core.research.workflow.contracts._canonical import sha256_hex

from .contracts import ArtifactRef, Contract, Digest, Identity, Text

OPTIMIZATION_DECISION_ARTIFACT_KIND = "optimization_iteration_decision"

IterationAction = Literal[
    "discuss",
    "collect_knowledge",
    "plan_candidate",
    "retest",
    "repair_baseline",
    "stop",
]

ITERATION_ACTION_ROUTES: dict[str, str | None] = {
    "discuss": "optimization_discussion",
    "collect_knowledge": "optimization_knowledge",
    "plan_candidate": "optimization_plan",
    "retest": "operator_execution",
    "repair_baseline": "operator_baseline",
    "stop": None,
}


def iteration_route_for_action(action: IterationAction) -> str | None:
    """Return the single server-owned successor for an accepted action."""

    return ITERATION_ACTION_ROUTES[action]


def is_stage3_operator_run(run) -> bool:
    """True only for runs pinned to the v2 multi-action workflow contract."""

    from core.research.workflow.definition_registry import (
        WorkflowDefinitionRegistryError,
        resolve_definition_by_version_id,
    )

    try:
        definition = resolve_definition_by_version_id(run.workflow_version_id)
    except (AttributeError, WorkflowDefinitionRegistryError):
        return False
    return (
        definition.workflowId == "operator-optimization"
        and definition.schemaVersion == "1.2.0"
    )


def decision_id_for(run_id: str, feedback_ref: ArtifactRef | Mapping) -> str:
    payload = (
        feedback_ref.model_dump(mode="json")
        if isinstance(feedback_ref, ArtifactRef)
        else dict(feedback_ref)
    )
    return "decision-" + sha256_hex({"runId": run_id, "feedbackRef": payload})[:24]


class OperatorIterationDecisionProposal(Contract):
    """Untrusted model output; the service assigns evidence identity."""

    schemaVersion: Literal[2] = 2
    inputHash: Digest
    kind: IterationAction
    reason: Text


class OperatorIterationDecision(Contract):
    """One immutable decision bound to one durable feedback request."""

    schemaVersion: Literal[2] = 2
    decisionId: Identity
    kind: IterationAction
    reason: Text
    decidedBy: Identity


class OperatorIterationDecisionArtifact(Contract):
    """Canonical decision plus the exact evidence snapshot it consumed."""

    schemaVersion: Literal[2] = 2
    optimizationCampaignId: Identity
    roundId: Identity
    runId: Identity
    inputHash: Digest
    feedbackRef: ArtifactRef
    evaluationRef: ArtifactRef
    decision: OperatorIterationDecision


__all__ = [
    "OPTIMIZATION_DECISION_ARTIFACT_KIND",
    "OperatorIterationDecision",
    "OperatorIterationDecisionArtifact",
    "OperatorIterationDecisionProposal",
    "decision_id_for",
    "iteration_route_for_action",
    "is_stage3_operator_run",
]
