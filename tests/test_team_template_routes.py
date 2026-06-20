from fastapi.testclient import TestClient

from core.web.app import create_app
from core.web.control import CONTROL_TOKEN_HEADER, get_control_token
from core.web.services import agent_directory_service, chat_room_service, session_service, team_service, team_template_service
from tests.helpers.system_agent_state import _mark_config_agent_instances_present


def _client() -> TestClient:
    return TestClient(create_app(), headers={CONTROL_TOKEN_HEADER: get_control_token()})


def _use_tmp_project_root(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chat_room_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(team_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(team_template_service, "PROJECT_ROOT", tmp_path)


def test_team_template_routes_list_medical_demo_template(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    client = _client()

    response = client.get("/api/team-templates")

    assert response.status_code == 200, response.text
    templates = response.json()["templates"]
    medical = next(item for item in templates if item["templateId"] == "medical-consultation-demo")
    assert medical["defaultTeamName"] == "医疗问诊 Demo 团队"
    assert medical["roleCount"] == 4
    assert medical["chatRoom"]["mode"] == "medical_consultation_panel"
    assert medical["chatRoom"]["purpose"] == "medical_triage"

    heletech = next(item for item in templates if item["templateId"] == "heletech-maternal-digital-health-demo")
    assert heletech["defaultTeamName"] == "和乐妇幼数字健康 Demo 团队"
    assert heletech["roleCount"] == 5
    assert heletech["chatRoom"]["mode"] == "round_robin"
    assert heletech["chatRoom"]["purpose"] == "meeting"


def test_team_template_instantiate_creates_medical_team_agents_and_room(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _mark_config_agent_instances_present()
    client = _client()

    response = client.post(
        "/api/team-templates/medical-consultation-demo/instantiate",
        json={"name": "医疗问诊试运行"},
    )

    assert response.status_code == 201, response.text
    payload = response.json()
    team = payload["team"]
    assert team["name"] == "医疗问诊试运行"
    assert team["teamKind"] == "template_demo"
    assert team["teamCategory"] == "演示业务团队"
    assert team["teamSource"] == "team_template"
    assert team["teamTemplateId"] == "medical-consultation-demo"
    assert team["memberCount"] == 4
    assert len(payload["createdAgents"]) == 4
    assert team["linkedChatRoom"]["mode"] == "medical_consultation_panel"
    assert team["linkedChatRoom"]["purpose"] == "medical_triage"
    assert {member["role"] for member in team["members"]} == {
        "问诊主持 / 结果整理",
        "风险分诊 / 安全审查",
        "症状采集员",
        "全科/专科顾问",
    }

    room = client.get(f"/api/chat-rooms/{team['linkedChatRoomId']}").json()
    assert room["mode"] == "medical_consultation_panel"
    assert room["purpose"] == "medical_triage"
    assert room["config"]["teamKind"] == "template_demo"
    assert room["config"]["teamTemplateId"] == "medical-consultation-demo"
    assert len(room["participants"]) == 4
    assert [participant["teamRole"] for participant in room["participants"]][0] == "问诊主持 / 结果整理"

    canvas = client.get(f"/api/teams/{team['teamId']}/canvas").json()
    assert len(canvas["nodes"]) == 4
    assert len(canvas["edges"]) == 6
    assert canvas["validation"]["valid"] is True

    agents = client.get("/api/agents").json()
    demo_agents = [
        agent for agent in agents
        if agent.get("metadata", {}).get("teamTemplateId") == "medical-consultation-demo"
    ]
    assert len(demo_agents) == 4
    assert all("agent_message_tool" in agent["toolPolicy"]["allowedTools"] for agent in demo_agents)
    assert all("research_knowledge_query_tool" not in agent["toolPolicy"]["allowedTools"] for agent in demo_agents)


def test_team_template_instantiate_creates_heletech_demo_team(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _mark_config_agent_instances_present()
    client = _client()

    response = client.post(
        "/api/team-templates/heletech-maternal-digital-health-demo/instantiate",
        json={"name": "和乐演示试运行"},
    )

    assert response.status_code == 201, response.text
    payload = response.json()
    team = payload["team"]
    assert team["name"] == "和乐演示试运行"
    assert team["teamKind"] == "template_demo"
    assert team["teamCategory"] == "演示业务团队"
    assert team["teamSource"] == "team_template"
    assert team["teamTemplateId"] == "heletech-maternal-digital-health-demo"
    assert team["memberCount"] == 5
    assert len(payload["createdAgents"]) == 5
    assert team["linkedChatRoom"]["mode"] == "round_robin"
    assert team["linkedChatRoom"]["purpose"] == "meeting"
    assert {member["role"] for member in team["members"]} == {
        "方案主持",
        "妇幼业务顾问",
        "病历集成顾问",
        "数据科研顾问",
        "合规交付顾问",
    }
    assert [member["purpose"] for member in team["members"]] == [
        "方案编排",
        "妇幼流程",
        "病历集成",
        "科研数据",
        "合规交付",
    ]
    assert team["members"][1]["responsibilities"] == [
        "负责孕前、孕产、儿童保健、免疫接种、高危孕产妇和新生儿救治等业务流程建议。"
    ]

    room = client.get(f"/api/chat-rooms/{team['linkedChatRoomId']}").json()
    assert room["mode"] == "round_robin"
    assert room["purpose"] == "meeting"
    assert room["config"]["teamKind"] == "template_demo"
    assert room["config"]["teamTemplateId"] == "heletech-maternal-digital-health-demo"
    assert len(room["participants"]) == 5
    assert [participant["teamRole"] for participant in room["participants"]][0] == "方案主持"
    assert room["config"]["heletechMaternalDigitalHealthDemo"] is True

    canvas = client.get(f"/api/teams/{team['teamId']}/canvas").json()
    assert len(canvas["nodes"]) == 5
    assert len(canvas["edges"]) == 8
    assert canvas["validation"]["valid"] is True
    assert canvas["nodes"][0]["id"] == "heletech-1"
    assert [node["purpose"] for node in canvas["nodes"]] == ["方案编排", "妇幼流程", "病历集成", "科研数据", "合规交付"]

    agents = client.get("/api/agents").json()
    demo_agents = [
        agent for agent in agents
        if agent.get("metadata", {}).get("teamTemplateId") == "heletech-maternal-digital-health-demo"
    ]
    assert len(demo_agents) == 5
    assert all("agent_message_tool" in agent["toolPolicy"]["allowedTools"] for agent in demo_agents)
    assert all("research_knowledge_query_tool" not in agent["toolPolicy"]["allowedTools"] for agent in demo_agents)
    assert all(agent.get("metadata", {}).get("heletechMaternalDigitalHealthDemo") is True for agent in demo_agents)
    assert all("medicalTriageDemo" not in agent.get("metadata", {}) for agent in demo_agents)
