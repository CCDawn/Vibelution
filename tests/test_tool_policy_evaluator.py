import json
from pathlib import Path

import pytest

from core.authorization import (
    AgentIdentityMissingError,
    ToolDenyCode,
    ToolPolicyInvalidError,
    ToolPolicyMissingError,
    ToolRegistryMissingError,
    TurnToolGrant,
    TurnToolGrantMissingError,
    authorization_cache_key,
    evaluate_tool_policy,
    normalize_legacy_tool_policy,
)
from core.web.services import agent_directory_service, agent_role_tool_profile_service, tool_catalog


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "tool_authorization" / "agent_policy_baselines.json"


def _descriptors():
    return (
        tool_catalog.build_tool_descriptor("grep_search_tool", args_schema={"type": "object"}),
        tool_catalog.build_tool_descriptor("web_search_tool", args_schema={"type": "object"}),
        tool_catalog.build_tool_descriptor("apply_patch_tool", args_schema={"type": "object"}),
    )


def _policy(raw):
    return normalize_legacy_tool_policy(
        {"policyId": "policy-test", **raw},
        registered_tool_names=[descriptor.name for descriptor in _descriptors()],
    )


def _grant(*, capabilities=None, denied=(), approval_mode="on_request"):
    all_capabilities = sorted({capability for descriptor in _descriptors() for capability in descriptor.capabilities})
    return TurnToolGrant(
        turn_id="turn-1",
        source="session",
        allowed_capabilities=tuple(all_capabilities if capabilities is None else capabilities),
        denied_tools=tuple(denied),
        approval_mode=approval_mode,
    )


def _evaluate(policy, grant, *, available=None):
    return evaluate_tool_policy(
        agent_id="agent-1",
        policy=policy,
        grant=grant,
        descriptors=_descriptors(),
        registry_version=1,
        registry_fingerprint="registry-1",
        available_tool_names=available,
        generated_at="2026-07-14T00:00:00Z",
    )


def test_deny_first_evaluator_keeps_blocked_and_unassigned_tools_invisible():
    policy = _policy(
        {
            "allowedTools": ["grep_search_tool", "web_search_tool"],
            "blockedTools": ["web_search_tool"],
            "preferredTools": ["grep_search_tool"],
            "networkAccess": "full",
            "mutationAccess": "workspace",
        }
    )

    decision = _evaluate(policy, _grant())

    assert decision.visible_tools == ("grep_search_tool",)
    assert decision.executable_tools == ("grep_search_tool",)
    assert decision.preferred_tools == ("grep_search_tool",)
    assert decision.deny_reason_for("web_search_tool").code is ToolDenyCode.AGENT_BLOCKED
    assert decision.deny_reason_for("apply_patch_tool").code is ToolDenyCode.NOT_ASSIGNED


def test_deny_reasons_carry_rule_id_and_gate_id_for_audit():
    policy = _policy(
        {
            "allowedTools": ["grep_search_tool", "web_search_tool"],
            "blockedTools": ["web_search_tool"],
            "preferredTools": ["grep_search_tool"],
            "networkAccess": "none",
            "mutationAccess": "none",
        }
    )

    decision = _evaluate(policy, _grant())

    blocked = decision.deny_reason_for("web_search_tool")
    unassigned = decision.deny_reason_for("apply_patch_tool")
    # grep_search_tool 保持可见可执行；web 被 blocked、apply_patch 未分配。
    assert decision.deny_reason_for("grep_search_tool") is None
    assert blocked.gate_id == "policy.blockedTools"
    assert blocked.rule_id == "policy-test:policy.blockedTools:agent_blocked"
    assert unassigned.gate_id == "policy.allowedTools"
    assert unassigned.rule_id == "policy-test:policy.allowedTools:not_assigned"
    projection = decision.public_projection()["denied"]
    assert projection["web_search_tool"]["ruleId"] == blocked.rule_id
    assert projection["apply_patch_tool"]["ruleId"] == unassigned.rule_id
    # 同一 deny code 由不同规则源触发时 ruleId 必须可区分。
    assert blocked.rule_id != unassigned.rule_id


