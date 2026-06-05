import json

import pytest
from fastapi.testclient import TestClient

from core.web.app import create_app
from core.web.control import CONTROL_TOKEN_HEADER, get_control_token
from core.web.services import (
    agent_directory_service,
    agent_mode_binding_service,
    research_organization_service,
    session_service,
    team_service,
)


class FakeWorkspace:
    def __init__(self, root):
        self.root = root / "workspace"

    def get_research_organization_path(self):
        return self.root / "research" / "organization_graph.json"

    def read_research_organization(self):
        path = self.get_research_organization_path()
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}

    def write_research_organization(self, data):
        path = self.get_research_organization_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return True


@pytest.fixture
def org_workspace(tmp_path, monkeypatch):
    workspace = FakeWorkspace(tmp_path)
    monkeypatch.setattr(research_organization_service, "get_workspace", lambda: workspace)
    monkeypatch.setattr(research_organization_service, "record_research_scene_event", lambda *args, **kwargs: None)
    return workspace


def _core_agents(org):
    ceo = next(node for node in org["agents"] if node["role"] == "ceo")
    advisor = next(node for node in org["agents"] if node["role"] == "organization_advisor")
    steward = next(node for node in org["agents"] if node["role"] == "capability_steward")
    return ceo, advisor, steward


def test_research_organization_initializes_protected_core_agents_with_explicit_tools(org_workspace):
    org = research_organization_service.get_research_organization()
    ceo, advisor, steward = _core_agents(org)

    assert org["path"].replace("\\", "/").endswith("workspace/research/organization_graph.json")
    assert ceo["protected"] is True
    assert advisor["protected"] is True
    assert steward["protected"] is True
    assert ceo["agent"]["metadata"]["systemRole"] == "ceo"
    assert advisor["agent"]["metadata"]["systemRole"] == "organization_advisor"
    assert steward["agent"]["metadata"]["systemRole"] == "capability_steward"
    assert ceo["toolPolicy"]["allowedTools"] == [
        "agent_message_tool",
        "research_agent_creation_proposal_tool",
        "research_communication_edge_proposal_tool",
        "research_proposal_apply_tool",
        "web_search_tool",
        "web_fetch_tool",
    ]
    assert advisor["toolPolicy"]["allowedTools"] == [
        "agent_message_tool",
        "agent_tool_permission_request_tool",
        "research_agent_creation_proposal_tool",
        "research_communication_edge_proposal_tool",
        "research_proposal_apply_tool",
        "web_search_tool",
        "web_fetch_tool",
    ]
    assert steward["toolPolicy"]["allowedTools"] == [
        "agent_message_tool",
        "agent_tool_permission_request_tool",
        "research_agent_creation_proposal_tool",
        "research_communication_edge_proposal_tool",
        "research_proposal_apply_tool",
        "web_search_tool",
        "web_fetch_tool",
        "read_memory_tool",
        "get_memory_summary_tool",
        "search_memory_tool",
        "read_dynamic_prompt_tool",
        "research_knowledge_query_tool",
    ]
    assert "write_file_tool" not in steward["toolPolicy"]["allowedTools"]
    assert "cli_tool" not in steward["toolPolicy"]["allowedTools"]
    assert steward["memoryPolicy"]["readSharedGroups"] == ["project", "research", "agent_config"]
    assert steward["memoryPolicy"]["writeSharedGroups"] == ["agent_config"]
    assert (ceo["agentId"], advisor["agentId"]) in {(edge["fromAgentId"], edge["toAgentId"]) for edge in org["edges"]}
    assert (ceo["agentId"], steward["agentId"]) in {(edge["fromAgentId"], edge["toAgentId"]) for edge in org["edges"]}
    assert (advisor["agentId"], steward["agentId"]) in {(edge["fromAgentId"], edge["toAgentId"]) for edge in org["edges"]}


def test_research_organization_archives_duplicate_core_nodes_and_marks_missing_agents_stale(org_workspace):
    org = research_organization_service.get_research_organization()
    ceo, _, _ = _core_agents(org)
    graph = org_workspace.read_research_organization()
    graph["agents"].extend(
        [
            {
                "nodeId": "duplicate-ceo",
                "agentId": "agent-missing-duplicate-ceo",
                "displayName": "旧 CEO Agent",
                "role": "ceo",
                "employeeRank": "ceo",
                "protected": True,
                "status": "active",
            },
            {
                "nodeId": "missing-specialist",
                "agentId": "agent-missing-specialist",
                "displayName": "缺失研究员",
                "role": "research_specialist",
                "employeeRank": "specialist",
                "status": "active",
            },
        ]
    )
    org_workspace.write_research_organization(graph)

    repaired = research_organization_service.get_research_organization()

    ceo_nodes = [node for node in repaired["agents"] if node["role"] == "ceo"]
    active_ceo_nodes = [node for node in ceo_nodes if node["status"] == "active"]
    missing_specialist = next(node for node in repaired["agents"] if node["agentId"] == "agent-missing-specialist")
    assert [node["agentId"] for node in active_ceo_nodes] == [ceo["agentId"]]
    assert "agent-missing-duplicate-ceo" not in {node["agentId"] for node in repaired["agents"]}
    assert missing_specialist["status"] == "stale"
    assert missing_specialist["missingAgent"] is True


