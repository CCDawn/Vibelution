"""Launcher platform approval summaries expose complete scope without bodies."""
from __future__ import annotations

import json
import threading
import time

import pytest

from core.assistant_runtime.platform_approval import platform_management_approval_summary
from core.infrastructure import native_runtime
from core.web.services.session import tool_approvals
from core.web.services.session import assistant_manage_policy as policy


@pytest.fixture(autouse=True)
def isolated_approval_state(monkeypatch):
    tool_approvals.reset_tool_approval_state(clear_durable=False)
    monkeypatch.setattr(tool_approvals, "_record_approval_event", lambda *args, **kwargs: None)
    yield
    tool_approvals.reset_tool_approval_state(clear_durable=False)


def cases():
    base = {"project_id": "project-a", "request_id": "request-a"}
    return {
        "dispatch_cancel": {"project_id": "project-a", "dispatch_id": "dispatch-a", "native_task_id": "task-a"},
        "runtime_command": {**base, "kind": "team_run", "resource_id": "run-a", "team_id": "team-a",
                            "flow_id": "flow-a", "command": "stop", "expected_revision": "9007199254740993"},
        "team_update": {**base, "team_id": "team-a", "expected_team_fingerprint": "a" * 64,
                        "updates": {"name": "Team", "description": "PRIVATE_TEAM_DESCRIPTION",
                        "members": [{"agentId": "member-a", "role": "member", "purpose": "PRIVATE_PURPOSE"}]}},
        "agent_tool_policy_update": {**base, "agent_id": "agent-a", "expected_config_revision": 9007199254740993,
            "expected_agent_updated_at": "2026-11-02T00:00:00Z", "expected_policy_fingerprint": "b" * 64,
            "expected_registry_version": "registry-v1", "expected_registry_fingerprint": "c" * 64,
            "updates": {"allowedTools": ["read_file_tool", "write_file_tool"], "preferredTools": ["read_file_tool"],
                "blockedTools": ["exec_command"], "readScopes": ["private", "shared"], "writeScopes": ["private"],
                "allowedCommandKinds": ["read"], "networkAccess": "restricted", "mutationAccess": "workspace",
                "delegationAccess": "assigned_only", "approvalOverrides": {"write_file_tool": "always"},
                "maxCallsPerTurn": 12, "maxCallsPerTurnByModelFamily": {"model-family": 7},
                "perToolRules": {"read_file_tool": {"approval": "never"}}}},
        "agent_dispatch_access_set": {**base, "agent_id": "agent-a", "enabled": True,
            "expected_public_config_hash": "f" * 64, "expected_eligibility_fingerprint": "e" * 64},
        "knowledge_acl_grant": {**base, "knowledge_base_id": "team:team-a:kb-a", "target_agent_id": "agent-a",
                                "permissions": ["read", "review"], "expected_acl_fingerprint": "d" * 64},
        "knowledge_acl_revoke": {**base, "knowledge_base_id": "agent:owner-a:kb-a", "target_agent_id": "agent-a",
                                 "permissions": ["propose"], "expected_acl_fingerprint": "e" * 64},
        "flow_save": {**base, "team_id": "team-a", "flow_id": "flow-a", "expectedRevision": 9007199254740993,
            "flow": {"id": "flow-a", "name": "PRIVATE_FLOW_NAME", "description": "PRIVATE_FLOW_DESCRIPTION",
                "fields": [{"id": "goal", "label": "PRIVATE_INPUT_LABEL", "kind": "text", "required": True}],
                "steps": [{"id": "work", "kind": "agent", "owner": "agent-a", "label": "PRIVATE_NODE_LABEL",
                           "instruction": "PRIVATE_FULL_PROMPT"}]}},
        "flow_start": {**base, "team_id": "team-a", "flow_id": "flow-a", "expectedRevision": 9007199254740993,
                       "values": {"goal": "PRIVATE_USER_GOAL"}},
    }


def test_dispatch_cancel_summary_is_bound_to_original_native_task(monkeypatch):
    parameters = {"project_id": "project-a", "dispatch_id": "dispatch-a", "native_task_id": "task-a"}
    summary = platform_management_approval_summary("dispatch_cancel", parameters)
    assert summary["assistantPlatformPreviewVersion"] == 1
    assert summary["assistantTargets"] == parameters
    assert len(summary["assistantParametersDigest"]) == 64
    monkeypatch.setattr(native_runtime, "is_launcher_assistant_process", lambda: True)
    projected = tool_approvals._assistant_management_summary({"action": "dispatch_cancel", "arguments_json": json.dumps(parameters)})
    assert projected == summary


