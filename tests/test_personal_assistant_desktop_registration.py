"""Registration and explicit assistant-policy migration; never use a desktop."""

import ast
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Literal

import pytest
from langchain_core.tools import tool
from pydantic import BaseModel, ConfigDict, ValidationError

from core.web.services import agent_directory_service as directory
from core.web.services import personal_assistant_service as service
from core.web.services import tool_catalog
from tests.test_financial_report_registry import definition
from tests.test_personal_assistant_service import finance_env, personal_env

OBSERVE = "personal_assistant_desktop_observe_tool"
ACTION = "personal_assistant_desktop_action_tool"
ROOT = Path(__file__).resolve().parents[1]
OLD_TOOLS = (
    "personal_assistant_overview_tool", "personal_assistant_manage_tool",
    "append_personal_memory_tool", "supersede_personal_memory_tool",
)


@pytest.mark.parametrize("name, expected", [(OBSERVE, set()), (ACTION, {"action", "observation_id", "text"})])
def test_registered_schema_hides_checker_and_preserves_internal_dispatch(name, expected):
    calls = []
    impl = lambda **kwargs: calls.append(kwargs) or "accepted"
    namespace = {
        "tool": tool,
        "_personal_assistant_desktop_observe_impl": impl,
        "_personal_assistant_desktop_action_impl": impl,
        "BaseModel": BaseModel, "ConfigDict": ConfigDict, "Literal": Literal,
    }
    tree = ast.parse((ROOT / "tools/Key_Tools.py").read_text(encoding="utf-8-sig"))
    classes = [n for n in tree.body if isinstance(n, ast.ClassDef) and n.name.startswith("_PersonalAssistantDesktop")]
    exec(compile(ast.Module(body=classes, type_ignores=[]), "desktop schemas", "exec"), namespace)
    wrapper = definition("tools/Key_Tools.py", name, namespace)
    assert set(wrapper.args) == expected
    checker = lambda: "cancelled"
    args = {"action": "save", "observation_id": "obs-1", "text": ""} if name == ACTION else {}
    assert wrapper.func(**args, _cancel_checker=checker) == "accepted"
    assert calls == [{**args, "_cancel_checker": checker}]
    with pytest.raises(ValidationError):
        wrapper.args_schema.model_validate({**args, "_cancel_checker": "model supplied"})
    if name == ACTION:
        assert wrapper.args["action"]["enum"] == ["launch", "type_text", "save", "save_foreground", "end"]
    builder = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_build_key_tools")
    assert sum(isinstance(n, ast.Name) and n.id == name for n in builder.body[-1].value.elts) == 1


@pytest.mark.parametrize("name,risk,approval,concurrency", [(OBSERVE, "read", "never", "safe"), (ACTION, "execute", "always", "serialized")])
def test_desktop_descriptors_are_explicit_restricted_and_truthful(name, risk, approval, concurrency):
    descriptor = tool_catalog.build_tool_descriptor(name, args_schema={})
    assert (descriptor.risk, descriptor.approval, descriptor.concurrency) == (risk, approval, concurrency)
    assert descriptor.availability.platforms == ("windows",)
    assert descriptor.availability.required_config == ("VIBELUTION_DESKTOP_CUA_CONFIG",)
    assert name in tool_catalog.explicit_allow_tool_names()
    assert tool_catalog.permission_tier_for_tool(name) == "high"
    assert "delete_or_cleanup" not in tool_catalog.risk_tags_for_tool(name)


@pytest.mark.parametrize("approval", ["silent", None, [], True])
def test_catalog_approval_override_rejects_unknown_values(monkeypatch, approval):
    monkeypatch.setitem(tool_catalog.TOOL_CATALOG, OBSERVE, {
        "category": "runtime_control", "capabilityTags": ["desktop_observation"], "approval": approval,
    })
    with pytest.raises(tool_catalog.ToolDescriptorError, match="approval"):
        tool_catalog.build_tool_descriptor(OBSERVE, args_schema={})


def test_desktop_executor_budget_and_write_guards(monkeypatch):
    from core.infrastructure.tool_executor import ToolExecutor
    # Load only registration; do not import all tool implementations or start an app.
    monkeypatch.setitem(sys.modules, "tools.Key_Tools", SimpleNamespace(create_key_tools=lambda: []))
    executor = ToolExecutor()
    for name in (OBSERVE, ACTION):
        assert executor._resolve_timeout(name, {}) == 90
        assert name not in executor._retryable_tools
    monkeypatch.setenv("VIBELUTION_SUBAGENT_MODE", "readonly")
    assert executor._check_readonly_subagent_block(ACTION)
    assert executor._check_readonly_subagent_block(OBSERVE) is None
    session = SimpleNamespace(get_runtime_goal_packet=lambda: SimpleNamespace(allow_file_writes=False))
    assert executor._check_runtime_goal_capability_block(session, ACTION, {})
    assert executor._check_runtime_goal_capability_block(session, OBSERVE, {}) is None


@pytest.mark.parametrize("private", [False, True])
def test_explicit_setup_upgrades_only_exact_old_policies(personal_env, private):
    row = service.create_personal_assistant()["assistant"]
    agent = directory.get_agent(row["agentId"])
    old = {"allowedTools": list(OLD_TOOLS), "preferredTools": list(OLD_TOOLS),
           "networkAccess": "none", "mutationAccess": "controlled", "maxCallsPerTurn": 8}
    if private:
        old["writeScopes"] = ["private"]
    stored = directory.normalize_tool_policy(old, agent["toolPolicyId"])
    stored["policyVersion"] = 2
    state = directory.load_state()
    state["toolPolicies"][agent["toolPolicyId"]] = stored
    for persisted in state["agents"]:
        if persisted["agentId"] == row["agentId"]:
            persisted["toolPolicy"] = stored
    directory.save_state(state)
    before = directory.load_state()
    assert service.get_personal_assistant()["assistant"]["setupStatus"] == "setup_required"
    assert directory.load_state() == before
    assert not {OBSERVE, ACTION}.intersection(directory.get_agent(row["agentId"])["toolPolicy"]["allowedTools"])
    assert service.create_personal_assistant()["assistant"]["setupStatus"] == "ready"
    updated = directory.get_agent(row["agentId"])["toolPolicy"]
    assert {OBSERVE, ACTION} <= set(updated["allowedTools"])
    assert updated["writeScopes"] == ["private"]


@pytest.mark.parametrize("policy", [{"allowedTools": [], "preferredTools": []},
    # Structurally custom: preferredTools differ from any provisioning snapshot.
    # A budget-only deviation no longer counts as custom because snapshot
    # budgets follow the live config knob and are system-written.
    {"allowedTools": list(OLD_TOOLS), "preferredTools": [], "maxCallsPerTurn": 5}])
def test_get_and_repeated_setup_preserve_custom_zero_tool_policies(personal_env, policy):
    row = service.create_personal_assistant()["assistant"]
    directory.update_agent_instance(row["agentId"], tool_policy=policy)
    before = directory.load_state()
    service.get_personal_assistant()
    assert directory.load_state() == before
    service.create_personal_assistant()
    assert directory.load_state() == before


def test_legacy_policy_snapshots_keep_original_four_tools():
    assert service.LEGACY_POLICY["allowedTools"] == list(OLD_TOOLS)
    assert service.PRIVATE_V2_POLICY == {**service.LEGACY_POLICY, "writeScopes": ["private"]}
    assert {OBSERVE, ACTION} <= set(service.TOOLS)