def test_research_organization_canvas_repairs_when_active_canvas_agents_are_empty(org_workspace):
    org_workspace.write_research_organization(
        {
            "schemaVersion": 1,
            "agents": [
                {
                    "nodeId": "stale-ceo",
                    "agentId": "agent-missing-ceo",
                    "displayName": "旧 CEO",
                    "role": "ceo",
                    "employeeRank": "ceo",
                    "protected": True,
                    "status": "active",
                }
            ],
            "edges": [],
        }
    )

    canvas = research_organization_service.get_research_organization_canvas_graph()

    assert len(canvas["agents"]) >= 3
    assert {node["role"] for node in canvas["agents"]} >= {"ceo", "organization_advisor", "capability_steward"}
    assert all(node["agentId"] != "agent-missing-ceo" for node in canvas["agents"])
    assert all(node["status"] == "active" for node in canvas["agents"])


def test_research_organization_canvas_prunes_unresolvable_embedded_core_snapshots(org_workspace):
    ceo_detail = session_service.create_chat_session(title="绑定 CEO")
    advisor_detail = session_service.create_chat_session(title="绑定组织顾问")
    steward_detail = session_service.create_chat_session(title="绑定能力管家")
    ceo = agent_directory_service.update_agent_instance(
        ceo_detail["agentId"],
        primary_mode="research",
        role_key="research_ceo",
        metadata={"systemRole": "ceo", "researchOrgRole": "ceo", "protected": True},
    )
    advisor = agent_directory_service.update_agent_instance(
        advisor_detail["agentId"],
        primary_mode="research",
        role_key="research_organization_advisor",
        metadata={
            "systemRole": "organization_advisor",
            "researchOrgRole": "organization_advisor",
            "protected": True,
        },
    )
    steward = agent_directory_service.update_agent_instance(
        steward_detail["agentId"],
        primary_mode="research",
        role_key="research_capability_steward",
        metadata={"systemRole": "capability_steward", "researchOrgRole": "capability_steward", "protected": True},
    )
    agent_mode_binding_service.update_mode_binding(
        "research",
        default_agent_id=steward["agentId"],
        available_agent_ids=[steward["agentId"], advisor["agentId"], ceo["agentId"]],
        pool=[steward["agentId"], advisor["agentId"], ceo["agentId"]],
    )
    org_workspace.write_research_organization(
        {
            "schemaVersion": 1,
            "agents": [
                {
                    "nodeId": "embedded-ceo",
                    "agentId": "agent-embedded-missing-ceo",
                    "displayName": "嵌入快照 CEO",
                    "role": "ceo",
                    "employeeRank": "ceo",
                    "protected": True,
                    "status": "active",
                    "agent": {"agentId": "agent-embedded-missing-ceo", "status": "active"},
                }
            ],
            "edges": [
                {
                    "edgeId": "edge-embedded",
                    "fromAgentId": "agent-embedded-missing-ceo",
                    "toAgentId": "agent-embedded-missing-advisor",
                    "status": "active",
                }
            ],
        }
    )

    canvas = research_organization_service.get_research_organization_canvas_graph()

    assert {node["agentId"] for node in canvas["agents"]} == {
        ceo["agentId"],
        advisor["agentId"],
        steward["agentId"],
    }
    assert "agent-embedded-missing-ceo" not in {node["agentId"] for node in canvas["agents"]}
    assert all("embedded" not in edge["edgeId"] for edge in canvas["edges"])


