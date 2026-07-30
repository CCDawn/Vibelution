from types import SimpleNamespace

from core.authorization import tool_authorization_service
from core.infrastructure import tool_executor as tool_executor_module
from core.infrastructure.tool_executor import ToolExecutor
from core.web.services import agent_directory_service


def _install(*, agent_id="agent-a", turn_id="turn-a", tools=("allowed_tool",)):
    report = SimpleNamespace(
        decision=SimpleNamespace(
            agent_id=agent_id,
            turn_id=turn_id,
            decision_fingerprint="decision-a",
            executable_tools=tools,
        )
    )
    tool_authorization_service.install_execution_authorization(report)


def _runtime(
    monkeypatch,
    *,
    agent_id="agent-a",
    turn_id="turn-a",
    allowed_tools=("allowed_tool",),
    max_calls_per_turn=0,
):
    monkeypatch.setattr(
        agent_directory_service,
        "current_agent_runtime",
        lambda: {
            "agentId": agent_id,
            "turnId": turn_id,
            "agentConfigSnapshot": {
                "agentId": agent_id,
                "configRevision": 3,
                "configHash": "config-hash-a",
            },
            "permissionPreset": "request_approval",
            "runtimePermissions": {
                "preset": "request_approval",
                "sandboxMode": "workspace_write",
                "approvalPolicy": "on_request",
                "approvalsReviewer": "user",
            },
            "toolPolicy": {
                "policyId": "tool-agent-a",
                "allowedTools": list(allowed_tools),
                "preferredTools": [],
                "blockedTools": [],
                "maxCallsPerTurn": max_calls_per_turn,
            },
        },
    )


def test_authorized_tool_reaches_implementation(monkeypatch):
    _runtime(monkeypatch)
    _install()
    executor = ToolExecutor()
    calls = []
    executor.register_tool("allowed_tool", lambda: calls.append("called") or "ok")

    result, action = executor.execute("allowed_tool", {}, tool_call_id="call-a")

    assert result == "ok"
    assert action is None
    assert calls == ["called"]


def test_unassigned_tool_is_blocked_before_implementation(monkeypatch):
    _runtime(monkeypatch)
    _install()
    executor = ToolExecutor()
    calls = []
    executor.register_tool("hidden_tool", lambda: calls.append("called") or "unsafe")

    result, action = executor.execute("hidden_tool", {}, tool_call_id="call-hidden")

    assert "未被本回合授权执行" in result
    assert action is None
    assert calls == []


def test_agent_tool_call_without_call_id_is_blocked(monkeypatch):
    _runtime(monkeypatch)
    _install()
    executor = ToolExecutor()
    calls = []
    executor.register_tool("allowed_tool", lambda: calls.append("called") or "unsafe")

    result, _action = executor.execute("allowed_tool", {})

    assert "缺少 callId" in result
    assert calls == []


def test_stale_turn_authorization_is_blocked(monkeypatch):
    _runtime(monkeypatch, turn_id="turn-new")
    _install(turn_id="turn-old")
    executor = ToolExecutor()
    calls = []
    executor.register_tool("allowed_tool", lambda: calls.append("called") or "unsafe")

    result, _action = executor.execute("allowed_tool", {}, tool_call_id="call-a")

    assert "不属于当前回合" in result
    assert calls == []


def test_stale_agent_config_authorization_is_blocked(monkeypatch):
    _runtime(monkeypatch)
    _install()
    _runtime(monkeypatch)
    runtime = agent_directory_service.current_agent_runtime()
    runtime["agentConfigSnapshot"]["configRevision"] = 4
    runtime["agentConfigSnapshot"]["configHash"] = "config-hash-b"
    monkeypatch.setattr(
        agent_directory_service,
        "current_agent_runtime",
        lambda: runtime,
    )
    executor = ToolExecutor()
    calls = []
    executor.register_tool("allowed_tool", lambda: calls.append("called") or "unsafe")

    result, _action = executor.execute(
        "allowed_tool",
        {},
        tool_call_id="call-a",
    )

    assert "配置快照不一致" in result
    assert calls == []


def test_missing_decision_in_agent_context_fails_closed(monkeypatch):
    _runtime(monkeypatch)
    tool_authorization_service.clear_execution_authorization()
    executor = ToolExecutor()
    calls = []
    executor.register_tool("allowed_tool", lambda: calls.append("called") or "unsafe")

    result, _action = executor.execute("allowed_tool", {}, tool_call_id="call-a")

    assert "缺少可信工具授权决策" in result
    assert calls == []


def test_non_agent_system_execution_keeps_existing_executor_contract(monkeypatch):
    monkeypatch.setattr(agent_directory_service, "current_agent_runtime", lambda: {})
    tool_authorization_service.clear_execution_authorization()
    executor = ToolExecutor()
    executor.register_tool("system_tool", lambda: "ok")

    result, action = executor.execute("system_tool", {})

    assert result == "ok"
    assert action is None