@pytest.mark.parametrize("action", list(cases()))
def test_platform_summary_uses_same_closed_dto_and_never_records_user_bodies(monkeypatch, action):
    parameters = cases()[action]
    summary = platform_management_approval_summary(action, parameters)
    monkeypatch.setattr(native_runtime, "is_launcher_assistant_process", lambda: True)
    assert summary == tool_approvals._assistant_management_summary({"action": action, "arguments_json": json.dumps(parameters)})
    assert summary["assistantDetailsOmitted"] is False
    assert "PRIVATE_" not in json.dumps(summary)
    for key, value in parameters.items():
        if key in summary["assistantTargets"]:
            assert summary["assistantTargets"][key] == str(value)
    with pytest.raises(ValueError):
        platform_management_approval_summary(action, {**parameters, "approved": True})
    assert action in policy.ASSISTANT_MANAGE_HIGH_RISK_ACTIONS
    with pytest.raises(ValueError):
        policy.grant_assistant_action_window(agent_id="assistant-a", action=action)


def test_policy_summary_shows_all_permission_fields_and_exact_large_revision():
    parameters = cases()["agent_tool_policy_update"]
    summary = platform_management_approval_summary("agent_tool_policy_update", parameters)
    assert summary["assistantTargets"]["expected_config_revision"] == "9007199254740993"
    assert summary["assistantChangedFields"] == sorted(parameters["updates"])
    assert set(summary["assistantDelta"]) == set(parameters["updates"])
    assert summary["assistantDelta"]["maxCallsPerTurn"] == "12"
    assert summary["assistantDelta"]["maxCallsPerTurnByModelFamily"] == {"model-family": "7"}
    bad = {**parameters, "updates": {"perToolRules": {"read_file_tool": {"approval": "never", "approvalGrants": ["secret"]}}}}
    with pytest.raises(ValueError):
        platform_management_approval_summary("agent_tool_policy_update", bad)


def test_team_member_role_qualifications_are_visible_and_bound_to_member_identity():
    parameters = cases()["team_update"]
    parameters["updates"] = {"members": [
        {"memberId": "membership-b", "agentId": "agent-b", "role": " LEAD ", "purpose": "PRIVATE_PURPOSE",
         "responsibilities": ["PRIVATE_RESPONSIBILITY"]},
        {"memberId": "membership-a", "agentId": "agent-a", "role": "member"},
    ]}
    summary = platform_management_approval_summary("team_update", parameters)
    assert summary["assistantDelta"]["memberRoles"] == [
        {"memberId": "membership-b", "agentId": "agent-b", "role": " LEAD ", "effectiveRole": "lead", "knowledgeReviewEligible": True},
        {"memberId": "membership-a", "agentId": "agent-a", "role": "member", "effectiveRole": "member", "knowledgeReviewEligible": False},
    ]
    assert summary["assistantDetailsOmitted"] is False
    assert "PRIVATE_" not in json.dumps(summary)


def test_unsafe_team_member_role_is_a_critical_preview_omission():
    parameters = cases()["team_update"]
    parameters["updates"] = {"members": [{"memberId": "membership-a", "agentId": "agent-a", "role": "lead\u202eHIDDEN"}]}
    summary = platform_management_approval_summary("team_update", parameters)
    assert summary["assistantDetailsOmitted"] is True
    assert "HIDDEN" not in json.dumps(summary)


def test_team_role_qualification_uses_native_role_normalization_and_review_table(monkeypatch):
    from core.web.services import team_knowledge_service as knowledge

    monkeypatch.setattr(knowledge, "REVIEW_ROLES", {"custom-reviewer"})
    parameters = cases()["team_update"]
    parameters["updates"] = {"members": [
        {"agentId": "agent-a", "role": " Custom-Reviewer "}, {"agentId": "agent-b", "role": "lead"},
        {"agentId": "agent-c", "role": ""},
    ]}
    summary = platform_management_approval_summary("team_update", parameters)
    rows = summary["assistantDelta"]["memberRoles"]
    assert [row["effectiveRole"] for row in rows] == ["custom-reviewer", "lead", "member"]
    assert [row["knowledgeReviewEligible"] for row in rows] == [True, False, False]
    assert summary["assistantContentOmitted"] is False and summary["assistantDetailsOmitted"] is False


def test_sensitive_or_oversized_policy_detail_is_explicitly_unreviewable():
    parameters = cases()["agent_tool_policy_update"]
    parameters["updates"] = {"blockedCommandPatterns": ["PRIVATE_COMMAND_PATTERN"]}
    summary = platform_management_approval_summary("agent_tool_policy_update", parameters)
    assert summary["assistantDetailsOmitted"] is True and "PRIVATE_COMMAND_PATTERN" not in str(summary)
    assert summary["assistantDelta"]["blockedCommandPatternsCount"] == "1"
    parameters["updates"] = {"allowedTools": ["tool_" + "a" * 110 + str(i) for i in range(200)]}
    summary = platform_management_approval_summary("agent_tool_policy_update", parameters)
    assert summary["assistantDetailsOmitted"] is True and "omittedFields" in summary["assistantDelta"]


