"""Launcher management modes change consent, never project or tool authority."""
import json

import pytest

from core.web.services.local_assistant import consent


@pytest.fixture
def native_mode(monkeypatch):
    from core.web.services.local_assistant import management_permissions

    current = {"preset": "request_approval", "revision": 0}
    monkeypatch.setattr(consent, "_native_launcher", lambda runtime: True)
    monkeypatch.setattr(management_permissions, "read", lambda agent_id: dict(current))
    return current


def check(action, parameters, agent_preset="full_access"):
    return consent.local_approval_policy({"agentId": "assistant"}, "personal_assistant_manage_tool",
        {"action": action, "arguments_json": json.dumps(parameters)}, ("always", "destructive"), agent_preset)


TEAM = {"project_id": "project", "request_id": "create-team", "name": "资料搜集团队"}
PURGE = {"project_id": "project", "request_id": "purge-agents", "purges": [
    {"agent_id": "archived-agent", "expected_config_revision": 9007199254740993}]}
LIFECYCLE = {"project_id": "project", "operation": "restart", "request_id": "restart-platform"}


def test_management_mode_is_independent_of_ordinary_agent_full_access(native_mode):
    assert check("team_create", TEAM) == (("always", "execute"), "request_approval")
    native_mode.update(preset="auto_review", revision=1)
    assert check("team_create", TEAM, "request_approval") == (None, "request_approval")
    assert check("agent_purge_batch", PURGE) == (("always", "destructive"), "request_approval")
    native_mode.update(preset="full_access", revision=2)
    assert check("agent_purge_batch", PURGE, "request_approval") == (None, "request_approval")
    assert check("project_lifecycle", LIFECYCLE, "request_approval") == (None, "request_approval")


@pytest.mark.parametrize("preset", ["request_approval", "auto_review", "full_access"])
def test_scope_expansion_always_requires_a_separate_operator_decision(native_mode, preset):
    native_mode["preset"] = preset
    assert check("authorization_upgrade", {"project_id": "project", "add_scopes": ["agents:purge"]}) == (
        ("always", "destructive"), "request_approval")
    assert check("reminder_handoff_recover", {"project_id": "project", "preview_id": "f" * 64}) == (
        ("always", "destructive"), "request_approval")


def test_member_removal_is_routine_but_team_cascade_is_destructive(native_mode):
    native_mode["preset"] = "auto_review"
    remove = {"project_id": "project", "request_id": "remove-member", "team_id": "team",
              "expected_team_fingerprint": "a" * 64, "agent_id": "member"}
    assert check("team_member_remove", remove) == (None, "request_approval")
    archive = {key: value for key, value in remove.items() if key != "agent_id"}
    archive.update(expected_member_agent_ids=["member"], expected_linked_chat_room_id="room")
    assert check("team_archive", archive) == (("always", "destructive"), "request_approval")
    assert check("project_lifecycle", LIFECYCLE) == (("always", "destructive"), "request_approval")


@pytest.mark.parametrize("preset", ["request_approval", "auto_review", "full_access"])
@pytest.mark.parametrize("parameters", [{**TEAM, "unknown": True}, {**TEAM, "name": ""}, {**TEAM, "request_id": False}])
def test_invalid_arguments_never_receive_automatic_consent(native_mode, preset, parameters):
    native_mode["preset"] = preset
    assert check("team_create", parameters)[0] == ("always", "destructive")


def test_unknown_action_and_unavailable_mode_keep_confirmation(native_mode, monkeypatch):
    from core.web.services.local_assistant import management_permissions

    native_mode["preset"] = "full_access"
    assert check("future_unknown_action", TEAM)[0] == ("always", "destructive")
    monkeypatch.setattr(management_permissions, "read", lambda agent_id: (_ for _ in ()).throw(ValueError("unavailable")))
    assert check("team_create", TEAM)[0] == ("always", "execute")


def test_duplicate_keys_nan_and_non_object_inputs_are_not_valid_arguments():
    from core.web.services.local_assistant.management_approval import parse_arguments

    for value in ('{"project_id":"first","project_id":"second"}', '{"nested":{"x":1,"x":2}}',
                  '{"value":NaN}', '[]', 'null', '{"value":Infinity}'):
        with pytest.raises(ValueError):
            parse_arguments(value)


