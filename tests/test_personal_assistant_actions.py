"""Everyday assistant actions keep identity, bounded authority and replay safety."""
import json
from concurrent.futures import ThreadPoolExecutor

import pytest
from langchain_core.tools import tool

from core.web.services import agent_directory_service as directory, personal_assistant_service as service, tool_catalog
from tests.test_financial_report_registry import definition
from tests.test_personal_assistant_service import finance_env, personal_env
from tests.test_personal_assistant_tools import assistant_runtime
from tools import pa_platform_actions as actions, personal_assistant_tools as tools


def call(action, parameters=None):
    return json.loads(tools.personal_assistant_action_tool(action, parameters))


def test_object_action_requires_canonical_identity(personal_env, monkeypatch):
    monkeypatch.setattr(directory, "current_agent_runtime", dict)
    monkeypatch.setattr(actions, "execute_action", lambda *args: pytest.fail("unbound execution"))
    assert call("settings_update", {"updates": []})["ok"] is False


def test_ordinary_update_uses_object_schema_and_native_readback(assistant_runtime, personal_env):
    target = personal_env["other"]
    before = directory.get_agent(target)
    description = call("describe", {"action": "agent_update"})
    assert "displayName" in description["updatesSchema"]["properties"]
    assert "permissionPreset" not in description["updatesSchema"]["properties"]
    result = call("agent_update", {"agent_id": target, "updates": {"displayName": "新名字"}})
    assert result["ok"] and result["displayName"] == "新名字"
    current = directory.get_agent(target)
    assert current["displayName"] == "新名字"
    assert current["toolPolicy"] == before["toolPolicy"]
    assert current["permissionPreset"] == before["permissionPreset"]


@pytest.mark.parametrize("field,value", [
    ("permissionPreset", "full_access"), ("toolPolicy", {"allowedTools": ["cli_tool"]}),
    ("toolPolicyId", "other"), ("roleKey", "personal_assistant"), ("status", "archived"),
    ("metadata", {"perceptionPolicy": {}}), ("delegationPolicy", {"allowSubagents": True}),
    ("memoryPolicy", {"readableAgentIds": ["*"]}), ("display_name", "snake field"),
])
def test_privilege_identity_lifecycle_fields_are_rejected_whole_batch(assistant_runtime, personal_env, field, value):
    target = personal_env["other"]
    before = directory.get_agent(target)
    result = call("agent_update", {"agent_id": target, "updates": {"displayName": "must not land", field: value}})
    assert result["ok"] is False
    assert directory.get_agent(target) == before


def test_action_does_not_reconfigure_canonical_assistant(assistant_runtime):
    result = call("agent_update", {"agent_id": assistant_runtime["agentId"], "updates": {"displayName": "other"}})
    assert result["ok"] is False


def test_create_bounded_worker_and_replay_does_not_duplicate(assistant_runtime, monkeypatch, tmp_path):
    from core.web.services import agent_operation_service as owner
    saved = {}
    calls = []
    monkeypatch.setattr(directory, "_workspace_path", lambda *args: tmp_path.joinpath(*args))
    actor_id = assistant_runtime["agentId"]
    real_get = directory.get_agent
    monkeypatch.setattr(directory, "get_agent", lambda key: saved.get(key) or real_get(key))
    def create(**kwargs):
        calls.append(kwargs)
        saved["created"] = {"agentId": "created", "directSessionId": "session-created", "displayName": kwargs["display_name"]}
        return saved["created"]
    monkeypatch.setattr(owner, "create_agent_from_catalog_request", create)
    monkeypatch.setattr(directory, "update_agent_instance", lambda key, **kwargs: saved[key])
    parameters = {"display_name": "帮手", "request_id": "create-once", "model_id": "test-model"}
    # Worker runtime identity is passed explicitly; filesystem admission is cross-thread.
    runtime = {"agentId": actor_id, "sessionId": assistant_runtime["directSessionId"]}
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: actions.execute_action("agent_create", parameters, runtime), range(2)))
    assert all(result["ok"] for result in results) and len(calls) == 1
    assert calls[0]["tool_policy"]["allowedTools"] == ["agent_message_tool"]
    assert calls[0]["primary_mode"] == "chat"
    assert "personalAssistantTask" in calls[0]["task_profile"]["responsibilities"]
    assert "evidenceRefs" in calls[0]["task_profile"]["responsibilities"]
    with pytest.raises(ValueError, match="request_id"):
        actions.execute_action("agent_create", {**parameters, "display_name": "different"}, runtime)