def test_execution_deny_reasons_carry_their_rule_source():
    policy = _policy(
        {
            "allowedTools": ["web_search_tool", "apply_patch_tool"],
            "preferredTools": [],
            "networkAccess": "none",
            "mutationAccess": "none",
        }
    )

    decision = _evaluate(policy, _grant())

    network = decision.deny_reason_for("web_search_tool")
    mutation = decision.deny_reason_for("apply_patch_tool")
    assert network.gate_id == "policy.networkAccess"
    assert network.rule_id == "policy-test:policy.networkAccess:network_denied"
    assert mutation.gate_id == "policy.mutationAccess"
    assert mutation.rule_id == "policy-test:policy.mutationAccess:mutation_denied"


def test_externally_blocked_tool_gets_distinct_not_assigned_rule_id():
    policy = _policy(
        {
            "allowedTools": ["grep_search_tool", "web_search_tool"],
            "preferredTools": [],
            "networkAccess": "full",
            "mutationAccess": "workspace",
        }
    )

    decision = evaluate_tool_policy(
        agent_id="agent-1",
        policy=policy,
        grant=_grant(),
        descriptors=_descriptors(),
        registry_version=1,
        registry_fingerprint="registry-1",
        available_tool_names=("grep_search_tool", "web_search_tool", "apply_patch_tool"),
        externally_blocked_tools=("apply_patch_tool",),
        generated_at="2026-07-14T00:00:00Z",
    )

    reason = decision.deny_reason_for("apply_patch_tool")
    assert reason.code is ToolDenyCode.NOT_ASSIGNED
    assert reason.gate_id == "binding.externallyBlockedTools"
    assert reason.rule_id == "policy-test:binding.externallyBlockedTools:not_assigned"


def test_turn_constraints_and_environment_only_narrow_visibility():
    policy = _policy(
        {
            "allowedTools": ["grep_search_tool", "web_search_tool", "apply_patch_tool"],
            "preferredTools": [],
            "networkAccess": "full",
            "mutationAccess": "workspace",
        }
    )
    grant = _grant(capabilities=("network",), denied=("grep_search_tool",))

    decision = _evaluate(policy, grant, available=("grep_search_tool", "apply_patch_tool"))

    assert decision.visible_tools == ()
    assert decision.deny_reason_for("grep_search_tool").code is ToolDenyCode.TURN_DENIED
    assert decision.deny_reason_for("apply_patch_tool").code is ToolDenyCode.CAPABILITY_MISMATCH
    assert decision.deny_reason_for("web_search_tool").code is ToolDenyCode.ENVIRONMENT_UNAVAILABLE


def test_turn_grant_cannot_expand_agent_assignment():
    policy = _policy(
        {
            "allowedTools": ["grep_search_tool"],
            "preferredTools": [],
            "networkAccess": "full",
            "mutationAccess": "workspace",
        }
    )

    decision = _evaluate(policy, _grant())

    assert decision.visible_tools == ("grep_search_tool",)
    assert decision.deny_reason_for("web_search_tool").code is ToolDenyCode.NOT_ASSIGNED
    assert decision.deny_reason_for("apply_patch_tool").code is ToolDenyCode.NOT_ASSIGNED


def test_execution_constraints_do_not_reintroduce_or_hide_visible_tools():
    policy = _policy(
        {
            "allowedTools": ["web_search_tool", "apply_patch_tool"],
            "preferredTools": [],
            "networkAccess": "none",
            "mutationAccess": "none",
        }
    )

    decision = _evaluate(policy, _grant())

    assert decision.visible_tools == ("apply_patch_tool", "web_search_tool")
    assert decision.executable_tools == ()
    assert decision.deny_reason_for("web_search_tool").code is ToolDenyCode.NETWORK_DENIED
    assert decision.deny_reason_for("apply_patch_tool").code is ToolDenyCode.MUTATION_DENIED


def test_approval_mode_can_only_narrow_execution():
    policy = _policy(
        {
            "allowedTools": ["web_search_tool"],
            "preferredTools": [],
            "networkAccess": "full",
            "mutationAccess": "workspace",
        }
    )

    decision = _evaluate(policy, _grant(approval_mode="never"))

    assert decision.visible_tools == ("web_search_tool",)
    assert decision.executable_tools == ()
    assert decision.deny_reason_for("web_search_tool").code is ToolDenyCode.APPROVAL_REQUIRED


