import json

import pytest

from tests.test_operator_optimization_budget import activity
from tests.test_operator_optimization_rounds import ready
from tests.test_operator_optimization_discussion import discussion_case
from core.web.services.team_workflow.operator_optimization import discussion_runtime as runtime
from core.web.services.team_workflow.operator_optimization.store import CampaignConflict


@pytest.fixture
def native_ports(activity, discussion_case, monkeypatch):
    campaign, run, payload = discussion_case
    run.workflow_version_id = "operator-v1"
    snapshot = json.loads(run.input_snapshot_json)
    assert "modelRoutingPolicy" in snapshot
    monkeypatch.setattr(runtime, "get_write_store", lambda: type("Store", (), {"get_run": lambda self, _: run})())
    monkeypatch.setattr(runtime.team_service, "get_team", lambda _: {"members": [
        {"agentId": "planner", "role": "experiment_planner"}, {"agentId": "reviewer", "role": "reviewer"}]})
    calls, rooms = [], {}
    def session(team, **kwargs):
        calls.append(("session", kwargs))
        return {"sessionId": "session-" + kwargs["agent_id"]}
    def create(**kwargs):
        calls.append(("create", kwargs))
        rooms[kwargs["room_id"]] = {"config": kwargs["config"], "rounds": []}
    def start(room_id, topic, **kwargs):
        calls.append(("start", kwargs))
        rooms[room_id]["rounds"].append({"roundId": "chat-round1"})
        return {"roundId": "chat-round1"}
    monkeypatch.setattr(runtime, "resolve_research_project_agent_session", session)
    monkeypatch.setattr(runtime.chat_room_service, "get_chat_room_detail", lambda room: rooms.get(room))
    monkeypatch.setattr(runtime.chat_room_service, "create_chat_room", create)
    monkeypatch.setattr(runtime.chat_room_service, "start_chat_room_round", start)
    # Collector/room tests simulate the future operator authority adapter.
    # The real native authority rejection is tested separately below.
    monkeypatch.setattr(runtime, "build_meeting_receipt_authority", lambda **kwargs: {
        "workflowRunId": kwargs["workflow_run_id"], "workflowId": kwargs["workflow_id"]})
    return campaign, run, calls, rooms


def test_discussion_uses_scoped_sessions_and_one_native_round(activity, native_ports):
    campaign, run, calls, rooms = native_ports
    first = runtime.open_discussion(activity[0], run.run_id)
    again = runtime.open_discussion(activity[0], run.run_id)
    assert first["roundId"] == again["roundId"]
    assert again["reused"]
    assert [kind for kind, _ in calls] == ["session", "session", "create", "start"]
    for _, request in calls[:2]:
        assert request["research_project_id"] == activity[1]
        assert request["workflow_run_id"] == run.run_id
        assert request["workflow_node_id"] == "optimization_discussion"
        assert request["discussion_scope"].workflowRunId == run.run_id
    assert runtime.chat_room_service._is_challenge_discussion_room(rooms[first["roomId"]])
    assert rooms[first["roomId"]]["config"]["finalParticipantSessionId"] == "session-reviewer"
    authority = calls[-1][1]["_model_invocation_receipt_authority"]
    assert authority["workflowRunId"] == run.run_id
    assert authority["workflowId"] == "operator-optimization"


def test_discussion_does_not_reuse_room_from_other_run(activity, native_ports):
    campaign, run, calls, rooms = native_ports
    result = runtime.open_discussion(activity[0], run.run_id)
    rooms[result["roomId"]]["config"]["workflowRunId"] = "other"
    with pytest.raises(CampaignConflict, match="different frozen input"):
        runtime.open_discussion(activity[0], run.run_id)
    assert sum(kind == "start" for kind, _ in calls) == 1


def test_one_member_cannot_be_reported_as_team_discussion(activity, native_ports, monkeypatch):
    campaign, run, calls, rooms = native_ports
    monkeypatch.setattr(runtime.team_service, "get_team", lambda _: {"members": [{"agentId": "solo"}]})
    with pytest.raises(CampaignConflict, match="at least two"):
        runtime.open_discussion(activity[0], run.run_id)
    assert calls == []


def test_completed_discussion_collects_hypothesis_with_provenance(activity, native_ports, discussion_case, monkeypatch):
    from core.web.services.team_workflow.research_runtime import model_invocation_receipt_registry as registry
    campaign, run, calls, rooms = native_ports
    result = runtime.open_discussion(activity[0], run.run_id)
    room = rooms[result["roomId"]]
    room["participants"] = [{"sessionId": "session-planner", "participantId": "p1"}, {"sessionId": "session-reviewer", "participantId": "p2"}]
    room["rounds"][0].update(status="completed", messages=[
        {"messageId": "m1", "sessionId": "session-planner", "participantId": "p1", "status": "completed", "content": "Propose fusion"},
        {"messageId": "m2", "sessionId": "session-reviewer", "participantId": "p2", "status": "completed", "content": json.dumps(discussion_case[2])}])
    receipts = [{"receiptId": "r1", "status": "succeeded", "scope": {"sessionId": "session-planner", "turnId": "chat-room:chat-round1:p1"}},
        {"receiptId": "r2", "status": "succeeded", "scope": {"sessionId": "session-reviewer", "turnId": "chat-room:chat-round1:p2"}}]
    monkeypatch.setattr(registry, "question_model_invocation_receipts", lambda *a, **k: receipts)
    # Retrieval order must not select a different final speaker.
    room["rounds"][0]["messages"].reverse()
    collected = runtime.collect_discussion(activity[0], run.run_id)
    assert collected["hypothesisRef"]["kind"] == "optimization_hypothesis"
    assert len(collected["discussion"]["messageRefs"]) == 2
    assert collected["discussion"]["costStatus"] == "unsettled"
    assert runtime.collect_discussion(activity[0], run.run_id) == collected
    receipts[-1]["scope"]["turnId"] = "other-turn"
    with pytest.raises(CampaignConflict, match="exact participant Turn"):
        runtime.collect_discussion(activity[0], run.run_id)
    receipts.pop()
    with pytest.raises(CampaignConflict, match="provider receipts"):
        runtime.collect_discussion(activity[0], run.run_id)


def test_native_authority_blocks_operator_before_sessions_or_model_start(activity, native_ports, monkeypatch):
    from core.web.services.team_workflow.research_runtime.meeting_receipt_authority import build_meeting_receipt_authority
    _, run, calls, rooms = native_ports
    monkeypatch.setattr(runtime, "build_meeting_receipt_authority", build_meeting_receipt_authority)
    with pytest.raises(CampaignConflict, match="receipt authority is unavailable"):
        runtime.open_discussion(activity[0], run.run_id)
    assert calls == []
    assert rooms == {}
