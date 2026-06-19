import copy
import json

import pytest

from core.web.services import agent_directory_service, agent_mode_binding_service

pytestmark = pytest.mark.serial


def _use_tmp_project_root(tmp_path, monkeypatch):
    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(tmp_path))
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_mode_binding_service, "PROJECT_ROOT", tmp_path)


def test_mode_binding_repairs_chat_and_research_agent_refs(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    chat_agent = agent_directory_service.create_agent_instance(
        display_name="对话 Agent",
        llm_bindings={"dialogue": {"modelId": "model-primary"}},
        primary_mode="chat",
        direct_session_id="session-chat",
    )
    research_agent = agent_directory_service.create_agent_instance(
        display_name="科研广搜 Agent",
        llm_bindings={"dialogue": {"modelId": "model-research-broad"}},
        primary_mode="research",
        role_key="research_broad",
        prompt_template_id="prompt-research-broad",
        direct_session_id="session-research",
        metadata={"researchAgentKey": "broad"},
    )

    payload = agent_mode_binding_service.get_mode_bindings_payload()

    assert payload["modes"]["chat"]["defaultAgentId"] == chat_agent["agentId"]
    assert chat_agent["agentId"] in payload["modes"]["chat"]["availableAgentIds"]
    assert research_agent["agentId"] in payload["modes"]["research"]["pool"]
    assert payload["agentRefs"][research_agent["agentId"]]["roleKey"] == "research_broad"
    assert "profileId" not in payload["agentRefs"][research_agent["agentId"]]
    assert payload["agentRefs"][research_agent["agentId"]]["llmBindings"]["dialogue"]["modelId"] == "model-research-broad"


def test_mode_binding_payload_reuses_loaded_agent_options_without_per_reference_get_agent(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    chat_agent = agent_directory_service.create_agent_instance(
        display_name="对话 Agent",
        llm_bindings={"dialogue": {"modelId": "model-primary"}},
        primary_mode="chat",
        direct_session_id="session-chat",
    )
    research_agent = agent_directory_service.create_agent_instance(
        display_name="科研 Agent",
        llm_bindings={"dialogue": {"modelId": "model-research-broad"}},
        primary_mode="research",
        role_key="research_broad",
    )
    agent_options = [
        {
            "agentId": chat_agent["agentId"],
            "agentCode": chat_agent["agentCode"],
            "displayName": chat_agent["displayName"],
            "primaryMode": chat_agent["primaryMode"],
            "roleKey": chat_agent["roleKey"],
            "llmBindings": chat_agent["llmBindings"],
            "promptTemplateId": chat_agent["promptTemplateId"],
            "directSessionId": chat_agent["directSessionId"],
            "metadata": chat_agent["metadata"],
        },
        {
            "agentId": research_agent["agentId"],
            "agentCode": research_agent["agentCode"],
            "displayName": research_agent["displayName"],
            "primaryMode": research_agent["primaryMode"],
            "roleKey": research_agent["roleKey"],
            "llmBindings": research_agent["llmBindings"],
            "promptTemplateId": research_agent["promptTemplateId"],
            "directSessionId": research_agent["directSessionId"],
            "metadata": research_agent["metadata"],
        },
    ]
    monkeypatch.setattr(
        agent_mode_binding_service,
        "get_agent",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("get_agent should not run during repair")),
    )
    monkeypatch.setattr(
        agent_mode_binding_service,
        "list_agents",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("list_agents should be provided by caller")),
    )

    payload = agent_mode_binding_service.get_mode_bindings_payload(agent_options=agent_options)

    assert payload["modes"]["chat"]["defaultAgentId"] == chat_agent["agentId"]
    assert research_agent["agentId"] in payload["modes"]["research"]["pool"]
    assert payload["agentRefs"][research_agent["agentId"]]["primaryMode"] == "research"
    assert "profileId" not in payload["agentRefs"][research_agent["agentId"]]