def test_unknown_create_is_not_automatically_retried(assistant_runtime, monkeypatch, tmp_path):
    from core.web.services import agent_operation_service as owner
    monkeypatch.setattr(directory, "_workspace_path", lambda *args: tmp_path.joinpath(*args))
    calls = []
    def fail(**kwargs):
        calls.append(kwargs)
        raise OSError("internal error with secret")
    monkeypatch.setattr(owner, "create_agent_from_catalog_request", fail)
    parameters = {"display_name": "帮手", "request_id": "unknown-once", "model_id": "test-model"}
    runtime = {"agentId": assistant_runtime["agentId"], "sessionId": assistant_runtime["directSessionId"]}
    first = actions.execute_action("agent_create", parameters, runtime)
    second = actions.execute_action("agent_create", parameters, runtime)
    assert first["status"] == second["status"] == "unknown" and len(calls) == 1
    assert "secret" not in json.dumps(first)


def test_action_descriptor_is_explicit_bounded_write_and_manage_stays_approved():
    wrapper = definition("tools/Key_Tools.py", "personal_assistant_action_tool", {
        "tool": tool, "_personal_assistant_action_impl": tools.personal_assistant_action_tool,
    })
    schema = wrapper.args_schema.model_json_schema()
    assert "object" in str(schema["properties"]["parameters"])
    descriptor = tool_catalog.build_tool_descriptor("personal_assistant_action_tool", args_schema=schema)
    assert descriptor.risk == "write" and descriptor.approval == "never"
    assert descriptor.concurrency == "serialized"
    assert not descriptor.write_scope_gated
    assert "personal_assistant_action_tool" in service.current_policy()["allowedTools"]
    assert "personal_assistant_action_tool" in tool_catalog.EXPLICIT_ALLOW_TOOLS
    assert tool_catalog.build_tool_descriptor("personal_assistant_manage_tool", args_schema={}).approval == "always"


@pytest.mark.parametrize("with_override", [False, True])
def test_old_untouched_provisioning_upgrades_actions_but_preserves_user_edits(assistant_runtime, with_override):
    agent_id = assistant_runtime["agentId"]
    old = service.current_policy()
    old["allowedTools"] = list(service._PRE_ACTIONS_TOOLS)
    old["preferredTools"] = list(service._PRE_ACTIONS_TOOLS)
    if not with_override:
        old.pop("approvalOverrides")
    directory.update_agent_instance(agent_id, tool_policy=old, task_profile=service._PRE_ACTIONS_TASK)
    assert service.get_personal_assistant()["assistant"]["setupStatus"] == "setup_required"
    service.create_personal_assistant()
    current = directory.get_agent(agent_id)
    assert "personal_assistant_action_tool" in current["toolPolicy"]["allowedTools"]
    assert "personal_assistant_action_tool" in current["taskProfile"]["responsibilities"]
    assert directory.resolve_delegation_policy_for_agent(agent_id)["allowWakeMessages"] is False
    custom = {**service.current_policy(), "blockedTools": ["personal_assistant_action_tool"]}
    directory.update_agent_instance(agent_id, tool_policy=custom)
    service.create_personal_assistant()
    assert "personal_assistant_action_tool" in directory.get_agent(agent_id)["toolPolicy"]["blockedTools"]


def test_team_plan_approval_is_concrete_and_bounded():
    from core.web.services.session.tool_approvals import _assistant_management_summary
    summary = _assistant_management_summary({"action": "team_run", "arguments_json": json.dumps({
        "name": "验收团队", "goal": "g" * 2000, "request_id": "team-once"})})
    assert not summary.get("assistantArgumentsInvalid")
    assert summary["assistantTargets"] == {"name": "验收团队", "template_id": "dev-team", "request_id": "team-once"}
    assert summary["assistantPlan"]["memberCount"] == 4
    assert summary["assistantPlan"]["startsImmediately"] is True
    assert len(summary["assistantPlan"]["goalPreview"]) == 160
    assert summary["assistantPlan"]["automaticRecovery"] is False
    assert summary["assistantPlan"]["localIntegration"] is False


def test_native_frozen_json_arrays_reach_settings_adapter_as_lists(assistant_runtime, monkeypatch):
    from core.llm.types import _freeze_json_value
    from tools import pa_settings_actions
    updates = [{"section": "ui", "key": "language", "value": "en"}]
    observed = []
    monkeypatch.setattr(pa_settings_actions, "settings_update", lambda value: observed.append(value) or {"ok": True})
    frozen = _freeze_json_value({"updates": updates})
    assert isinstance(frozen["updates"], tuple)
    assert call("settings_update", frozen)["ok"]
    assert observed == [updates] and type(observed[0]) is list and type(observed[0][0]) is dict


def test_partial_task_update_preserves_other_profile_fields(assistant_runtime, personal_env):
    target = personal_env["other"]
    directory.update_agent_instance(target, role_key="worker", task_profile={"mission": "old", "constraints": "retain"})
    result = call("agent_update", {"agent_id": target, "updates": {"taskProfile": {"mission": "new"}}})
    assert result["ok"]
    assert directory.get_agent(target)["taskProfile"]["constraints"] == "retain"
    before = directory.get_agent(target)
    assert call("agent_update", {"agent_id": target, "updates": {"taskProfile": {"unknown": "x"}}})["ok"] is False
    assert directory.get_agent(target) == before
