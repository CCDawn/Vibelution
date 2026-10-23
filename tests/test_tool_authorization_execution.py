from types import SimpleNamespace

import pytest

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


def test_call_budget_exhausted_hard_stops_without_running_tool(monkeypatch):
    """Quota exhaust must stop the turn — no more tool work, next turn resets count."""

    _runtime(monkeypatch, max_calls_per_turn=1)
    _install()
    context = tool_authorization_service.current_execution_authorization()
    assert context is not None
    context.max_calls_per_turn = 1
    context.call_count = 1
    executor = ToolExecutor()
    calls = []
    executor.register_tool("allowed_tool", lambda: calls.append("called") or "ok")

    result, action = executor.execute("allowed_tool", {}, tool_call_id="call-budget")

    assert "额度已用尽" in result
    assert "下一用户消息将重新统计额度" in result
    assert action == "tool_budget_exhausted"
    assert calls == []


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


def test_not_executable_denial_carries_decision_rule_id_and_reason(monkeypatch):
    """执行期拒绝必须可审计回决策级规则源：tool_not_executable 带 ruleId+reasonCode。"""

    _runtime(monkeypatch)
    _install()
    context = tool_authorization_service.current_execution_authorization()
    assert context is not None
    # 决策核真实产物会携带 denied（hidden_tool → not_assigned）；测试上下文补齐等价信息。
    context.deny_rules = (("hidden_tool", "not_assigned", "tool-agent-a:policy.allowedTools:not_assigned"),)
    recorded = []
    monkeypatch.setattr(
        "core.logging.tool_authorization_events.record_execution_denial_reason",
        lambda **kwargs: recorded.append(kwargs),
    )

    result = tool_authorization_service.authorize_tool_execution(
        tool_name="hidden_tool",
        tool_call_id="call-hidden",
    )

    assert result.allowed is False
    assert result.code == "tool_not_executable"
    assert result.reason_code == "not_assigned"
    assert result.rule_id == "tool-agent-a:policy.allowedTools:not_assigned"
    assert len(recorded) == 1
    fields = recorded[0]
    assert fields["tool_name"] == "hidden_tool"
    assert fields["gate_id"] == "tool_not_executable"
    assert fields["reason_code"] == "not_assigned"
    assert fields["rule_id"] == "tool-agent-a:policy.allowedTools:not_assigned"
    assert fields["agent_id"] == "agent-a"
    assert fields["turn_id"] == "turn-a"
    assert fields["decision_fingerprint"] == "decision-a"


def test_budget_denial_has_gate_id_without_decision_rule(monkeypatch):
    """额度闸拒绝的工具有自己的 gateId；决策级规则不适用时 reasonCode/ruleId 为空。"""

    _runtime(monkeypatch, max_calls_per_turn=1)
    _install()
    context = tool_authorization_service.current_execution_authorization()
    assert context is not None
    context.max_calls_per_turn = 1
    context.call_count = 1
    recorded = []
    monkeypatch.setattr(
        "core.logging.tool_authorization_events.record_execution_denial_reason",
        lambda **kwargs: recorded.append(kwargs),
    )

    result = tool_authorization_service.authorize_tool_execution(
        tool_name="allowed_tool",
        tool_call_id="call-over-budget",
    )

    assert result.allowed is False
    assert result.code == "call_budget_exhausted"
    assert result.reason_code == ""
    assert result.rule_id == ""
    assert recorded[0]["gate_id"] == "call_budget_exhausted"
    assert recorded[0]["reason_code"] == ""
    assert recorded[0]["rule_id"] == ""


def test_execution_denial_reason_event_is_recorded_via_scene_service(monkeypatch):
    """并行事件走 scene 服务，事件码为 tool.authorization.execution_denied_reason。"""

    _runtime(monkeypatch)
    _install()
    captured = []
    monkeypatch.setattr(
        "core.web.services.runtime_scene_service.record_runtime_scene_event",
        lambda *args, **kwargs: captured.append((args, kwargs)),
    )

    tool_authorization_service.authorize_tool_execution(
        tool_name="hidden_tool",
        tool_call_id="call-hidden",
    )

    reason_events = [item for item in captured if item[0][2] == "tool.authorization.execution_denied_reason"]
    assert len(reason_events) == 1
    args, kwargs = reason_events[0]
    assert args[0] == "tool_authorization"
    assert kwargs["outcome"] == "blocked"
    fields = kwargs["fields"]
    assert fields["toolName"] == "hidden_tool"
    assert fields["gateId"] == "tool_not_executable"
    assert fields["decisionFingerprintPresent"] is True


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