@pytest.mark.parametrize("kind,source", [("session", {"sessionId": "source-session", "turnId": "source-turn", "agentId": "source-agent"}),
                                         ("research", {"runId": "source-run", "nodeId": "source-node"})])
def test_supervising_flow_summary_contains_exact_native_source_references(kind, source):
    parameters = cases()["flow_save"]
    parameters["flow"] = {"id": "flow-a", "name": "PRIVATE_FLOW_NAME", "steps": [{"id": "supervise", "kind": kind,
        "label": "PRIVATE_NODE_LABEL", kind + "Source": source}]}
    summary = platform_management_approval_summary("flow_save", parameters)
    assert summary["assistantDelta"]["nodeSourceRefs"] == [source]
    assert "PRIVATE_" not in json.dumps(summary)


@pytest.mark.parametrize("action", list(cases()))
def test_full_access_platform_actions_still_auto_approve_without_native_request(monkeypatch, action):
    monkeypatch.setattr(native_runtime, "is_launcher_assistant_process", lambda: True)
    outcome = tool_approvals.authorize_or_wait(session_id="platform-session", turn_id="turn-a", agent_id="assistant-a",
        call_id="call-a", tool_name="personal_assistant_manage_tool",
        tool_args={"action": action, "arguments_json": json.dumps(cases()[action])}, approval="always", risk="destructive",
        decision_fingerprint="policy-a", config_revision=1, config_hash="config-a", permission_preset="full_access")
    assert outcome.allowed is True and outcome.code == "full_access_auto_approved"
    assert tool_approvals.list_tool_approval_requests("platform-session", status="pending") == []


def test_non_launcher_normal_acl_and_team_summaries_keep_existing_paths(monkeypatch):
    monkeypatch.setattr(native_runtime, "is_launcher_assistant_process", lambda: False)
    acl = tool_approvals._assistant_management_summary({"action": "knowledge_acl_grant", "arguments_json": json.dumps({
        "knowledge_base_id": "kb-a", "target_agent_id": "agent-a"})})
    assert acl["assistantPermissions"] == ["propose", "read"]
    assert "assistantPlatformPreviewVersion" not in acl
    team = tool_approvals._assistant_management_summary({"action": "team_update", "arguments_json": json.dumps({
        "team_id": "team-a", "name": "Team"})})
    assert "assistantPlatformPreviewVersion" not in team


@pytest.mark.parametrize("raw", ['{"project_id":"project-a","project_id":"forged"}', "[]", "{bad", '"private"'])
def test_platform_json_rejects_duplicates_and_malformed_values(monkeypatch, raw):
    monkeypatch.setattr(native_runtime, "is_launcher_assistant_process", lambda: True)
    summary = tool_approvals._assistant_management_summary({"action": "dispatch_cancel", "arguments_json": raw})
    assert summary == {"assistantAction": "dispatch_cancel", "assistantArgumentsInvalid": True}


def test_manual_request_freezes_exact_hash_and_cannot_receive_an_action_window(monkeypatch):
    monkeypatch.setattr(native_runtime, "is_launcher_assistant_process", lambda: True)
    arguments = {"action": "flow_start", "arguments_json": json.dumps(cases()["flow_start"])}
    outcome = []
    kwargs = dict(session_id="platform-session", turn_id="turn-a", agent_id="assistant-a", call_id="call-a",
        tool_name="personal_assistant_manage_tool", approval="always", risk="destructive", decision_fingerprint="policy-a",
        config_revision=1, config_hash="config-a", permission_preset="request_approval", timeout_seconds=5)
    worker = threading.Thread(target=lambda: outcome.append(tool_approvals.authorize_or_wait(tool_args=arguments, **kwargs)))
    worker.start()
    try:
        deadline = time.monotonic() + 3
        request = None
        while time.monotonic() < deadline:
            pending = tool_approvals.list_tool_approval_requests("platform-session", status="pending")
            if pending:
                request = pending[0]
                break
            time.sleep(0.01)
        assert request is not None
        assert request["argumentSummary"]["assistantPlatformPreviewVersion"] == 1
        assert "acceptWithActionWindow" not in request["availableDecisions"]
        assert request["argumentSummary"]["assistantContentOmitted"] is True
        assert request["argumentSummary"]["assistantDetailsOmitted"] is False
        changed = {"action": "flow_start", "arguments_json": json.dumps({**cases()["flow_start"], "values": {"goal": "changed"}})}
        with pytest.raises(tool_approvals.ToolApprovalConflictError):
            tool_approvals.authorize_or_wait(tool_args=changed, **kwargs)
        tool_approvals.resolve_tool_approval_request("platform-session", request["requestId"], decision="accept")
        worker.join(timeout=3)
        assert not worker.is_alive() and outcome[0].allowed is True
    finally:
        for request in tool_approvals.list_tool_approval_requests("platform-session", status="pending"):
            tool_approvals.resolve_tool_approval_request("platform-session", request["requestId"], decision="cancel")
        worker.join(timeout=3)
