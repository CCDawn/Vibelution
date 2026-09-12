from types import SimpleNamespace

import pytest

from core.web.services import chat_room_service as rooms
from core.web.services import agent_directory_service


@pytest.fixture
def participant(monkeypatch):
    monkeypatch.setattr(rooms, "_evaluate_speaker_supervision_policy", lambda _: SimpleNamespace(
        allowed=True, reason="", supervision_enabled=False, requires_review=False,
        review_mode="", evidence_level=""))
    monkeypatch.setattr(agent_directory_service, "record_supervision_policy_decision", lambda _: None)
    return {"participantId": "p1", "agentId": "a1", "sessionId": "s1", "agentCode": "A1"}


def test_operator_speaker_persists_only_dedicated_validated_result(participant):
    payload = {"schemaVersion": 1, "contribution": "Compare row fusion under fixed workload", "result": None}
    message = rooms._run_one_speaker(participant, "discuss", {
        "_operatorDiscussion": True, "_structuredMeetingMessage": True, "_structuredChatRoomContext": True,
    }, lambda *_: {"status": "completed", "operatorDiscussionPayload": payload,
        "raw_output": "unrelated visible text"})
    assert message["status"] == "completed"
    assert message["content"] == payload["contribution"]
    assert message["operatorDiscussionPayload"] == payload
    assert "messagePayload" not in message
    assert "contextPayload" not in message


def test_operator_speaker_cannot_promote_display_text_to_formal_result(participant):
    message = rooms._run_one_speaker(participant, "discuss", {"_operatorDiscussion": True},
        lambda *_: {"status": "completed", "raw_output": '{"contribution":"fake","result":null}'})
    assert message["status"] == "failed"
    assert "operatorDiscussionPayload" not in message


def test_ordinary_speaker_keeps_original_output(participant):
    message = rooms._run_one_speaker(participant, "discuss", {},
        lambda *_: {"status": "completed", "raw_output": "ordinary output"})
    assert message["status"] == "completed"
    assert message["content"] == "ordinary output"
    assert "operatorDiscussionPayload" not in message


def test_native_room_routes_one_operator_round_and_preserves_payload(tmp_path, monkeypatch):
    from tests.test_chat_room_service import _isolate_chat_room_kernel, _seed_chat_sessions
    from core.web.services.team_workflow.operator_optimization import discussion_authority

    _isolate_chat_room_kernel(tmp_path, monkeypatch)
    _seed_chat_sessions(tmp_path)
    from unittest.mock import Mock
    from core.web.services.team_workflow.research_runtime import formal_write_runtime
    store = Mock()
    monkeypatch.setattr(formal_write_runtime, "get_write_store", lambda: store)
    authority = {"authorityKind": "operator_discussion", "workflowRunId": "operator-run", "nodeRunId": "node1"}
    validated = []
    monkeypatch.setattr(discussion_authority, "validate_operator_authority",
        lambda value: validated.append(value) or value)
    room = rooms.create_chat_room(title="Operator discussion", purpose="meeting",
        participant_session_ids=["session-alpha", "session-beta"],
        config={"operatorDiscussionAuthority": authority})
    contexts = []
    def runner(participant, prompt, context):
        contexts.append(context)
        return {"status": "completed", "operatorDiscussionPayload": {
            "schemaVersion": 1, "contribution": "Test operator contribution", "result": None}}
    result = rooms.start_chat_room_round(room["roomId"], "operator discussion",
        config={"meetingType": "operator_optimization_discussion"},
        agent_runner=runner, _model_invocation_receipt_authority=authority)
    assert validated == [authority]
    store.submit.assert_called_once()
    assert len(contexts) == 2
    assert all(context["_operatorDiscussion"] and context["workflowRunId"] == "operator-run" for context in contexts)
    assert len(result["rounds"]) == 1
    assert all(message["operatorDiscussionPayload"]["result"] is None for message in result["rounds"][0]["messages"])
    with pytest.raises(rooms.ChatRoomValidationError, match="single logical round"):
        rooms.start_chat_room_round(room["roomId"], "repeat", agent_runner=runner,
            _model_invocation_receipt_authority=authority)
    assert len(contexts) == 2
