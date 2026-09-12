"""Operator-only speaker lineage and validated discussion outcomes."""
from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from .contracts import Contract, Digest, Identity, OptimizationHypothesis, Text


class OperatorInvocationBinding(Contract):
    schemaVersion: Literal[1] = 1
    workflowId: Literal["operator-optimization"] = "operator-optimization"
    formalNodeId: Literal["optimization_discussion"] = "optimization_discussion"
    teamId: Identity
    researchProjectId: Identity
    optimizationCampaignId: Identity
    roundId: Identity
    workflowRunId: Identity
    workflowVersionId: Identity
    # The Ledger node owns the budget; each participant owns a distinct Turn.
    formalNodeRunId: Identity
    formalNodeAttempt: int = Field(ge=1, strict=True)
    sessionId: Identity
    taskId: Identity
    turnId: Identity
    participantId: Identity
    modelPolicySha256: Digest


class OperatorDiscussionResult(Contract):
    status: Literal["selected", "no_viable_hypothesis"]
    reason: Text
    hypothesis: OptimizationHypothesis | None = None

    @model_validator(mode="after")
    def outcome_has_exactly_its_payload(self):
        if (self.status == "selected") != (self.hypothesis is not None):
            raise ValueError("Only a selected result must contain one hypothesis")
        return self


class OperatorDiscussionMessage(Contract):
    schemaVersion: Literal[1] = 1
    contribution: Text
    result: OperatorDiscussionResult | None = None