def test_research_organization_prefers_research_mode_binding_when_repairing_core_nodes(org_workspace):
    ceo_detail = session_service.create_chat_session(title="绑定 CEO")
    advisor_detail = session_service.create_chat_session(title="绑定组织顾问")
    steward_detail = session_service.create_chat_session(title="绑定能力管家")
    ceo = agent_directory_service.update_agent_instance(
        ceo_detail["agentId"],
        primary_mode="research",
        role_key="research_ceo",
        metadata={"systemRole": "ceo", "researchOrgRole": "ceo", "protected": True},
    )
    advisor = agent_directory_service.update_agent_instance(
        advisor_detail["agentId"],
        primary_mode="research",
        role_key="research_organization_advisor",
        metadata={
            "systemRole": "organization_advisor",
            "researchOrgRole": "organization_advisor",
            "protected": True,
        },
    )
    steward = agent_directory_service.update_agent_instance(
        steward_detail["agentId"],
        primary_mode="research",
        role_key="research_capability_steward",
        metadata={
            "systemRole": "capability_steward",
            "researchOrgRole": "capability_steward",
            "protected": True,
        },
    )
    duplicate_detail = session_service.create_chat_session(title="误建 CEO")
    duplicate = agent_directory_service.update_agent_instance(
        duplicate_detail["agentId"],
        primary_mode="research",
        role_key="research_ceo",
        metadata={"systemRole": "ceo", "researchOrgRole": "ceo", "protected": True},
    )
    agent_mode_binding_service.update_mode_binding(
        "research",
        default_agent_id=steward["agentId"],
        available_agent_ids=[steward["agentId"], advisor["agentId"], ceo["agentId"]],
        pool=[steward["agentId"], advisor["agentId"], ceo["agentId"]],
    )
    org_workspace.write_research_organization(
        {
            "schemaVersion": 1,
            "agents": [
                {
                    "nodeId": duplicate["agentId"],
                    "agentId": duplicate["agentId"],
                    "displayName": "误建 CEO",
                    "role": "ceo",
                    "employeeRank": "ceo",
                    "protected": True,
                    "status": "active",
                    "agent": duplicate,
                },
                {
                    "nodeId": ceo["agentId"],
                    "agentId": ceo["agentId"],
                    "displayName": "绑定 CEO",
                    "role": "ceo",
                    "employeeRank": "ceo",
                    "protected": True,
                    "status": "active",
                    "agent": ceo,
                },
            ],
            "edges": [
                {
                    "edgeId": f"edge-{duplicate['agentId']}-{advisor['agentId']}",
                    "fromAgentId": duplicate["agentId"],
                    "toAgentId": advisor["agentId"],
                    "label": "误建核心边",
                    "communicationPolicy": {},
                    "status": "active",
                }
            ],
        }
    )

    repaired = research_organization_service.get_research_organization()

    active_ids_by_role = {
        role: [
            node["agentId"]
            for node in repaired["agents"]
            if node["role"] == role and node["status"] == "active"
        ]
        for role in ("ceo", "organization_advisor", "capability_steward")
    }
    active_edge_endpoints = {
        (edge["fromAgentId"], edge["toAgentId"])
        for edge in repaired["edges"]
        if edge["status"] == "active"
    }
    assert active_ids_by_role == {
        "ceo": [ceo["agentId"]],
        "organization_advisor": [advisor["agentId"]],
        "capability_steward": [steward["agentId"]],
    }
    assert duplicate["agentId"] not in {node["agentId"] for node in repaired["agents"]}
    assert all(duplicate["agentId"] not in endpoints for endpoints in active_edge_endpoints)
    assert all(
        duplicate["agentId"] not in {edge["fromAgentId"], edge["toAgentId"]}
        for edge in repaired["edges"]
    )


def test_research_organization_context_block_is_filtered_to_connected_subgraph(org_workspace):
    org = research_organization_service.get_research_organization()
    ceo, advisor, steward = _core_agents(org)
    outsider = session_service.create_chat_session(title="断开研究员 Agent")
    outsider_agent = agent_directory_service.update_agent_instance(
        outsider["agentId"],
        primary_mode="research",
        role_key="research_specialist",
        metadata={"researchOrgRole": "research_specialist", "employeeRank": "specialist"},
    )
    graph = org_workspace.read_research_organization()
    graph["agents"].append(
        {
            "nodeId": outsider_agent["agentId"],
            "agentId": outsider_agent["agentId"],
            "role": "research_specialist",
            "employeeRank": "specialist",
            "status": "active",
        }
    )
    org_workspace.write_research_organization(graph)

    block = research_organization_service.build_research_organization_context_block(ceo["agentId"])

    assert "Research Organization Context" in block
    assert ceo["agentCode"] in block
    assert advisor["agentCode"] in block
    assert steward["agentCode"] in block
    assert f"edge-{ceo['agentId']}-{advisor['agentId']}" in block
    assert "allowedTypes=" in block
    assert "Use AgentId or AgentCode with agent_message_tool" in block
    assert f"agentId={outsider_agent['agentId']} " not in block


def test_user_message_bypasses_edges_and_wakes_target(org_workspace, monkeypatch):
    org = research_organization_service.get_research_organization()
    _, advisor, _ = _core_agents(org)
    wakes = []

    def fake_wake(message):
        wakes.append(message)
        return {
            "wakeRequested": True,
            "wakeStatus": "started",
            "messageId": message["messageId"],
            "targetAgentId": message["targetAgentId"],
            "targetSessionId": message["targetSessionId"],
            "turnId": "turn-1",
            "reason": "",
        }

    monkeypatch.setattr(session_service, "wake_agent_for_inbox_message", fake_wake)

    result = research_organization_service.send_research_org_message(
        {
            "sourceType": "user",
            "targetAgentId": advisor["agentId"],
            "messageType": "task",
            "content": "请评估是否需要新增神经科学专家。",
        }
    )

    delivery = result["message"]["deliveries"][0]
    assert delivery["allowed"] is True
    assert delivery["reason"] == "human_override"
    assert delivery["wakeStatus"] == "started"
    assert wakes and wakes[0]["metadata"]["humanOverride"] is True


def test_research_organization_routes_expose_graph_and_message_bus(org_workspace):
    client = TestClient(create_app(), headers={CONTROL_TOKEN_HEADER: get_control_token()})

    org_response = client.get("/api/research/organization")
    assert org_response.status_code == 200
    ceo, _, _ = _core_agents(org_response.json())

    message_response = client.post(
        "/api/research/organization/messages",
        json={
            "targetAgentId": ceo["agentId"],
            "messageType": "notice",
            "content": "路由层组织消息测试。",
            "wakeTarget": False,
            "mailboxOnly": True,
        },
    )

    assert message_response.status_code == 201, message_response.text
    payload = message_response.json()
    assert payload["message"]["deliveries"][0]["allowed"] is True
    assert payload["message"]["deliveries"][0]["wakeStatus"] == "not_requested"


