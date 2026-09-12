import json

import pytest

from tests.test_operator_optimization_budget import activity
from tests.test_operator_optimization_discussion import discussion_case
from tests.test_operator_optimization_rounds import ready
from core.web.services.team_workflow.operator_optimization import discussion_runtime as runtime
from core.web.services.team_workflow.operator_optimization.store import CampaignConflict


@pytest.fixture
def native_ports(activity, discussion_case, monkeypatch):
    campaign, run, payload = discussion_case
    run.workflow_version_id = "operator-v1"
    snapshot = json.loads(run.input_snapshot_json)
    assert "modelRoutingPolicy" in snapshot
    monkeypatch.setattr(runtime, "get_write_store", lambda: type("Store", (), {"get_run": lambda self, _: run})())
    calls, rooms = [], {}
    authority = {
        "schemaVersion": 1,
        "authorityKind": "operator_discussion",
        "teamId": activity[0],
        "researchProjectId": activity[1],
        "optimizationCampaignId": activity[2],
        "roundId": campaign.rounds[0].roundId,
        "workflowRunId": run.run_id,
        "workflowId": "operator-optimization",
        "workflowVersionId": "operator-v1",
        "nodeRunId": "node-run-1",
        "nodeAttempt": 1,
        "inputHash": runtime.sha256_hex(runtime.discussion_input(activity[0], run.run_id)),
        "participants": [
            {"agentId": "reviewer", "role": "reviewer", "modelRef": "provider/reviewer", "providerId": "provider", "modelId": "reviewer"},
            {"agentId": "planner", "role": "experiment_planner", "modelRef": "provider/planner", "providerId": "provider", "modelId": "planner"},
        ],
        "finalAgentId": "planner",
        "modelPolicySha256": "b" * 64,
    }
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
    monkeypatch.setattr(runtime, "build_operator_meeting_authority", lambda team_id, run_id, *, node_run_id: authority)
    monkeypatch.setattr(runtime, "validate_operator_authority", lambda value: value)
    return campaign, run, calls, rooms, authority


def test_discussion_uses_scoped_sessions_and_one_native_round(activity, native_ports):
    campaign, run, calls, rooms, authority = native_ports
    first = runtime.open_discussion(activity[0], run.run_id, node_run_id="node-run-1")
    again = runtime.open_discussion(activity[0], run.run_id, node_run_id="node-run-1")
    assert first["roundId"] == again["roundId"]
    assert again["reused"]
    assert [kind for kind, _ in calls] == ["session", "session", "create", "start"]
    assert [request["agent_id"] for kind, request in calls[:2]] == ["reviewer", "planner"]
    for _, request in calls[:2]:
        assert request["research_project_id"] == activity[1]
        assert request["workflow_run_id"] == run.run_id
        assert request["workflow_node_id"] == "optimization_discussion"
        assert request["discussion_scope"].workflowRunId == run.run_id
    assert runtime.chat_room_service._is_challenge_discussion_room(rooms[first["roomId"]])
    assert rooms[first["roomId"]]["config"]["finalParticipantSessionId"] == "session-planner"
    assert rooms[first["roomId"]]["config"]["finalParticipantAgentId"] == "planner"
    authority = calls[-1][1]["_model_invocation_receipt_authority"]
    assert authority["workflowRunId"] == run.run_id
    assert authority["workflowId"] == "operator-optimization"


def test_discussion_does_not_reuse_room_from_other_run(activity, native_ports):
    campaign, run, calls, rooms, authority = native_ports
    result = runtime.open_discussion(activity[0], run.run_id, node_run_id="node-run-1")
    rooms[result["roomId"]]["config"]["workflowRunId"] = "other"
    with pytest.raises(CampaignConflict, match="different frozen input"):
        runtime.open_discussion(activity[0], run.run_id, node_run_id="node-run-1")
    assert sum(kind == "start" for kind, _ in calls) == 1


def test_one_member_cannot_be_reported_as_team_discussion(activity, native_ports, monkeypatch):
    campaign, run, calls, rooms, authority = native_ports
    monkeypatch.setattr(runtime, "build_operator_meeting_authority", lambda *args, **kwargs: {
        **authority, "participants": [authority["participants"][0]], "finalAgentId": "reviewer"
    })
    with pytest.raises(CampaignConflict, match="at least two"):
        runtime.open_discussion(activity[0], run.run_id, node_run_id="node-run-1")
    assert calls == []


