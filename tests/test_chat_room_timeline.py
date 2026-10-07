"""Chat room append-only timeline log: store, write points and endpoint."""

import json

import pytest

from fastapi.testclient import TestClient

from core.chatroom import timeline as room_timeline
from core.ui.chat_state import save_chat_state
from core.web.app import create_app
from core.web.control import CONTROL_TOKEN_HEADER, get_control_token
from core.web.services import agent_directory_service, chat_room_service, session_service


client = TestClient(create_app(), headers={CONTROL_TOKEN_HEADER: get_control_token()})


@pytest.fixture(autouse=True)
def _pin_timeline_roots(tmp_path, monkeypatch):
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chat_room_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(room_timeline, "PROJECT_ROOT", tmp_path)


def _seed_chat_sessions(root):
    save_chat_state(
        root,
        {
            "version": 1,
            "active_conversation_id": "session-a",
            "conversations": [
                {
                    "conversation_id": "session-a",
                    "title": "Agent A",
                    "updated_at": "2026-05-26T10:00:00",
                    "messages": [{"role": "user", "content": "A 的上下文", "timestamp": "2026-05-26T10:00:00"}],
                },
                {
                    "conversation_id": "session-b",
                    "title": "Agent B",
                    "updated_at": "2026-05-26T10:01:00",
                    "messages": [{"role": "user", "content": "B 的上下文", "timestamp": "2026-05-26T10:01:00"}],
                },
            ],
        },
    )


def test_timeline_append_allocates_monotonic_room_seq(tmp_path):
    first = room_timeline.append_room_event(
        "room-t1",
        type=room_timeline.EVENT_TYPE_ROUND_STATE,
        round_id="round-1",
        payload={"status": "running"},
    )
    second = room_timeline.append_room_event(
        "room-t1",
        type=room_timeline.EVENT_TYPE_MEMBER_CHANGE,
        payload={"agentId": "agent-1"},
        from_id="agent-1",
    )
    third = room_timeline.append_room_event(
        "room-t2",
        type=room_timeline.EVENT_TYPE_ROUND_STATE,
        payload={"status": "running"},
    )

    assert [first["seq"], second["seq"]] == [1, 2]
    assert third["seq"] == 1, "seq is monotonic per room, not global"
    assert first["eventId"] and second["eventId"] and first["eventId"] != second["eventId"]
    assert first["type"] == "round_state"
    assert second["to"] == ""
    assert first["payload"] == {"status": "running"}
    assert first["createdAt"]

    events = room_timeline.read_events("room-t1")
    assert [item["seq"] for item in events] == [1, 2]
    assert timeline_file_exists("room-t1")


def timeline_file_exists(room_id: str) -> bool:
    return room_timeline.timeline_path(room_id).exists()


def test_timeline_read_events_cursor_and_limit(tmp_path):
    for index in range(1, 6):
        room_timeline.append_room_event(
            "room-cursor",
            type=room_timeline.EVENT_TYPE_MESSAGE,
            payload={"n": index},
        )

    page_one = room_timeline.read_events("room-cursor", after_seq=0, limit=2)
    assert [item["payload"]["n"] for item in page_one] == [1, 2]
    page_two = room_timeline.read_events("room-cursor", after_seq=page_one[-1]["seq"], limit=2)
    assert [item["payload"]["n"] for item in page_two] == [3, 4]
    page_three = room_timeline.read_events("room-cursor", after_seq=page_two[-1]["seq"], limit=2)
    assert [item["payload"]["n"] for item in page_three] == [5]
    assert room_timeline.read_events("room-cursor", after_seq=99) == []
    assert room_timeline.read_events("room-missing") == []


def test_timeline_read_quarantines_corrupt_line_and_append_continues(tmp_path):
    for index in range(1, 4):
        room_timeline.append_room_event(
            "room-corrupt",
            type=room_timeline.EVENT_TYPE_MESSAGE,
            payload={"n": index},
        )
    path = room_timeline.timeline_path("room-corrupt")
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write('{"eventId": "torn", "seq": "not-json-complete\n')

    events = room_timeline.read_events("room-corrupt")
    assert [item["payload"]["n"] for item in events] == [1, 2, 3]
    corrupt_path = path.with_name(path.name + ".corrupt")
    assert corrupt_path.exists()
    assert "torn" in corrupt_path.read_text(encoding="utf-8")
    # Quarantine is idempotent: a repeat read neither duplicates nor raises.
    assert [item["payload"]["n"] for item in room_timeline.read_events("room-corrupt")] == [1, 2, 3]

    healed = room_timeline.append_room_event(
        "room-corrupt",
        type=room_timeline.EVENT_TYPE_MESSAGE,
        payload={"n": 4},
    )
    assert healed["seq"] == 4, "torn tail must not reset or duplicate the room seq"
    assert [item["payload"]["n"] for item in room_timeline.read_events("room-corrupt")] == [1, 2, 3, 4]


def test_timeline_rejects_unknown_event_type_and_empty_room(tmp_path):
    with pytest.raises(room_timeline.TimelineError):
        room_timeline.append_room_event("room-x", type="bogus")
    with pytest.raises(room_timeline.TimelineError):
        room_timeline.append_room_event("  ", type=room_timeline.EVENT_TYPE_MESSAGE)


def _stub_round_runner(monkeypatch):
    monkeypatch.setattr(
        chat_room_service,
        "_run_participant_agent",
        lambda participant, prompt, context: {
            "status": "completed",
            "raw_output": f"{participant['title']} 发言",
            "summary": "ok",
        },
    )