def test_modes_are_read_for_each_new_management_call_without_replaying_old_calls(native_mode):
    assert check("team_create", TEAM)[0] is not None
    native_mode.update(preset="auto_review", revision=1)
    assert check("team_create", {**TEAM, "request_id": "next-request"})[0] is None
    native_mode.update(preset="request_approval", revision=2)
    assert check("team_create", {**TEAM, "request_id": "third-request"})[0] is not None


def test_non_native_sessions_and_other_tools_keep_their_existing_policy(monkeypatch):
    monkeypatch.setattr(consent, "_native_launcher", lambda runtime: False)
    assert check("team_create", TEAM) == (("always", "destructive"), "full_access")
    monkeypatch.setattr(consent, "_native_launcher", lambda runtime: True)
    assert consent.local_approval_policy({"agentId": "assistant"}, "read_file_tool", {"file_path": "file"},
        ("on_request", "read"), "auto_review") == (("on_request", "read"), "auto_review")


def test_old_action_window_does_not_bypass_native_management_confirmation(monkeypatch):
    from core.web.services.session import tool_approvals

    class PendingApprovalReached(Exception):
        pass

    def pending(**kwargs):
        raise PendingApprovalReached

    monkeypatch.setattr(consent, "_native_launcher", lambda runtime: True)
    monkeypatch.setattr(tool_approvals, "_assistant_action_window_remaining_seconds", lambda *_: 60)
    monkeypatch.setattr(tool_approvals, "_get_or_create_request", pending)
    call = dict(session_id="session", turn_id="turn", agent_id="assistant", call_id="call",
        tool_name="personal_assistant_manage_tool", tool_args={"action": "session_stop", "arguments_json": "{}"},
        approval="always", risk="destructive", decision_fingerprint="decision", config_revision=1,
        config_hash="config", permission_preset="request_approval")
    with pytest.raises(PendingApprovalReached):
        tool_approvals.authorize_or_wait(**call)
    monkeypatch.setattr(consent, "_native_launcher", lambda runtime: False)
    assert tool_approvals.authorize_or_wait(**call).code == "approved_for_action_window"


@pytest.mark.anyio
async def test_read_action_tool_cannot_bypass_management_mode_for_agent_writes(tmp_path):
    import asyncio
    from core.assistant_runtime import actions
    from core.assistant_runtime.dispatch import DispatchService

    writes = []
    class Client:
        async def diagnostics(self): return {"status": "healthy"}
        async def management_action(self, **kwargs):
            writes.append(kwargs)
            return {"status": "unknown", "action": kwargs["action"], "requestId": kwargs["request_id"], "verified": False, "reused": False}
    service = DispatchService(tmp_path / "profile", {"project": tmp_path / "project"}, client_factory=lambda *_a, **_kw: Client())
    actions.bind_actions(service, asyncio.get_running_loop())
    cases = {
        "agent_create": {"display_name": "Worker", "model_id": "model"},
        "agent_update": {"agent_id": "worker", "expected_config_revision": 1, "updates": {"displayName": "New name"}},
        "agent_avatar": {"agent_id": "worker", "expected_updated_at": "revision", "reset_to_default": True},
    }
    try:
        from core.web.services.external_management.contracts import contracts
        for action, parameters in cases.items():
            args = {"project_id": "project", "request_id": "write-" + action, **parameters}
            assert contracts()[action]["governed"] is False  # Ordinary platform contract is unchanged.
            assert actions.execute_action("describe", {"action": action})["governed"] is True
            denied = await asyncio.to_thread(actions.execute_action, action, args)
            assert denied["status"] == "approval_required"
        assert writes == []
        created = await asyncio.to_thread(actions.execute_action, "agent_create",
            {"project_id": "project", "request_id": "accepted", **cases["agent_create"]}, governed=True)
        assert created["status"] == "unknown" and len(writes) == 1
    finally:
        actions.unbind_actions(service)