def test_agent_message_without_edge_is_blocked_and_audited(org_workspace):
    org = research_organization_service.get_research_organization()
    _, advisor, _ = _core_agents(org)
    outsider = session_service.create_chat_session(title="外部科研 Agent")
    outsider_agent = agent_directory_service.update_agent_instance(
        outsider["agentId"],
        primary_mode="research",
        role_key="research_outsider",
        metadata={"researchOrgRole": "research_outsider", "employeeRank": "specialist"},
        tool_policy={"allowedTools": ["agent_message_tool"]},
    )
    graph = org_workspace.read_research_organization()
    graph["agents"].append(
        {
            "nodeId": outsider_agent["agentId"],
            "agentId": outsider_agent["agentId"],
            "role": "research_outsider",
            "employeeRank": "specialist",
            "status": "active",
            "x": 100,
            "y": 320,
        }
    )
    org_workspace.write_research_organization(graph)

    result = research_organization_service.send_research_org_message(
        {
            "sourceType": "agent",
            "sourceAgentId": advisor["agentId"],
            "targetAgentId": outsider_agent["agentId"],
            "messageType": "notice",
            "intent": "status_report",
            "content": "越权广播测试。",
            "wakeTarget": False,
        }
    )

    delivery = result["message"]["deliveries"][0]
    assert delivery["allowed"] is False
    assert delivery["reason"] == "communication_edge_missing"
    assert result["organization"]["auditEvents"][-1]["eventType"] == "message_blocked"


def test_required_supervision_policy_blocks_agent_research_org_message(org_workspace, monkeypatch):
    org = research_organization_service.get_research_organization()
    ceo, advisor, _ = _core_agents(org)
    recorded_events = []
    monkeypatch.setattr(
        agent_directory_service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: recorded_events.append((args, kwargs)) or {"accepted": True},
    )
    agent_directory_service.update_agent_instance(
        ceo["agentId"],
        supervision_policy={
            "supervisionEnabled": True,
            "requiresReview": True,
            "reviewMode": "required",
            "evidenceLevel": "strict",
        },
    )

    result = research_organization_service.send_research_org_message(
        {
            "sourceType": "agent",
            "sourceAgentId": ceo["agentId"],
            "targetAgentId": advisor["agentId"],
            "messageType": "task",
            "intent": "decision_request",
            "content": "这条自主任务需要先复核。",
            "wakeTarget": True,
        }
    )

    delivery = result["message"]["deliveries"][0]
    assert delivery["allowed"] is False
    assert delivery["reason"] == "supervision_review_required"
    assert delivery["wakeStatus"] == "blocked"
    assert delivery["supervision"]["reviewMode"] == "required"
    assert delivery["supervision"]["evidenceLevel"] == "strict"
    assert delivery["inboxMessageId"] == ""
    assert agent_directory_service.list_agent_inbox_messages_for_agent(advisor["agentId"], status="pending") == []
    assert result["organization"]["auditEvents"][-1]["eventType"] == "message_blocked"
    assert result["organization"]["auditEvents"][-1]["reason"] == "supervision_review_required"
    assert any(
        event[0][:3] == ("supervision_policy", "execute", "supervision.policy_blocked")
        and event[1]["fields"]["agentId"] == ceo["agentId"]
        and event[1]["fields"]["action"] == "research_org_message"
        and event[1]["fields"]["reviewMode"] == "required"
        for event in recorded_events
    )


def test_advisory_supervision_policy_observes_agent_message_without_blocking(org_workspace, monkeypatch):
    org = research_organization_service.get_research_organization()
    ceo, advisor, _ = _core_agents(org)
    recorded_events = []
    monkeypatch.setattr(
        agent_directory_service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: recorded_events.append((args, kwargs)) or {"accepted": True},
    )
    agent_directory_service.update_agent_instance(
        ceo["agentId"],
        supervision_policy={
            "supervisionEnabled": True,
            "requiresReview": False,
            "reviewMode": "advisory",
            "evidenceLevel": "light",
        },
    )

    result = research_organization_service.send_research_org_message(
        {
            "sourceType": "agent",
            "sourceAgentId": ceo["agentId"],
            "targetAgentId": advisor["agentId"],
            "messageType": "task",
            "intent": "decision_request",
            "content": "这条自主任务允许发送但要留下监督观察。",
            "wakeTarget": False,
        }
    )

    delivery = result["message"]["deliveries"][0]
    assert delivery["allowed"] is True
    assert delivery["reason"] == "policy_allowed"
    assert delivery["supervision"]["reviewMode"] == "advisory"
    assert delivery["supervision"]["requiresReview"] is False
    assert delivery["inboxMessageId"]
    assert any(
        event[0][:3] == ("supervision_policy", "execute", "supervision.policy_observed")
        and event[1]["fields"]["agentId"] == ceo["agentId"]
        and event[1]["fields"]["action"] == "research_org_message"
        and event[1]["fields"]["reviewMode"] == "advisory"
        for event in recorded_events
    )


