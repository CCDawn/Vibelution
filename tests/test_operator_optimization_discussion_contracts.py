import pytest
from pydantic import ValidationError

from core.research.operator_optimization.discussion_contracts import (
    OperatorDiscussionResult,
    OperatorInvocationBinding,
)


def binding(**changes):
    return OperatorInvocationBinding.model_validate(dict(
        teamId="team1", researchProjectId="project1", optimizationCampaignId="campaign1",
        roundId="round1", workflowRunId="run1", workflowVersionId="version1",
        formalNodeRunId="node1", formalNodeAttempt=1, sessionId="session1",
        taskId="speaker1", turnId="chat-room:round1:participant1", participantId="participant1",
        modelPolicySha256="a" * 64, **changes,
    ))


def test_binding_keeps_operator_scope_and_real_node_budget_identity():
    value = binding()
    assert value.workflowId == "operator-optimization"
    assert value.formalNodeId == "optimization_discussion"
    assert value.model_dump()["formalNodeRunId"] == "node1"
    assert value.participantId == "participant1"


@pytest.mark.parametrize("field,value", [
    ("workflowId", "challenge-cup-research"), ("formalNodeId", "hypothesis_design"),
    ("modelPolicySha256", "unverified"),
])
def test_binding_rejects_other_workflow_or_unverified_policy(field, value):
    data = binding().model_dump()
    data[field] = value
    with pytest.raises(ValidationError):
        OperatorInvocationBinding.model_validate(data)


def test_no_viable_hypothesis_is_explicit_and_does_not_fabricate_one():
    result = OperatorDiscussionResult(status="no_viable_hypothesis", reason="Baseline evidence is inconclusive")
    assert result.hypothesis is None
    with pytest.raises(ValidationError):
        OperatorDiscussionResult(status="selected", reason="promising")