def test_mode_binding_repairs_supervised_slots_from_agent_instances(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    baseline = agent_directory_service.create_agent_instance(
        display_name="监督进化基线 Agent",
        llm_bindings={"dialogue": {"modelId": "model-supervised-baseline"}},
        primary_mode="supervised_evolution",
        role_key="baseline",
        prompt_template_id="prompt-supervised-baseline",
        direct_session_id="session-baseline",
        metadata={"supervisedRole": "baseline"},
    )

    payload = agent_mode_binding_service.get_mode_bindings_payload()

    assert payload["modes"]["supervised_evolution"]["slots"]["baseline"] == baseline["agentId"]


def test_mode_binding_drops_archived_agent_with_repair_warning(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    agent = agent_directory_service.create_agent_instance(
        display_name="旧 Agent",
        llm_bindings={"dialogue": {"modelId": "model-primary"}},
        primary_mode="chat",
        direct_session_id="session-old",
    )
    state = agent_mode_binding_service.default_mode_binding_state()
    state["modes"]["chat"]["defaultAgentId"] = agent["agentId"]
    state["modes"]["chat"]["availableAgentIds"] = [agent["agentId"]]
    agent_mode_binding_service.save_mode_binding_state(state)
    agent_directory_service.archive_agent_instance(agent["agentId"])

    payload = agent_mode_binding_service.get_mode_bindings_payload(agent_options=[])

    assert payload["modes"]["chat"]["defaultAgentId"] == ""
    assert payload["modes"]["chat"]["availableAgentIds"] == []
    assert any(item["agentId"] == agent["agentId"] for item in payload["repairWarnings"])


def test_mode_binding_repair_logs_missing_active_reference_context(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    events = []
    monkeypatch.setattr(agent_mode_binding_service, "record_runtime_scene_event", lambda *args, **kwargs: events.append((args, kwargs)))
    state = agent_mode_binding_service.default_mode_binding_state()
    state["modes"]["chat"]["defaultAgentId"] = "agent-missing"
    state["modes"]["chat"]["availableAgentIds"] = ["agent-missing"]
    agent_mode_binding_service.save_mode_binding_state(state)

    payload = agent_mode_binding_service.get_mode_bindings_payload(agent_options=[])

    assert payload["modes"]["chat"]["defaultAgentId"] == ""
    missing_events = [event for event in events if event[0][2] == "mode_binding.missing_agent"]
    assert len(missing_events) == 1
    fields = missing_events[0][1]["fields"]
    assert fields["mode"] == "chat"
    assert fields["warningCount"] == 2
    assert fields["uniqueAgentCount"] == 1
    assert fields["agentIds"] == ["agent-missing"]
    assert fields["fieldCounts"] == {"defaultAgentId": 1, "availableAgentIds": 1}
    assert fields["activeAgentCount"] == 0
    assert fields["storagePath"] == "workspace/agent_config/mode_bindings.json"


def test_mode_binding_repair_keeps_excluded_agent_tombstones_quiet(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    events = []
    monkeypatch.setattr(agent_mode_binding_service, "record_runtime_scene_event", lambda *args, **kwargs: events.append((args, kwargs)))
    state = agent_mode_binding_service.default_mode_binding_state()
    state["modes"]["chat"]["excludedAgentIds"] = ["agent-removed"]
    agent_mode_binding_service.save_mode_binding_state(state)

    payload = agent_mode_binding_service.get_mode_bindings_payload()

    assert payload["modes"]["chat"]["excludedAgentIds"] == ["agent-removed"]
    assert not any(event[0][2] == "mode_binding.missing_agent" for event in events)


def test_mode_binding_update_rejects_archived_agent(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    agent = agent_directory_service.create_agent_instance(
        display_name="归档 Agent",
        llm_bindings={"dialogue": {"modelId": "model-primary"}},
        primary_mode="chat",
    )
    agent_directory_service.archive_agent_instance(agent["agentId"])

    try:
        agent_mode_binding_service.update_mode_binding("chat", default_agent_id=agent["agentId"])
    except agent_mode_binding_service.AgentModeBindingError as exc:
        assert "archived" in str(exc)
    else:
        raise AssertionError("Expected archived agent binding update to fail")


def test_remove_agent_from_mode_bindings_excludes_removed_fixed_slot(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    agent = agent_directory_service.create_agent_instance(
        display_name="监督进化裁决 Agent",
        llm_bindings={"dialogue": {"modelId": "model-primary"}},
        primary_mode="supervised_evolution",
        role_key="judge",
        prompt_template_id="prompt-supervised-judge",
        metadata={"supervisedRole": "judge"},
    )
    agent_mode_binding_service.update_mode_binding(
        "supervised_evolution",
        available_agent_ids=[agent["agentId"]],
        slots={"judge": agent["agentId"]},
    )

    payload = agent_mode_binding_service.remove_agent_from_mode_bindings(agent["agentId"])

    mode = payload["modes"]["supervised_evolution"]
    assert mode["slots"]["judge"] == ""
    assert "judge" in mode["excludedSlots"]
    assert agent["agentId"] not in mode["availableAgentIds"]


def test_remove_agent_from_mode_bindings_preserves_fixed_role_tombstone_after_repair(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    agent = agent_directory_service.create_agent_instance(
        display_name="自进化执行 Agent",
        llm_bindings={"dialogue": {"modelId": "model-primary"}},
        primary_mode="self_evolution",
        role_key="executor",
        prompt_template_id="prompt-self-executor",
    )
    seeded = agent_mode_binding_service.get_mode_bindings_payload()
    assert seeded["modes"]["self_evolution"]["slots"]["executor"] == agent["agentId"]
    agent_directory_service.archive_agent_instance(agent["agentId"])
    repaired = agent_mode_binding_service.get_mode_bindings_payload()
    assert repaired["modes"]["self_evolution"]["slots"]["executor"] == ""

    payload = agent_mode_binding_service.remove_agent_from_mode_bindings(agent["agentId"])

    mode = payload["modes"]["self_evolution"]
    assert mode["slots"]["executor"] == ""
    assert "executor" in mode["excludedSlots"]
    assert agent["agentId"] not in mode["availableAgentIds"]


def test_mode_binding_repair_persists_flow_binding_normalization(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    active_agent = agent_directory_service.create_agent_instance(
        display_name="新科研 Agent",
        llm_bindings={"dialogue": {"modelId": "model-research-deep"}},
        primary_mode="research",
        role_key="research_deep",
    )
    bindings = []
    for item in agent_mode_binding_service.DEFAULT_MODE_BINDINGS:
        record = copy.deepcopy(item)
        if record["mode"] == "research":
            record["defaultAgentId"] = active_agent["agentId"]
            record["availableAgentIds"] = [active_agent["agentId"]]
            record["pool"] = [active_agent["agentId"]]
            record["flowBindings"] = {"Deep Search!": active_agent["agentId"]}
        bindings.append(record)
    path = agent_mode_binding_service.mode_binding_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"schemaVersion": 1, "updatedAt": "2026-05-27T00:00:00Z", "bindings": bindings}, ensure_ascii=False),
        encoding="utf-8",
    )

    payload = agent_mode_binding_service.get_mode_bindings_payload()
    persisted = agent_mode_binding_service._load_mode_bindings()
    research = next(item for item in persisted["bindings"] if item["mode"] == "research")

    assert payload["modes"]["research"]["flowBindings"] == {"deep_search": active_agent["agentId"]}
    assert research["flowBindings"] == {"deep_search": active_agent["agentId"]}


def test_agent_mode_membership_updates_chat_and_research_without_reseeding_removed_agent(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    agent = agent_directory_service.create_agent_instance(
        display_name="科研 Agent",
        llm_bindings={"dialogue": {"modelId": "model-research-broad"}},
        primary_mode="research",
        role_key="research_broad",
    )

    added = agent_mode_binding_service.update_agent_mode_membership(
        agent["agentId"],
        chat_default=True,
        chat_available=True,
        research_pool=True,
    )
    removed = agent_mode_binding_service.update_agent_mode_membership(
        agent["agentId"],
        chat_default=False,
        chat_available=False,
        research_pool=False,
    )
    repaired = agent_mode_binding_service.get_mode_bindings_payload()

    assert added["modes"]["chat"]["defaultAgentId"] == agent["agentId"]
    assert agent["agentId"] in added["modes"]["research"]["pool"]
    assert removed["modes"]["chat"]["defaultAgentId"] != agent["agentId"]
    assert agent["agentId"] not in removed["modes"]["chat"]["availableAgentIds"]
    assert agent["agentId"] not in removed["modes"]["research"]["pool"]
    assert agent["agentId"] in removed["modes"]["chat"]["excludedAgentIds"]
    assert agent["agentId"] in removed["modes"]["research"]["excludedAgentIds"]
    assert agent["agentId"] not in repaired["modes"]["research"]["pool"]


def test_agent_mode_membership_assigns_unique_supervised_and_self_slots(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    first = agent_directory_service.create_agent_instance(
        display_name="第一 Agent",
        llm_bindings={"dialogue": {"modelId": "model-primary"}},
        primary_mode="supervised_evolution",
        role_key="baseline",
    )
    second = agent_directory_service.create_agent_instance(
        display_name="第二 Agent",
        llm_bindings={"dialogue": {"modelId": "model-primary"}},
        primary_mode="supervised_evolution",
        role_key="reviewer",
    )

    agent_mode_binding_service.update_agent_mode_membership(first["agentId"], supervised_slot="baseline")
    payload = agent_mode_binding_service.update_agent_mode_membership(second["agentId"], supervised_slot="baseline")
    cleared = agent_mode_binding_service.update_agent_mode_membership(second["agentId"], supervised_slot="")

    assert payload["modes"]["supervised_evolution"]["slots"]["baseline"] == second["agentId"]
    assert first["agentId"] not in payload["modes"]["supervised_evolution"]["slots"].values()
    assert cleared["modes"]["supervised_evolution"]["slots"]["baseline"] == ""
    assert second["agentId"] in cleared["modes"]["supervised_evolution"]["excludedAgentIds"]
    assert "baseline" in cleared["modes"]["supervised_evolution"]["excludedSlots"]
