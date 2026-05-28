from fastapi.testclient import TestClient

from core.web.app import create_app
from core.web.control import CONTROL_TOKEN_HEADER, get_control_token
from core.web.services import agent_directory_service, project_agent_bus_service, session_service, team_service


def _client() -> TestClient:
    return TestClient(create_app(), headers={CONTROL_TOKEN_HEADER: get_control_token()})


def test_team_routes_create_detail_and_canvas(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(project_agent_bus_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(team_service, "PROJECT_ROOT", tmp_path)
    agent = agent_directory_service.create_agent_instance(display_name="Alpha", direct_session_id="session-alpha")
    client = _client()

    create_response = client.post(
        "/api/teams",
        json={"name": "产品团队", "members": [{"agentId": agent["agentId"], "role": "lead"}]},
    )

    assert create_response.status_code == 201, create_response.text
    team = create_response.json()
    assert team["members"][0]["agentId"] == agent["agentId"]
    assert client.get(f"/api/teams/{team['teamId']}").status_code == 200
    canvas_response = client.get(f"/api/teams/{team['teamId']}/canvas")
    assert canvas_response.status_code == 200
    assert canvas_response.json()["canvasKind"] == "team_organization_canvas"


def test_team_routes_save_canvas(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(project_agent_bus_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(team_service, "PROJECT_ROOT", tmp_path)
    client = _client()
    team = client.post("/api/teams", json={"name": "画布团队"}).json()
    canvas = client.get(f"/api/teams/{team['teamId']}/canvas").json()
    canvas["nodes"].append(
        {
            "id": "reviewer",
            "label": "评审",
            "type": "role",
            "x": 480,
            "y": 120,
            "agentId": "",
            "role": "reviewer",
            "purpose": "检查输出",
        }
    )
    canvas["edges"] = [{"id": "lead-reviewer", "source": "team-lead", "target": "reviewer", "type": "supports"}]

    response = client.put(f"/api/teams/{team['teamId']}/canvas", json=canvas)

    assert response.status_code == 200, response.text
    assert response.json()["validation"]["valid"] is True
    assert len(response.json()["nodes"]) == 2


def test_team_routes_send_message_to_team_members(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(project_agent_bus_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(team_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        project_agent_bus_service.session_service,
        "wake_agent_for_inbox_message",
        lambda message: {
            "wakeRequested": True,
            "wakeStatus": "started",
            "messageId": message["messageId"],
            "targetAgentId": message["targetAgentId"],
            "targetSessionId": message["targetSessionId"],
            "turnId": "turn-route-team",
            "reason": "",
        },
    )
    agent = agent_directory_service.create_agent_instance(display_name="Alpha", direct_session_id="session-alpha")
    client = _client()
    team = client.post("/api/teams", json={"name": "消息团队", "members": [{"agentId": agent["agentId"]}]}).json()

    response = client.post(f"/api/teams/{team['teamId']}/messages", json={"content": "请同步状态"})

    assert response.status_code == 201, response.text
    event = response.json()
    assert event["targetAgentIds"] == [agent["agentId"]]
    assert event["metadata"]["teamId"] == team["teamId"]