def test_decision_carries_tool_risk_and_approval_requirements():
    policy = _policy(
        {
            "allowedTools": ["grep_search_tool", "web_search_tool", "apply_patch_tool"],
            "preferredTools": [],
            "networkAccess": "full",
            "mutationAccess": "workspace",
        }
    )

    decision = _evaluate(policy, _grant())

    assert decision.approval_requirements == (
        ("apply_patch_tool", "on_request", "write"),
        ("grep_search_tool", "never", "read"),
        ("web_search_tool", "on_request", "network"),
    )
    assert decision.public_projection()["approvalRequirements"]["web_search_tool"] == {
        "approval": "on_request",
        "risk": "network",
    }


def test_always_approval_tool_remains_requestable_in_on_request_mode():
    descriptor = tool_catalog.build_tool_descriptor(
        "trigger_self_restart_tool",
        args_schema={"type": "object"},
    )
    policy = normalize_legacy_tool_policy(
        {
            "policyId": "policy-restart",
            "allowedTools": ["trigger_self_restart_tool"],
            "preferredTools": [],
            "mutationAccess": "controlled",
        },
        registered_tool_names=["trigger_self_restart_tool"],
    )
    grant = TurnToolGrant(
        turn_id="turn-restart",
        source="session",
        allowed_capabilities=descriptor.capabilities,
        denied_tools=(),
        approval_mode="on_request",
    )

    decision = evaluate_tool_policy(
        agent_id="agent-1",
        policy=policy,
        grant=grant,
        descriptors=(descriptor,),
        registry_version=1,
        registry_fingerprint="registry-restart",
        generated_at="2026-07-30T00:00:00Z",
    )

    assert decision.visible_tools == ("trigger_self_restart_tool",)
    assert decision.executable_tools == ("trigger_self_restart_tool",)
    assert decision.approval_requirements == (
        ("trigger_self_restart_tool", "always", "destructive"),
    )


def test_stage_writeback_tool_is_exempt_from_approval_requirements():
    """交付类写回工具属任务自身产物落盘，不产生审批需求；普通工具不受影响。"""

    descriptors = (
        tool_catalog.build_tool_descriptor("grep_search_tool", args_schema={"type": "object"}),
        tool_catalog.build_tool_descriptor(
            "source_collection_stage_writeback_tool",
            args_schema={"type": "object"},
            source="generated",
        ),
    )
    policy = normalize_legacy_tool_policy(
        {
            "policyId": "policy-writeback",
            "allowedTools": ["grep_search_tool", "source_collection_stage_writeback_tool"],
            "preferredTools": [],
            "networkAccess": "restricted",
            "mutationAccess": "workspace",
        },
        registered_tool_names=[descriptor.name for descriptor in descriptors],
    )
    grant = TurnToolGrant(
        turn_id="turn-writeback",
        source="research",
        allowed_capabilities=tuple(sorted({capability for descriptor in descriptors for capability in descriptor.capabilities})),
        denied_tools=(),
        approval_mode="on_request",
    )

    decision = evaluate_tool_policy(
        agent_id="agent-1",
        policy=policy,
        grant=grant,
        descriptors=descriptors,
        registry_version=1,
        registry_fingerprint="registry-writeback",
        generated_at="2026-08-28T00:00:00Z",
    )

    assert decision.visible_tools == ("grep_search_tool", "source_collection_stage_writeback_tool")
    assert decision.executable_tools == ("grep_search_tool", "source_collection_stage_writeback_tool")
    assert [name for name, _approval, _risk in decision.approval_requirements] == ["grep_search_tool"]


def test_decision_and_cache_key_are_deterministic():
    policy = _policy(
        {
            "allowedTools": ["grep_search_tool"],
            "preferredTools": ["grep_search_tool"],
            "networkAccess": "restricted",
            "mutationAccess": "controlled",
        }
    )
    grant = _grant()

    first = _evaluate(policy, grant)
    second = _evaluate(policy, grant)
    first_key = authorization_cache_key(
        agent_id="agent-1",
        policy=policy,
        grant=grant,
        registry_version=1,
        registry_fingerprint="registry-1",
        available_tool_names=("grep_search_tool",),
    )
    second_key = authorization_cache_key(
        agent_id="agent-1",
        policy=policy,
        grant=grant,
        registry_version=1,
        registry_fingerprint="registry-1",
        available_tool_names=("grep_search_tool", "grep_search_tool"),
    )

    assert first.decision_fingerprint == second.decision_fingerprint
    assert first_key == second_key


