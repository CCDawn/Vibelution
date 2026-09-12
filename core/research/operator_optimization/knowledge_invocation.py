"""Real source-child identity for operator model accounting."""
from typing import Literal

from pydantic import Field

from .candidate import Contract, Digest, Identity


class OperatorKnowledgeInvocationBinding(Contract):
    schemaVersion: Literal[1] = 1
    accountingKind: Literal["operator_knowledge"] = "operator_knowledge"
    workflowId: Literal["challenge-cup-knowledge-sideflow"] = "challenge-cup-knowledge-sideflow"
    formalNodeId: Literal["source_finding", "source_extraction", "evidence_relations", "knowledge_ingestion"]
    questionId: Literal["OPERATOR-SOFTMAX"] = "OPERATOR-SOFTMAX"
    teamId: Identity
    researchProjectId: Identity
    optimizationCampaignId: Identity
    roundId: Identity
    parentRunId: Identity
    parentNodeRunId: Identity
    knowledgeInvocationId: Identity
    requestHash: Digest
    workflowRunId: Identity
    workflowVersionId: Identity
    formalNodeRunId: Identity
    formalNodeAttempt: int = Field(ge=1, strict=True)
    sessionId: Identity
    taskId: Identity
    turnId: Identity
    modelPolicySha256: Digest


def parse_operator_invocation_binding(payload):
    if payload.get("workflowId") == "challenge-cup-knowledge-sideflow":
        return OperatorKnowledgeInvocationBinding.model_validate(payload)
    from .discussion_contracts import OperatorInvocationBinding

    return OperatorInvocationBinding.model_validate(payload)
