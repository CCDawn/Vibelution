"""Assistant settings adapters preserve native identity and partial updates."""
import threading

import pytest

from tools import pa_assistant_actions as actions


def test_settings_patch_reads_back_and_does_not_return_model_routes(monkeypatch):
    from core.web.services import personal_assistant_service as owner
    state = {"displayName": "鲸鱼", "preferences": {"showStatus": True, "showTitles": True},
             "model": {"currentModelId": "provider/model", "choices": [{"secret": "hidden"}]}}
    monkeypatch.setattr(owner, "get_personal_assistant_settings", lambda: {"settings": state})
    def update(**values):
        state["preferences"].update(values["preferences"])
    monkeypatch.setattr(owner, "update_personal_assistant_settings", update)
    result = actions.execute("assistant_settings_update", {"preferences": {"showStatus": False}}, {})
    assert result["verified"] and result["preferences"] == {"showStatus": False, "showTitles": True}
    assert "hidden" not in str(result) and result["modelId"] == "provider/model"


@pytest.mark.parametrize("parameters", [{}, {"display_name": None}, {"preferences": {}},
    {"preferences": {"showStatus": None}}, {"preferences": {"showStatus": "false"}},
    {"preferences": {"actorAgentId": "other"}}])
def test_invalid_settings_never_write(monkeypatch, parameters):
    from core.web.services import personal_assistant_service as owner
    monkeypatch.setattr(owner, "update_personal_assistant_settings", lambda **values: pytest.fail("invalid write"))
    with pytest.raises(ValueError):
        actions.execute("assistant_settings_update", parameters, {})


def test_dialogue_patch_merges_under_native_lock_and_reads_back(monkeypatch):
    from core.web.services import virtual_human_life_service as owner
    state = {"speakingInitiative": "talkative", "questionInitiative": "few", "preferenceProposalMode": "manual_only"}
    lock = threading.RLock()
    class Native:
        def _lock_for(self, agent_id):
            assert agent_id == "current"
            return lock
    monkeypatch.setattr(owner, "get_virtual_human_life_service", Native)
    monkeypatch.setattr(owner, "virtual_human_dialogue_settings", lambda agent_id: dict(state))
    def update(agent_id, *, settings):
        assert agent_id == "current" and lock._is_owned()
        assert settings == {**state, "questionInitiative": "proactive"}
        state.update(settings)
    monkeypatch.setattr(owner, "update_virtual_human_dialogue_settings", update)
    result = actions.execute("dialogue_settings_update", {"questionInitiative": "proactive"}, {"agentId": "current"})
    assert result["verified"] and result["speakingInitiative"] == "talkative"
    assert result["preferenceProposalMode"] == "manual_only"


def test_model_set_reports_unknown_when_native_readback_disagrees(monkeypatch):
    from core.web.services import personal_assistant_service as owner
    monkeypatch.setattr(owner, "update_personal_assistant_model", lambda model_id: {})
    monkeypatch.setattr(owner, "get_personal_assistant_settings", lambda: {"settings": {"model": {"currentModelId": "old"}}})
    result = actions.execute("assistant_model_set", {"model_id": "new"}, {})
    assert not result["ok"] and not result["verified"] and result["status"] == "unknown"