def test_completed_discussion_collects_hypothesis_with_provenance(activity, native_ports, discussion_case, monkeypatch):
    from core.web.services.team_workflow.research_runtime import model_invocation_receipt_registry as registry
    campaign, run, calls, rooms, authority = native_ports
    result = runtime.open_discussion(activity[0], run.run_id, node_run_id="node-run-1")
    room = rooms[result["roomId"]]
    room["participants"] = [
        {"sessionId": "session-planner", "participantId": "p1", "agentId": "planner"},
        {"sessionId": "session-reviewer", "participantId": "p2", "agentId": "reviewer"},
    ]
    room["rounds"][0].update(status="completed", messages=[
        {"messageId": "m1", "sessionId": "session-planner", "participantId": "p1", "agentId": "planner", "status": "completed", "operatorDiscussionPayload": {"schemaVersion": 1, "contribution": "汇总受控融合方案。", "result": {"status": "selected", "reason": "证据支持", "hypothesis": discussion_case[2]}}},
        {"messageId": "m2", "sessionId": "session-reviewer", "participantId": "p2", "agentId": "reviewer", "status": "completed", "operatorDiscussionPayload": {"schemaVersion": 1, "contribution": "建议核对寄存器压力。", "result": None}}])
    receipts = [{"receiptId": "r1", "status": "retried", "scope": {"sessionId": "session-planner", "turnId": "chat-room:chat-round1:p1"}},
        {"receiptId": "r2", "status": "succeeded", "scope": {"sessionId": "session-reviewer", "turnId": "chat-room:chat-round1:p2"}}]
    monkeypatch.setattr(registry, "question_model_invocation_receipts", lambda *a, **k: receipts)
    # Retrieval order must not select a different final speaker.
    room["rounds"][0]["messages"].reverse()
    collected = runtime.collect_discussion(activity[0], run.run_id)
    assert collected["hypothesisRef"]["kind"] == "optimization_hypothesis"
    assert len(collected["discussion"]["provenance"]["messageRefs"]) == 2
    assert collected["discussion"]["provenance"]["costStatus"] == "unsettled"
    assert {row["status"] for row in collected["discussion"]["provenance"]["modelReceiptRefs"]} == {"retried", "succeeded"}
    assert runtime.collect_discussion(activity[0], run.run_id) == collected
    receipts[-1]["scope"]["turnId"] = "other-turn"
    with pytest.raises(CampaignConflict, match="exact participant Turn"):
        runtime.collect_discussion(activity[0], run.run_id)
    receipts.pop()
    with pytest.raises(CampaignConflict, match="provider receipts"):
        runtime.collect_discussion(activity[0], run.run_id)


def test_native_authority_blocks_operator_before_sessions_or_model_start(activity, native_ports, monkeypatch):
    _, run, calls, rooms, authority = native_ports
    monkeypatch.setattr(runtime, "build_operator_meeting_authority", lambda *args, **kwargs: (_ for _ in ()).throw(CampaignConflict("authority unavailable")))
    with pytest.raises(CampaignConflict, match="receipt authority is unavailable"):
        runtime.open_discussion(activity[0], run.run_id, node_run_id="node-run-1")
    assert calls == []
    assert rooms == {}


def test_open_discussion_requires_real_node_attempt_identity(activity, native_ports):
    _, run, calls, rooms, _ = native_ports

    with pytest.raises(CampaignConflict, match="node_run_id"):
        runtime.open_discussion(activity[0], run.run_id)
    assert calls == []
    assert rooms == {}


def test_concurrent_discussion_open_reuses_single_round_under_campaign_lock(activity, native_ports):
    from concurrent.futures import ThreadPoolExecutor
    _, run, calls, rooms, _ = native_ports
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: runtime.open_discussion(activity[0], run.run_id,
            node_run_id="node-run-1"), range(2)))
    assert results[0]["roundId"] == results[1]["roundId"]
    assert sum(kind == "start" for kind, _ in calls) == 1

def test_no_viable_discussion_persists_source_and_pauses_without_hypothesis(activity, native_ports, monkeypatch):
    from core.web.services.team_workflow.research_runtime import model_invocation_receipt_registry as registry

    _, run, calls, rooms, _ = native_ports
    opened = runtime.open_discussion(activity[0], run.run_id, node_run_id="node-run-1")
    room = rooms[opened["roomId"]]
    room["participants"] = [
        {"sessionId": "session-reviewer", "participantId": "p2", "agentId": "reviewer"},
        {"sessionId": "session-planner", "participantId": "p1", "agentId": "planner"},
    ]
    room["rounds"][0].update(status="completed", messages=[
        {"messageId": "m2", "sessionId": "session-reviewer", "participantId": "p2", "agentId": "reviewer", "status": "completed", "operatorDiscussionPayload": {"schemaVersion": 1, "contribution": "当前证据不足。", "result": None}},
        {"messageId": "m1", "sessionId": "session-planner", "participantId": "p1", "agentId": "planner", "status": "completed", "operatorDiscussionPayload": {"schemaVersion": 1, "contribution": "无法形成可测量方案。", "result": {"status": "no_viable_hypothesis", "reason": "现有证据无法区分候选机制"}}},
    ])
    receipts = [
        {"receiptId": "r1", "status": "succeeded", "scope": {"sessionId": "session-reviewer", "turnId": "chat-room:chat-round1:p2"}},
        {"receiptId": "r2", "status": "succeeded", "scope": {"sessionId": "session-planner", "turnId": "chat-room:chat-round1:p1"}},
    ]
    monkeypatch.setattr(registry, "question_model_invocation_receipts", lambda *a, **k: receipts)

    collected = runtime.collect_discussion(activity[0], run.run_id)

    assert collected["status"] == "no_viable_hypothesis"
    assert collected["hypothesisRef"] is None
    assert runtime.read_campaign(activity[0], activity[1], activity[2]).status == "paused"
