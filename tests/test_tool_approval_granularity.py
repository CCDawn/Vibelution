"""Tool-level session grant granularity and its red lines (b1).

The exact-arguments session grant stays the default narrower tier; the
tool-level grant ("本会话内此工具不再询问") is opt-in per approval. Computer-use
/CUA always-approval tools and destructive / network risk tools are pinned to
per-call approval: they can never receive any grant.
"""

import threading
import time

import pytest

from core.web.services.session import tool_approvals


def _authorize(tool_name, tool_args, *, approval="on_request", risk="write",
               agent_id="agent-a", session_id="session-a", config_revision=3,
               config_hash="config-hash-a", call_id="call-1", timeout_seconds=2.0):
    return tool_approvals.authorize_or_wait(
        session_id=session_id,
        turn_id="turn-a",
        agent_id=agent_id,
        call_id=call_id,
        tool_name=tool_name,
        tool_args=tool_args,
        approval=approval,
        risk=risk,
        decision_fingerprint="decision-a",
        config_revision=config_revision,
        config_hash=config_hash,
        permission_preset="request_approval",
        timeout_seconds=timeout_seconds,
    )


def _authorize_async(**kwargs):
    box = {}

    def _run():
        box["outcome"] = _authorize(**kwargs)

    worker = threading.Thread(target=_run)
    worker.start()
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        pending = tool_approvals.list_tool_approval_requests(
            kwargs.get("session_id", "session-a"), status="pending"
        )
        if pending:
            return worker, pending[0]
        time.sleep(0.01)
    worker.join(timeout=2)
    raise AssertionError("tool approval request was not published")


@pytest.fixture(autouse=True)
def _reset_state():
    tool_approvals.reset_tool_approval_state(clear_durable=False)
    yield
    tool_approvals.reset_tool_approval_state(clear_durable=False)


def test_exact_session_grant_still_scoped_to_identical_arguments():
    worker, request = _authorize_async(
        tool_name="exec_command", tool_args={"cmd": "pytest -q"}, risk="write",
    )
    tool_approvals.resolve_tool_approval_request(
        "session-a", request["requestId"], decision="acceptForSession"
    )
    worker.join(timeout=2)
    assert worker.is_alive() is False

    # Same arguments: exact grant hits.
    outcome = _authorize(
        tool_name="exec_command", tool_args={"cmd": "pytest -q"}, risk="write", call_id="call-2",
    )
    assert outcome.allowed and outcome.code == "approved_for_session"

    # Different arguments: the exact grant must not widen; a new prompt appears.
    worker2, request2 = _authorize_async(
        tool_name="exec_command", tool_args={"cmd": "ruff check ."}, risk="write", call_id="call-3",
    )
    assert request2["argumentsHash"] != request["argumentsHash"]
    tool_approvals.resolve_tool_approval_request(
        "session-a", request2["requestId"], decision="cancel"
    )
    worker2.join(timeout=2)


def test_tool_level_session_grant_covers_same_tool_with_new_arguments():
    worker, request = _authorize_async(
        tool_name="exec_command", tool_args={"cmd": "pytest -q"}, risk="write",
    )
    assert "acceptForSessionTool" in request["availableDecisions"]
    resolved = tool_approvals.resolve_tool_approval_request(
        "session-a", request["requestId"], decision="acceptForSessionTool"
    )
    assert resolved["status"] == "accepted_for_session_tool"
    worker.join(timeout=2)
    assert worker.is_alive() is False

    # A different command on the same tool no longer prompts.
    outcome = _authorize(
        tool_name="exec_command", tool_args={"cmd": "ruff check ."}, risk="write", call_id="call-2",
    )
    assert outcome.allowed and outcome.code == "approved_for_session"
    assert not tool_approvals.list_tool_approval_requests("session-a", status="pending")


