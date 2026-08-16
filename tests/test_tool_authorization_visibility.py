from types import SimpleNamespace

import pytest

import agent as agent_module
from agent import SelfEvolvingAgent
from core.authorization.tool_authorization_service import (
    ToolAuthorizationContextError,
    resolve_enforced_authorization,
)
from core.orchestration.tool_authorization_binding import (
    bind_authorization_runtime,
    guard_restart_focus_tool,
    hidden_tool_call_message,
    is_tool_visible_to_agent,
    materialize_authorized_tools,
    restart_allowed_tool_names,
)


def _tool(name: str):
    return SimpleNamespace(name=name)


def test_enforced_authorization_requires_agent_and_turn_identity():
    with pytest.raises(ToolAuthorizationContextError, match="agentId"):
        resolve_enforced_authorization(runtime={})

    with pytest.raises(ToolAuthorizationContextError, match="turnId"):
        resolve_enforced_authorization(
            runtime={"agentId": "agent-a"},
        )


def test_bind_authorization_runtime_fills_identity_without_policy():
    runtime = bind_authorization_runtime(
        current_runtime={},
        turn_runtime={"runId": "turn-a", "agentId": "agent-a", "mode": "chat"},
        agent_binding={"directSessionId": "session-a"},
    )
    assert runtime["agentId"] == "agent-a"
    assert runtime["turnId"] == "turn-a"
    assert runtime["runId"] == "turn-a"
    assert runtime["mode"] == "chat"


def test_adapter_materialize_and_visibility_match_agent_wrappers():
    report = SimpleNamespace(
        decision=SimpleNamespace(visible_tools=("read_file_tool",)),
    )
    tools = [_tool("read_file_tool"), _tool("write_file_tool")]
    assert [tool.name for tool in materialize_authorized_tools(tools, report)] == ["read_file_tool"]
    assert is_tool_visible_to_agent("read_file_tool", {"read_file_tool"}) is True
    assert is_tool_visible_to_agent("spawn_agent_tool", {"read_file_tool"}) is False
    assert "未暴露给当前 Agent" in hidden_tool_call_message("spawn_agent_tool")
    assert "trigger_self_restart_tool" in restart_allowed_tool_names()
    assert guard_restart_focus_tool("apply_diff_edit_tool", restart_focus=True)
    assert guard_restart_focus_tool("trigger_self_restart_tool", restart_focus=True) is None
    assert guard_restart_focus_tool("apply_diff_edit_tool", restart_focus=False) is None


def test_authorized_surface_materializes_only_canonical_visible_tools():
    report = SimpleNamespace(
        decision=SimpleNamespace(
            visible_tools=("read_file_tool",),
            decision_fingerprint="decision-1",
        )
    )

    visible = SelfEvolvingAgent._materialize_authorized_tools(
        [_tool("read_file_tool"), _tool("write_file_tool")],
        report,
    )

    assert [tool.name for tool in visible] == ["read_file_tool"]


def test_authorized_surface_fails_closed_without_decision():
    assert SelfEvolvingAgent._materialize_authorized_tools([_tool("read_file_tool")], None) == []


def test_authorization_resolution_failure_records_diagnostic_and_returns_no_report(monkeypatch):
    from core.authorization import tool_authorization_service
    from core.logging import tool_authorization_events
    from core.web.services import agent_directory_service

    failures = []
    monkeypatch.setattr(
        agent_directory_service,
        "current_agent_runtime",
        lambda: {"agentId": "agent-a", "turnId": "turn-a"},
    )
    monkeypatch.setattr(
        tool_authorization_service,
        "resolve_enforced_authorization",
        lambda **_kwargs: (_ for _ in ()).throw(ToolAuthorizationContextError("missing policy")),
    )
    monkeypatch.setattr(
        tool_authorization_events,
        "record_authorization_failure",
        lambda **kwargs: failures.append(kwargs),
    )

    instance = SelfEvolvingAgent.__new__(SelfEvolvingAgent)
    instance.runtime_agent_binding = {"agentId": "agent-a"}
    report = instance._resolve_tool_authorization([_tool("read_file_tool")])

    assert report is None
    assert len(failures) == 1
    assert failures[0]["runtime"]["agentId"] == "agent-a"


def test_invocation_context_carries_authorization_decision_fingerprint(monkeypatch):
    instance = SelfEvolvingAgent.__new__(SelfEvolvingAgent)
    instance.runtime_agent_binding = {"agentId": "agent-a", "directSessionId": "session-a"}
    instance._tool_authorization_decision_fingerprint = "decision-1"
    instance._get_mode_policy = lambda: SimpleNamespace(
        mode=SimpleNamespace(value="chat"),
        orchestrator_kind="chat",
    )
    monkeypatch.setattr(
        agent_module,
        "_turn_runtime_from_env",
        lambda: {
            "runId": "turn-a",
            "sessionId": "session-a",
            "agentId": "agent-a",
            "llmSlot": "dialogue",
        },
    )
    monkeypatch.setattr(agent_module, "current_llm_status_context", lambda: {})

    context = instance._build_llm_invocation_context()

    assert context.metadata["toolAuthorizationDecisionFingerprint"] == "decision-1"
    assert context.metadata["turnId"] == "turn-a"


