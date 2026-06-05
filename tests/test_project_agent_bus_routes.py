from fastapi.testclient import TestClient

from core.web.app import create_app
from core.web.control import CONTROL_TOKEN_HEADER, get_control_token
from core.web.services import agent_directory_service, project_agent_bus_service, session_service


def _client() -> TestClient:
    return TestClient(create_app(), headers={CONTROL_TOKEN_HEADER: get_control_token()})


def test_project_agent_bus_routes_list_and_send_message(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(project_agent_bus_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    agent = agent_directory_service.create_agent_instance(display_name="Alpha", direct_session_id="session-alpha")
    monkeypatch.setattr(
        project_agent_bus_service.session_service,
        "wake_agent_for_inbox_message",
        lambda message: {
            "wakeRequested": True,
            "wakeStatus": "started",
            "messageId": message["messageId"],
            "targetAgentId": message["targetAgentId"],
            "targetSessionId": message["targetSessionId"],
            "turnId": "turn-route",
            "reason": "",
        },
    )

    response = _client().post(
        "/api/project-agent-bus/messages",
        json={"content": f"@{agent['agentCode']} 路由投递", "interruptMode": "none"},
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["targetAgentIds"] == [agent["agentId"]]
    assert payload["deliveries"][0]["status"] == "delivered"

    list_response = _client().get("/api/project-agent-bus")
    assert list_response.status_code == 200
    listed = list_response.json()
    assert listed["events"][-1]["eventId"] == payload["eventId"]
    assert listed["activeAgentCount"] == 2


def test_project_agent_bus_route_revokes_message_and_requests_stop(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(project_agent_bus_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    agent = agent_directory_service.create_agent_instance(display_name="Alpha", direct_session_id="session-alpha")
    stopped = []
    monkeypatch.setattr(
        project_agent_bus_service.session_service,
        "wake_agent_for_inbox_message",
        lambda message: {
            "wakeRequested": True,
            "wakeStatus": "started",
            "messageId": message["messageId"],
            "targetAgentId": message["targetAgentId"],
            "targetSessionId": message["targetSessionId"],
            "turnId": "turn-route",
            "reason": "",
        },
    )
    monkeypatch.setattr(
        project_agent_bus_service.session_service,
        "request_stop_session_turn",
        lambda session_id: stopped.append(session_id) or {"status": "stopped"},
    )
    client = _client()
    send_response = client.post(
        "/api/project-agent-bus/messages",
        json={"content": f"@{agent['agentCode']} 路由投递", "interruptMode": "none"},
    )
    assert send_response.status_code == 201
    event_id = send_response.json()["eventId"]

    revoke_response = client.post(
        f"/api/project-agent-bus/messages/{event_id}/revoke",
        json={"reason": "发错内容", "stopTargets": True},
    )

    assert revoke_response.status_code == 200
    revoked = revoke_response.json()
    assert revoked["status"] == "revoked"
    assert revoked["revocations"][0]["stopStatus"] == "stopped"
    assert stopped == ["session-alpha"]
