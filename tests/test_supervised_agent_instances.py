from fastapi.testclient import TestClient
import pytest

from core.ui.chat_state import load_chat_state, save_chat_state
from core.web.app import create_app
from core.web.control import CONTROL_TOKEN_HEADER, get_control_token
from core.web.services import (
    agent_directory_service,
    agent_mode_binding_service,
    session_service,
    supervised_agent_service,
)


client = TestClient(create_app(), headers={CONTROL_TOKEN_HEADER: get_control_token()})


def _use_tmp_project_root(tmp_path, monkeypatch):
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_mode_binding_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(supervised_agent_service, "PROJECT_ROOT", tmp_path)


def _seed_active_chat(root):
    save_chat_state(
        root,
        {
            "version": 1,
            "active_conversation_id": "session-user",
            "conversations": [
                {
                    "conversation_id": "session-user",
                    "title": "用户当前会话",
                    "agent_profile_id": "primary",
                    "updated_at": "2026-05-27T00:00:00",
                    "messages": [],
                }
            ],
        },
    )


def test_ensure_supervised_agent_instances_creates_fixed_role_agents_without_stealing_active_session(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _seed_active_chat(tmp_path)

    agents = supervised_agent_service.ensure_supervised_agent_instances()

    by_role = {agent["metadata"]["supervisedRole"]: agent for agent in agents}
    assert set(by_role) == {"baseline", "candidate", "reviewer", "auditor", "judge"}
    assert by_role["baseline"]["profileId"] == "supervised_baseline"
    assert by_role["baseline"]["primaryMode"] == "supervised_evolution"
    assert by_role["baseline"]["roleKey"] == "baseline"
    assert by_role["baseline"]["promptTemplateId"] == "prompt-supervised-baseline"
    assert by_role["candidate"]["profileId"] == "supervised_candidate"
    assert by_role["reviewer"]["profileId"] == "primary"
    assert all(agent["directSessionId"] for agent in agents)
    assert all(agent["metadata"]["agentMode"] == "supervised_evolution" for agent in agents)
    assert all(agent["metadata"]["configSurface"] == "model_config" for agent in agents)

    state = load_chat_state(tmp_path)
    assert state["active_conversation_id"] == "session-user"


def test_ensure_supervised_agent_instances_is_idempotent_and_repairs_metadata(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    events = []
    monkeypatch.setattr(
        agent_directory_service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: events.append((args, kwargs)) or {"accepted": True},
    )

    first = supervised_agent_service.ensure_supervised_agent_instances()
    baseline = next(agent for agent in first if agent["metadata"]["supervisedRole"] == "baseline")
    agent_directory_service.archive_agent_instance(baseline["agentId"])
    agent_directory_service.update_agent_instance(
        baseline["agentId"],
        display_name="旧名称",
        profile_id="primary",
        metadata={"supervisedRoleLabel": "旧标签"},
    )

    second = supervised_agent_service.ensure_supervised_agent_instances()

    assert len(second) == len(first)
    assert {agent["agentId"] for agent in second} == {agent["agentId"] for agent in first}
    repaired = next(agent for agent in second if agent["metadata"]["supervisedRole"] == "baseline")
    assert repaired["displayName"] != "监督进化基线 Agent"
    assert repaired["profileId"] == "supervised_baseline"
    assert repaired["status"] == "active"
    assert repaired["metadata"]["supervisedRoleLabel"] == "监督进化基线 Agent"
    assert repaired["metadata"]["functionalDisplayName"] == "监督进化基线 Agent"
    reactivated_events = [item for item in events if item[0][2] == "agent.reactivated"]
    assert reactivated_events[-1][1]["fields"]["agentId"] == baseline["agentId"]


def test_agents_api_auto_syncs_supervised_agent_instances(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)

    response = client.get("/api/agents")

    assert response.status_code == 200, response.text
    roles = {
        item["metadata"].get("supervisedRole")
        for item in response.json()
        if isinstance(item.get("metadata"), dict) and item["metadata"].get("supervisedRole")
    }
    assert roles == {"baseline", "candidate", "reviewer", "auditor", "judge"}


def test_supervised_agent_bindings_are_run_safe_payloads(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)

    bindings = supervised_agent_service.supervised_agent_bindings()

    assert bindings["baseline"]["profileId"] == "supervised_baseline"
    assert bindings["baseline"]["agentCode"]
    assert bindings["baseline"]["primaryMode"] == "supervised_evolution"
    assert bindings["baseline"]["roleKey"] == "baseline"
    assert bindings["baseline"]["promptTemplateId"] == "prompt-supervised-baseline"
    assert bindings["baseline"]["toolPolicyId"]
    assert bindings["baseline"]["memoryPolicyId"]
    assert bindings["candidate"]["profileId"] == "supervised_candidate"
    assert bindings["judge"]["roleLabel"] == "监督进化裁决 Agent"
    assert all("metadata" not in binding for binding in bindings.values())
    assert all("toolPolicy" not in binding for binding in bindings.values())
    assert all("memoryPolicy" not in binding for binding in bindings.values())
    assert all(binding["agentId"] for binding in bindings.values())


def test_supervised_agent_bindings_follow_mode_binding_slot_replacement(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    supervised_agent_service.ensure_supervised_agent_instances()
    replacement = agent_directory_service.create_agent_instance(
        display_name="替换基线 Agent",
        profile_id="primary",
        primary_mode="supervised_evolution",
        role_key="baseline",
        prompt_template_id="prompt-supervised-baseline",
    )
    current = agent_mode_binding_service.get_mode_bindings_payload()["modes"]["supervised_evolution"]
    slots = dict(current["slots"])
    slots["baseline"] = replacement["agentId"]
    agent_mode_binding_service.update_mode_binding("supervised_evolution", slots=slots)

    bindings = supervised_agent_service.supervised_agent_bindings()

    assert bindings["baseline"]["agentId"] == replacement["agentId"]
    assert bindings["baseline"]["displayName"] != "替换基线 Agent"
    assert agent_directory_service.get_agent(replacement["agentId"])["metadata"]["functionalDisplayName"] == "替换基线 Agent"


def test_supervised_agent_bindings_block_archived_slot_replacement(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    supervised_agent_service.ensure_supervised_agent_instances()
    replacement = agent_directory_service.create_agent_instance(
        display_name="将被归档的基线 Agent",
        profile_id="primary",
        primary_mode="supervised_evolution",
        role_key="baseline",
        prompt_template_id="prompt-supervised-baseline",
    )
    current = agent_mode_binding_service.get_mode_bindings_payload()["modes"]["supervised_evolution"]
    slots = dict(current["slots"])
    slots["baseline"] = replacement["agentId"]
    agent_mode_binding_service.update_mode_binding("supervised_evolution", slots=slots)
    agent_directory_service.archive_agent_instance(replacement["agentId"])

    with pytest.raises(supervised_agent_service.SupervisedAgentBindingError, match="baseline"):
        supervised_agent_service.supervised_agent_bindings()


def test_child_process_agent_runtime_falls_back_to_supervised_env(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    baseline = next(
        agent
        for agent in supervised_agent_service.ensure_supervised_agent_instances()
        if agent["metadata"]["supervisedRole"] == "baseline"
    )
    agent_directory_service.update_agent_instance(
        baseline["agentId"],
        tool_policy={"allowedTools": ["read_file_tool"]},
        supervision_policy={
            "supervisionEnabled": True,
            "requiresReview": True,
            "reviewMode": "required",
            "evidenceLevel": "strict",
        },
    )
    monkeypatch.setenv("VIBELUTION_AGENT_ID", baseline["agentId"])
    monkeypatch.setenv("VIBELUTION_AGENT_DIRECT_SESSION_ID", baseline["directSessionId"])
    monkeypatch.setenv("VIBELUTION_SUPERVISED_ROLE", "baseline")

    runtime = agent_directory_service.current_agent_runtime()
    visible_tools = agent_directory_service.filter_llm_tools_for_current_agent(
        [
            type("Tool", (), {"name": "read_file_tool"})(),
            type("Tool", (), {"name": "cli_tool"})(),
        ]
    )

    assert runtime["agentId"] == baseline["agentId"]
    assert runtime["sessionId"] == baseline["directSessionId"]
    assert runtime["supervisedRole"] == "baseline"
    assert runtime["supervisionPolicy"]["reviewMode"] == "required"
    assert runtime["supervisionPolicy"]["evidenceLevel"] == "strict"
    assert [tool.name for tool in visible_tools] == ["read_file_tool"]
