import json
from types import SimpleNamespace

import pytest

from tests.test_operator_optimization_budget import activity
from tests.test_operator_optimization_rounds import ready
from tests.test_operator_optimization_discussion import discussion_case
from core.research.operator_optimization.model_budget_contracts import OperatorDiscussionBudget
from core.web.services.team_workflow.operator_optimization import discussion_authority as authority
from core.web.services.team_workflow.operator_optimization.store import CampaignConflict


@pytest.fixture
def setup(activity, discussion_case, monkeypatch):
    campaign, run, _ = discussion_case
    run.workflow_version_id, run.status = "operator-v1", "running"
    snapshot = json.loads(run.input_snapshot_json)
    snapshot["agentBindingSnapshot"] = [{"nodeId": "optimization_discussion", "agentId": "planner"}]
    run.input_snapshot_json = json.dumps(snapshot)
    attempt = SimpleNamespace(node_run_id="node1", finished_at_ms=None, attempt=1)
    monkeypatch.setattr(authority, "get_write_store", lambda: SimpleNamespace(
        get_run=lambda _: run, latest_attempt=lambda *_: attempt))
    budget = OperatorDiscussionBudget(tokenLimit=1000, maxOutputTokensPerCall=100, maxCalls=3,
        prices=[dict(modelRef="provider/model", priceVersion="v1", currency="CNY", inputPerMillion=1, outputPerMillion=2)])
    campaign = campaign.model_copy(update={"budget": campaign.budget.model_copy(update={"discussion": budget})})
    monkeypatch.setattr(authority, "read_campaign", lambda *_: campaign)
    monkeypatch.setattr(authority.team_service, "get_team", lambda _: {"members": [
        {"agentId": "planner", "role": "experiment_planner"}, {"agentId": "reviewer", "role": "reviewer"}]})
    monkeypatch.setattr(authority.agent_directory_service, "get_agent", lambda agent_id, **_: {"agentId": agent_id})
    monkeypatch.setattr(authority.chat_room_service, "_resolve_chat_room_agent_llm", lambda _: SimpleNamespace(
        model_ref="provider/model", provider_id="provider", model="model"))
    return run, attempt


def test_server_setup_freezes_routes_planner_and_actual_attempt(activity, setup):
    run, _ = setup
    result = authority.build_operator_meeting_authority(activity[0], run.run_id, node_run_id="node1")
    assert result["participants"][-1]["agentId"] == result["finalAgentId"] == "planner"
    assert authority.validate_operator_authority(result) == result
    assert authority.build_operator_meeting_authority(activity[0], run.run_id, node_run_id="node1") == result
    for key in ("researchProjectId", "roundId", "nodeRunId"):
        with pytest.raises(CampaignConflict):
            authority.validate_operator_authority({**result, key: "other"})


def test_stopped_attempt_cannot_mint_speaker_authority(activity, setup):
    run, attempt = setup
    attempt.finished_at_ms = 1
    with pytest.raises(CampaignConflict, match="active node"):
        authority.build_operator_meeting_authority(activity[0], run.run_id, node_run_id="node1")


def test_operator_stop_fence_distinguishes_receipt_wait_from_user_block(activity, setup):
    run, _ = setup
    result = authority.build_operator_meeting_authority(activity[0], run.run_id, node_run_id="node1")
    run.status = "blocked"
    run.blocked_problem_json = json.dumps({"code": "agent_completion_dependency_pending"})
    assert authority.operator_workflow_stop_reason(result) == ""
    run.blocked_problem_json = json.dumps({"code": "user_block"})
    assert authority.operator_workflow_stop_reason(result) == "operator_workflow_blocked"
    run.status = "cancelled"
    assert authority.operator_workflow_stop_reason(result) == "operator_discussion_authority_inactive"
