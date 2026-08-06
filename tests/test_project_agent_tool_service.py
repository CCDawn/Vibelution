from __future__ import annotations

import json

import pytest

from core.external_agent.mcp_stdio_server import TOOLS, _call_tool, _dispatch
from core.external_agent.project_agent_tool_service import (
    ProjectAgentToolError,
    list_project_agents_for_tool,
    run_project_agent_tool,
)


def test_list_project_agents_for_tool_shapes_summary() -> None:
    def _list(**_kwargs):
        return [
            {
                "agentId": "a2",
                "agentCode": "reviewer",
                "displayName": "Reviewer",
                "status": "active",
                "permissionPreset": "auto_review",
            },
            {
                "agentId": "a1",
                "agentCode": "coder",
                "displayName": "Coder",
                "status": "active",
            },
        ]

    payload = list_project_agents_for_tool(list_agents_fn=_list)
    assert payload["status"] == "ok"
    assert payload["count"] == 2
    assert payload["agents"][0]["displayName"] == "Coder"
    assert payload["agents"][1]["agentId"] == "a2"


def test_run_project_agent_tool_sync_happy_path() -> None:
    created: dict[str, object] = {}
    submitted: dict[str, object] = {}
    polls = {"n": 0}

    def _get_agent(agent_id: str, **_kwargs):
        if agent_id == "agent-1":
            return {"agentId": "agent-1", "agentCode": "coder", "displayName": "Coder"}
        return None

    def _create_session(**kwargs):
        created.update(kwargs)
        return {"sessionId": "sess-1"}

    def _submit(session_id: str, content: str, **kwargs):
        submitted.update({"sessionId": session_id, "content": content, **kwargs})
        return {"turnId": "turn-1"}

    def _detail(session_id: str, **_kwargs):
        polls["n"] += 1
        if polls["n"] < 2:
            return {"status": "running", "activeTurnId": "turn-1", "messages": []}
        return {
            "status": "ready",
            "activeTurnId": "",
            "messages": [
                {"role": "user", "content": "do the thing"},
                {"role": "assistant", "content": "done: thing complete"},
            ],
        }

    result = run_project_agent_tool(
        agent_id="agent-1",
        task="do the thing",
        timeout_seconds=10,
        create_session_fn=_create_session,
        submit_message_fn=_submit,
        get_detail_fn=_detail,
        get_agent_fn=_get_agent,
        list_agents_fn=lambda **_k: [],
        list_approvals_fn=lambda *_a, **_k: [],
        sleep_fn=lambda _s: None,
        monotonic_fn=lambda: 0.0 if polls["n"] < 5 else 0.0,
    )
    assert created["agent_id"] == "agent-1"
    assert submitted["content"] == "do the thing"
    assert result["status"] == "ok"
    assert result["sessionId"] == "sess-1"
    assert result["reply"] == "done: thing complete"
    assert result["permissionMode"] == "auto_review"


def test_run_project_agent_tool_requires_task() -> None:
    with pytest.raises(ProjectAgentToolError):
        run_project_agent_tool(agent_id="a", task="  ")


def test_run_project_agent_tool_auto_accepts_approvals() -> None:
    polls = {"n": 0}
    resolved: list[tuple[str, str, str]] = []

    def _get_agent(agent_id: str, **_kwargs):
        return {"agentId": agent_id, "displayName": "X"}

    def _detail(session_id: str, **_kwargs):
        polls["n"] += 1
        if polls["n"] == 1:
            return {"status": "running", "activeTurnId": "t1", "messages": []}
        return {
            "status": "ready",
            "messages": [{"role": "assistant", "content": "ok"}],
        }

    def _list_approvals(session_id: str, status: str = ""):
        if polls["n"] == 1:
            return [{"requestId": "req-1", "status": "pending"}]
        return []

    def _resolve(session_id: str, request_id: str, decision: str):
        resolved.append((session_id, request_id, decision))
        return {"status": "resolved"}

    result = run_project_agent_tool(
        agent_id="agent-1",
        task="hi",
        create_session_fn=lambda **_k: {"sessionId": "s1"},
        submit_message_fn=lambda *_a, **_k: {"turnId": "t1"},
        get_detail_fn=_detail,
        get_agent_fn=_get_agent,
        list_agents_fn=lambda **_k: [],
        list_approvals_fn=_list_approvals,
        resolve_approval_fn=_resolve,
        sleep_fn=lambda _s: None,
        monotonic_fn=lambda: 0.0,
    )
    assert result["status"] == "ok"
    assert resolved == [("s1", "req-1", "accept")]
    assert result["approvalAutoAccepted"] >= 1


def test_mcp_tools_list_and_call_list_agents() -> None:
    assert {tool["name"] for tool in TOOLS} == {"list_project_agents", "run_project_agent"}
    listed = _dispatch({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert listed is not None
    assert "result" in listed
    assert len(listed["result"]["tools"]) == 2


def test_mcp_initialize() -> None:
    response = _dispatch(
        {
            "jsonrpc": "2.0",
            "id": 0,
            "method": "initialize",
            "params": {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "test"}},
        }
    )
    assert response is not None
    assert response["result"]["serverInfo"]["name"] == "vibelution-project-agent"


def test_mcp_call_tool_invalid_argument() -> None:
    with pytest.raises(ProjectAgentToolError):
        _call_tool("run_project_agent", {"task": ""})
