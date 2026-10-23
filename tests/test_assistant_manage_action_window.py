"""Assistant manage action risk tiers and the time-boxed delegation window (b3).

The tier table is a frozen server constant: low-risk session lifecycle actions
may receive an "action window" after one approval (direct execution for N
hours); everything else — restarts, config writes, deletes, external grants,
workflow orchestration — keeps per-call approval. Conservative default:
unknown actions are high-risk.
"""

import threading
import time

import pytest

from core.web.services.session import assistant_manage_policy as policy
from core.web.services.session import tool_approvals


@pytest.fixture(autouse=True)
def _reset_state():
    tool_approvals.reset_tool_approval_state(clear_durable=False)
    yield
    tool_approvals.reset_tool_approval_state(clear_durable=False)


def _manage_args(action, arguments_json):
    return {"action": action, "arguments_json": arguments_json}


def _authorize_manage(action, arguments_json, *, agent_id="assistant-a", call_id="call-1",
                      timeout_seconds=2.0):
    return tool_approvals.authorize_or_wait(
        session_id="session-a",
        turn_id="turn-a",
        agent_id=agent_id,
        call_id=call_id,
        tool_name=policy.ASSISTANT_MANAGE_TOOL_NAME,
        tool_args=_manage_args(action, arguments_json),
        approval="always",
        risk="destructive",
        decision_fingerprint="decision-a",
        config_revision=3,
        config_hash="config-hash-a",
        permission_preset="request_approval",
        timeout_seconds=timeout_seconds,
    )


def _authorize_manage_async(action, arguments_json, **kwargs):
    def _run():
        _authorize_manage(action, arguments_json, **kwargs)

    worker = threading.Thread(target=_run)
    worker.start()
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        pending = [
            item
            for item in tool_approvals.list_tool_approval_requests("session-a", status="pending")
            if item["toolName"] == policy.ASSISTANT_MANAGE_TOOL_NAME
        ]
        if pending:
            return worker, pending[0]
        time.sleep(0.01)
    worker.join(timeout=2)
    raise AssertionError("manage approval request was not published")


def test_tier_table_is_closed_and_conservative():
    assert policy.ASSISTANT_MANAGE_LOW_RISK_ACTIONS <= policy.ASSISTANT_MANAGE_ACTIONS
    assert (
        policy.ASSISTANT_MANAGE_HIGH_RISK_ACTIONS
        == policy.ASSISTANT_MANAGE_ACTIONS - policy.ASSISTANT_MANAGE_LOW_RISK_ACTIONS
    )
    # Explicit red-line actions can never sit in the low-risk tier. Managed
    # writes (team_create/knowledge_ingest/config_update) stay per-call.
    for action in (
        "restart", "agent_create", "agent_update", "agent_archive",
        "session_delete", "knowledge_acl_grant",
        "workflow_recovery_bind", "workflow_recovery_revoke", "workflow_start",
        "team_create", "knowledge_ingest", "config_update",
    ):
        assert action in policy.ASSISTANT_MANAGE_HIGH_RISK_ACTIONS
        assert action not in policy.ASSISTANT_MANAGE_LOW_RISK_ACTIONS


