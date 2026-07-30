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
