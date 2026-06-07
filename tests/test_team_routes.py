from fastapi.testclient import TestClient

from core.web.app import create_app
from core.web.control import CONTROL_TOKEN_HEADER, get_control_token
from core.web.routes import teams as teams_route
from core.web.services import agent_directory_service, chat_room_service, project_agent_bus_service, session_service, team_service


def _client() -> TestClient:
    return TestClient(create_app(), headers={CONTROL_TOKEN_HEADER: get_control_token()})


def test_team_routes_create_detail_and_canvas(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chat_room_service, "PROJECT_ROOT", tmp_path)
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
    assert team["linkedChatRoomId"]
    assert team["linkedChatRoom"]["participantCount"] == 1
    assert client.get(f"/api/teams/{team['teamId']}").status_code == 200
    canvas_response = client.get(f"/api/teams/{team['teamId']}/canvas")
    assert canvas_response.status_code == 200
    assert canvas_response.json()["canvasKind"] == "team_organization_canvas"


def test_team_routes_reject_agent_that_already_belongs_to_active_team(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chat_room_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(project_agent_bus_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(team_service, "PROJECT_ROOT", tmp_path)
    agent = agent_directory_service.create_agent_instance(display_name="Alpha", direct_session_id="session-alpha")
    client = _client()
    first_response = client.post(
        "/api/teams",
        json={"name": "第一团队", "members": [{"agentId": agent["agentId"], "role": "lead"}]},
    )

    response = client.post(
        "/api/teams",
        json={"name": "第二团队", "members": [{"agentId": agent["agentId"], "role": "reviewer"}]},
    )

    assert first_response.status_code == 201, first_response.text
    assert response.status_code == 422
    assert "already belongs to Team" in response.json()["detail"]


def test_team_list_route_materializes_evolution_system_teams(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chat_room_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(project_agent_bus_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(team_service, "PROJECT_ROOT", tmp_path)
    client = _client()

    response = client.get("/api/teams")

    assert response.status_code == 200, response.text
    teams = {team["teamId"]: team for team in response.json()["teams"]}
    assert {"self-evolution-team", "supervised-evolution-team"}.issubset(teams)
    assert teams["self-evolution-team"]["linkedChatRoomId"]
    assert teams["supervised-evolution-team"]["linkedChatRoomId"]
    assert response.json()["summary"]["activeTeamCount"] == 2


def test_team_list_route_skips_system_bootstrap_when_teams_exist(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chat_room_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(project_agent_bus_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(team_service, "PROJECT_ROOT", tmp_path)
    team_service.ensure_evolution_system_teams()
    monkeypatch.setattr(
        teams_route,
        "ensure_evolution_system_teams",
        lambda: (_ for _ in ()).throw(AssertionError("system team bootstrap should be skipped")),
    )
    client = _client()

    response = client.get("/api/teams")

    assert response.status_code == 200, response.text
    teams = {team["teamId"]: team for team in response.json()["teams"]}
    assert {"self-evolution-team", "supervised-evolution-team"}.issubset(teams)


def test_team_routes_save_canvas(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chat_room_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(project_agent_bus_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(team_service, "PROJECT_ROOT", tmp_path)
    client = _client()
    team = client.post("/api/teams", json={"name": "画布团队"}).json()
    assert team["linkedChatRoomId"]
    assert team["linkedChatRoom"]["participantCount"] == 0
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


def test_team_routes_sync_linked_chat_room(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chat_room_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(project_agent_bus_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(team_service, "PROJECT_ROOT", tmp_path)
    agent = agent_directory_service.create_agent_instance(display_name="Alpha", direct_session_id="session-alpha")
    client = _client()
    team = client.post("/api/teams", json={"name": "同步团队", "members": [{"agentId": agent["agentId"]}]}).json()

    response = client.post(f"/api/teams/{team['teamId']}/chat-room/sync")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["linkedChatRoomId"] == team["linkedChatRoomId"]
    room = client.get(f"/api/chat-rooms/{payload['linkedChatRoomId']}").json()
    assert room["config"]["source"] == "team"
    assert room["config"]["teamId"] == team["teamId"]


def test_archived_team_room_is_hidden_from_conversation_index(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chat_room_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(project_agent_bus_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(team_service, "PROJECT_ROOT", tmp_path)
    client = _client()
    team = client.post("/api/teams", json={"name": "医疗问诊"}).json()
    room_id = team["linkedChatRoomId"]

    archive_response = client.patch(f"/api/teams/{team['teamId']}", json={"status": "archived"})
    conversations = client.get("/api/conversations").json()
    room_response = client.get(f"/api/chat-rooms/{room_id}")

    assert archive_response.status_code == 200, archive_response.text
    assert archive_response.json()["status"] == "archived"
    assert all(item.get("roomId") != room_id for item in conversations)
    assert room_response.status_code == 200
    assert room_response.json()["roomId"] == room_id


def test_team_delete_route_cascades_member_agent_archive(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chat_room_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(project_agent_bus_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(team_service, "PROJECT_ROOT", tmp_path)
    agent = agent_directory_service.create_agent_instance(display_name="Alpha", direct_session_id="session-alpha")
    client = _client()
    team = client.post("/api/teams", json={"name": "删除团队", "members": [{"agentId": agent["agentId"]}]}).json()

    response = client.delete(f"/api/teams/{team['teamId']}")

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "archived"
    assert agent_directory_service.get_agent(agent["agentId"], include_archived=True)["status"] == "archived"


def test_team_delete_route_removes_archived_agent_from_extra_chat_rooms(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chat_room_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(project_agent_bus_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(team_service, "PROJECT_ROOT", tmp_path)
    alpha = session_service.create_chat_session(title="Alpha")
    beta = session_service.create_chat_session(title="Beta")
    client = _client()
    team = client.post("/api/teams", json={"name": "删除团队", "members": [{"agentId": alpha["agentId"]}]}).json()
    extra_room = chat_room_service.create_chat_room(
        title="额外群聊",
        participant_agent_ids=[alpha["agentId"], beta["agentId"]],
    )

    response = client.delete(f"/api/teams/{team['teamId']}")

    assert response.status_code == 200, response.text
    assert client.get(f"/api/chat-rooms/{team['linkedChatRoomId']}").status_code == 404
    extra_room_detail = client.get(f"/api/chat-rooms/{extra_room['roomId']}").json()
    assert [participant["agentId"] for participant in extra_room_detail["participants"]] == [beta["agentId"]]


def test_team_delete_route_repairs_already_archived_team_members(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chat_room_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(project_agent_bus_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(team_service, "PROJECT_ROOT", tmp_path)
    agent = agent_directory_service.create_agent_instance(display_name="Legacy", direct_session_id="session-legacy")
    client = _client()
    team = client.post("/api/teams", json={"name": "旧删除团队", "members": [{"agentId": agent["agentId"]}]}).json()
    state = team_service._load_index()
    stored = next(item for item in state["teams"] if item["teamId"] == team["teamId"])
    stored["status"] = "archived"
    team_service._save_index(state)

    response = client.delete(f"/api/teams/{team['teamId']}")

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "archived"
    assert agent_directory_service.get_agent(agent["agentId"], include_archived=True)["status"] == "archived"


def test_team_delete_route_rejects_system_team(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chat_room_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(project_agent_bus_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(team_service, "PROJECT_ROOT", tmp_path)
    team_service.ensure_evolution_system_teams()
    client = _client()

    response = client.delete("/api/teams/self-evolution-team")

    assert response.status_code == 422
    assert "System Team cannot be archived" in response.json()["detail"]


def test_team_routes_send_message_to_team_members(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chat_room_service, "PROJECT_ROOT", tmp_path)
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
