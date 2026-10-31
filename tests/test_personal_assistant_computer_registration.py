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


def test_tool_bridge_retains_missing_grant_reason(monkeypatch):
    from core.web.services import personal_assistant_computer_service as service
    monkeypatch.setattr(computer_tools, "_identity", lambda: {"agentId": "a", "sessionId": "s", "turnId": "t"})
    monkeypatch.setattr(service, "_canonical", lambda: {"agentId": "a", "directSessionId": "s"})
    monkeypatch.setattr(service, "_configuration", lambda _: (1, "config"))
    monkeypatch.setattr(service, "_authorization_request", None, raising=False)
    monkeypatch.setattr(service, "_grant", None)
    monkeypatch.setattr(service, "_status", "idle")
    monkeypatch.setattr(service, "_quarantine", None)
    monkeypatch.setattr(service, "_event", lambda *args: None)
    monkeypatch.setattr(service.adapter, "driver_binary", lambda: "pinned-driver")
    monkeypatch.setattr(service.adapter, "Connection", lambda *_: pytest.fail("ungranted connection"))
    payload = json.loads(computer_tools.personal_assistant_computer_observe_tool(lambda: ""))
    assert payload["ok"] is False and payload["status"] == "blocked"
    assert payload["reason"] == "authorization_required"


def test_authorization_request_uses_operator_state_without_changing_native_projection(monkeypatch, tmp_path):
    from core.chat.turn_journal import append_turn_event, load_turn_events, EVENT_ASSISTANT_ITEM_COMMITTED, EVENT_TOOL_RESULT, EVENT_TURN_STARTED
    from core.web.services import session_service
    from core.web.services import personal_assistant_computer_service as service

    monkeypatch.setattr(computer_tools, "_identity", lambda: {"agentId": "a", "sessionId": "s", "turnId": "t"})
    monkeypatch.setattr(service, "_canonical", lambda: {"agentId": "a", "directSessionId": "s"})
    monkeypatch.setattr(service, "_configuration", lambda _: (1, "config"))
    monkeypatch.setattr(service, "_authorization_request", None, raising=False)
    monkeypatch.setattr(service, "_grant", None)
    monkeypatch.setattr(service, "_status", "idle")
    monkeypatch.setattr(service, "_quarantine", None)
    monkeypatch.setattr(service, "_event", lambda *args: None)
    monkeypatch.setattr(service.adapter, "driver_binary", lambda: "pinned-driver")
    monkeypatch.setattr(service.adapter, "Connection", lambda *_: pytest.fail("ungranted connection"))
    result = computer_tools.personal_assistant_computer_observe_tool(lambda: "")
    assert json.loads(result)["reason"] == "authorization_required"
    append_turn_event(tmp_path, "s", "t", EVENT_TURN_STARTED, status="running")
    append_turn_event(tmp_path, "s", "t", EVENT_ASSISTANT_ITEM_COMMITTED, status="ready", payload={
        "kind": "tool_call", "phase": "tool_call", "status": "ready", "itemId": "tool-item",
        "callId": "call-1", "toolName": OBSERVE, "sessionId": "s", "turnId": "t"})
    append_turn_event(tmp_path, "s", "t", EVENT_TOOL_RESULT, status="done", tool_call_id="call-1", payload={
        "toolCall": {"callId": "call-1", "name": OBSERVE, "status": "done", "summary": result, "result": result}})
    events = load_turn_events(tmp_path, "s")
    monkeypatch.setattr(session_service, "_load_session_conversation_events_cached", lambda _session_id: events)
    items = session_service._build_session_turn_items_projection(session_id="s", turn_id="t", message_id="m", done=True)
    slimmed = session_service._slim_session_turn_items_for_window_payload(items)
    tool = next(item for item in slimmed if item["type"] == "tool_call")
    assert tool["toolName"] == OBSERVE
    assert tool["output"] == json.loads(result)["message"]
    request = service.get_state()["authorizationRequest"]
    assert request == {"id": request["id"], "agentId": "a", "sessionId": "s", "turnId": "t"}


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