def test_missing_or_corrupt_inputs_fail_closed_with_typed_errors():
    policy = _policy({"allowedTools": [], "preferredTools": []})
    grant = _grant()

    with pytest.raises(AgentIdentityMissingError):
        evaluate_tool_policy(
            agent_id="",
            policy=policy,
            grant=grant,
            descriptors=_descriptors(),
            registry_version=1,
            registry_fingerprint="registry-1",
        )
    with pytest.raises(ToolPolicyMissingError):
        normalize_legacy_tool_policy(None, registered_tool_names=("grep_search_tool",))
    with pytest.raises(ToolRegistryMissingError):
        evaluate_tool_policy(
            agent_id="agent-1",
            policy=policy,
            grant=grant,
            descriptors=(),
            registry_version=1,
            registry_fingerprint="registry-1",
        )
    with pytest.raises(TurnToolGrantMissingError):
        evaluate_tool_policy(
            agent_id="agent-1",
            policy=policy,
            grant=None,
            descriptors=_descriptors(),
            registry_version=1,
            registry_fingerprint="registry-1",
        )
    with pytest.raises(ToolPolicyInvalidError, match="unknown tools"):
        normalize_legacy_tool_policy(
            {"policyId": "bad", "allowedTools": ["unknown_tool"], "preferredTools": []},
            registered_tool_names=("grep_search_tool",),
        )


def test_legacy_normalization_preserves_zero_tools_and_merges_denied_tools():
    zero = normalize_legacy_tool_policy(
        {"policyId": "zero", "allowedTools": [], "preferredTools": []},
        registered_tool_names=("grep_search_tool", "web_search_tool"),
    )
    migrated = normalize_legacy_tool_policy(
        {
            "policyId": "legacy",
            "allowedTools": ["grep_search_tool"],
            "preferredTools": [],
            "blockedTools": ["web_search_tool"],
            "deniedTools": ["grep_search_tool"],
        },
        registered_tool_names=("grep_search_tool", "web_search_tool"),
    )
    wide = normalize_legacy_tool_policy(
        {"policyId": "wide", "allowAllTools": True, "preferredTools": []},
        registered_tool_names=("web_search_tool", "grep_search_tool"),
    )

    assert zero.allowed_tools == ()
    assert migrated.blocked_tools == ("web_search_tool", "grep_search_tool")
    assert wide.allowed_tools == ("grep_search_tool", "web_search_tool")


def test_default_session_v2_projection_matches_frozen_baseline():
    fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    case = next(item for item in fixture["cases"] if item["case_id"] == "default_session_agent")

    policy = agent_directory_service.default_session_agent_tool_policy_v2(
        "tool-session",
        registered_tool_names=tool_catalog.TOOL_CATALOG,
    )

    assert list(policy.allowed_tools) == case["expected_allowed_tools"]
    assert list(policy.preferred_tools) == case["expected_preferred_tools"]


@pytest.mark.parametrize("role_key", ["source_finder", "challenge_cup_iteration_planner"])
def test_fixed_role_profiles_materialize_forbidden_tools_inside_policy_v2(role_key):
    fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    case = next(item for item in fixture["cases"] if item.get("role_key") == role_key)

    policy = agent_role_tool_profile_service.resolve_role_tool_policy_v2(
        role_key=role_key,
        primary_mode="research",
        policy_id=f"tool-{role_key}",
        registered_tool_names=tool_catalog.TOOL_CATALOG,
    )

    assert policy is not None
    assert set(case["expected_required_tools"]).issubset(policy.allowed_tools)
    assert set(case["expected_forbidden_tools"]).issubset(policy.blocked_tools)