def test_execution_decisions_emit_bounded_audit_events(monkeypatch):
    _runtime(monkeypatch)
    _install()
    events = []
    monkeypatch.setattr(
        tool_executor_module,
        "_record_tool_scene_event",
        lambda *args, **kwargs: events.append((args, kwargs)),
    )
    executor = ToolExecutor()
    executor.register_tool("allowed_tool", lambda: "ok")
    executor.register_tool("hidden_tool", lambda: "unsafe")

    executor.execute("allowed_tool", {}, tool_call_id="call-a")
    executor.execute("hidden_tool", {}, tool_call_id="call-b")

    authorization_events = [item for item in events if item[0][1].startswith("tool.authorization.execution_")]
    assert [item[0][1] for item in authorization_events] == [
        "tool.authorization.execution_allowed",
        "tool.authorization.execution_denied",
    ]
    assert authorization_events[1][1]["fields"]["code"] == "tool_not_executable"


def test_call_budget_is_shared_by_execution_authorization(monkeypatch):
    _runtime(monkeypatch, max_calls_per_turn=1)
    _install()
    executor = ToolExecutor()
    calls = []
    executor.register_tool("allowed_tool", lambda: calls.append("called") or "ok")

    first, _ = executor.execute("allowed_tool", {}, tool_call_id="call-1")
    second, _ = executor.execute("allowed_tool", {}, tool_call_id="call-2")

    assert first == "ok"
    assert "调用额度已用尽" in second
    assert calls == ["called"]


def test_empty_terminal_wait_does_not_consume_general_call_budget(monkeypatch):
    _runtime(monkeypatch, allowed_tools=("exec_command", "write_stdin"), max_calls_per_turn=1)
    _install(tools=("exec_command", "write_stdin"))

    command = tool_authorization_service.authorize_tool_execution(
        tool_name="exec_command",
        tool_call_id="call-command",
        tool_args={"cmd": "echo ready"},
    )
    terminal_wait = tool_authorization_service.authorize_tool_execution(
        tool_name="write_stdin",
        tool_call_id="call-wait",
        tool_args={"session_id": "sandbox-a", "chars": ""},
    )
    blocked = tool_authorization_service.authorize_tool_execution(
        tool_name="exec_command",
        tool_call_id="call-over-budget",
        tool_args={"cmd": "echo again"},
    )

    assert command.allowed is True
    assert terminal_wait.allowed is True
    assert terminal_wait.code == "allowed_terminal_wait"
    assert blocked.allowed is False
    assert blocked.code == "call_budget_exhausted"


def test_empty_terminal_wait_has_a_bounded_per_session_limit(monkeypatch):
    _runtime(monkeypatch, allowed_tools=("write_stdin",), max_calls_per_turn=1)
    _install(tools=("write_stdin",))

    results = [
        tool_authorization_service.authorize_tool_execution(
            tool_name="write_stdin",
            tool_call_id=f"call-wait-{index}",
            tool_args={"session_id": "sandbox-a", "chars": ""},
        )
        for index in range(9)
    ]

    assert all(result.allowed for result in results[:8])
    assert results[-1].allowed is False
    assert results[-1].code == "terminal_wait_budget_exhausted"


def test_empty_terminal_wait_has_a_turn_bound_across_session_ids(monkeypatch):
    _runtime(monkeypatch, allowed_tools=("write_stdin",), max_calls_per_turn=1)
    _install(tools=("write_stdin",))

    results = [
        tool_authorization_service.authorize_tool_execution(
            tool_name="write_stdin",
            tool_call_id=f"call-wait-{index}",
            tool_args={"session_id": f"sandbox-{index}", "chars": ""},
        )
        for index in range(17)
    ]

    assert all(result.allowed for result in results[:16])
    assert results[-1].allowed is False
    assert results[-1].code == "terminal_wait_turn_budget_exhausted"


def test_delegation_constraint_is_enforced_by_canonical_authorization(monkeypatch):
    _runtime(monkeypatch, allowed_tools=("spawn_agent_tool",))
    monkeypatch.setattr(
        agent_directory_service,
        "current_agent_runtime",
        lambda: {
            "agentId": "agent-a",
            "turnId": "turn-a",
            "agentConfigSnapshot": {
                "agentId": "agent-a",
                "configRevision": 3,
                "configHash": "config-hash-a",
            },
            "permissionPreset": "request_approval",
            "toolPolicy": {"allowedTools": ["spawn_agent_tool"]},
            "delegationPolicy": {"allowSubagents": False},
        },
    )
    _install(tools=("spawn_agent_tool",))
    executor = ToolExecutor()
    calls = []
    executor.register_tool("spawn_agent_tool", lambda **_kwargs: calls.append("called") or "unsafe")

    result, _ = executor.execute("spawn_agent_tool", {"goal": "probe"}, tool_call_id="call-delegate")

    assert "DelegationPolicy" in result
    assert "关闭子 agent 派发权限" in result
    assert calls == []