def test_delivery_writeback_tool_is_authorized_when_call_budget_exhausted(monkeypatch):
    """额度耗尽后交付类写回工具仍须放行且不占额度：否则整回合成果零交付。"""

    _runtime(
        monkeypatch,
        allowed_tools=("grep_search_tool", "source_collection_stage_writeback_tool", "research_stage_writeback_tool"),
        max_calls_per_turn=32,
    )
    _install(tools=("grep_search_tool", "source_collection_stage_writeback_tool", "research_stage_writeback_tool"))
    context = tool_authorization_service.current_execution_authorization()
    assert context is not None
    context.max_calls_per_turn = 32
    context.call_count = 32

    writeback = tool_authorization_service.authorize_tool_execution(
        tool_name="source_collection_stage_writeback_tool",
        tool_call_id="call-writeback",
    )
    suffix_tool = tool_authorization_service.authorize_tool_execution(
        tool_name="research_stage_writeback_tool",
        tool_call_id="call-suffix-writeback",
    )

    assert writeback.allowed is True
    assert writeback.code == "allowed"
    assert suffix_tool.allowed is True
    assert context.call_count == 32


def test_delivery_writeback_calls_have_their_own_turn_cap(monkeypatch):
    """豁免写回必须有独立上限：封死熔断后无限连发写回的消耗通道。"""

    _runtime(
        monkeypatch,
        allowed_tools=("source_collection_stage_writeback_tool",),
    )
    _install(tools=("source_collection_stage_writeback_tool",))
    context = tool_authorization_service.current_execution_authorization()
    assert context is not None
    cap = tool_authorization_service.MAX_DELIVERY_EXEMPT_CALLS_PER_TURN
    context.delivery_exempt_call_count = cap

    denied = tool_authorization_service.authorize_tool_execution(
        tool_name="source_collection_stage_writeback_tool",
        tool_call_id="call-writeback-over-cap",
    )

    assert denied.allowed is False
    assert denied.code == "delivery_writeback_budget_exhausted"
    # 先递增再判超限：第 cap+1 次调用被拒，计数停在 cap+1。
    assert context.delivery_exempt_call_count == cap + 1


def test_regular_research_tool_still_blocked_when_call_budget_exhausted(monkeypatch):
    """额度耗尽后普通探查工具仍被额度闸拒绝（保持原行为）。"""

    _runtime(monkeypatch, max_calls_per_turn=1)
    _install()
    context = tool_authorization_service.current_execution_authorization()
    assert context is not None
    context.max_calls_per_turn = 1
    context.call_count = 1

    blocked = tool_authorization_service.authorize_tool_execution(
        tool_name="allowed_tool",
        tool_call_id="call-over-budget",
    )

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


def test_string_false_delegation_flag_still_blocks_subagents(monkeypatch):
    for flag in ("false", "off", b"false"):
        monkeypatch.setattr(
            agent_directory_service,
            "current_agent_runtime",
            lambda current_flag=flag: {
                "agentId": "agent-a",
                "turnId": "turn-a",
                "agentConfigSnapshot": {
                    "agentId": "agent-a",
                    "configRevision": 3,
                    "configHash": "config-hash-a",
                },
                "permissionPreset": "request_approval",
                "toolPolicy": {"allowedTools": ["spawn_agent_tool"]},
                "delegationPolicy": {"allowSubagents": current_flag},
            },
        )
        _install(tools=("spawn_agent_tool",))
        executor = ToolExecutor()
        calls = []
        executor.register_tool("spawn_agent_tool", lambda **_kwargs: calls.append("called") or "unsafe")

        result, _ = executor.execute("spawn_agent_tool", {"goal": "probe"}, tool_call_id="call-delegate")

        assert "DelegationPolicy" in result, flag
        assert calls == []


