"""Tool and API discovery resolve to the same bounded semantic operations."""
import json

import pytest

from tools import pa_platform_actions as actions, personal_assistant_tools as tools
from tests.test_personal_assistant_tools import assistant_runtime, finance_env, personal_env


def test_every_extension_is_discoverable_with_exact_schema():
    index = actions.action_catalog()
    entries = {item["action"]: item for item in index["actions"]}
    for name, contract in actions.extension_contracts().items():
        assert entries[name]["governed"] == contract["governed"]
        assert actions.action_catalog(name)["parameters"]["additionalProperties"] is False
        if contract["governed"]:
            assert name in index["governedActions"]["actions"]


def test_governed_actions_cannot_write_through_direct_action_tool(assistant_runtime, monkeypatch):
    from tools import pa_workspace_actions as workspace
    monkeypatch.setattr(workspace, "execute", lambda *args, **kwargs: pytest.fail("approval bypass"))
    result = json.loads(tools.personal_assistant_action_tool("session_pin", {"session_id": "test"}))
    assert not result["ok"] and result["status"] == "approval_required"
    assert result["tool"] == "personal_assistant_manage_tool"


def test_manage_passes_native_approval_flag_only_from_dispatcher(assistant_runtime, monkeypatch):
    from tools import pa_workspace_actions as workspace
    calls = []
    def execute(action, parameters, runtime, *, governed=False):
        calls.append((action, parameters, governed, runtime["agentId"]))
        return {"ok": True, "verified": True, "status": "completed", "sessionId": "test", "pinned": True}
    monkeypatch.setattr(workspace, "execute", execute)
    result = json.loads(tools.personal_assistant_manage_tool("session_pin", '{"session_id":"test"}'))
    assert result["verified"] and result["pinned"]
    assert calls == [("session_pin", {"session_id": "test"}, True, assistant_runtime["agentId"])]


def test_native_validation_errors_do_not_echo_secret_input(assistant_runtime):
    result = json.loads(tools.personal_assistant_manage_tool("session_pin", json.dumps({"session_id": {"secret": "do-not-echo"}})))
    assert not result["ok"] and "do-not-echo" not in str(result)


def test_approval_names_semantic_operation_target_and_side_effects():
    from core.web.services.session.tool_approvals import _assistant_management_summary
    preview = _assistant_management_summary({"action": "team_archive", "arguments_json": '{"team_id":"fixture"}'})
    assert preview["assistantAction"] == "team_archive"
    assert preview["assistantTargets"]["team_id"] == "fixture"
    assert "级联" in preview["assistantOperationDescription"]
    assert "assistantArgumentsInvalid" not in preview
    invalid = _assistant_management_summary({"action": "team_archive", "arguments_json": '{"team_id":"fixture","actor":"operator"}'})
    assert invalid["assistantArgumentsInvalid"]


def test_registered_api_maps_to_approved_semantic_action_not_http_proxy():
    from core.web.services.personal_assistant_platform_api import catalog
    operation = {"operationId": "pin", "tags": ["sessions"]}
    entry = catalog._catalog_entry("post", "/api/sessions/{session_id}/pin", operation, set())
    assert entry["tool"] == "personal_assistant_manage_tool" and entry["action"] == "session_pin"
    assert entry["approval"]["required"] == "native management approval"
    for path in ("/api/agents/{agent_id}/perception/configuration", "/api/sessions/{session_id}/tool-approvals/{request_id}/decision", "/api/reset"):
        assert not catalog._catalog_entry("post", path, operation, set())["executable"]


def test_provider_approval_displays_destination_without_accepting_secret_url():
    from core.web.services.session.tool_approvals import _assistant_management_summary
    values = {"provider_id": "fixture", "base_url": "http://127.0.0.1:12345/v1"}
    result = _assistant_management_summary({"action": "provider_add", "arguments_json": json.dumps(values)})
    assert result["assistantTargets"]["base_url"] == values["base_url"]
    values["base_url"] = "https://secret-key@example.com/v1"
    invalid = _assistant_management_summary({"action": "provider_add", "arguments_json": json.dumps(values)})
    assert invalid["assistantArgumentsInvalid"] and "secret-key" not in str(invalid)
