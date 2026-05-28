import json

import pytest
from fastapi.testclient import TestClient

from core.web.app import create_app
from core.web.control import CONTROL_TOKEN_HEADER, get_control_token
from core.web.services import agent_directory_service, research_organization_service, session_service


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
    return ceo, advisor


def test_research_organization_initializes_protected_core_agents_with_explicit_tools(org_workspace):
    org = research_organization_service.get_research_organization()
    ceo, advisor = _core_agents(org)

    assert org["path"].replace("\\", "/").endswith("workspace/research/organization_graph.json")
    assert ceo["protected"] is True
    assert advisor["protected"] is True
    assert ceo["agent"]["metadata"]["systemRole"] == "ceo"
    assert advisor["agent"]["metadata"]["systemRole"] == "organization_advisor"
    assert ceo["toolPolicy"]["allowedTools"]
    assert advisor["toolPolicy"]["allowedTools"]
    assert {edge["fromAgentId"] for edge in org["edges"]} == {ceo["agentId"], advisor["agentId"]}


def test_user_message_bypasses_edges_and_wakes_target(org_workspace, monkeypatch):
    org = research_organization_service.get_research_organization()
    _, advisor = _core_agents(org)
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
    ceo, _ = _core_agents(org_response.json())

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
    _, advisor = _core_agents(org)
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
    ceo, advisor = _core_agents(org)
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
    ceo, advisor = _core_agents(org)
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
    ceo, advisor = _core_agents(org)
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
    ceo, advisor = _core_agents(org)
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
            "content": "请形成组织调整提案。",
            "wakeTarget": True,
        }
    )

    assert report["message"]["deliveries"][0]["allowed"] is True
    assert report["message"]["deliveries"][0]["wakeStatus"] == "not_requested"
    assert task["message"]["deliveries"][0]["wakeStatus"] == "started"
    assert len(wakes) == 1


def test_busy_target_keeps_pending_message_and_retry_can_wake(org_workspace, monkeypatch):
    org = research_organization_service.get_research_organization()
    ceo, advisor = _core_agents(org)
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
    ceo, _ = _core_agents(org)

    with pytest.raises(agent_directory_service.AgentDirectoryError, match="Protected core Agent"):
        agent_directory_service.archive_agent_instance(ceo["agentId"])


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

    applied = research_organization_service.apply_research_org_proposal(proposal["proposalId"])

    created = applied["results"][0]
    assert created["status"] == "applied"
    assert created["agentId"]
    created_node = next(node for node in applied["organization"]["agents"] if node["agentId"] == created["agentId"])
    assert created_node["allowedTools"] == ["agent_message_tool", "web_search_tool"]


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
    ceo, _ = _core_agents(org)
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
            "content": "归档后不应再接收任务。",
        }
    )

    assert blocked["message"]["deliveries"][0]["allowed"] is False
    assert blocked["message"]["deliveries"][0]["reason"] == "target_agent_archived_or_missing"
    assert any(node["agentId"] == created_agent_id for node in blocked["organization"]["agents"])