def test_explicit_allow_subagents_still_authorizes(monkeypatch):
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
            "delegationPolicy": {"allowSubagents": True},
        },
    )
    _install(tools=("spawn_agent_tool",))

    result = tool_authorization_service.authorize_tool_execution(
        tool_name="spawn_agent_tool",
        tool_call_id="call-delegate",
        tool_args={"goal": "probe"},
    )

    assert result.allowed is True
    assert result.code in {"allowed", "allowed_terminal_wait"}


def test_invalid_config_revision_fails_closed_without_int_crash(monkeypatch):
    _runtime(monkeypatch)
    runtime = dict(agent_directory_service.current_agent_runtime())
    runtime["agentConfigSnapshot"] = dict(runtime["agentConfigSnapshot"], configRevision="bad")
    monkeypatch.setattr(agent_directory_service, "current_agent_runtime", lambda: runtime)

    with pytest.raises(tool_authorization_service.ToolAuthorizationContextError):
        _install()


def test_non_mapping_runtime_install_fails_closed_without_dict_crash(monkeypatch):
    monkeypatch.setattr(agent_directory_service, "current_agent_runtime", lambda: ["not-a-map"])

    with pytest.raises(tool_authorization_service.ToolAuthorizationContextError):
        _install()


def _write_scope_runtime(monkeypatch, *, tool_policy):
    """Runtime fixture carrying an explicit toolPolicy shape (writeScopes included)."""

    monkeypatch.setattr(
        agent_directory_service,
        "current_agent_runtime",
        lambda: {
            "agentId": "agent-planner",
            "turnId": "turn-planner",
            "agentConfigSnapshot": {
                "agentId": "agent-planner",
                "configRevision": 3,
                "configHash": "config-hash-planner",
            },
            "permissionPreset": "request_approval",
            "runtimePermissions": {
                "preset": "request_approval",
                "sandboxMode": "workspace_write",
                "approvalPolicy": "on_request",
                "approvalsReviewer": "user",
            },
            "toolPolicy": tool_policy,
        },
    )


def _install_real_write_scope_decision(*, tool_policy, write_tool):
    """Evaluate a real decision for one write-class tool and install it end to end.

    apply_diff_edit_tool 是规格点名的写类工具（file_write），被拒用例在
    executable 检查处即被拦、不会触及审批流；放行用例改用审批豁免白名单里的
    source_collection_stage_writeback_tool（risk=write），隔离 session 审批流。
    """

    from core.authorization.tool_policy_evaluator import evaluate_tool_policy, normalize_legacy_tool_policy
    from core.web.services import tool_catalog

    descriptor = tool_catalog.build_tool_descriptor(write_tool, args_schema={"type": "object"})
    policy = normalize_legacy_tool_policy(
        {"policyId": "tool-dev-planner", **tool_policy},
        registered_tool_names=(descriptor.name,),
    )
    grant = tool_authorization_service.TurnToolGrant(
        turn_id="turn-planner",
        source="team",
        allowed_capabilities=tuple(descriptor.capabilities),
        denied_tools=(),
        approval_mode="on_request",
    )
    decision = evaluate_tool_policy(
        agent_id="agent-planner",
        policy=policy,
        grant=grant,
        descriptors=(descriptor,),
        registry_version=1,
        registry_fingerprint="registry-planner",
        generated_at="2026-10-08T00:00:00Z",
    )
    tool_authorization_service.install_execution_authorization(
        SimpleNamespace(decision=decision)
    )
    return decision