def test_disabled_supervision_policy_does_not_gate_agent_message(org_workspace, monkeypatch):
    org = research_organization_service.get_research_organization()
    ceo, advisor, _ = _core_agents(org)
    recorded_events = []
    monkeypatch.setattr(
        agent_directory_service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: recorded_events.append((args, kwargs)) or {"accepted": True},
    )
    agent_directory_service.update_agent_instance(
        ceo["agentId"],
        supervision_policy={
            "supervisionEnabled": True,
            "requiresReview": True,
            "reviewMode": "disabled",
            "evidenceLevel": "strict",
        },
    )

    result = research_organization_service.send_research_org_message(
        {
            "sourceType": "agent",
            "sourceAgentId": ceo["agentId"],
            "targetAgentId": advisor["agentId"],
            "messageType": "task",
            "intent": "decision_request",
            "content": "监督禁用时不应阻断。",
            "wakeTarget": False,
        }
    )

    delivery = result["message"]["deliveries"][0]
    assert delivery["allowed"] is True
    assert delivery["reason"] == "policy_allowed"
    assert delivery["supervision"]["reviewMode"] == "disabled"
    assert delivery["supervision"]["requiresReview"] is False
    assert not any(event[0][:3] == ("supervision_policy", "execute", "supervision.policy_blocked") for event in recorded_events)


def test_upward_report_enters_mailbox_without_wake_and_ceo_task_wakes(org_workspace, monkeypatch):
    org = research_organization_service.get_research_organization()
    ceo, advisor, _ = _core_agents(org)
    wakes = []

    def fake_wake(message):
        wakes.append(message["messageId"])
        return {
            "wakeRequested": True,
            "wakeStatus": "started",
            "messageId": message["messageId"],
            "targetAgentId": message["targetAgentId"],
            "targetSessionId": message["targetSessionId"],
            "turnId": "turn-started",
            "reason": "",
        }

    monkeypatch.setattr(session_service, "wake_agent_for_inbox_message", fake_wake)

    report = research_organization_service.send_research_org_message(
        {
            "sourceType": "agent",
            "sourceAgentId": advisor["agentId"],
            "targetAgentId": ceo["agentId"],
            "messageType": "report",
            "intent": "status_report",
            "content": "建议新增一个论文审查 Agent。",
            "wakeTarget": True,
        }
    )
    task = research_organization_service.send_research_org_message(
        {
            "sourceType": "agent",
            "sourceAgentId": ceo["agentId"],
            "targetAgentId": advisor["agentId"],
            "messageType": "task",
            "intent": "decision_request",
            "content": "请形成组织调整提案。",
            "wakeTarget": True,
        }
    )

    assert report["message"]["deliveries"][0]["allowed"] is True
    assert report["message"]["deliveries"][0]["wakeStatus"] == "not_requested"
    assert task["message"]["deliveries"][0]["wakeStatus"] == "started"
    assert len(wakes) == 1


def test_core_capability_steward_edges_route_policy_requests(org_workspace):
    org = research_organization_service.get_research_organization()
    ceo, advisor, steward = _core_agents(org)

    ceo_request = research_organization_service.send_research_org_message(
        {
            "sourceType": "agent",
            "sourceAgentId": ceo["agentId"],
            "targetAgentId": steward["agentId"],
            "messageType": "task",
            "intent": "tool_policy",
            "content": "请审查数据库试水团队的工具权限。",
            "wakeTarget": False,
        }
    )
    advisor_request = research_organization_service.send_research_org_message(
        {
            "sourceType": "agent",
            "sourceAgentId": advisor["agentId"],
            "targetAgentId": steward["agentId"],
            "messageType": "request",
            "intent": "permission_review",
            "content": "请确认新成员是否只需要只读工具。",
            "wakeTarget": False,
        }
    )
    steward_report = research_organization_service.send_research_org_message(
        {
            "sourceType": "agent",
            "sourceAgentId": steward["agentId"],
            "targetAgentId": ceo["agentId"],
            "messageType": "report",
            "intent": "capability_report",
            "content": "建议暂不开放写文件工具。",
            "wakeTarget": True,
        }
    )

    assert ceo_request["message"]["deliveries"][0]["allowed"] is True
    assert advisor_request["message"]["deliveries"][0]["allowed"] is True
    assert steward_report["message"]["deliveries"][0]["allowed"] is True
    assert steward_report["message"]["deliveries"][0]["wakeStatus"] == "not_requested"


def test_core_management_edges_allow_ceo_approval_notice_and_capability_design(org_workspace):
    org = research_organization_service.get_research_organization()
    ceo, advisor, steward = _core_agents(org)

    notice = research_organization_service.send_research_org_message(
        {
            "sourceType": "agent",
            "sourceAgentId": ceo["agentId"],
            "targetAgentId": advisor["agentId"],
            "messageType": "notice",
            "intent": "notice",
            "content": "已收到用户确认，请停止重复提交同类提案。",
            "wakeTarget": False,
        }
    )
    approve = research_organization_service.send_research_org_message(
        {
            "sourceType": "agent",
            "sourceAgentId": ceo["agentId"],
            "targetAgentId": steward["agentId"],
            "messageType": "decision",
            "intent": "approve",
            "content": "批准按当前方案准备能力配置。",
            "wakeTarget": False,
        }
    )
    capability_design = research_organization_service.send_research_org_message(
        {
            "sourceType": "agent",
            "sourceAgentId": ceo["agentId"],
            "targetAgentId": steward["agentId"],
            "messageType": "request",
            "intent": "capability_design",
            "content": "请调整记忆库管理 Agent 的能力设计。",
            "wakeTarget": False,
        }
    )

    assert notice["message"]["deliveries"][0]["allowed"] is True
    assert approve["message"]["deliveries"][0]["allowed"] is True
    assert capability_design["message"]["deliveries"][0]["allowed"] is True


