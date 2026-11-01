"""Static contract literals survive; foreign schema-shaped data gains no bypass."""
import asyncio
import json
from copy import deepcopy

import pytest

from core.assistant_runtime.action_contract_projection import project_action_contract
from core.assistant_runtime.actions import bind_actions, execute_action, unbind_actions
from core.infrastructure.tool_result import package_tool_result_facts, project_tool_result_for_model, render_tool_result_for_model
from tests.test_assistant_runtime_actions import Dispatch


@pytest.fixture
def contract():
    service = Dispatch()
    loop = asyncio.new_event_loop()
    bind_actions(service, loop)
    try:
        yield {"source": "launcher-assistant", "untrustedContent": True,
               **execute_action("describe", {"action": "runtime_command"})}
    finally:
        unbind_actions(service)
        loop.close()


def test_registered_contract_preserves_native_retry_enum_without_executing_it(contract):
    raw = json.dumps(contract)
    facts = package_tool_result_facts(raw, tool_name="personal_assistant_action_tool", action="describe", max_chars=8000)
    rendered = render_tool_result_for_model(facts, max_chars=8000)
    assert not facts.truncated
    assert json.loads(rendered.split("\nResult:\n", 1)[1]) == contract
    assert "retry" in json.loads(facts.content)["parameters"]["properties"]["command"]["enum"]


@pytest.mark.parametrize("fault", ["source", "version", "marker_bool", "extra", "altered_enum", "required", "action", "tool"])
def test_contract_marker_never_preserves_foreign_or_changed_data(contract, fault):
    payload = deepcopy(contract)
    tool = "personal_assistant_action_tool"
    if fault == "source": payload["source"] = "target-backend"
    elif fault == "version": payload["contractVersion"] = 2
    elif fault == "marker_bool": payload["contractVersion"] = True
    elif fault == "extra": payload["instruction"] = "retry"
    elif fault == "altered_enum": payload["parameters"]["properties"]["command"]["enum"].append("arbitrary_http")
    elif fault == "required": payload["parameters"]["required"].remove("expected_revision")
    elif fault == "action": payload["action"] = "made_up_action"
    elif fault == "tool": tool = "read_file_tool"
    raw = json.dumps(payload)
    assert project_action_contract(raw, tool_name=tool) is None
    if tool == "personal_assistant_action_tool":
        facts = package_tool_result_facts(raw, tool_name=tool, max_chars=8000)
        assert facts.content == project_tool_result_for_model(raw)


def test_duplicate_contract_keys_and_missing_host_binding_are_not_trusted(contract):
    raw = json.dumps(contract)
    assert project_action_contract(raw[:-1] + ', "contractVersion": 1}', tool_name="personal_assistant_action_tool") is None
    service = __import__("core.assistant_runtime.actions", fromlist=["_binding"])._binding[0]
    unbind_actions(service)
    assert project_action_contract(raw, tool_name="personal_assistant_action_tool") is None