def test_explicit_empty_write_scope_policy_blocks_write_tool_at_execution(monkeypatch):
    """决策层 WRITE_SCOPE_DENIED 落到执行层：tool_not_executable 且 ruleId 可审计回闸门。"""

    _write_scope_runtime(
        monkeypatch,
        tool_policy={
            "policyId": "tool-dev-planner",
            "allowedTools": ["apply_diff_edit_tool"],
            "preferredTools": [],
            "writeScopes": [],
        },
    )
    decision = _install_real_write_scope_decision(
        tool_policy={
            "allowedTools": ["apply_diff_edit_tool"],
            "preferredTools": [],
            "writeScopes": [],
        },
        write_tool="apply_diff_edit_tool",
    )
    reason = decision.deny_reason_for("apply_diff_edit_tool")
    assert reason is not None
    assert reason.rule_id == "tool-dev-planner:policy.writeScopes:write_scope_denied"

    executor = ToolExecutor()
    calls = []
    executor.register_tool("apply_diff_edit_tool", lambda: calls.append("called") or "unsafe")

    result, action = executor.execute("apply_diff_edit_tool", {}, tool_call_id="call-planner")

    assert "未被本回合授权执行" in result
    assert action is None
    assert calls == []
    execution = tool_authorization_service.authorize_tool_execution(
        tool_name="apply_diff_edit_tool",
        tool_call_id="call-planner",
    )
    assert execution.allowed is False
    assert execution.code == "tool_not_executable"
    assert execution.reason_code == "write_scope_denied"
    assert execution.rule_id == "tool-dev-planner:policy.writeScopes:write_scope_denied"


def test_undeclared_write_scope_policy_keeps_write_tool_executable(monkeypatch):
    """未声明 writeScopes 键的存量策略零影响：写工具照常放行执行。

    用审批豁免白名单内的写类工具（risk=write），避免测试依赖 session 审批流。
    """

    write_tool = "source_collection_stage_writeback_tool"
    _write_scope_runtime(
        monkeypatch,
        tool_policy={
            "policyId": "tool-dev-planner",
            "allowedTools": [write_tool],
            "preferredTools": [],
        },
    )
    decision = _install_real_write_scope_decision(
        tool_policy={
            "allowedTools": [write_tool],
            "preferredTools": [],
        },
        write_tool=write_tool,
    )
    assert decision.deny_reason_for(write_tool) is None

    executor = ToolExecutor()
    calls = []
    executor.register_tool(write_tool, lambda: calls.append("called") or "ok")

    result, action = executor.execute(write_tool, {}, tool_call_id="call-planner")

    assert result == "ok"
    assert calls == ["called"]
    assert action is None
    execution = tool_authorization_service.authorize_tool_execution(
        tool_name=write_tool,
        tool_call_id="call-planner",
    )
    assert execution.allowed is True


def _dedupe_runtime_fixture():
    """Runtime carrying explicit llm identity so the config fallback never fires."""

    return {
        "agentId": "agent-dedupe",
        "turnId": "turn-dedupe",
        "agent": {"agentId": "agent-dedupe"},
        "agentConfigSnapshot": {
            "agentId": "agent-dedupe",
            "configRevision": 11,
            "configHash": "config-hash-dedupe",
        },
        "permissionPreset": "request_approval",
        "llmModel": "dedupe-model",
        "llmProvider": "dedupe-provider",
        "toolPolicy": {
            "policyId": "tool-agent-dedupe",
            "allowedTools": ["grep_search_tool"],
            "preferredTools": [],
        },
    }


def _context_fields(context):
    from dataclasses import fields

    return {
        item.name: getattr(context, item.name)
        for item in fields(context)
        if item.name != "call_count_lock"
    }


def test_install_execution_authorization_with_bound_runtime_is_equivalent(monkeypatch):
    """TTFT 批六消重：传入 bind 阶段 runtime 与旧 getter 路径逐字段等价，且不再取 getter。"""

    from core.authorization.tool_authorization_service import resolve_enforced_authorization
    from core.orchestration.tool_authorization_binding import bind_authorization_runtime

    runtime_fixture = _dedupe_runtime_fixture()
    getter_calls = {"count": 0}

    def fake_getter():
        getter_calls["count"] += 1
        return dict(runtime_fixture)

    monkeypatch.setattr(agent_directory_service, "current_agent_runtime", fake_getter)
    report = resolve_enforced_authorization(
        runtime=dict(runtime_fixture),
        registry_payload={
            "registryVersion": 1,
            "registryFingerprint": "registry-dedupe",
            "descriptors": [
                {
                    "name": "grep_search_tool",
                    "enabled": True,
                    "capabilities": ["read"],
                    "risk": "read",
                    "approval": "never",
                    "aliases": [],
                }
            ],
            "tools": [
                {"name": "grep_search_tool", "enabled": True, "runtimeActive": True, "llmVisible": True}
            ],
        },
        generated_at="2026-10-21T00:00:00Z",
    )

    # 旧路径：自行取 current_agent_runtime。
    context_legacy = tool_authorization_service.install_execution_authorization(report)
    assert getter_calls["count"] == 1

    # 新路径：绑定层传入 bind 阶段已取到的 runtime，getter 不再被触碰。
    bound_runtime = bind_authorization_runtime(
        current_runtime=dict(runtime_fixture),
        turn_runtime={"agentId": "agent-dedupe", "turnId": "turn-dedupe"},
        agent_binding=None,
    )
    context_bound = tool_authorization_service.install_execution_authorization(report, runtime=bound_runtime)
    assert getter_calls["count"] == 1

    assert _context_fields(context_bound) == _context_fields(context_legacy)
    assert context_bound.model == "dedupe-model"
    assert context_bound.provider == "dedupe-provider"
    assert context_bound.max_calls_per_turn == context_legacy.max_calls_per_turn
    assert context_bound.budget_profile == context_legacy.budget_profile


