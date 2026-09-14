"""Single native decision Agent identity, independent of discussion speakers."""

from typing import Literal

from pydantic import Field

from .contracts import Contract, Digest, Identity


class OperatorDecisionInvocationBinding(Contract):
    schemaVersion: Literal[1] = 1
    accountingKind: Literal["operator_decision"] = "operator_decision"
    workflowId: Literal["operator-optimization"] = "operator-optimization"
    formalNodeId: Literal["optimization_decision"] = "optimization_decision"
    questionId: Literal["OPERATOR-SOFTMAX"] = "OPERATOR-SOFTMAX"
    teamId: Identity
    researchProjectId: Identity
    optimizationCampaignId: Identity
    roundId: Identity
    workflowRunId: Identity
    workflowVersionId: Identity
    formalNodeRunId: Identity
    formalNodeAttempt: int = Field(ge=1, strict=True)
    sessionId: Identity
    taskId: Identity
    turnId: Identity
    inputHash: Digest
    modelPolicySha256: Digest
