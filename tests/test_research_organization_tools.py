import json

from core.web.services import agent_directory_service, research_organization_service
from tools.research_organization_tools import (
    research_agent_creation_proposal_tool,
    research_communication_edge_proposal_tool,
)


def test_research_agent_creation_tool_creates_user_gated_create_agent_proposal(monkeypatch):
    proposer = {
        "agentId": "agent-steward",
        "agentCode": "A013",
        "displayName": "白予安",
        "metadata": {"systemRole": "capability_steward"},
    }
    monkeypatch.setattr(agent_directory_service, "current_agent_runtime", lambda: {"agentId": proposer["agentId"]})
    created_payloads = []

    def fake_create(payload):
        created_payloads.append(payload)
        return {
            "proposal": {
                "proposalId": "roprop-create-agent",
                "status": "pending_user_confirmation",
                "riskLevel": "high",
                "requiresUserConfirmation": True,
            }
        }

    monkeypatch.setattr(research_organization_service, "create_research_org_proposal", fake_create)

    result = json.loads(
        research_agent_creation_proposal_tool(
            display_name="知识库管理员",
            role="research_knowledge_steward",
            responsibilities="维护科研数据库 schema；清理知识库写入队列",
            allowed_tools="agent_message_tool,research_knowledge_query_tool",
            read_shared_groups="project,research,agent_config",
            write_shared_groups="research",
            communication_targets="CEO;Capability Steward",
            reason="数据库试水需要最小知识库治理角色。",
        )
    )

    assert result["ok"] is True
    assert result["status"] == "proposal_created"
    assert result["proposalId"] == "roprop-create-agent"
    assert result["requiresUserConfirmation"] is True
    payload = created_payloads[0]
    action = payload["actions"][0]
    assert payload["proposedByAgentId"] == "agent-steward"
    assert action["actionType"] == "create_agent"
    assert action["displayName"] == "知识库管理员"
    assert action["role"] == "research_knowledge_steward"
    assert action["allowedTools"] == ["agent_message_tool", "research_knowledge_query_tool"]
    assert action["readSharedGroups"] == ["project", "research", "agent_config"]
    assert action["writeSharedGroups"] == ["research"]
    assert action["communicationTargets"] == ["CEO", "Capability Steward"]


def test_research_agent_creation_tool_requires_display_name(monkeypatch):
    monkeypatch.setattr(agent_directory_service, "current_agent_runtime", lambda: {"agentId": "agent-steward"})

    result = json.loads(research_agent_creation_proposal_tool(display_name=""))

    assert result["ok"] is False
    assert result["status"] == "blocked"
    assert result["error"] == "display_name_required"


def test_research_communication_edge_tool_creates_reviewable_proposal(monkeypatch):
    proposer = {
        "agentId": "agent-advisor",
        "agentCode": "A012",
        "displayName": "江知微",
        "metadata": {"systemRole": "organization_advisor"},
    }
    target = {
        "agentId": "agent-steward",
        "agentCode": "A013",
        "displayName": "白予安",
        "metadata": {"systemRole": "capability_steward"},
    }
    monkeypatch.setattr(agent_directory_service, "current_agent_runtime", lambda: {"agentId": proposer["agentId"]})
    monkeypatch.setattr(agent_directory_service, "list_agents", lambda include_archived=False: [proposer, target])
    created_payloads = []

    def fake_create(payload):
        created_payloads.append(payload)
        return {
            "proposal": {
                "proposalId": "roprop-test",
                "status": "ceo_approved",
                "riskLevel": "medium",
                "requiresUserConfirmation": False,
            }
        }

    monkeypatch.setattr(research_organization_service, "create_research_org_proposal", fake_create)

    result = json.loads(
        research_communication_edge_proposal_tool(
            action="update",
            source_agent="A012",
            target_agent="A013",
            label="顾问请求能力边界复核",
            allowed_message_types="request,report",
            allowed_intents="permission_review,capability_plan",
            wake_strategy="mailbox_only",
            reason="需要让组织顾问和能力管家复核新增成员边界。",
        )
    )

    assert result["ok"] is True
    assert result["status"] == "proposal_created"
    assert result["proposalId"] == "roprop-test"
    action = created_payloads[0]["actions"][0]
    assert action["actionType"] == "update_communication_edge"
    assert action["fromAgentId"] == "agent-advisor"
    assert action["toAgentId"] == "agent-steward"
    assert action["communicationPolicy"]["allowedMessageTypes"] == ["request", "report"]
    assert action["communicationPolicy"]["allowedIntents"] == ["permission_review", "capability_plan"]
    assert action["communicationPolicy"]["wakeStrategy"] == "mailbox_only"


def test_research_communication_edge_tool_requires_agent_runtime(monkeypatch):
    monkeypatch.setattr(agent_directory_service, "current_agent_runtime", lambda: {})

    result = json.loads(research_communication_edge_proposal_tool(action="create", source_agent="A012", target_agent="A013"))

    assert result["ok"] is False
    assert result["status"] == "blocked"
    assert result["error"] == "agent_runtime_missing"