def test_runtime_llm_identity_memo_reuses_config_fallback_per_snapshot(monkeypatch):
    """TTFT 批六消重：config get_profile 回退按快照身份 memo，同身份只解析一次。"""

    from config import settings as config_settings

    tool_authorization_service.clear_llm_identity_memo()
    calls = {"get_profile": 0}

    class _FakeProvider:
        provider_id = "memo-provider"

    class _FakeProfile:
        model = "memo-model"
        profile_id = "memo-profile"
        provider = _FakeProvider()

    class _FakeLLM:
        def get_profile(self, role="primary"):
            calls["get_profile"] += 1
            return _FakeProfile()

    class _FakeConfig:
        llm = _FakeLLM()

    monkeypatch.setattr(config_settings, "get_config", lambda: _FakeConfig())

    snapshot = {"agentConfigSnapshot": {"configRevision": 7, "configHash": "hash-memo"}}
    first = tool_authorization_service._runtime_llm_identity(dict(snapshot))
    second = tool_authorization_service._runtime_llm_identity(dict(snapshot))
    assert first == ("memo-model", "memo-provider", "memo-profile")
    assert second == first
    assert calls["get_profile"] == 1

    # 快照身份推进 → 旧 memo 不复用，重新解析。
    bumped = {"agentConfigSnapshot": {"configRevision": 8, "configHash": "hash-memo-2"}}
    assert tool_authorization_service._runtime_llm_identity(dict(bumped)) == first
    assert calls["get_profile"] == 2

    # 无可信快照身份（revision<1）→ 不 memo，逐次解析。
    untrusted = {"agentConfigSnapshot": {"configRevision": 0, "configHash": ""}}
    assert tool_authorization_service._runtime_llm_identity(dict(untrusted)) == first
    assert tool_authorization_service._runtime_llm_identity(dict(untrusted)) == first
    assert calls["get_profile"] == 4

    tool_authorization_service.clear_llm_identity_memo()


def _override_runtime(
    *,
    session_id="session-override",
    agent_id="agent-override",
    revision=5,
    config_hash="hash-override",
):
    runtime = {
        "agentId": agent_id,
        "turnId": "turn-override",
        "sessionId": session_id,
        "agent": {"agentId": agent_id},
        "agentConfigSnapshot": {
            "agentId": agent_id,
            "configRevision": revision,
            "configHash": config_hash,
        },
        "permissionPreset": "request_approval",
        "llmModel": "override-model",
        "llmProvider": "override-provider",
        "toolPolicy": {"policyId": "tool-agent-override", "maxCallsPerTurn": 32},
    }
    return runtime


