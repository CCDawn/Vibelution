import json

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
    assert "profileId" not in by_role["baseline"]
    assert by_role["baseline"]["llmBindings"]["dialogue"]["modelId"]
    assert by_role["baseline"]["primaryMode"] == "supervised_evolution"
    assert by_role["baseline"]["roleKey"] == "baseline"
    assert by_role["baseline"]["promptTemplateId"] == "prompt-supervised-baseline"
    assert "profileId" not in by_role["candidate"]
    assert "profileId" not in by_role["reviewer"]
    assert all(agent["directSessionId"] for agent in agents)
    assert all(agent["metadata"]["agentMode"] == "supervised_evolution" for agent in agents)
    assert all(agent["metadata"]["configSurface"] == "model_config" for agent in agents)
    assert by_role["judge"]["metadata"]["protected"] is True
    assert by_role["baseline"]["metadata"]["protected"] is False

    state = load_chat_state(tmp_path)
    assert state["active_conversation_id"] == "session-user"


def test_ensure_supervised_agent_instances_is_idempotent_and_repairs_active_metadata(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    events = []
    monkeypatch.setattr(
        agent_directory_service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: events.append((args, kwargs)) or {"accepted": True},
    )

    first = supervised_agent_service.ensure_supervised_agent_instances()
    baseline = next(agent for agent in first if agent["metadata"]["supervisedRole"] == "baseline")
    agent_directory_service.update_agent_instance(
        baseline["agentId"],
        display_name="旧名称",
        llm_bindings={"dialogue": {"modelId": "model-primary"}},
        metadata={"supervisedRoleLabel": "旧标签"},
    )

    second = supervised_agent_service.ensure_supervised_agent_instances()

    assert len(second) == len(first)
    assert {agent["agentId"] for agent in second} == {agent["agentId"] for agent in first}
    repaired = next(agent for agent in second if agent["metadata"]["supervisedRole"] == "baseline")
    assert repaired["displayName"] != "监督进化基线 Agent"
    assert "profileId" not in repaired
    assert repaired["status"] == "active"
    assert repaired["metadata"]["supervisedRoleLabel"] == "监督进化基线 Agent"
    assert repaired["metadata"]["functionalDisplayName"] == "监督进化基线 Agent"
    assert repaired["llmBindings"]["dialogue"]["modelId"] == "model-primary"


def test_ensure_supervised_agent_instances_does_not_reactivate_archived_fixed_role(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    events = []
    monkeypatch.setattr(
        supervised_agent_service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: events.append((args, kwargs)) or {"accepted": True},
    )

    first = supervised_agent_service.ensure_supervised_agent_instances()
    baseline = next(agent for agent in first if agent["metadata"]["supervisedRole"] == "baseline")
    agent_mode_binding_service.remove_agent_from_mode_bindings(baseline["agentId"])
    agent_directory_service.archive_agent_instance(baseline["agentId"])

    second = supervised_agent_service.ensure_supervised_agent_instances()

    assert baseline["agentId"] not in {agent["agentId"] for agent in second}
    archived = agent_directory_service.get_agent(baseline["agentId"], include_archived=True)
    assert archived["status"] == "archived"
    payload = agent_mode_binding_service.get_mode_bindings_payload()["modes"]["supervised_evolution"]
    assert payload["slots"]["baseline"] == ""
    assert "baseline" in payload["excludedSlots"]
    assert baseline["agentId"] not in payload["availableAgentIds"]
    skipped_events = [
        item for item in events if item[0][2] == "supervised.agent_instance.sync_skipped_excluded_slot"
    ]
    assert skipped_events[-1][1]["fields"]["agentId"] == baseline["agentId"]


def test_ensure_supervised_agent_instances_restores_core_judge_without_duplicates(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)

    first = supervised_agent_service.ensure_supervised_agent_instances()
    judge = next(agent for agent in first if agent["metadata"]["supervisedRole"] == "judge")
    agent_mode_binding_service.remove_agent_from_mode_bindings(judge["agentId"])
    state = agent_directory_service.load_state()
    for item in state["agents"]:
        if item["agentId"] == judge["agentId"]:
            item["status"] = "archived"
            item["metadata"]["protected"] = False
    agent_directory_service.save_state(state)
    tombstoned = agent_mode_binding_service.get_mode_bindings_payload()["modes"]["supervised_evolution"]
    assert tombstoned["slots"]["judge"] == ""
    assert "judge" in tombstoned["excludedSlots"]

    second = supervised_agent_service.ensure_supervised_agent_instances()

    judges = [
        agent
        for agent in agent_directory_service.list_agents(include_archived=True)
        if agent.get("metadata", {}).get("supervisedRole") == "judge"
    ]
    assert [agent["agentId"] for agent in judges] == [judge["agentId"]]
    restored = next(agent for agent in second if agent["metadata"]["supervisedRole"] == "judge")
    assert restored["agentId"] == judge["agentId"]
    assert restored["status"] == "active"
    assert restored["metadata"]["protected"] is True
    payload = agent_mode_binding_service.get_mode_bindings_payload()["modes"]["supervised_evolution"]
    assert payload["slots"]["judge"] == judge["agentId"]
    assert "judge" not in payload["excludedSlots"]


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

    assert not bindings["baseline"]["profileId"]
    assert bindings["baseline"]["dialogueModelId"]
    assert bindings["baseline"]["llmBindings"]["dialogue"]["modelId"] == bindings["baseline"]["dialogueModelId"]
    assert bindings["baseline"]["agentCode"]
    assert bindings["baseline"]["primaryMode"] == "supervised_evolution"
    assert bindings["baseline"]["roleKey"] == "baseline"
    assert bindings["baseline"]["promptTemplateId"] == "prompt-supervised-baseline"
    assert bindings["baseline"]["toolPolicyId"]
    assert bindings["baseline"]["memoryPolicyId"]
    assert not bindings["candidate"]["profileId"]
    assert bindings["candidate"]["dialogueModelId"]
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
        llm_bindings={"dialogue": {"modelId": "model-primary"}},
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
        llm_bindings={"dialogue": {"modelId": "model-primary"}},
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


def test_supervised_agent_bindings_block_missing_dialogue_model(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    agents = supervised_agent_service.ensure_supervised_agent_instances()
    baseline = next(agent for agent in agents if agent["metadata"]["supervisedRole"] == "baseline")
    state = agent_directory_service.load_state()
    for item in state["agents"]:
        if item.get("agentId") == baseline["agentId"]:
            item["llmBindings"] = {}
    agent_directory_service.registry_path().write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

    with pytest.raises(supervised_agent_service.SupervisedAgentBindingError, match="dialogue LLM binding"):
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