@pytest.mark.slow
def test_room_round_writes_timeline_events_and_endpoint_serves_them(tmp_path, monkeypatch):
    _seed_chat_sessions(tmp_path)
    _stub_round_runner(monkeypatch)

    room = client.post(
        "/api/chat-rooms",
        json={
            "title": "时间线群聊",
            "participantSessionIds": ["session-a", "session-b"],
            "purpose": "chat",
        },
    ).json()
    round_response = client.post(
        f"/api/chat-rooms/{room['roomId']}/rounds",
        json={"topic": "验证时间线写入"},
    )
    assert round_response.status_code == 202
    from tests.helpers.chat_turn_harness import wait_for_chat_room_round_completed

    detail = wait_for_chat_room_round_completed(client, room["roomId"], timeout_s=8.0)
    latest_round = detail["rounds"][-1]

    response = client.get(f"/api/chat-rooms/{room['roomId']}/timeline")
    assert response.status_code == 200
    payload = response.json()
    assert payload["roomId"] == room["roomId"]
    types = [item["type"] for item in payload["events"]]
    assert types[0] == "round_state"
    assert payload["events"][0]["payload"]["status"] == "running"
    assert payload["events"][0]["payload"]["roundId"] == latest_round["roundId"]
    assert "round_state" in types[1:], types
    finished = [item for item in payload["events"] if item["type"] == "round_state"][-1]
    assert finished["payload"]["status"] == "completed"
    message_events = [item for item in payload["events"] if item["type"] == "message"]
    assert len(message_events) == 2
    assert [item["seq"] for item in payload["events"]] == sorted(
        item["seq"] for item in payload["events"]
    )
    api_messages = {item["messageId"]: item for item in latest_round["messages"]}
    room_participant_ids = {
        str(item.get("participantId") or "") for item in detail["participants"]
    }
    for event in message_events:
        assert event["payload"]["messageId"] in api_messages
        assert event["payload"]["content"] == api_messages[event["payload"]["messageId"]]["content"]
        assert event["roundId"] == latest_round["roundId"]
        assert event["from"] in room_participant_ids

    # Cursor pagination serves the same log incrementally.
    first_page = client.get(
        f"/api/chat-rooms/{room['roomId']}/timeline",
        params={"cursor": 0, "limit": 2},
    ).json()
    assert len(first_page["events"]) == 2
    assert first_page["hasMore"] is True
    second_page = client.get(
        f"/api/chat-rooms/{room['roomId']}/timeline",
        params={"cursor": first_page["nextCursor"], "limit": 2},
    ).json()
    assert second_page["events"][0]["seq"] > first_page["events"][-1]["seq"]
    tail_page = client.get(
        f"/api/chat-rooms/{room['roomId']}/timeline",
        params={"cursor": second_page["nextCursor"], "limit": 2},
    ).json()
    all_seqs = (
        [item["seq"] for item in first_page["events"]]
        + [item["seq"] for item in second_page["events"]]
        + [item["seq"] for item in tail_page["events"]]
    )
    assert all_seqs == [item["seq"] for item in payload["events"]]


def test_timeline_endpoint_returns_404_for_unknown_room(tmp_path):
    response = client.get("/api/chat-rooms/room-missing/timeline")
    assert response.status_code == 404


@pytest.mark.slow
def test_member_change_write_points_append_timeline_events(tmp_path, monkeypatch):
    _seed_chat_sessions(tmp_path)
    alpha = session_service.create_chat_session(title="Alpha Agent")
    beta = session_service.create_chat_session(title="Beta Agent")
    room = client.post(
        "/api/chat-rooms",
        json={
            "title": "成员变动群聊",
            "participantSessionIds": [alpha["id"]],
        },
    ).json()

    updated = client.patch(
        f"/api/chat-rooms/{room['roomId']}",
        json={"participantSessionIds": [alpha["id"], beta["id"]]},
    )
    assert updated.status_code == 200
    updated_room = updated.json()
    updated_participant_ids = [
        str(item.get("participantId") or "") for item in updated_room["participants"]
    ]

    events = client.get(f"/api/chat-rooms/{room['roomId']}/timeline").json()["events"]
    member_events = [item for item in events if item["type"] == "member_change"]
    assert len(member_events) == 1
    payload = member_events[0]["payload"]
    assert payload["addedParticipantIds"] == [
        item
        for item in updated_participant_ids
        if item not in {str(p.get("participantId") or "") for p in room["participants"]}
    ]
    assert payload["removedParticipantIds"] == []
    assert sorted(payload["participantIds"]) == sorted(updated_participant_ids)

    # Agent membership panel path lands the same event type.
    gamma = session_service.create_chat_session(title="Gamma Agent")
    agent_room = chat_room_service.create_chat_room(
        title="成员面板群聊",
        participant_agent_ids=[alpha["agentId"], beta["agentId"]],
    )
    membership = chat_room_service.update_agent_chat_room_membership(
        gamma["agentId"],
        [agent_room["roomId"]],
    )
    assert agent_room["roomId"] in membership["changedRoomIds"]
    agent_events = client.get(f"/api/chat-rooms/{agent_room['roomId']}/timeline").json()["events"]
    agent_member_events = [item for item in agent_events if item["type"] == "member_change"]
    assert len(agent_member_events) == 1
    assert agent_member_events[0]["payload"]["agentId"] == gamma["agentId"]
    assert agent_member_events[0]["from"] == gamma["agentId"]
    assert agent_member_events[0]["payload"]["selected"] is True
