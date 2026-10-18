import json
from types import SimpleNamespace
import sys

import pytest

from core.web.services import tool_catalog
from tools import personal_assistant_computer_tools as computer_tools

OBSERVE = "personal_assistant_computer_observe_tool"
ACTION = "personal_assistant_computer_action_tool"


def test_tool_bridge_uses_canonical_runtime_and_never_accepts_a_window(monkeypatch):
    checker = lambda: ""
    calls = []
    monkeypatch.setattr(computer_tools, "_identity", lambda: {"agentId": "a", "sessionId": "s", "turnId": "t"})
    monkeypatch.setattr(computer_tools.service, "execute", lambda *args, **kwargs: calls.append((args, kwargs)) or {"ok": True})
    assert json.loads(computer_tools.personal_assistant_computer_observe_tool(checker))["ok"]
    assert json.loads(computer_tools.personal_assistant_computer_action_tool("click", "observation", "1", _cancel_checker=checker))["ok"]
    assert calls[0][0] == (("a", "s", "t"),)
    assert calls[1][1] == {"action": "click", "observation_id": "observation", "element_id": "1", "text": "", "cancel_checker": checker}


def test_tool_bridge_refuses_unbound_agents(monkeypatch):
    def deny():
        raise ValueError("private detail")
    monkeypatch.setattr(computer_tools, "_identity", deny)
    monkeypatch.setattr(computer_tools.service, "execute", lambda *args, **kwargs: pytest.fail("identity bypass"))
    result = computer_tools.personal_assistant_computer_observe_tool()
    assert not json.loads(result)["ok"] and "private detail" not in result


@pytest.mark.parametrize("name,approval", [(OBSERVE, "never"), (ACTION, "always")])
def test_new_tools_are_explicit_high_tier_and_keep_native_approval(name, approval):
    descriptor = tool_catalog.build_tool_descriptor(name, args_schema={})
    assert descriptor.approval == approval
    assert name in tool_catalog.explicit_allow_tool_names()
    assert tool_catalog.permission_tier_for_tool(name) == "high"
    assert descriptor.availability.platforms == ("windows",)


def test_no_auto_retry_and_readonly_agents_cannot_send_input(monkeypatch):
    from core.infrastructure.tool_executor import ToolExecutor
    monkeypatch.setitem(sys.modules, "tools.Key_Tools", SimpleNamespace(create_key_tools=lambda: []))
    executor = ToolExecutor()
    assert executor._resolve_timeout(ACTION, {}) == 90
    assert executor._resolve_timeout(OBSERVE, {}) == 90
    assert ACTION not in executor._retryable_tools and OBSERVE not in executor._retryable_tools
    monkeypatch.setenv("VIBELUTION_SUBAGENT_MODE", "readonly")
    assert executor._check_readonly_subagent_block(ACTION)
    assert executor._check_readonly_subagent_block(OBSERVE) is None