def test_explicit_empty_write_scopes_hard_deny_write_tools():
    """planner 形状：显式 writeScopes: [] 时写类工具在决策层被 WRITE_SCOPE_DENIED 拒绝。"""

    policy = _policy(
        {
            "allowedTools": ["grep_search_tool", "apply_patch_tool"],
            "preferredTools": [],
            "networkAccess": "full",
            "mutationAccess": "controlled",
            "writeScopes": [],
        }
    )
    assert policy.write_scopes_declared is True

    decision = _evaluate(policy, _grant())

    assert decision.visible_tools == ("apply_patch_tool", "grep_search_tool")
    assert decision.executable_tools == ("grep_search_tool",)
    reason = decision.deny_reason_for("apply_patch_tool")
    assert reason is not None
    assert reason.code is ToolDenyCode.WRITE_SCOPE_DENIED
    assert reason.gate_id == "policy.writeScopes"
    assert reason.rule_id == "policy-test:policy.writeScopes:write_scope_denied"
    assert "write" in reason.message.lower()
    projection = decision.public_projection()["denied"]["apply_patch_tool"]
    assert projection["code"] == "write_scope_denied"
    assert projection["ruleId"] == reason.rule_id


def test_non_empty_write_scopes_keep_write_tools_executable():
    """developer 形状：非空 writeScopes（如 [private]）放行写工具；路径约束归容器层。"""

    policy = _policy(
        {
            "allowedTools": ["grep_search_tool", "apply_patch_tool"],
            "preferredTools": [],
            "networkAccess": "full",
            "mutationAccess": "controlled",
            "writeScopes": ["private"],
        }
    )
    assert policy.write_scopes_declared is True

    decision = _evaluate(policy, _grant())

    assert decision.executable_tools == ("apply_patch_tool", "grep_search_tool")
    assert decision.deny_reason_for("apply_patch_tool") is None


def test_missing_write_scopes_key_keeps_legacy_behavior_and_decision_shape():
    """legacy 形状：未声明 writeScopes 键的存量策略零影响，写工具照常可执行。"""

    policy = _policy(
        {
            "allowedTools": ["grep_search_tool", "apply_patch_tool"],
            "preferredTools": [],
            "networkAccess": "full",
            "mutationAccess": "controlled",
        }
    )
    assert policy.write_scopes_declared is False
    # 投影 schema 保持稳定：不因内部 declared 标志新增键。
    assert "writeScopesDeclared" not in policy.public_projection()

    decision = _evaluate(policy, _grant())

    assert decision.executable_tools == ("apply_patch_tool", "grep_search_tool")
    assert decision.deny_reason_for("apply_patch_tool") is None


def test_explicit_empty_write_scopes_do_not_touch_non_write_tools():
    """非写工具不受空写范围闸门影响：read/network 工具保持可执行。"""

    policy = _policy(
        {
            "allowedTools": ["grep_search_tool", "web_search_tool"],
            "preferredTools": [],
            "networkAccess": "full",
            "mutationAccess": "controlled",
            "writeScopes": [],
        }
    )

    decision = _evaluate(policy, _grant())

    assert decision.executable_tools == ("grep_search_tool", "web_search_tool")
    assert decision.deny_reason_for("grep_search_tool") is None
    assert decision.deny_reason_for("web_search_tool") is None


def test_role_profile_materialization_keeps_empty_default_scopes_inert():
    """代码内置角色 profile 物化总是携带 writeScopes 键：空默认按未声明处理，存量固定角色零影响。"""

    policy = _policy(
        {
            "allowedTools": ["grep_search_tool", "apply_patch_tool"],
            "preferredTools": [],
            "networkAccess": "full",
            "mutationAccess": "controlled",
            "writeScopes": [],
            "roleToolProfileId": "profile-research-collector",
        }
    )
    assert policy.write_scopes_declared is False

    decision = _evaluate(policy, _grant())

    assert decision.executable_tools == ("apply_patch_tool", "grep_search_tool")
    assert decision.deny_reason_for("apply_patch_tool") is None