@pytest.mark.parametrize(
    "action",
    ["team_create", "knowledge_ingest", "config_update"],
)
def test_managed_write_actions_have_no_window_grant_and_stay_per_call(action):
    # The window grant machine refuses managed writes outright.
    with pytest.raises(ValueError):
        policy.grant_assistant_action_window(agent_id="assistant-a", action=action)
    # While a low-risk window is active, a managed write still prompts and the
    # card reports the action as window-ineligible.
    policy.grant_assistant_action_window(agent_id="assistant-a", action="session_stop")
    worker, request = _authorize_manage_async(
        action,
        {
            "team_create": '{"name": "交付团队"}',
            "knowledge_ingest": '{"inboxSourceId": "isrc-1", "ownerType": "team", "ownerId": "team-1"}',
            "config_update": '{"updates": [{"section": "ui", "key": "language", "value": "en"}]}',
        }[action],
        call_id=f"call-{action}",
    )
    assert request["status"] == "pending"
    assert "acceptWithActionWindow" not in request["availableDecisions"]
    assert request.get("assistantActionWindow", {}).get("eligible") is False
    projection = tool_approvals._argument_summary(
        policy.ASSISTANT_MANAGE_TOOL_NAME,
        _manage_args(action, _preview_args(action)),
    )
    assert projection.get("assistantAction") == action
    assert not projection.get("assistantArgumentsInvalid")
    tool_approvals.resolve_tool_approval_request(
        "session-a", request["requestId"], decision="cancel"
    )
    worker.join(timeout=2)


def _preview_args(action):
    return {
        "team_create": '{"name": "交付团队", "templateId": "dev-team"}',
        "knowledge_ingest": '{"inboxSourceId": "isrc-1", "ownerType": "team", "ownerId": "team-1"}',
        "config_update": '{"updates": [{"section": "ui", "key": "language", "value": "en"}]}',
    }[action]


def test_action_window_bypasses_repeated_prompts_within_window():
    worker, request = _authorize_manage_async(
        "session_stop", '{"session_id": "sess-1", "turn_id": "turn-1"}'
    )
    assert request["availableDecisions"].count("acceptWithActionWindow") == 1
    resolved = tool_approvals.resolve_tool_approval_request(
        "session-a", request["requestId"], decision="acceptWithActionWindow"
    )
    assert resolved["status"] == "accepted_with_action_window"
    worker.join(timeout=2)
    assert worker.is_alive() is False

    # Same low-risk action with different arguments: direct execution.
    outcome = _authorize_manage(
        "session_stop", '{"session_id": "sess-2", "turn_id": "turn-2"}', call_id="call-2",
    )
    assert outcome.allowed and outcome.code == "approved_for_action_window"

    # Other low-risk actions are not covered by this window.
    worker2, request2 = _authorize_manage_async(
        "session_create", '{"agent_id": "agent-1", "title": "新会话"}', call_id="call-3",
    )
    assert request2["status"] == "pending"
    tool_approvals.resolve_tool_approval_request(
        "session-a", request2["requestId"], decision="acceptWithActionWindow"
    )
    worker2.join(timeout=2)


def test_high_risk_actions_ignore_active_windows_and_stay_per_call():
    worker, request = _authorize_manage_async(
        "session_update", '{"session_id": "sess-1", "title": "改名"}'
    )
    tool_approvals.resolve_tool_approval_request(
        "session-a", request["requestId"], decision="acceptWithActionWindow"
    )
    worker.join(timeout=2)
    assert policy.assistant_action_window_remaining(
        agent_id="assistant-a",
        tool_name=policy.ASSISTANT_MANAGE_TOOL_NAME,
        tool_args=_manage_args("session_update", "{}"),
    ) > 0

    # High-risk action while a low-risk window is active: still prompts.
    worker2, request2 = _authorize_manage_async("restart", '{"reason": "reload"}', call_id="call-2")
    assert request2["status"] == "pending"
    assert "acceptWithActionWindow" not in request2["availableDecisions"]
    assert request2.get("assistantActionWindow", {}).get("eligible") is False
    with pytest.raises(tool_approvals.ToolApprovalConflictError, match="action-window"):
        tool_approvals.resolve_tool_approval_request(
            "session-a", request2["requestId"], decision="acceptWithActionWindow"
        )
    tool_approvals.resolve_tool_approval_request(
        "session-a", request2["requestId"], decision="cancel"
    )
    worker2.join(timeout=2)

    # session_delete is delete-class: never windowable.
    assert "session_delete" in policy.ASSISTANT_MANAGE_HIGH_RISK_ACTIONS


