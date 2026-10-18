"""Public Companion seeds reuse native identities and remain dormant."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from core.agent_plugins.virtual_human_life import native_wakeup
from core.agent_plugins.virtual_human_life.service import VirtualHumanLifeService
from core.web.services import agent_directory_service as directory
from core.web.services import agent_plugin_service, session_service, virtual_human_life_service as life
from core.web.services.agent_directory.companion_preset import ensure_public_companion


@pytest.fixture
def deployment(tmp_path, monkeypatch):
    from core.infrastructure import developer_sandbox
    from core.web.services import (
        agent_mode_binding_service, chat_room_service, project_agent_bus_service, team_service,
    )
    from core.web.services.session import directory_runtime

    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(tmp_path))
    for module in (
        directory, session_service, team_service, agent_mode_binding_service,
        chat_room_service, project_agent_bus_service, life,
    ):
        monkeypatch.setattr(module, "PROJECT_ROOT", tmp_path)
    config_path = tmp_path / "developer-off.toml"
    config_path.write_text("[launcher]\ncontrol_port = 8765\n", encoding="utf-8")
    monkeypatch.setattr(developer_sandbox, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(developer_sandbox, "CONFIG_PATH", config_path)
    monkeypatch.setattr(directory, "CONFIG_PATH", config_path)
    monkeypatch.setattr(directory_runtime, "get_open_directory_store", lambda: None)
    monkeypatch.setattr(directory_runtime, "is_directory_store_open", lambda: False)
    monkeypatch.setattr(session_service, "default_session_llm_bindings", dict)
    monkeypatch.setattr(life, "_record_scene", lambda *args, **kwargs: None)
    (tmp_path / "workspace" / "shared").mkdir(parents=True)
    now = datetime(2026, 10, 17, 15, 30, tzinfo=timezone.utc)

    forbidden_calls = []

    def forbidden(*args, **kwargs):
        forbidden_calls.append(True)
        pytest.fail("Preset initialization must never call a model or submit a native Turn")

    service = VirtualHumanLifeService(
        tmp_path,
        agent_loader=lambda agent_id, **kwargs: directory.get_agent(agent_id, **kwargs),
        agent_lister=lambda: directory.list_agents(detail="config"),
        plugin_root_resolver=lambda agent_id: tmp_path / "plugin" / agent_id,
        schedule_planner=forbidden,
        proactive_submitter=forbidden,
        conversation_submitter=forbidden,
        auto_mailbox_dispatch=False,
        now_provider=lambda: now,
        directory_visibility_manager=life._default_directory_visibility_manager,
        steward_provisioner=life._default_steward_provisioner,
    )
    life.set_virtual_human_life_service_for_tests(service)
    owner = directory.create_agent_instance(display_name="洛天依", llm_bindings={})
    session_service.ensure_agent_direct_session(agent_id=owner["agentId"], title="洛天依")
    try:
        yield tmp_path, service, owner["agentId"], now
    finally:
        life.set_virtual_human_life_service_for_tests(None)
        assert forbidden_calls == []


CONFIG = {"homeLocation": {"locationId": "CN-SHANGHAI"}, "lifeIdentityKind": "student"}


def test_seed_is_visible_paused_and_has_two_empty_native_helpers(deployment):
    root, service, owner_id, now = deployment
    helpers = ensure_public_companion(owner_id, CONFIG)
    binding = service.binding_for(owner_id)
    assert binding["enabled"] is True
    assert binding["proactiveMessagesEnabled"] is False
    assert binding["autonomyLevel"] == "assisted"
    assert binding["steward"]["enabled"] is False
    assert binding["lifeWorld"]["setupState"] == "draft"
    rows = agent_plugin_service.list_virtual_human_companions()
    assert [row["agentId"] for row in rows] == [owner_id]
    assert rows[0]["snapshot"]["state"]["lifePaused"] is True
    assert len(set(helpers.values()) | {owner_id}) == 3
    for helper_id in helpers.values():
        helper = directory.get_agent(helper_id)
        assert helper["permissionPreset"] == "request_approval"
        assert not directory.agent_dialogue_model_id(helper)
        assert helper["metadata"]["conversationIndexKind"] == directory.CONVERSATION_INDEX_KIND_HIDDEN
        state = session_service.load_session_chat_state(root, helper["directSessionId"])
        assert state["agent_id"] == helper_id
        assert not state.get("messages")
        assert not state.get("turns")
        assert state["metadata"]["externalTaskId"] == owner_id
    for days in (0, 1, 10):
        assert service.heartbeat_agent(owner_id, now=now + timedelta(days=days))["paused"]
        assert service.self_continuity.tick(owner_id, now=now + timedelta(days=days))["status"] == "paused"


@pytest.mark.parametrize("phase", ["before_publish", "after_publish"])
def test_interrupted_seed_is_already_paused_and_replays_without_duplicate_helpers(
    deployment, monkeypatch, phase,
):
    _root, service, owner_id, now = deployment
    if phase == "before_publish":
        original = life.update_virtual_human_binding

        def interrupt(*args, **kwargs):
            assert service.store.read_json(owner_id, "state.json")["lifePaused"]
            raise RuntimeError("seed interrupted")

        monkeypatch.setattr(life, "update_virtual_human_binding", interrupt)
    else:
        original = service.execute_command

        def interrupt(*args, **kwargs):
            assert service.heartbeat_agent(owner_id, now=now)["paused"]
            raise RuntimeError("seed interrupted")

        monkeypatch.setattr(service, "execute_command", interrupt)
    with pytest.raises(RuntimeError, match="seed interrupted"):
        ensure_public_companion(owner_id, CONFIG)
    assert service.store.read_json(owner_id, "state.json")["lifePaused"]
    if phase == "before_publish":
        assert not service.binding_for(owner_id)["enabled"]
        monkeypatch.setattr(life, "update_virtual_human_binding", original)
    else:
        monkeypatch.setattr(service, "execute_command", original)
    first = ensure_public_companion(owner_id, CONFIG)
    assert ensure_public_companion(owner_id, CONFIG) == first
    assert len([
        agent for agent in directory.list_agents(include_archived=True)
        if agent["agentId"] == owner_id or (agent.get("metadata") or {}).get("lifeStewardForAgentId") == owner_id
        or (agent.get("metadata") or {}).get("selfWakeForAgentId") == owner_id
    ]) == 3


def test_existing_native_provisioners_claim_dormant_helpers(deployment):
    _root, service, owner_id, _now = deployment
    helpers = ensure_public_companion(owner_id, CONFIG)
    directory.update_agent_instance(owner_id, llm_bindings={"dialogue": {"modelId": "user-model"}})
    binding = service.binding_for(owner_id)
    service.set_binding(
        owner_id, enabled=True, expected_version=binding["configVersion"],
        config={"autonomyLevel": "autonomous"},
    )
    worker_session = native_wakeup.ensure_session(owner_id)
    assert directory.get_agent(helpers["selfWakeAgentId"])["directSessionId"] == worker_session
    draft = service.life_world_projection(owner_id)["draft"]
    confirmed = life.confirm_virtual_human_life_world(
        owner_id, draft_id=draft["draftId"], expected_draft_revision=draft["revision"],
        expected_binding_version=service.binding_for(owner_id)["configVersion"],
        idempotency_key="user-confirmed-life",
    )
    assert confirmed["binding"]["steward"]["agentId"] == helpers["stewardAgentId"]
    assert set(helpers.values()).issubset({
        agent["agentId"] for agent in directory.list_agents(include_archived=True)
    })
    assert service.store.read_json(owner_id, "state.json")["lifePaused"] is True


def test_interrupted_helper_configuration_reuses_native_creation_receipt(deployment, monkeypatch):
    _root, service, owner_id, now = deployment
    original = directory.update_agent_instance
    interrupted = []

    def fail_helper_configuration(agent_id, **kwargs):
        if kwargs.get("role_key") == "virtual_human_life_steward" and not interrupted:
            interrupted.append(agent_id)
            raise RuntimeError("helper configuration interrupted")
        return original(agent_id, **kwargs)

    monkeypatch.setattr(directory, "update_agent_instance", fail_helper_configuration)
    with pytest.raises(RuntimeError, match="helper configuration interrupted"):
        ensure_public_companion(owner_id, CONFIG)
    assert service.heartbeat_agent(owner_id, now=now)["paused"]
    helpers = ensure_public_companion(owner_id, CONFIG)
    assert helpers["stewardAgentId"] == interrupted[0]
    assert ensure_public_companion(owner_id, CONFIG) == helpers


def test_seed_does_not_resurrect_archived_owner(deployment):
    _root, _service, owner_id, _now = deployment
    directory.archive_agent_instance(owner_id)
    assert ensure_public_companion(owner_id, CONFIG) == {}
    assert not any(
        (agent.get("metadata") or {}).get("lifeStewardForAgentId") == owner_id
        or (agent.get("metadata") or {}).get("selfWakeForAgentId") == owner_id
        for agent in directory.list_agents(include_archived=True)
    )