def _control_plane_write_scope_policy_and_descriptors():
    """planner 形状：显式空写范围 + 控制面类与文件写类工具各一。"""

    descriptors = (
        tool_catalog.build_tool_descriptor("agent_message_tool", args_schema={"type": "object"}),
        tool_catalog.build_tool_descriptor("dev_task_board_tool", args_schema={"type": "object"}),
        tool_catalog.build_tool_descriptor("apply_diff_edit_tool", args_schema={"type": "object"}),
    )
    policy = normalize_legacy_tool_policy(
        {
            "policyId": "policy-planner",
            "allowedTools": ["agent_message_tool", "dev_task_board_tool", "apply_diff_edit_tool"],
            "preferredTools": [],
            "mutationAccess": "controlled",
            "writeScopes": [],
        },
        registered_tool_names=[descriptor.name for descriptor in descriptors],
    )
    grant = TurnToolGrant(
        turn_id="turn-planner",
        source="team",
        allowed_capabilities=tuple(sorted({capability for descriptor in descriptors for capability in descriptor.capabilities})),
        denied_tools=(),
        approval_mode="on_request",
    )
    return descriptors, policy, grant


def test_communication_only_write_tool_is_exempt_from_empty_write_scope_gate():
    """agent_message_tool 写类标签全部落在控制面豁免集：空写范围下仍放行队内沟通。"""

    descriptors, policy, grant = _control_plane_write_scope_policy_and_descriptors()
    message_descriptor = descriptors[0]
    assert message_descriptor.risk == "write"
    assert message_descriptor.write_scope_gated is False
    assert policy.write_scopes_declared is True

    decision = evaluate_tool_policy(
        agent_id="agent-1",
        policy=policy,
        grant=grant,
        descriptors=descriptors,
        registry_version=1,
        registry_fingerprint="registry-planner",
        generated_at="2026-10-08T00:00:00Z",
    )

    assert "agent_message_tool" in decision.executable_tools
    assert decision.deny_reason_for("agent_message_tool") is None


def test_team_workflow_state_write_tool_is_exempt_from_empty_write_scope_gate():
    """dev_task_board_tool（team_workflow_state_write）是控制面操作：空写范围下放行。"""

    descriptors, policy, grant = _control_plane_write_scope_policy_and_descriptors()
    board_descriptor = descriptors[1]
    assert board_descriptor.risk == "write"
    assert board_descriptor.write_scope_gated is False
    assert policy.write_scopes_declared is True

    decision = evaluate_tool_policy(
        agent_id="agent-1",
        policy=policy,
        grant=grant,
        descriptors=descriptors,
        registry_version=1,
        registry_fingerprint="registry-planner",
        generated_at="2026-10-08T00:00:00Z",
    )

    assert decision.executable_tools == ("agent_message_tool", "dev_task_board_tool")
    assert decision.deny_reason_for("dev_task_board_tool") is None


def test_file_write_tool_still_denied_under_empty_write_scope_gate():
    """apply_diff_edit_tool（file_write）不受控制面豁免影响：空写范围下仍 WRITE_SCOPE_DENIED。"""

    descriptors, policy, grant = _control_plane_write_scope_policy_and_descriptors()
    edit_descriptor = descriptors[2]
    assert edit_descriptor.risk == "write"
    assert edit_descriptor.write_scope_gated is True

    decision = evaluate_tool_policy(
        agent_id="agent-1",
        policy=policy,
        grant=grant,
        descriptors=descriptors,
        registry_version=1,
        registry_fingerprint="registry-planner",
        generated_at="2026-10-08T00:00:00Z",
    )

    reason = decision.deny_reason_for("apply_diff_edit_tool")
    assert reason is not None
    assert reason.code is ToolDenyCode.WRITE_SCOPE_DENIED
    assert reason.gate_id == "policy.writeScopes"
    assert reason.rule_id == "policy-planner:policy.writeScopes:write_scope_denied"


def test_registry_projection_carries_write_scope_gate_flag_to_decision():
    """Registry 投影的 writeScopeGated 透传进决策输入：缺字段时 fail-closed 视为受闸。"""

    from core.authorization import tool_authorization_service as auth_service

    message_descriptor = tool_catalog.build_tool_descriptor("agent_message_tool", args_schema={"type": "object"})
    projection = message_descriptor.public_projection()
    assert projection["writeScopeGated"] is False

    parsed = auth_service._descriptors_from_registry({"descriptors": [projection]})[0]
    assert parsed.write_scope_gated is False
    legacy_parsed = auth_service._descriptors_from_registry(
        {"descriptors": [{key: value for key, value in projection.items() if key != "writeScopeGated"}]}
    )[0]
    assert legacy_parsed.write_scope_gated is True