def test_session_override_memo_reuses_resolution_per_snapshot_identity(monkeypatch):
    """TTFT 批七：session override 查询按快照身份 memo，同身份只走一次 store 读。"""

    from core.orchestration import session_budget_resolve

    tool_authorization_service.clear_session_override_memo()
    calls = {"resolve": 0}

    def fake_resolve(session_id):
        calls["resolve"] += 1
        return session_budget_resolve.SessionBudgetParameters(maxCallsPerTurn=48)

    monkeypatch.setattr(session_budget_resolve, "get_session_budget_parameters", fake_resolve)

    runtime = _override_runtime()
    assert tool_authorization_service._session_override_max_calls_per_turn(dict(runtime)) == 48
    assert tool_authorization_service._session_override_max_calls_per_turn(dict(runtime)) == 48
    assert calls["resolve"] == 1

    # 快照身份推进（override 写路径以 Agent configRevision CAS 守护）→ 重新解析。
    bumped = _override_runtime(revision=6, config_hash="hash-override-2")
    assert tool_authorization_service._session_override_max_calls_per_turn(dict(bumped)) == 48
    assert calls["resolve"] == 2

    # agent 变化（session 重绑）→ 新键，重新解析。
    rebound = _override_runtime(agent_id="agent-override-2")
    assert tool_authorization_service._session_override_max_calls_per_turn(dict(rebound)) == 48
    assert calls["resolve"] == 3

    # 无可信快照身份（revision<1 或缺 hash）→ 不 memo，逐次解析。
    untrusted = _override_runtime(revision=0, config_hash="")
    assert tool_authorization_service._session_override_max_calls_per_turn(dict(untrusted)) == 48
    assert tool_authorization_service._session_override_max_calls_per_turn(dict(untrusted)) == 48
    assert calls["resolve"] == 5

    # 清空后同键重新解析。
    tool_authorization_service.clear_session_override_memo()
    assert tool_authorization_service._session_override_max_calls_per_turn(dict(runtime)) == 48
    assert calls["resolve"] == 6

    tool_authorization_service.clear_session_override_memo()


def test_session_override_memo_keeps_unset_result_negative(monkeypatch):
    """无 override 的会话（最常见的每轮 I/O 来源）同样命中 memo，返回值不变。"""

    from core.orchestration import session_budget_resolve

    tool_authorization_service.clear_session_override_memo()
    calls = {"resolve": 0}

    def fake_resolve(session_id):
        calls["resolve"] += 1
        return None

    monkeypatch.setattr(session_budget_resolve, "get_session_budget_parameters", fake_resolve)

    runtime = _override_runtime(session_id="session-unset")
    assert tool_authorization_service._session_override_max_calls_per_turn(dict(runtime)) is None
    assert tool_authorization_service._session_override_max_calls_per_turn(dict(runtime)) is None
    assert calls["resolve"] == 1

    tool_authorization_service.clear_session_override_memo()


def test_session_override_memo_distinguishes_explicit_unlimited_from_unset(monkeypatch):
    from core.orchestration import session_budget_resolve

    calls = []

    def fake_resolve(session_id):
        calls.append(session_id)
        return SimpleNamespace(maxCallsPerTurn=0) if session_id == "session-unlimited" else None

    monkeypatch.setattr(session_budget_resolve, "get_session_budget_parameters", fake_resolve)
    tool_authorization_service.clear_session_override_memo()
    try:
        for _ in range(2):
            assert tool_authorization_service._session_override_max_calls_per_turn(
                _override_runtime(session_id="session-unlimited")
            ) == 0
            assert tool_authorization_service._session_override_max_calls_per_turn(
                _override_runtime(session_id="session-unset")
            ) is None
        assert calls == ["session-unlimited", "session-unset"]
    finally:
        tool_authorization_service.clear_session_override_memo()


def test_install_execution_authorization_records_sub_anchor_timing():
    """TTFT 批七：install 内部细分锚点写入线程局部，供绑定层并入 timing 事件。"""

    runtime = _override_runtime()
    tool_authorization_service.clear_execution_authorization()
    context = tool_authorization_service.install_execution_authorization(
        SimpleNamespace(
            decision=SimpleNamespace(
                agent_id=runtime["agentId"],
                turn_id=runtime["turnId"],
                decision_fingerprint="decision-timing",
                executable_tools=("grep_search_tool",),
            )
        ),
        runtime=dict(runtime),
    )
    assert context.max_calls_per_turn == 32

    timing = tool_authorization_service.last_install_execution_timing()
    assert timing is not None
    assert set(timing) == {"identityMs", "maxCallsMs", "installCoreMs"}
    for value in timing.values():
        assert isinstance(value, int) and value >= 0

    tool_authorization_service.clear_execution_authorization()