def test_busy_target_keeps_pending_message_and_retry_can_wake(org_workspace, monkeypatch):
    org = research_organization_service.get_research_organization()
    ceo, advisor, _ = _core_agents(org)
    wake_statuses = ["skipped_busy", "started"]

    def fake_wake(message):
        status = wake_statuses.pop(0)
        if status == "started":
            agent_directory_service.consume_agent_inbox_message(
                message["targetAgentId"],
                message["messageId"],
                consumed_by_session_id=message["targetSessionId"],
                consumed_by_turn_id="turn-after-retry",
            )
        return {
            "wakeRequested": True,
            "wakeStatus": status,
            "messageId": message["messageId"],
            "targetAgentId": message["targetAgentId"],
            "targetSessionId": message["targetSessionId"],
            "turnId": "turn-after-retry" if status == "started" else "",
            "reason": "target_session_busy" if status == "skipped_busy" else "",
        }

    monkeypatch.setattr(session_service, "wake_agent_for_inbox_message", fake_wake)
    result = research_organization_service.send_research_org_message(
        {
            "sourceType": "agent",
            "sourceAgentId": ceo["agentId"],
            "targetAgentId": advisor["agentId"],
            "messageType": "task",
            "intent": "decision_request",
            "content": "忙碌重试测试。",
            "wakeTarget": True,
        }
    )
    inbox_id = result["message"]["deliveries"][0]["inboxMessageId"]

    assert result["message"]["deliveries"][0]["wakeStatus"] == "skipped_busy"
    assert agent_directory_service.list_agent_inbox_messages_for_agent(advisor["agentId"], status="pending")

    retry = research_organization_service.retry_research_org_message_wake(result["message"]["messageId"])

    assert retry["results"][0]["wakeStatus"] == "started"
    assert retry["message"]["deliveries"][0]["inboxMessageId"] == inbox_id
    assert agent_directory_service.list_agent_inbox_messages_for_agent(advisor["agentId"], status="pending") == []


def test_protected_core_agents_cannot_be_archived(org_workspace):
    org = research_organization_service.get_research_organization()
    _, _, steward = _core_agents(org)

    with pytest.raises(agent_directory_service.AgentDirectoryError, match="Protected core Agent"):
        agent_directory_service.archive_agent_instance(steward["agentId"])


def test_high_risk_create_agent_proposal_requires_user_apply(org_workspace):
    proposal_result = research_organization_service.create_research_org_proposal(
        {
            "title": "新增神经科学专家 Agent",
            "actions": [
                {
                    "actionType": "create_agent",
                    "displayName": "神经科学专家 Agent",
                    "role": "neuroscience_specialist",
                    "employeeRank": "specialist",
                    "allowedTools": ["agent_message_tool", "web_search_tool"],
                }
            ],
        }
    )
    proposal = proposal_result["proposal"]

    assert proposal["status"] == "pending_user_confirmation"
    assert proposal["requiresUserConfirmation"] is True

    applied = research_organization_service.apply_research_org_proposal(
        proposal["proposalId"],
        confirmation={"source": "test", "text": "用户确认新增神经科学专家"},
    )

    created = applied["results"][0]
    assert created["status"] == "applied"
    assert created["agentId"]
    created_node = next(node for node in applied["organization"]["agents"] if node["agentId"] == created["agentId"])
    assert created_node["allowedTools"] == ["agent_message_tool", "web_search_tool"]
    assert applied["proposal"]["auditTrail"][-1]["confirmation"]["text"] == "用户确认新增神经科学专家"


def test_equivalent_pending_create_agent_proposal_is_reused(org_workspace):
    first = research_organization_service.create_research_org_proposal(
        {
            "actions": [
                {
                    "actionType": "create_agent",
                    "displayName": "记忆库管理员",
                    "role": "memory_steward",
                    "roleKey": "memory_steward",
                    "allowedTools": ["agent_message_tool"],
                }
            ],
        }
    )
    second = research_organization_service.create_research_org_proposal(
        {
            "actions": [
                {
                    "actionType": "create_agent",
                    "displayName": "记忆库管理员",
                    "role": "memory_steward",
                    "roleKey": "memory_steward",
                    "allowedTools": ["agent_message_tool", "web_search_tool"],
                }
            ],
        }
    )

    assert second.get("reused") is True
    assert second["proposal"]["proposalId"] == first["proposal"]["proposalId"]
    org = research_organization_service.get_research_organization()
    matching = [
        item for item in org["proposals"]
        if item["proposalId"] == first["proposal"]["proposalId"]
    ]
    assert len(matching) == 1


