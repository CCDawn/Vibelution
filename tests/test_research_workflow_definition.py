from core.research.workflow.definition import build_challenge_cup_workflow_definition
from core.research.workflow.models import NodeSessionScopePolicy


def test_only_hypothesis_design_uses_candidate_session_fan_out() -> None:
    definition = build_challenge_cup_workflow_definition()
    policies = {node.nodeId: node.sessionScopePolicy for node in definition.nodes}

    assert policies["hypothesis_design"] is NodeSessionScopePolicy.CANDIDATE_FAN_OUT
    assert all(
        policy is NodeSessionScopePolicy.NODE_SHARED
        for node_id, policy in policies.items()
        if node_id != "hypothesis_design"
    )
    projected = next(
        node.to_dict()
        for node in definition.nodes
        if node.nodeId == "hypothesis_design"
    )
    assert projected["sessionScopePolicy"] == "candidate_fan_out"