def test_action_window_expires_and_is_bounded_to_one_agent():
    policy.grant_assistant_action_window(agent_id="assistant-a", action="session_create", duration_seconds=0.05)
    assert policy.assistant_action_window_remaining(
        agent_id="assistant-a",
        tool_name=policy.ASSISTANT_MANAGE_TOOL_NAME,
        tool_args=_manage_args("session_create", "{}"),
    ) > 0
    time.sleep(0.06)
    assert policy.assistant_action_window_remaining(
        agent_id="assistant-a",
        tool_name=policy.ASSISTANT_MANAGE_TOOL_NAME,
        tool_args=_manage_args("session_create", "{}"),
    ) == 0.0

    # Another agent's window never leaks (the assistant identity is scoped).
    policy.grant_assistant_action_window(agent_id="assistant-b", action="session_create")
    assert policy.assistant_action_window_remaining(
        agent_id="assistant-a",
        tool_name=policy.ASSISTANT_MANAGE_TOOL_NAME,
        tool_args=_manage_args("session_create", "{}"),
    ) == 0.0
    tool_approvals.reset_tool_approval_state()
    assert policy.assistant_action_window_remaining(
        agent_id="assistant-b",
        tool_name=policy.ASSISTANT_MANAGE_TOOL_NAME,
        tool_args=_manage_args("session_create", "{}"),
    ) == 0.0


def test_window_grant_refuses_high_risk_and_unknown_actions():
    for action in ("restart", "session_delete", "not_an_action"):
        with pytest.raises(ValueError):
            policy.grant_assistant_action_window(agent_id="assistant-a", action=action)


def test_projection_reports_tier_and_remaining_window_on_approval_card():
    worker, request = _authorize_manage_async(
        "session_stop", '{"session_id": "sess-1", "turn_id": "turn-1"}'
    )
    projection = request["assistantActionWindow"]
    assert projection["eligible"] is True
    assert projection["remainingSeconds"] == 0
    assert projection["durationSeconds"] == policy.DEFAULT_ACTION_WINDOW_SECONDS
    assert projection["activeWindows"] == []
    tool_approvals.resolve_tool_approval_request(
        "session-a", request["requestId"], decision="acceptWithActionWindow"
    )
    worker.join(timeout=2)

    # A second pending request for another low-risk action now carries the
    # live session_stop window so the card can render remaining time.
    worker2, request2 = _authorize_manage_async(
        "session_create", '{"agent_id": "agent-1", "title": "新会话"}', call_id="call-2",
    )
    window_projection = request2["assistantActionWindow"]
    assert window_projection["eligible"] is True
    active = {item["action"]: item["remainingSeconds"] for item in window_projection["activeWindows"]}
    assert 0 < active["session_stop"] <= policy.DEFAULT_ACTION_WINDOW_SECONDS
    tool_approvals.resolve_tool_approval_request(
        "session-a", request2["requestId"], decision="cancel"
    )
    worker2.join(timeout=2)


def test_non_manage_tools_never_get_an_action_window_projection():
    worker, request = _authorize_manage_async(
        "session_stop", '{"session_id": "sess-1", "turn_id": "turn-1"}'
    )
    tool_approvals.resolve_tool_approval_request(
        "session-a", request["requestId"], decision="acceptWithActionWindow"
    )
    worker.join(timeout=2)

    # exec_command requests carry no assistantActionWindow key and never see
    # the manage window bypass even while manage windows are active.
    from tests.test_tool_approval_granularity import _authorize_async

    worker3, plain_request = _authorize_async(
        tool_name="exec_command", tool_args={"cmd": "echo hi"}, risk="write", call_id="call-3",
    )
    assert "assistantActionWindow" not in plain_request
    assert "acceptWithActionWindow" not in plain_request["availableDecisions"]
    tool_approvals.resolve_tool_approval_request(
        "session-a", plain_request["requestId"], decision="cancel"
    )
    worker3.join(timeout=2)
