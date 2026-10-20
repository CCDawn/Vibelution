"""Assistant default authorization reaches the existing isolated affairs ledger."""

import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from langchain_core.tools import StructuredTool

from core.authorization import tool_authorization_service as auth
from core.authorization.tool_policy_evaluator import evaluate_tool_policy, normalize_legacy_tool_policy
from core.authorization.tool_policy_models import TurnToolGrant
from core.infrastructure.tool_executor import ToolExecutor
from core.agent_plugins.personal_affairs.service import PersonalAffairsService
from core.web.services import agent_directory_service as directory, personal_assistant_service as assistant
from core.web.services import personal_affairs_service as affairs, personal_attention_service as attention, tool_catalog
from tools import personal_affairs_tools
from tests.test_personal_assistant_service import personal_env, finance_env

TOOL = "personal_affairs_tool"


def decision(agent):
    names = tuple(dict.fromkeys((*assistant.TOOLS, TOOL)))
    descriptors = [tool_catalog.build_tool_descriptor(name, args_schema={}) for name in names]
    return evaluate_tool_policy(agent_id=agent["agentId"],
        policy=normalize_legacy_tool_policy(agent["toolPolicy"], registered_tool_names=names, policy_id=agent["toolPolicyId"]),
        grant=TurnToolGrant(turn_id="affairs-turn", source="session", allowed_capabilities=tuple(sorted({
            cap for descriptor in descriptors for cap in descriptor.capabilities})), denied_tools=(), approval_mode="on_request"),
        descriptors=descriptors, registry_version=1, registry_fingerprint="affairs-test")


def test_new_assistant_can_execute_affairs_tool(personal_env):
    row = assistant.create_personal_assistant()["assistant"]
    agent = directory.get_agent(row["agentId"])
    assert TOOL in agent["toolPolicy"]["allowedTools"]
    result = decision(agent)
    assert TOOL in result.visible_tools and TOOL in result.executable_tools
    assert TOOL in agent["taskProfile"]["responsibilities"]


@pytest.mark.parametrize("custom", ["", "network", "blocked", "zero", "prompt"])
def test_existing_query_default_upgrades_only_on_explicit_setup(personal_env, custom):
    row = assistant.create_personal_assistant()["assistant"]
    prior_tools = [name for name in assistant.TOOLS if name != TOOL]
    policy = {**assistant.current_policy(), "allowedTools": prior_tools, "preferredTools": prior_tools}
    if custom == "network":
        policy["networkAccess"] = "none"
    elif custom == "blocked":
        policy["blockedTools"] = [TOOL]
    elif custom == "zero":
        policy["allowedTools"] = policy["preferredTools"] = []
    task = {"responsibilities": "我的自定义职责"} if custom == "prompt" else assistant._PRE_AFFAIRS_TASK
    directory.update_agent_instance(row["agentId"], tool_policy=policy, task_profile=task)
    before = directory.get_agent(row["agentId"])
    assistant.get_personal_assistant()
    assert directory.get_agent(row["agentId"]) == before
    assistant.create_personal_assistant()
    after = directory.get_agent(row["agentId"])
    if custom in {"network", "blocked", "zero"}:
        assert after["toolPolicy"] == before["toolPolicy"] and after["taskProfile"] == before["taskProfile"]
        assert TOOL not in decision(after).executable_tools
    else:
        assert TOOL in decision(after).executable_tools
        expected_task = before["taskProfile"] if custom == "prompt" else directory.normalize_task_profile(assistant.TASK)
        assert after["taskProfile"] == expected_task


def test_authorized_calls_persist_affairs_and_feed_existing_reminders(personal_env, monkeypatch):
    row = assistant.create_personal_assistant()["assistant"]
    agent = directory.get_agent(row["agentId"])
    granted = decision(agent)
    assert TOOL in granted.executable_tools
    now = datetime(2026, 10, 19, 9, 0, tzinfo=timezone.utc)
    store = PersonalAffairsService(personal_env["root"], agent_loader=directory.get_agent, now_provider=lambda: now)
    monkeypatch.setattr(affairs, "_SERVICE", store)
    runtime = {"agentId": row["agentId"], "sessionId": row["directSessionId"], "turnId": "affairs-turn",
        "toolPolicy": agent["toolPolicy"], "agentConfigSnapshot": agent, "permissionPreset": "request_approval"}
    monkeypatch.setattr(directory, "current_agent_runtime", lambda: runtime)
    wrapper = StructuredTool.from_function(personal_affairs_tools.personal_affairs_tool)
    executor = ToolExecutor()
    executor.register_tool(TOOL, lambda **arguments: wrapper.invoke(arguments))
    counter = 0

    def call(**arguments):
        nonlocal counter
        counter += 1
        raw, action = executor.execute(TOOL, arguments, tool_call_id=f"affairs-call-{counter}")
        assert action is None
        result = json.loads(raw)
        assert result["ok"], result
        return result

    auth.install_execution_authorization(SimpleNamespace(decision=granted))
    try:
        ids = [call(action="add", kind=kind, title=kind, due_at="2026-10-19T16:00:00+08:00")["item"]["itemId"]
            for kind in ("todo", "schedule", "goal")]
        for kind in ("todo", "schedule", "goal"):
            selected = call(action="list", kind=kind)["affairs"]["items"]
            assert len(selected) == 1 and selected[0]["kind"] == kind
        call(action="set_due", item_id=ids[2], due_at="2026-10-20T09:00:00+08:00")
        monkeypatch.setattr(attention, "collect_knowledge_review_attention", lambda: [])
        monkeypatch.setattr(attention, "collect_anomaly_attention", lambda: [])
        first = attention.attach_attention_to_overview({"attention": []})
        assert {item["title"] for item in first["humanAttention"]} == {"事务提醒：todo", "事务提醒：schedule"}
        call(action="complete", item_id=ids[0])
        call(action="cancel", item_id=ids[1])
        assert affairs.collect_affair_reminder_attention() == []
        call(action="reopen", item_id=ids[0])
        assert affairs.collect_affair_reminder_attention()[0]["title"] == "事务提醒：todo"
        assert store.list_items(personal_env["other"])["items"] == []
        assert len(store.store.read_jsonl(row["agentId"], "affairs/items.jsonl")) == 3
    finally:
        auth.clear_execution_authorization()
