from fastapi.testclient import TestClient

from core.agent_kernel import service as agent_kernel_service
from core.infrastructure import developer_sandbox
from core.web.app import create_app
from core.web.control import CONTROL_TOKEN_HEADER, get_control_token
from core.web.services import agent_directory_service, project_agent_bus_service, session_service


def _client() -> TestClient:
    return TestClient(create_app(), headers={CONTROL_TOKEN_HEADER: get_control_token()})


def _use_tmp_project_root(tmp_path, monkeypatch):
    project_root = tmp_path / "project"
    data_home = tmp_path / "operator-data"
    project_root.mkdir()
    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(data_home))
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", project_root)
    monkeypatch.setattr(project_agent_bus_service, "PROJECT_ROOT", project_root)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", project_root)
    monkeypatch.setattr(agent_kernel_service, "PROJECT_ROOT", project_root)
    monkeypatch.setattr(developer_sandbox, "PROJECT_ROOT", project_root)


def test_project_agent_bus_routes_list_and_send_message(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
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
    assert payload["kernel"]["enabled"] is True
    assert payload["kernel"]["taskId"]
    assert payload["deliveries"][0]["kernelTaskId"] == payload["kernel"]["taskId"]

    list_response = _client().get("/api/project-agent-bus")
    assert list_response.status_code == 200
    listed = list_response.json()
    assert listed["events"][-1]["eventId"] == payload["eventId"]
    assert listed["activeAgentCount"] == 2


def test_project_agent_bus_route_revokes_message_and_requests_stop(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
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
