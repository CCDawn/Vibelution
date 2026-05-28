import time

from fastapi.testclient import TestClient

from core.ui.chat_state import save_chat_state
from core.web.app import create_app
from core.web.control import CONTROL_TOKEN_HEADER, get_control_token
from core.web.services import agent_directory_service, chat_room_service, session_service


client = TestClient(create_app(), headers={CONTROL_TOKEN_HEADER: get_control_token()})


def test_chat_room_modes_api_exposes_opportunistic_as_ready():
    response = client.get("/api/chat-rooms/modes")

    assert response.status_code == 200
    modes = {item["id"]: item for item in response.json()}
    assert modes["round_robin"]["status"] == "ready"
    assert modes["opportunistic"]["status"] == "ready"


def _wait_for_completed_room_round(room_id: str, *, timeout: float = 2.0) -> dict:
    deadline = time.monotonic() + timeout
    detail: dict = {}
    while time.monotonic() < deadline:
        response = client.get(f"/api/chat-rooms/{room_id}")
        assert response.status_code == 200
        detail = response.json()
        latest_round = detail["rounds"][-1]
        if latest_round["status"] == "completed":
            return detail
        time.sleep(0.02)
    raise AssertionError(f"chat room round did not complete: {detail}")


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


def test_chat_room_api_create_and_run_round(tmp_path, monkeypatch):
    _seed_chat_sessions(tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chat_room_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        chat_room_service,
        "_run_participant_agent",
        lambda participant, prompt, context: {
            "status": "completed",
            "raw_output": f"{participant['title']} 发言",
            "summary": "ok",
        },
    )

    create_response = client.post(
        "/api/chat-rooms",
        json={
            "title": "项目群聊",
            "participantSessionIds": ["session-a", "session-b"],
        },
    )

    assert create_response.status_code == 201
    room = create_response.json()
    assert room["title"] == "项目群聊"
    assert len(room["participants"]) == 2

    round_response = client.post(
        f"/api/chat-rooms/{room['roomId']}/rounds",
        json={"topic": "确认第一版群聊行为"},
    )

    assert round_response.status_code == 202
    started = round_response.json()
    assert started["status"] in {"running", "ready"}
    assert started["rounds"][-1]["status"] in {"running", "completed"}

    detail = _wait_for_completed_room_round(room["roomId"])
    latest_round = detail["rounds"][-1]
    assert latest_round["topic"] == "确认第一版群聊行为"
    assert latest_round["status"] == "completed"
    assert [message["content"] for message in latest_round["messages"]] == ["Agent A 发言", "Agent B 发言"]


def test_chat_room_api_creates_room_from_agent_ids(tmp_path, monkeypatch):
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chat_room_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    alpha = session_service.create_chat_session(title="Alpha Agent")
    beta = session_service.create_chat_session(title="Beta Agent")

    response = client.post(
        "/api/chat-rooms",
        json={
            "title": "动态群聊",
            "agentIds": [alpha["agentId"], beta["agentId"]],
            "mode": "round_robin",
        },
    )

    assert response.status_code == 201, response.text
    room = response.json()
    assert room["title"] == "动态群聊"
    assert [participant["agentId"] for participant in room["participants"]] == [alpha["agentId"], beta["agentId"]]


def test_chat_room_api_rejects_missing_participant(tmp_path, monkeypatch):
    _seed_chat_sessions(tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chat_room_service, "PROJECT_ROOT", tmp_path)

    response = client.post(
        "/api/chat-rooms",
        json={
            "title": "坏房间",
            "participantSessionIds": ["missing-session"],
        },
    )

    assert response.status_code == 422


def test_chat_room_api_updates_and_deletes_room(tmp_path, monkeypatch):
    _seed_chat_sessions(tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chat_room_service, "PROJECT_ROOT", tmp_path)

    create_response = client.post(
        "/api/chat-rooms",
        json={
            "title": "待管理群聊",
            "participantSessionIds": ["session-a"],
        },
    )
    assert create_response.status_code == 201
    room = create_response.json()

    update_response = client.patch(
        f"/api/chat-rooms/{room['roomId']}",
        json={
            "title": "已管理群聊",
            "participantSessionIds": ["session-b"],
        },
    )

    assert update_response.status_code == 200
    updated = update_response.json()
    assert updated["title"] == "已管理群聊"
    assert [participant["sessionId"] for participant in updated["participants"]] == ["session-b"]

    delete_response = client.delete(f"/api/chat-rooms/{room['roomId']}")

    assert delete_response.status_code == 200
    assert delete_response.json() == {"deleted": True, "roomId": room["roomId"]}
    assert client.get(f"/api/chat-rooms/{room['roomId']}").status_code == 404