def test_duplicate_pending_create_agent_proposals_are_superseded_on_repair(org_workspace):
    first = research_organization_service.create_research_org_proposal(
        {
            "actions": [
                {
                    "actionType": "create_agent",
                    "displayName": "记忆库管理员",
                    "role": "memory_curator",
                    "roleKey": "memory_curator",
                    "allowedTools": ["agent_message_tool"],
                }
            ],
        }
    )["proposal"]
    graph = org_workspace.read_research_organization()
    duplicate = json.loads(json.dumps(first))
    duplicate["proposalId"] = "roprop-duplicate-memory-curator"
    duplicate["createdAt"] = "2026-01-01T00:00:00+00:00"
    duplicate["updatedAt"] = "2026-01-01T00:00:00+00:00"
    graph["proposals"].append(duplicate)
    org_workspace.write_research_organization(graph)

    repaired = research_organization_service.get_research_organization()

    canonical = next(item for item in repaired["proposals"] if item["proposalId"] == first["proposalId"])
    superseded = next(item for item in repaired["proposals"] if item["proposalId"] == duplicate["proposalId"])
    assert canonical["status"] == "pending_user_confirmation"
    assert superseded["status"] == "superseded"
    assert superseded["supersededByProposalId"] == first["proposalId"]


def test_semantic_duplicate_memory_manager_proposals_are_superseded_on_repair(org_workspace):
    curator = research_organization_service.create_research_org_proposal(
        {
            "actions": [
                {
                    "actionType": "create_agent",
                    "displayName": "记忆库管理员",
                    "role": "memory_curator",
                    "roleKey": "memory_curator",
                    "allowedTools": ["agent_message_tool"],
                }
            ],
        }
    )["proposal"]
    graph = org_workspace.read_research_organization()
    steward = json.loads(json.dumps(curator))
    steward["proposalId"] = "roprop-duplicate-memory-steward"
    steward["title"] = "新增记忆库管理agent"
    steward["actions"][0]["displayName"] = "记忆库管理agent"
    steward["actions"][0]["role"] = "memory_steward"
    steward["actions"][0]["roleKey"] = "memory_steward"
    graph["proposals"].append(steward)
    org_workspace.write_research_organization(graph)

    repaired = research_organization_service.get_research_organization()

    canonical = next(item for item in repaired["proposals"] if item["proposalId"] == curator["proposalId"])
    superseded = next(item for item in repaired["proposals"] if item["proposalId"] == steward["proposalId"])
    assert canonical["status"] == "pending_user_confirmation"
    assert superseded["status"] == "superseded"
    assert superseded["supersededByProposalId"] == curator["proposalId"]


def test_generic_research_specialist_role_does_not_merge_distinct_agent_names(org_workspace):
    first = research_organization_service.create_research_org_proposal(
        {
            "actions": [
                {
                    "actionType": "create_agent",
                    "displayName": "技术架构分析师",
                    "role": "research_specialist",
                    "allowedTools": ["agent_message_tool"],
                }
            ],
        }
    )
    second = research_organization_service.create_research_org_proposal(
        {
            "actions": [
                {
                    "actionType": "create_agent",
                    "displayName": "数据库工程师",
                    "role": "research_specialist",
                    "allowedTools": ["agent_message_tool"],
                }
            ],
        }
    )

    assert second.get("reused") is not True
    assert second["proposal"]["proposalId"] != first["proposal"]["proposalId"]


def test_create_agent_proposal_separates_unknown_tools_from_allowed_tools(org_workspace):
    proposal = research_organization_service.create_research_org_proposal(
        {
            "actions": [
                {
                    "actionType": "create_agent",
                    "displayName": "记忆库管理员",
                    "role": "memory_steward",
                    "roleKey": "memory_steward",
                    "allowedTools": [
                        "agent_message_tool",
                        "memory_tools.py",
                        "codebase_analyzer",
                        "web_search_tool",
                    ],
                }
            ],
        }
    )["proposal"]
    action = proposal["actions"][0]

    assert action["allowedTools"] == ["agent_message_tool", "web_search_tool"]
    assert action["missingTools"] == ["memory_tools.py", "codebase_analyzer"]
    assert action["requestedTools"] == ["memory_tools.py", "codebase_analyzer"]

    applied = research_organization_service.apply_research_org_proposal(
        proposal["proposalId"],
        confirmation={"source": "test", "text": "用户确认创建记忆库管理员"},
    )

    created = applied["results"][0]
    created_node = next(node for node in applied["organization"]["agents"] if node["agentId"] == created["agentId"])
    assert created_node["allowedTools"] == ["agent_message_tool", "web_search_tool"]