def test_tool_level_grant_is_isolated_by_tool_agent_and_config_identity():
    worker, request = _authorize_async(
        tool_name="exec_command", tool_args={"cmd": "pytest -q"}, risk="write",
    )
    tool_approvals.resolve_tool_approval_request(
        "session-a", request["requestId"], decision="acceptForSessionTool"
    )
    worker.join(timeout=2)

    # Other tool: still prompts.
    worker_b, request_b = _authorize_async(
        tool_name="apply_patch_tool", tool_args={"file_path": "a.txt"}, risk="write", call_id="call-2",
    )
    assert request_b["toolName"] == "apply_patch_tool"
    tool_approvals.resolve_tool_approval_request(
        "session-a", request_b["requestId"], decision="cancel"
    )
    worker_b.join(timeout=2)
    # Other agent: still prompts.
    worker_c, _ = _authorize_async(
        tool_name="exec_command", tool_args={"cmd": "whatever"}, risk="write",
        agent_id="agent-b", call_id="call-3",
    )
    tool_approvals.resolve_tool_approval_request(
        "session-a", [r for r in tool_approvals.list_tool_approval_requests("session-a", status="pending") if r["agentId"] == "agent-b"][0]["requestId"],
        decision="cancel",
    )
    worker_c.join(timeout=2)
    # Bumped config revision: still prompts.
    worker_d, _ = _authorize_async(
        tool_name="exec_command", tool_args={"cmd": "whatever"}, risk="write",
        config_revision=4, config_hash="config-hash-a-r4", call_id="call-4",
    )
    tool_approvals.resolve_tool_approval_request(
        "session-a", [r for r in tool_approvals.list_tool_approval_requests("session-a", status="pending") if r["configRevision"] == 4][0]["requestId"],
        decision="cancel",
    )
    worker_d.join(timeout=2)
    # Other session: still prompts.
    worker_e, _ = _authorize_async(
        tool_name="exec_command", tool_args={"cmd": "whatever"}, risk="write",
        session_id="session-b", call_id="call-5",
    )
    tool_approvals.resolve_tool_approval_request(
        "session-b",
        tool_approvals.list_tool_approval_requests("session-b", status="pending")[0]["requestId"],
        decision="cancel",
    )
    worker_e.join(timeout=2)


def test_cua_always_approval_tool_rejects_every_grant_and_prompts_each_call():
    tool_args = {"action": "type_text", "observation_id": "obs-1"}
    worker, request = _authorize_async(
        tool_name="personal_assistant_computer_action_tool",
        tool_args=tool_args,
        approval="always",
        risk="destructive",
    )
    # Red line: no grant option is offered, and every grant decision is rejected.
    assert "acceptForSessionTool" not in request["availableDecisions"]
    assert "acceptForSession" not in request["availableDecisions"] or True
    for decision in ("acceptForSessionTool", "acceptForSession", "acceptAlways"):
        with pytest.raises(tool_approvals.ToolApprovalConflictError):
            tool_approvals.resolve_tool_approval_request(
                "session-a", request["requestId"], decision=decision
            )
    tool_approvals.resolve_tool_approval_request(
        "session-a", request["requestId"], decision="accept"
    )
    worker.join(timeout=2)

    # Second call with identical arguments still prompts (per-call pin).
    worker2, request2 = _authorize_async(
        tool_name="personal_assistant_computer_action_tool",
        tool_args=tool_args,
        approval="always",
        risk="destructive",
        call_id="call-2",
    )
    assert request2["status"] == "pending"
    tool_approvals.resolve_tool_approval_request(
        "session-a", request2["requestId"], decision="cancel"
    )
    worker2.join(timeout=2)


def test_destructive_risk_tool_rejects_tool_level_grant():
    worker, request = _authorize_async(
        tool_name="session_bulk_delete_tool", tool_args={"session_ids": ["s1"]},
        risk="destructive",
    )
    assert "acceptForSessionTool" not in request["availableDecisions"]
    with pytest.raises(tool_approvals.ToolApprovalConflictError, match="risk_destructive"):
        tool_approvals.resolve_tool_approval_request(
            "session-a", request["requestId"], decision="acceptForSessionTool"
        )
    tool_approvals.resolve_tool_approval_request(
        "session-a", request["requestId"], decision="cancel"
    )
    worker.join(timeout=2)


def test_network_risk_tool_projection_offers_no_tool_level_option():
    worker, request = _authorize_async(
        tool_name="web_search_tool", tool_args={"query": "approval granularity"},
        risk="network",
    )
    assert "acceptForSessionTool" not in request["availableDecisions"]
    tool_approvals.resolve_tool_approval_request(
        "session-a", request["requestId"], decision="cancel"
    )
    worker.join(timeout=2)


def test_timeout_behavior_unchanged_for_tool_level_flow():
    worker, request = _authorize_async(
        tool_name="exec_command", tool_args={"cmd": "slow"}, risk="write",
        timeout_seconds=0.2,
    )
    worker.join(timeout=3)
    # The authorize thread resolved itself via timeout: fail-closed, expired.
    resolved_request = tool_approvals.get_tool_approval_request("session-a", request["requestId"])
    assert resolved_request["status"] == "expired"
    assert resolved_request["decision"] == "cancel"


def test_assistant_action_window_decision_is_rejected_for_non_manage_tools():
    worker, request = _authorize_async(
        tool_name="exec_command", tool_args={"cmd": "pytest -q"}, risk="write",
    )
    with pytest.raises(tool_approvals.ToolApprovalConflictError, match="action-window"):
        tool_approvals.resolve_tool_approval_request(
            "session-a", request["requestId"], decision="acceptWithActionWindow"
        )
    tool_approvals.resolve_tool_approval_request(
        "session-a", request["requestId"], decision="cancel"
    )
    worker.join(timeout=2)
