"""Structured decision contract for the post-evidence operator loop."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Literal

from core.research.workflow.contracts._canonical import sha256_hex

from .contracts import ArtifactRef, Contract, Digest, Identity, Text

OPTIMIZATION_DECISION_ARTIFACT_KIND = "optimization_iteration_decision"


def decision_id_for(run_id: str, feedback_ref: ArtifactRef | Mapping) -> str:
    payload = (
        feedback_ref.model_dump(mode="json")
        if isinstance(feedback_ref, ArtifactRef)
        else dict(feedback_ref)
    )
    return "decision-" + sha256_hex({"runId": run_id, "feedbackRef": payload})[:24]


class OperatorIterationDecisionProposal(Contract):
    """Untrusted model output; the service assigns evidence identity."""

    schemaVersion: Literal[1] = 1
    inputHash: Digest
    kind: Literal["continue", "stop"]
    reason: Text


class OperatorIterationDecision(Contract):
    """One immutable decision bound to one durable feedback request."""

    schemaVersion: Literal[1] = 1
    decisionId: Identity
    kind: Literal["continue", "stop"]
    reason: Text
    decidedBy: Identity


class OperatorIterationDecisionArtifact(Contract):
    """Canonical decision plus the exact evidence snapshot it consumed."""

    schemaVersion: Literal[1] = 1
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
]
