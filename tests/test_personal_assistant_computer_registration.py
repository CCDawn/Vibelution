import json
from types import SimpleNamespace
import sys

import pytest

from core.web.services import tool_catalog
from tools import personal_assistant_computer_tools as computer_tools

OBSERVE = "personal_assistant_computer_observe_tool"
ACTION = "personal_assistant_computer_action_tool"


def test_tool_bridge_forwards_model_window_and_launch_parameters(monkeypatch):
    checker = lambda: ""
    calls = []
    monkeypatch.setattr(computer_tools, "_identity", lambda: {"agentId": "a", "sessionId": "s", "turnId": "t"})
    monkeypatch.setattr(computer_tools.service, "execute", lambda *args, **kwargs: calls.append((args, kwargs)) or {"ok": True})
    assert json.loads(computer_tools.personal_assistant_computer_observe_tool("excel", checker))["ok"]
    assert json.loads(computer_tools.personal_assistant_computer_action_tool(
        "click", "observation", "1", window="excel", _cancel_checker=checker))["ok"]
    assert json.loads(computer_tools.personal_assistant_computer_action_tool(
        "launch", target="notepad", _cancel_checker=checker))["ok"]
    assert json.loads(computer_tools.personal_assistant_computer_action_tool(
        "click_at", "observation", x=12, y=34, _cancel_checker=checker))["ok"]
    assert calls[0][1] == {"action": "observe", "observation_id": "", "element_id": "", "text": "",
                           "window": "excel", "target": "", "x": None, "y": None, "cancel_checker": checker}
    assert calls[1][1]["window"] == "excel" and calls[1][1]["action"] == "click"
    assert calls[2][1]["target"] == "notepad" and calls[2][1]["action"] == "launch"
    assert calls[3][1]["x"] == 12 and calls[3][1]["y"] == 34


def test_tool_bridge_reports_blocked_when_native_identity_is_unready(monkeypatch):
    from core.web.services import personal_assistant_computer_service as service

    def deny():
        raise service.adapter.ComputerBlocked("请先初始化并打开个人助理会话。", "Initialize first.")
    monkeypatch.setattr(computer_tools, "_identity", lambda: {"agentId": "a", "sessionId": "s", "turnId": "t"})
    monkeypatch.setattr(service, "_canonical", deny)
    monkeypatch.setattr(service, "_grant", None)
    monkeypatch.setattr(service, "_status", "idle")
    monkeypatch.setattr(service, "_quarantine", None)
    monkeypatch.setattr(service, "_event", lambda *args, **kwargs: None)
    payload = json.loads(computer_tools.personal_assistant_computer_observe_tool(lambda: ""))
    assert payload["ok"] is False and payload["status"] == "blocked"
    assert "reason" not in payload


def test_tool_bridge_refuses_unbound_agents(monkeypatch):
    def deny():
        raise ValueError("private detail")
    monkeypatch.setattr(computer_tools, "_identity", deny)
    monkeypatch.setattr(computer_tools.service, "execute", lambda *args, **kwargs: pytest.fail("identity bypass"))
    result = computer_tools.personal_assistant_computer_observe_tool()
    assert not json.loads(result)["ok"] and "private detail" not in result


@pytest.mark.parametrize("name,approval", [(OBSERVE, "never"), (ACTION, "on_request")])
def test_new_tools_keep_explicit_or_default_native_approval(name, approval):
    descriptor = tool_catalog.build_tool_descriptor(name, args_schema={})
    assert descriptor.approval == approval
    assert name in tool_catalog.explicit_allow_tool_names()
    assert tool_catalog.permission_tier_for_tool(name) == "high"
    assert descriptor.availability.platforms == ("windows",)


def test_action_tools_are_eligible_for_tool_level_session_grants():
    from types import SimpleNamespace as Request
    from core.web.services.session import tool_approvals
    for name in (ACTION, "personal_assistant_desktop_action_tool"):
        descriptor = tool_catalog.build_tool_descriptor(name, args_schema={})
        request = Request(approval=descriptor.approval, tool_name=name, risk=descriptor.risk,
                          tool_args={})
        assert tool_approvals._tool_level_session_grant_ineligibility(request) == ""


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
