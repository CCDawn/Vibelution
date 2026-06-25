from fastapi.testclient import TestClient

from core.web.app import create_app
from core.web.control import CONTROL_TOKEN_HEADER, get_control_token
from core.web.routes import teams as teams_route
from core.web.services import agent_directory_service, chat_room_service, project_agent_bus_service, session_service, team_service
from tests.helpers.system_agent_state import _seed_ai_search_system_team_ready, _seed_system_team_bootstrap_ready


def _client() -> TestClient:
    return TestClient(create_app(), headers={CONTROL_TOKEN_HEADER: get_control_token()})


def _isolate_team_route_state(tmp_path, monkeypatch):
    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(tmp_path))
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chat_room_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(project_agent_bus_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(team_service, "PROJECT_ROOT", tmp_path)


def test_team_routes_create_detail_and_canvas(tmp_path, monkeypatch):
    _isolate_team_route_state(tmp_path, monkeypatch)
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


def test_team_routes_repair_knowledge_expansion_team_agents(tmp_path, monkeypatch):
    _isolate_team_route_state(tmp_path, monkeypatch)
    client = _client()

    response = client.post("/api/teams/knowledge-expansion-team/knowledge-expansion-agents/repair")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["teamId"] == "knowledge-expansion-team"
    assert payload["memberCount"] == 5
    assert payload["team"]["teamKind"] == "knowledge_expansion"
    assert payload["team"]["linkedChatRoom"]["purpose"] == "knowledge_expansion"


def test_team_routes_reject_agent_that_already_belongs_to_active_team(tmp_path, monkeypatch):
    _isolate_team_route_state(tmp_path, monkeypatch)
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


def test_team_list_route_schedules_system_bootstrap_without_inline_materialization(tmp_path, monkeypatch):
    _isolate_team_route_state(tmp_path, monkeypatch)
    requested_reasons = []

    def fake_request_system_team_bootstrap(*, reason):
        requested_reasons.append(reason)
        return {
            "schemaVersion": 1,
            "status": "running",
            "requiredSteps": ["evolution_system_teams", "ai_search_system_team"],
            "reason": reason,
            "startedAt": "2026-06-19T00:00:00Z",
            "finishedAt": "",
            "lastError": "",
            "elapsedMs": 0,
            "attempt": 1,
            "requestId": "test-bootstrap",
        }

    monkeypatch.setattr(teams_route, "request_system_team_bootstrap", fake_request_system_team_bootstrap)
    client = _client()

    response = client.get("/api/teams")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["teams"] == []
    assert payload["summary"]["activeTeamCount"] == 0
    assert payload["systemTeamBootstrap"]["status"] == "running"
    assert payload["systemTeamBootstrap"]["requiredSteps"] == ["evolution_system_teams", "ai_search_system_team"]
    assert requested_reasons == ["team_list"]


def test_team_list_route_reads_utf8_bom_team_index(tmp_path, monkeypatch):
    _isolate_team_route_state(tmp_path, monkeypatch)
    client = _client()
    create_response = client.post("/api/teams", json={"name": "BOM 团队"})
    assert create_response.status_code == 201, create_response.text

    index_path = team_service._teams_index_path()
    index_path.write_text(index_path.read_text(encoding="utf-8"), encoding="utf-8-sig")
    monkeypatch.setattr(
        teams_route,
        "request_system_team_bootstrap",
        lambda *, reason: {
            "schemaVersion": 1,
            "status": "ready",
            "requiredSteps": [],
            "reason": reason,
            "startedAt": "",
            "finishedAt": "2026-06-21T00:00:00Z",
            "lastError": "",
            "elapsedMs": 0,
            "attempt": 0,
            "requestId": "",
        },
    )

    response = client.get("/api/teams")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert [team["name"] for team in payload["teams"]] == ["BOM 团队"]
    assert payload["summary"]["activeTeamCount"] == 1
    assert payload["systemTeamBootstrap"]["status"] == "ready"


def test_ai_search_run_routes_start_and_list_runs(tmp_path, monkeypatch):
    _isolate_team_route_state(tmp_path, monkeypatch)

    def fake_web_search(query, *, max_results):
        return (
            f"关于「{query}」，搜索到 1 条相关结果：\n\n"
            "• 模型厂商发布了新动态。\n\n"
            "**参考来源：**\n"
            "1. [Official](https://example.com/official)\n"
        )

    monkeypatch.setattr(team_service, "_run_ai_web_search", fake_web_search)
    monkeypatch.setattr(team_service, "ensure_ai_search_system_team", _seed_ai_search_system_team_ready)
    client = _client()
    team_service.ensure_ai_search_system_team()

    response = client.post(
        "/api/teams/ai-search-team/ai-search-runs",
        json={"topic": "AI 模型最新动态", "sourceLimit": 3, "maxResultsPerQuery": 1},
    )

    assert response.status_code == 201, response.text
    run = response.json()
    assert run["teamId"] == "ai-search-team"
    assert run["status"] == "completed"
    assert run["summary"]["cardCount"] == 3
    assert run["cards"][0]["references"][0]["url"] == "https://example.com/official"

    list_response = client.get("/api/teams/ai-search-team/ai-search-runs")
    assert list_response.status_code == 200, list_response.text
    assert list_response.json()["runs"][0]["runId"] == run["runId"]


def test_ai_search_run_route_rejects_non_ai_search_team(tmp_path, monkeypatch):
    _isolate_team_route_state(tmp_path, monkeypatch)
    client = _client()
    team = client.post("/api/teams", json={"name": "普通团队"}).json()

    response = client.post(f"/api/teams/{team['teamId']}/ai-search-runs", json={})

    assert response.status_code == 422
    assert "AI search" in response.json()["detail"]


def test_team_list_route_reports_ready_when_system_teams_exist(tmp_path, monkeypatch):
    _isolate_team_route_state(tmp_path, monkeypatch)
    _seed_system_team_bootstrap_ready()
    client = _client()

    response = client.get("/api/teams")

    assert response.status_code == 200, response.text
    payload = response.json()
    teams = {team["teamId"]: team for team in payload["teams"]}
    assert {"self-evolution-team", "supervised-evolution-team", "ai-search-team", "knowledge-expansion-team"}.issubset(teams)
    assert payload["systemTeamBootstrap"]["status"] == "ready"
    assert payload["systemTeamBootstrap"]["requiredSteps"] == []


def test_team_routes_save_canvas(tmp_path, monkeypatch):
    _isolate_team_route_state(tmp_path, monkeypatch)
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


def test_team_canvas_route_returns_agent_identity_source_authority(tmp_path, monkeypatch):
    _isolate_team_route_state(tmp_path, monkeypatch)
    agent = agent_directory_service.create_agent_instance(display_name="Alpha Source", direct_session_id="session-alpha")
    client = _client()
    team = client.post("/api/teams", json={"name": "源边界团队", "members": [{"agentId": agent["agentId"], "role": "lead"}]}).json()
    canvas = client.get(f"/api/teams/{team['teamId']}/canvas").json()
    canvas["nodes"][0]["agentCode"] = "spoofed-code"
    canvas["nodes"][0]["agentName"] = "Spoofed Name"
    canvas["nodes"][0]["agentSourceRef"] = {"owner": "FakeProjection"}
    canvas["nodes"][0]["agentProjectionEdit"] = {"canonicalEditRoute": "/teams?team=fake"}
    canvas["nodes"][0]["agentProjectionCanWrite"] = True

    response = client.put(f"/api/teams/{team['teamId']}/canvas", json=canvas)

    assert response.status_code == 200, response.text
    node = response.json()["nodes"][0]
    assert node["agentCode"] == agent["agentCode"]
    assert node["agentName"] == agent["displayName"]
    assert node["agentSourceRef"]["owner"] == "AgentDirectory"
    assert node["agentSourceRef"]["canonicalEditRoute"] == f"/agents?agent={agent['agentId']}&pane=config"
    assert node["agentProjectionEdit"]["canWrite"] is False
    assert node["agentProjectionEdit"]["mode"] == "deep_link_to_source"
    assert node["agentProjectionCanWrite"] is False


def test_team_routes_sync_linked_chat_room(tmp_path, monkeypatch):
    _isolate_team_route_state(tmp_path, monkeypatch)
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


def test_archived_team_room_is_hidden_from_conversation_index_and_deleted(tmp_path, monkeypatch):
    _isolate_team_route_state(tmp_path, monkeypatch)
    client = _client()
    team = client.post("/api/teams", json={"name": "医疗问诊"}).json()
    room_id = team["linkedChatRoomId"]

    archive_response = client.patch(f"/api/teams/{team['teamId']}", json={"status": "archived"})
    conversations = client.get("/api/conversations").json()
    room_response = client.get(f"/api/chat-rooms/{room_id}")

    assert archive_response.status_code == 200, archive_response.text
    assert archive_response.json()["status"] == "archived"
    assert all(item.get("roomId") != room_id for item in conversations)
    assert room_response.status_code == 404


def test_team_delete_route_cascades_member_agent_archive(tmp_path, monkeypatch):
    _isolate_team_route_state(tmp_path, monkeypatch)
    agent = agent_directory_service.create_agent_instance(display_name="Alpha", direct_session_id="session-alpha")
    client = _client()
    team = client.post("/api/teams", json={"name": "删除团队", "members": [{"agentId": agent["agentId"]}]}).json()

    response = client.delete(f"/api/teams/{team['teamId']}")

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "archived"
    assert agent_directory_service.get_agent(agent["agentId"], include_archived=True)["status"] == "archived"


def test_team_delete_route_removes_archived_agent_from_extra_chat_rooms(tmp_path, monkeypatch):
    _isolate_team_route_state(tmp_path, monkeypatch)
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
    _isolate_team_route_state(tmp_path, monkeypatch)
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
    _isolate_team_route_state(tmp_path, monkeypatch)
    _seed_system_team_bootstrap_ready()
    client = _client()

    response = client.delete("/api/teams/self-evolution-team")

    assert response.status_code == 422
    assert "System Team cannot be archived" in response.json()["detail"]


def test_team_routes_send_message_to_team_members(tmp_path, monkeypatch):
    _isolate_team_route_state(tmp_path, monkeypatch)
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