def test_bind_authorization_runtime_fills_empty_run_id_and_rejects_non_mapping():
    runtime = bind_authorization_runtime(
        current_runtime={"agentId": "agent-a", "runId": "", "mode": ""},
        turn_runtime={"runId": "turn-b", "mode": "chat"},
        agent_binding="not-a-mapping",
    )
    assert runtime["agentId"] == "agent-a"
    assert runtime["turnId"] == "turn-b"
    assert runtime["runId"] == "turn-b"
    assert runtime["mode"] == "chat"

    runtime = bind_authorization_runtime(
        current_runtime="broken",
        turn_runtime={"runId": "turn-c", "agentId": "agent-c", "mode": "agent"},
        agent_binding=None,
    )
    assert runtime["agentId"] == "agent-c"
    assert runtime["turnId"] == "turn-c"


def test_visibility_treats_string_names_as_one_tool_not_characters():
    assert is_tool_visible_to_agent("read_file_tool", "read_file_tool") is True
    assert is_tool_visible_to_agent("read_file_tool", "write_file_tool") is False
    report = SimpleNamespace(decision=SimpleNamespace(visible_tools="read_file_tool"))
    tools = [_tool("read_file_tool"), _tool("write_file_tool")]
    assert [tool.name for tool in materialize_authorized_tools(tools, report)] == ["read_file_tool"]
    assert materialize_authorized_tools(7, report) == []
    assert is_tool_visible_to_agent("read_file_tool", [_tool("read_file_tool")]) is True


def test_binding_coerces_bytes_json_and_string_false_restart_focus():
    runtime = bind_authorization_runtime(
        current_runtime={"agentId": b"agent-a", "runId": b"", "mode": b""},
        turn_runtime={"runId": b"turn-b", "mode": b"chat"},
        agent_binding=None,
    )
    assert runtime["agentId"] == "agent-a"
    assert runtime["turnId"] == "turn-b"
    assert runtime["runId"] == "turn-b"
    assert runtime["mode"] == "chat"

    runtime = bind_authorization_runtime(
        current_runtime='{"agent_id": "agent-json"}',
        turn_runtime='{"run_id": "turn-json", "mode": "chat"}',
        agent_binding=None,
    )
    assert runtime["agentId"] == "agent-json"
    assert runtime["turnId"] == "turn-json"
    assert runtime["runId"] == "turn-json"

    report = SimpleNamespace(decision=SimpleNamespace(visible_tools=b'["read_file_tool"]'))
    tools = [_tool("read_file_tool"), _tool("write_file_tool")]
    assert [tool.name for tool in materialize_authorized_tools(tools, report)] == ["read_file_tool"]
    assert is_tool_visible_to_agent(b"read_file_tool", ["read_file_tool"]) is True
    assert "read_file_tool" in hidden_tool_call_message(b"read_file_tool")
    assert guard_restart_focus_tool("apply_diff_edit_tool", restart_focus="false") is None
    assert guard_restart_focus_tool("apply_diff_edit_tool", restart_focus=b"off") is None
    assert guard_restart_focus_tool(b"trigger_self_restart_tool", restart_focus="true") is None
    assert guard_restart_focus_tool("apply_diff_edit_tool", restart_focus="true")
    runtime = bind_authorization_runtime(
        current_runtime=memoryview(b'{"agent_id":"agent-view"}'),
        turn_runtime=bytearray(b'{"run_id":"turn-view","mode":"chat"}'),
        agent_binding=None,
    )
    assert runtime["agentId"] == "agent-view"
    assert runtime["runId"] == "turn-view"
    assert is_tool_visible_to_agent(
        memoryview(b"read_file_tool"),
        bytearray(b'["read_file_tool"]'),
    ) is True
    assert is_tool_visible_to_agent(
        "read_file_tool",
        {"read_file_tool": bytearray(b"false"), "write_file_tool": "true"},
    ) is False
    assert is_tool_visible_to_agent(
        "write_file_tool",
        {"read_file_tool": bytearray(b"false"), "write_file_tool": "true"},
    ) is True
    assert guard_restart_focus_tool("apply_diff_edit_tool", restart_focus=bytearray(b"false")) is None
    assert materialize_authorized_tools("read_file_tool", report) == []
