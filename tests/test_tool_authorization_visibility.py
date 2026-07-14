from types import SimpleNamespace

import pytest

import agent as agent_module
from agent import SelfEvolvingAgent
from core.authorization.tool_authorization_service import (
    ToolAuthorizationContextError,
    resolve_enforced_authorization,
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
