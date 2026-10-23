"""Dialogue preferences use native assistant identity without enabling Companion."""

import pytest
from fastapi import HTTPException

from core.agent_plugins.virtual_human_life.service import (
    BindingDisabledError,
    VirtualHumanLifeError,
    VirtualHumanLifeService,
)
from core.web.routes import virtual_human_life as routes
from core.web.services import agent_directory_service as directory
from core.web.services import personal_assistant_service as personal
from core.web.services import virtual_human_life_service as facade
from tests.test_personal_assistant_service import finance_env, personal_env


@pytest.fixture
def dialogue_service(personal_env, monkeypatch):
    root = personal_env["root"]
    service = VirtualHumanLifeService(
        root,
        agent_loader=facade._default_agent_loader,
        agent_lister=facade._default_agent_lister,
        plugin_root_resolver=lambda agent_id: root / "dialogue-plugins" / agent_id,
        auto_mailbox_dispatch=False,
    )
    monkeypatch.setattr(facade, "get_virtual_human_life_service", lambda: service)
    return service


def _assert_no_settings(service, agent_id):
    assert service.binding_for(agent_id) is None
    assert service.store.read_json(agent_id, "conversation/dialogue_settings.json") is None


def test_new_assistant_can_save_and_read_without_creating_binding(
    personal_env, dialogue_service
):
    agent_id = personal.create_personal_assistant()["assistant"]["agentId"]
    before_directory = directory.load_state()
    _assert_no_settings(dialogue_service, agent_id)
    assert facade.virtual_human_dialogue_settings(agent_id)["speakingInitiative"] == "natural"

    updated = facade.update_virtual_human_dialogue_settings(
        f" {agent_id} ",
        settings={"speakingInitiative": "restrained", "questionInitiative": "few"},
    )

    assert updated["agentId"] == agent_id
    assert updated["speakingInitiative"] == "restrained"
    assert updated["questionInitiative"] == "few"
    assert facade.virtual_human_dialogue_settings(agent_id) == updated
    assert dialogue_service.binding_for(agent_id) is None
    assert directory.load_state() == before_directory
    _assert_no_settings(dialogue_service, personal_env["owner"])
    # The low-level default and proposal decisions retain Companion authorization.
    with pytest.raises(BindingDisabledError):
        dialogue_service.update_dialogue_settings(agent_id, settings={})
    with pytest.raises(BindingDisabledError):
        facade.accept_virtual_human_preference_proposal(agent_id, proposal_id="missing")
    with pytest.raises(BindingDisabledError):
        facade.reject_virtual_human_preference_proposal(agent_id, proposal_id="missing")


def test_ordinary_unbound_agent_is_rejected_without_assistant_directory_scan(
    personal_env, dialogue_service, monkeypatch
):
    def forbidden():
        pytest.fail("ordinary Agent must not scan the personal-assistant directory")

    monkeypatch.setattr(personal, "profile_agent", forbidden)
    agent_id = personal_env["owner"]
    with pytest.raises(BindingDisabledError):
        facade.update_virtual_human_dialogue_settings(agent_id, settings={})
    _assert_no_settings(dialogue_service, agent_id)


def test_enabled_companion_keeps_original_path_despite_assistant_identity_conflict(
    personal_env, dialogue_service, monkeypatch
):
    agent_id = personal.create_personal_assistant()["assistant"]["agentId"]
    dialogue_service.set_binding(agent_id, enabled=True, expected_version=0)

    def conflict():
        raise directory.AgentStateConflictError("conflicting assistant directory")

    monkeypatch.setattr(personal, "profile_agent", conflict)
    # A legacy adapter can keep its existing signature on the original path.
    original = dialogue_service.update_dialogue_settings
    calls = []

    def legacy_update(target, *, settings):
        calls.append(target)
        return original(target, settings=settings)

    monkeypatch.setattr(dialogue_service, "update_dialogue_settings", legacy_update)
    updated = facade.update_virtual_human_dialogue_settings(
        agent_id, settings={"speakingInitiative": "talkative"}
    )
    assert updated["speakingInitiative"] == "talkative"
    assert calls == [agent_id]
    assert dialogue_service.binding_for(agent_id)["enabled"] is True


@pytest.mark.parametrize("changes", [
    {"status": "archived"},
    {"roleKey": "ordinary"},
    {"primaryMode": "chat"},
])
def test_archived_or_forged_assistant_profile_fails_closed(
    personal_env, dialogue_service, changes
):
    agent_id = personal.create_personal_assistant()["assistant"]["agentId"]
    state = directory.load_state()
    next(row for row in state["agents"] if row["agentId"] == agent_id).update(changes)
    directory.save_state(state)

    with pytest.raises(VirtualHumanLifeError):
        facade.update_virtual_human_dialogue_settings(agent_id, settings={})
    _assert_no_settings(dialogue_service, agent_id)


def test_duplicate_assistant_identity_returns_route_conflict_without_writing(
    personal_env, dialogue_service
):
    agent_id = personal.create_personal_assistant()["assistant"]["agentId"]
    duplicate = directory.create_agent_instance(
        display_name="Duplicate assistant",
        metadata={"personalAssistantProfile": personal.PROFILE},
    )
    directory.update_agent_instance(duplicate["agentId"], status="archived")

    with pytest.raises(HTTPException) as error:
        routes.life_dialogue_settings_update(
            agent_id, routes.VirtualHumanDialogueSettingsRequest(questionInitiative="few")
        )
    assert error.value.status_code == 409
    _assert_no_settings(dialogue_service, agent_id)


def test_canonical_identity_must_match_target(personal_env, dialogue_service, monkeypatch):
    agent_id = personal.create_personal_assistant()["assistant"]["agentId"]
    monkeypatch.setattr(
        personal, "profile_agent", lambda: directory.get_agent(personal_env["owner"])
    )
    with pytest.raises(BindingDisabledError):
        facade.update_virtual_human_dialogue_settings(agent_id, settings={})
    _assert_no_settings(dialogue_service, agent_id)
    _assert_no_settings(dialogue_service, personal_env["owner"])


def test_assistant_archived_after_identity_check_cannot_write(
    personal_env, dialogue_service, monkeypatch
):
    agent_id = personal.create_personal_assistant()["assistant"]["agentId"]
    original = personal.profile_agent

    def archive_after_read():
        active = original()
        directory.update_agent_instance(agent_id, status="archived")
        return active

    monkeypatch.setattr(personal, "profile_agent", archive_after_read)
    with pytest.raises(VirtualHumanLifeError, match="Agent not found"):
        facade.update_virtual_human_dialogue_settings(agent_id, settings={})
    _assert_no_settings(dialogue_service, agent_id)


def test_assistant_settings_still_validate_enums(personal_env, dialogue_service):
    agent_id = personal.create_personal_assistant()["assistant"]["agentId"]
    with pytest.raises(VirtualHumanLifeError, match="Unsupported Companion dialogue setting"):
        facade.update_virtual_human_dialogue_settings(
            agent_id, settings={"questionInitiative": "never"}
        )
    _assert_no_settings(dialogue_service, agent_id)