def test_historical_pending_create_agent_proposal_allowed_tools_are_repaired(org_workspace):
    proposal = research_organization_service.create_research_org_proposal(
        {
            "actions": [
                {
                    "actionType": "create_agent",
                    "displayName": "记忆库管理员",
                    "role": "memory_steward",
                    "roleKey": "memory_steward",
                    "allowedTools": ["agent_message_tool"],
                }
            ],
        }
    )["proposal"]
    graph = org_workspace.read_research_organization()
    stored = next(item for item in graph["proposals"] if item["proposalId"] == proposal["proposalId"])
    stored["actions"][0]["allowedTools"] = [
        "agent_message_tool",
        "memory_tools.py",
        "codebase_analyzer",
        "web_search_tool",
    ]
    org_workspace.write_research_organization(graph)

    repaired = research_organization_service.get_research_organization()

    repaired_proposal = next(item for item in repaired["proposals"] if item["proposalId"] == proposal["proposalId"])
    repaired_action = repaired_proposal["actions"][0]
    assert repaired_action["allowedTools"] == ["agent_message_tool", "web_search_tool"]
    assert repaired_action["missingTools"] == ["memory_tools.py", "codebase_analyzer"]
    assert repaired_action["requestedTools"] == ["memory_tools.py", "codebase_analyzer"]


def test_applying_confirmed_create_agent_proposal_is_idempotent(org_workspace):
    proposal = research_organization_service.create_research_org_proposal(
        {
            "actions": [
                {
                    "actionType": "create_agent",
                    "displayName": "记忆库管理员",
                    "role": "memory_steward",
                    "roleKey": "memory_steward",
                    "allowedTools": ["agent_message_tool"],
                }
            ],
        }
    )["proposal"]

    applied = research_organization_service.apply_research_org_proposal(proposal["proposalId"])
    repeated = research_organization_service.apply_research_org_proposal(proposal["proposalId"])

    assert applied["results"][0]["status"] == "applied"
    created_agent_id = applied["results"][0]["agentId"]
    assert created_agent_id
    assert repeated["results"] == []
    org = research_organization_service.get_research_organization()
    created_nodes = [node for node in org["agents"] if node["agentId"] == created_agent_id]
    assert len(created_nodes) == 1


def test_edge_proposal_apply_syncs_research_team_canvas(org_workspace):
    org = research_organization_service.get_research_organization()
    ceo, _, steward = _core_agents(org)

    proposal = research_organization_service.create_research_org_proposal(
        {
            "actions": [
                {
                    "actionType": "update_communication_edge",
                    "fromAgentId": ceo["agentId"],
                    "toAgentId": steward["agentId"],
                    "label": "CEO 请求能力策略复核",
                    "communicationPolicy": {
                        "allowedMessageTypes": ["request", "task"],
                        "allowedIntents": ["capability_policy", "decision_request"],
                        "wakeStrategy": "immediate",
                    },
                }
            ],
        }
    )["proposal"]

    applied = research_organization_service.apply_research_org_proposal(proposal["proposalId"])

    updated_edge = next(
        edge for edge in applied["organization"]["edges"]
        if edge["fromAgentId"] == ceo["agentId"] and edge["toAgentId"] == steward["agentId"]
    )
    canvas = team_service.get_team_canvas("research-team")
    canvas_edge = next(
        edge for edge in canvas["edges"]
        if edge["source"] == ceo["agentId"] and edge["target"] == steward["agentId"] and edge.get("type") == "communication"
    )
    assert updated_edge["label"] == "CEO 请求能力策略复核"
    assert canvas_edge["label"] == "CEO 请求能力策略复核"


def test_archived_former_agent_stays_visible_but_cannot_receive_new_task(org_workspace):
    create_result = research_organization_service.apply_research_org_proposal(
        research_organization_service.create_research_org_proposal(
            {
                "actions": [
                    {
                        "actionType": "create_agent",
                        "displayName": "临时研究员 Agent",
                        "allowedTools": ["agent_message_tool"],
                    }
                ],
            }
        )["proposal"]["proposalId"]
    )
    created_agent_id = create_result["results"][0]["agentId"]
    org = create_result["organization"]
    ceo, _, _ = _core_agents(org)
    edge_result = research_organization_service.apply_research_org_proposal(
        research_organization_service.create_research_org_proposal(
            {
                "actions": [
                    {
                        "actionType": "create_edge",
                        "fromAgentId": ceo["agentId"],
                        "toAgentId": created_agent_id,
                        "communicationPolicy": {
                            "allowedMessageTypes": ["task"],
                            "wakeStrategy": "mailbox_only",
                        },
                    }
                ],
            }
        )["proposal"]["proposalId"]
    )
    assert any(edge["toAgentId"] == created_agent_id for edge in edge_result["organization"]["edges"])

    archive_result = research_organization_service.apply_research_org_proposal(
        research_organization_service.create_research_org_proposal(
            {
                "actions": [
                    {
                        "actionType": "archive_agent",
                        "agentId": created_agent_id,
                    }
                ],
            }
        )["proposal"]["proposalId"]
    )
    archived_node = next(node for node in archive_result["organization"]["agents"] if node["agentId"] == created_agent_id)
    assert archived_node["status"] == "archived"

    blocked = research_organization_service.send_research_org_message(
        {
            "sourceType": "agent",
            "sourceAgentId": ceo["agentId"],
            "targetAgentId": created_agent_id,
            "messageType": "task",
            "intent": "decision_request",
            "content": "归档后不应再接收任务。",
        }
    )

    assert blocked["message"]["deliveries"][0]["allowed"] is False
    assert blocked["message"]["deliveries"][0]["reason"] == "target_agent_archived_or_missing"
    assert any(node["agentId"] == created_agent_id for node in blocked["organization"]["agents"])
