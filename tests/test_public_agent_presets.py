"""Portable configuration uses native identities without touching existing data."""
from __future__ import annotations

import sys
from copy import deepcopy
from types import ModuleType, SimpleNamespace

import pytest

from core.web.services import agent_directory_service as directory
from core.web.services import session_service, team_service
from core.web.services.agent_directory import public_presets
from core.web.services.session import directory_runtime


@pytest.fixture
def fresh_deployment(tmp_path, monkeypatch):
    from core.infrastructure import developer_sandbox
    from core.web.services import agent_mode_binding_service, chat_room_service, project_agent_bus_service, prompt_template_service

    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(tmp_path))
    for service in (directory, session_service, team_service, agent_mode_binding_service,
                    chat_room_service, project_agent_bus_service):
        monkeypatch.setattr(service, "PROJECT_ROOT", tmp_path)
    config = tmp_path / "developer-off.toml"
    config.write_text("[launcher]\ncontrol_port = 8765\n", encoding="utf-8")
    monkeypatch.setattr(developer_sandbox, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(developer_sandbox, "CONFIG_PATH", config)
    monkeypatch.setattr(directory, "CONFIG_PATH", config)
    monkeypatch.setattr(prompt_template_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(prompt_template_service, "PROMPT_TEMPLATE_PATH", tmp_path / "prompt_templates.json")
    (tmp_path / "workspace" / "shared").mkdir(parents=True)
    monkeypatch.setattr(directory_runtime, "get_open_directory_store", lambda: None)
    monkeypatch.setattr(directory_runtime, "is_directory_store_open", lambda: False)
    monkeypatch.setattr(session_service, "default_session_llm_bindings",
                        lambda: {"dialogue": {"modelId": "deployment-default"}})
    llm = SimpleNamespace(model_library={"available": {}},
                          resolve_model_ref=lambda ref: "available" if ref == "alias" else ref)
    monkeypatch.setattr(public_presets, "get_config", lambda: SimpleNamespace(llm=llm))
    calls = []
    helper = ModuleType("core.web.services.agent_directory.companion_preset")
    helper.ensure_public_companion = lambda agent_id, config: calls.append((agent_id, config))
    monkeypatch.setitem(sys.modules, helper.__name__, helper)
    return calls


@pytest.fixture
def preset(monkeypatch):
    item = {"key": "public-researcher", "displayName": "公开研究员", "primaryMode": "chat",
            "roleKey": "research_broad", "promptTemplateId": "prompt-chat-default",
            "personaProfile": {"personality": "严谨且清晰"},
            "taskProfile": {"mission": "根据证据整理资料"},
            "preferredLlmBindings": {"dialogue": {"modelId": "missing-model"}},
            "reasoningEffortBySlot": {"dialogue": "high"},
            "llmModelParameters": {}, "toolPolicy": {}, "memoryPolicy": {}}
    monkeypatch.setattr(public_presets, "load_public_agent_presets", lambda: [deepcopy(item)])
    return item


def test_empty_deployment_materializes_catalog_with_native_sessions(fresh_deployment):
    presets = public_presets.load_public_agent_presets()
    assert len(presets) == 11
    result = public_presets.ensure_public_agent_presets()
    assert len(result["createdAgentIds"]) == 11
    assert len(set(result["publicPresetAgentIds"])) == 11
    for agent_id, preset in zip(result["publicPresetAgentIds"], presets):
        agent = directory.get_agent(agent_id)
        assert agent["displayName"] == preset["displayName"]
        assert agent["permissionPreset"] == "request_approval"
        assert agent["metadata"]["publicPresetSeedComplete"] is True
        assert agent["metadata"]["publicPresetPreferredLlmBindings"] == preset.get("preferredLlmBindings", {})
        assert not agent["metadata"].get("challengeCupTeamId")
        session = session_service.get_session_detail(agent["directSessionId"])
        assert session is not None
        assert session["agentId"] == agent_id
        if preset.get("avatarAsset"):
            filename = directory.agent_avatar_filename(agent["metadata"]["avatarImagePath"])
            assert directory.resolve_agent_avatar_file(filename).read_bytes() == (
                public_presets.PRESET_ROOT / preset["avatarAsset"]).read_bytes()
            assert agent["metadata"]["avatarImageSource"] == "custom"
    assert len(fresh_deployment) == sum(bool(item.get("companion")) for item in presets)


def test_missing_preferred_model_uses_deployment_default_and_keeps_profiles(fresh_deployment, preset):
    agent_id = public_presets.ensure_public_agent_presets()["publicPresetAgentIds"][0]
    agent = directory.get_agent(agent_id)
    assert agent["llmBindings"]["dialogue"]["modelId"] == "deployment-default"
    assert agent["metadata"]["publicPresetPreferredLlmBindings"] == preset["preferredLlmBindings"]
    assert agent["personaProfile"]["personality"] == "严谨且清晰"
    assert agent["taskProfile"]["mission"] == "根据证据整理资料"


def test_resolvable_preferred_model_is_used(fresh_deployment, preset):
    preset["preferredLlmBindings"]["dialogue"]["modelId"] = "alias"
    result = public_presets.ensure_public_agent_presets()
    assert directory.get_agent(result["publicPresetAgentIds"][0])["llmBindings"]["dialogue"]["modelId"] == "available"


@pytest.mark.parametrize("archived", [False, True])
def test_existing_unmarked_identity_is_reused_without_any_configuration_write(fresh_deployment, preset, archived):
    existing = directory.create_agent_instance(display_name=preset["displayName"], role_key=preset["roleKey"],
                                              llm_bindings={"dialogue": {"modelId": "user-model"}})
    directory.update_agent_instance(existing["agentId"], task_profile={"mission": "用户任务"})
    if archived:
        directory.archive_agent_instance(existing["agentId"])
    before = directory.get_agent(existing["agentId"], include_archived=True)
    result = public_presets.ensure_public_agent_presets()
    assert result == {"publicPresetAgentIds": [existing["agentId"]], "createdAgentIds": []}
    assert directory.get_agent(existing["agentId"], include_archived=True) == before
    assert not before["metadata"].get("publicPresetKey")
    assert not before["directSessionId"]


def test_active_exact_match_is_preferred_over_archived_legacy_identity(fresh_deployment, preset):
    archived = directory.create_agent_instance(display_name=preset["displayName"], role_key=preset["roleKey"])
    directory.archive_agent_instance(archived["agentId"])
    active = directory.create_agent_instance(display_name=preset["displayName"], role_key=preset["roleKey"])
    assert public_presets.ensure_public_agent_presets()["publicPresetAgentIds"] == [active["agentId"]]


def test_legacy_identity_match_distinguishes_same_name_and_role_by_source(fresh_deployment, preset):
    directory.create_agent_instance(display_name=preset["displayName"], role_key=preset["roleKey"],
                                    created_by="other-team")
    expected = directory.create_agent_instance(display_name=preset["displayName"], role_key=preset["roleKey"],
                                               created_by="original-team")
    preset["matchCreatedBy"] = "original-team"
    assert public_presets.ensure_public_agent_presets() == {
        "publicPresetAgentIds": [expected["agentId"]], "createdAgentIds": []}


@pytest.mark.parametrize("archive_after_seed", [False, True])
def test_completed_marker_preserves_user_changes_and_lifecycle(fresh_deployment, preset, archive_after_seed, monkeypatch):
    agent_id = public_presets.ensure_public_agent_presets()["publicPresetAgentIds"][0]
    directory.update_agent_instance(agent_id, display_name="用户改名", direct_session_id="",
                                    task_profile={"mission": "用户新的任务"},
                                    llm_bindings={"dialogue": {"modelId": "my-model"}})
    if archive_after_seed:
        directory.archive_agent_instance(agent_id)
    before = directory.get_agent(agent_id, include_archived=True)
    list_agents = directory.list_agents
    queries = []

    def summaries(**kwargs):
        queries.append(kwargs)
        return list_agents(**kwargs)

    monkeypatch.setattr(directory, "list_agents", summaries)
    assert public_presets.ensure_public_agent_presets() == {"publicPresetAgentIds": [agent_id], "createdAgentIds": []}
    assert directory.get_agent(agent_id, include_archived=True) == before
    assert queries == [{"include_archived": True, "detail": "summary"}]


def test_interrupted_seed_resumes_same_identity_and_finishes_once(fresh_deployment, preset, monkeypatch):
    original = session_service.ensure_agent_direct_session
    monkeypatch.setattr(session_service, "ensure_agent_direct_session",
                        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("seed interrupted")))
    with pytest.raises(RuntimeError, match="seed interrupted"):
        public_presets.ensure_public_agent_presets()
    interrupted = [agent for agent in directory.list_agents(include_archived=True)
                   if agent["metadata"].get("publicPresetKey") == preset["key"]]
    assert len(interrupted) == 1
    agent_id = interrupted[0]["agentId"]
    assert interrupted[0]["metadata"]["publicPresetSeedComplete"] is False
    monkeypatch.setattr(session_service, "ensure_agent_direct_session", original)
    assert public_presets.ensure_public_agent_presets() == {"publicPresetAgentIds": [agent_id], "createdAgentIds": []}
    assert directory.get_agent(agent_id)["directSessionId"]
    assert directory.get_agent(agent_id)["metadata"]["publicPresetSeedComplete"] is True


def test_companion_is_configured_only_during_unfinished_seed(fresh_deployment, preset):
    preset["roleKey"] = ""
    preset["companion"] = {"character": "public-character"}
    agent_id = public_presets.ensure_public_agent_presets()["publicPresetAgentIds"][0]
    agent = directory.get_agent(agent_id)
    assert agent["personaProfile"]["personality"] == preset["personaProfile"]["personality"]
    public_presets.ensure_public_agent_presets()
    assert fresh_deployment == [(agent_id, preset["companion"])]


def test_resume_after_companion_failure_preserves_created_native_session(fresh_deployment, preset, monkeypatch):
    preset["companion"] = {"character": "public-character"}
    helper = sys.modules["core.web.services.agent_directory.companion_preset"]
    original = helper.ensure_public_companion
    monkeypatch.setattr(helper, "ensure_public_companion",
                        lambda *args: (_ for _ in ()).throw(RuntimeError("companion interrupted")))
    with pytest.raises(RuntimeError, match="companion interrupted"):
        public_presets.ensure_public_agent_presets()
    agent = next(agent for agent in directory.list_agents()
                 if agent["metadata"].get("publicPresetKey") == preset["key"])
    session_id = agent["directSessionId"]
    assert session_id
    monkeypatch.setattr(helper, "ensure_public_companion", original)
    assert public_presets.ensure_public_agent_presets()["createdAgentIds"] == []
    assert directory.get_agent(agent["agentId"])["directSessionId"] == session_id
    assert fresh_deployment == [(agent["agentId"], preset["companion"])]


def test_unrelated_native_session_and_agent_are_unchanged(fresh_deployment, preset):
    ordinary = directory.create_agent_instance(display_name="普通会话", primary_mode="chat")
    session_service.ensure_agent_direct_session(agent_id=ordinary["agentId"], title="普通会话")
    before_agent = directory.get_agent(ordinary["agentId"])
    before_session = deepcopy(session_service.get_session_detail(before_agent["directSessionId"]))
    public_presets.ensure_public_agent_presets()
    assert directory.get_agent(ordinary["agentId"]) == before_agent
    assert session_service.get_session_detail(before_agent["directSessionId"]) == before_session


def test_custom_prompt_has_private_template_and_preserves_existing_customizations(fresh_deployment, preset):
    from core.web.services import prompt_template_service

    original_shared = prompt_template_service.get_prompt_template("prompt-chat-default")
    preset["promptContent"] = "公开资料整理工作约定"
    agent_id = public_presets.ensure_public_agent_presets()["publicPresetAgentIds"][0]
    template_id = directory.get_agent(agent_id)["promptTemplateId"]
    assert template_id == f"prompt-public-{preset['key']}"
    assert prompt_template_service.get_prompt_template(template_id)["content"] == preset["promptContent"]
    prompt_template_service.update_prompt_template(template_id, content="用户修改后的工作约定")
    public_presets.ensure_public_agent_presets()
    assert prompt_template_service.get_prompt_template(template_id)["content"] == "用户修改后的工作约定"
    assert prompt_template_service.get_prompt_template("prompt-chat-default") == original_shared
