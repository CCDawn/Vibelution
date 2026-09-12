from types import SimpleNamespace
from unittest.mock import Mock
import pytest

from core.web.services.team_workflow.operator_optimization import discussion_task as task
from core.web.services.team_workflow.research_runtime.completion_dependency import CompletionDependencyPending
from core.web.services.team_workflow.research_runtime.real_domain_ports import RealDomainPorts


@pytest.fixture
def meeting(monkeypatch):
    action = SimpleNamespace(run_id="run1", node_run_id="node1", node_id="optimization_discussion")
    authority = {"workflowRunId": "run1", "nodeRunId": "node1", "nodeAttempt": 1,
        "teamId": "team", "questionId": "OPERATOR-TEST", "finalAgentId": "planner",
        "participants": [{"agentId": "reviewer"}, {"agentId": "planner"}]}
    room = {"config": {"operatorDiscussionAuthority": authority},
        "participants": [{"agentId": agent, "sessionId": f"s{i}", "participantId": f"p{i}"}
            for i, agent in enumerate(("reviewer", "planner"))],
        "rounds": [{"roundId": "round1", "status": "running"}]}
    opened = Mock(return_value={"roomId": "room1", "roundId": "round1"})
    monkeypatch.setattr(task, "open_discussion", opened)
    monkeypatch.setattr(task.chat_room_service, "get_chat_room_detail", lambda _: room)
    store = SimpleNamespace(get_run=lambda _: SimpleNamespace(team_id="team"))
    handle = task.create_discussion_task(store, action)
    return store, action, handle, room, opened


def test_native_ports_resume_waits_without_starting_a_second_meeting(meeting, monkeypatch):
    store, action, handle, room, opened = meeting
    ports = RealDomainPorts(store)
    with pytest.raises(CompletionDependencyPending) as pending:
        ports.execute_agent_turn(action=action, handle=handle)
    assert pending.value.snapshot["meetingRunning"]
    assert not handle.scoped_handles
    assert handle.meeting_participants[-1]["taskId"] == "operator-speaker:round1:p1"
    room["rounds"][0]["status"] = "completed"
    receipts = Mock(return_value=[])
    monkeypatch.setattr(task, "_receipt_rows", receipts)
    with pytest.raises(CompletionDependencyPending) as pending:
        ports.execute_agent_turn(action=action, handle=handle)
    assert pending.value.snapshot == {"terminalStatus": "completed"}
    opened.assert_called_once()


def test_completed_meeting_collects_only_after_all_speaker_receipts(meeting, monkeypatch):
    store, action, handle, room, opened = meeting
    room["rounds"][0]["status"] = "completed"
    receipts = Mock(return_value=[{"status": "succeeded"}])
    monkeypatch.setattr(task, "_receipt_rows", receipts)
    budget = {"costStatus": "settled", "receiptId": "budget1"}
    monkeypatch.setattr(task, "settle_model_budget", lambda *_a, **_k: budget)
    collect = Mock(return_value={"status": "selected", "discussionRef": {
        "kind": "optimization_discussion", "sha256": "a" * 64}, "hypothesisRef": {
        "kind": "optimization_hypothesis", "sha256": "b" * 64}})
    monkeypatch.setattr(task, "collect_discussion", collect)
    result = RealDomainPorts(store).execute_agent_turn(action=action, handle=handle)
    assert receipts.call_count == 2
    assert collect.call_args.kwargs["budget_receipt"] == budget
    assert [r["kind"] for r in result.materialized_refs] == ["optimization_discussion", "optimization_hypothesis"]
    assert all("team/run1/" in r["canonicalRef"] for r in result.materialized_refs)
    opened.assert_called_once()


def test_failed_meeting_never_collects_or_reopens(meeting, monkeypatch):
    store, action, handle, room, opened = meeting
    room["rounds"][0]["status"] = "failed"
    settled = Mock()
    monkeypatch.setattr(task, "settle_model_budget", settled)
    collect = Mock()
    monkeypatch.setattr(task, "collect_discussion", collect)
    with pytest.raises(task.CampaignConflict, match="failed"):
        task.execute_discussion_task(store, action, handle)
    settled.assert_called_once()
    collect.assert_not_called()
    opened.assert_called_once()
