import threading
import time
from types import SimpleNamespace

import pytest

from core.authorization import tool_authorization_service
from core.infrastructure.tool_executor import ToolExecutor
from core.web.services import agent_directory_service
from core.web.services.session import tool_approvals


@pytest.fixture(autouse=True)
def _reset_approval_state():
    tool_approvals.reset_tool_approval_state()
    tool_authorization_service.clear_execution_authorization()
    yield
    tool_approvals.reset_tool_approval_state()
    tool_authorization_service.clear_execution_authorization()


def _runtime(
    monkeypatch,
    *,
    session_id="session-a",
    turn_id="turn-a",
    permission_preset="request_approval",
    config_revision=3,
    config_hash="config-hash-a",
):
    runtime_permissions = {
        "request_approval": {
            "preset": "request_approval",
            "sandboxMode": "workspace_write",
            "approvalPolicy": "on_request",
            "approvalsReviewer": "user",
        },
        "auto_review": {
            "preset": "auto_review",
            "sandboxMode": "workspace_write",
            "approvalPolicy": "on_request",
            "approvalsReviewer": "auto_review",
        },
        "full_access": {
            "preset": "full_access",
            "sandboxMode": "danger_full_access",
            "approvalPolicy": "never",
            "approvalsReviewer": "none",
        },
    }[permission_preset]
    monkeypatch.setattr(
        agent_directory_service,
        "current_agent_runtime",
        lambda: {
            "agentId": "agent-a",
            "sessionId": session_id,
            "turnId": turn_id,
            "agentConfigSnapshot": {
                "agentId": "agent-a",
                "configRevision": config_revision,
                "configHash": config_hash,
            },
            "permissionPreset": permission_preset,
            "runtimePermissions": runtime_permissions,
            "toolPolicy": {
                "policyId": "tool-agent-a",
                "allowedTools": [
                    "exec_command",
                    "web_search_tool",
                    "trigger_self_restart_tool",
                ],
                "preferredTools": [],
                "blockedTools": [],
                "maxCallsPerTurn": 20,
            },
        },
    )


def _install(*requirements):
    tool_authorization_service.install_execution_authorization(
        SimpleNamespace(
            decision=SimpleNamespace(
                agent_id="agent-a",
                turn_id="turn-a",
                decision_fingerprint="decision-a",
                executable_tools=tuple(item[0] for item in requirements),
                approval_requirements=tuple(requirements),
            )
        )
    )


def _wait_for_pending(session_id="session-a"):
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        pending = tool_approvals.list_tool_approval_requests(session_id, status="pending")
        if pending:
            return pending[0]
        time.sleep(0.01)
    raise AssertionError("tool approval request was not published")


def test_request_approval_policy_prompts_for_workspace_command(monkeypatch):
    _runtime(monkeypatch, permission_preset="request_approval")
    _install(("exec_command", "on_request", "execute"))
    calls = []
    executor = ToolExecutor()
    executor.register_tool("exec_command", lambda **kwargs: calls.append(kwargs) or "ok")
    result_box = {}

    worker = threading.Thread(
        target=lambda: (
            _install(("exec_command", "on_request", "execute")),
            result_box.setdefault(
                "value",
                executor.execute(
                    "exec_command",
                    {"cmd": "echo ready", "cwd": "."},
                    tool_call_id="call-command",
                ),
            ),
        )
    )
    worker.start()
    request = _wait_for_pending()
    tool_approvals.resolve_tool_approval_request(
        "session-a",
        request["requestId"],
        decision="accept",
    )
    worker.join(timeout=2)

    assert result_box["value"] == ("ok", None)
    assert calls == [{"cmd": "echo ready", "cwd": "."}]
    assert request["permissionPreset"] == "request_approval"
    assert request["configRevision"] == 3
    assert request["configHash"] == "config-hash-a"


def test_auto_review_runs_contained_workspace_command_without_prompt(monkeypatch):
    _runtime(monkeypatch, permission_preset="auto_review")
    _install(("exec_command", "on_request", "execute"))
    calls = []
    executor = ToolExecutor()
    executor.register_tool("exec_command", lambda **kwargs: calls.append(kwargs) or "ok")

    result, action = executor.execute(
        "exec_command",
        {"cmd": "echo ready", "cwd": "."},
        tool_call_id="call-command",
    )

    assert result == "ok"
    assert action is None
    assert calls == [{"cmd": "echo ready", "cwd": "."}]
    assert tool_approvals.list_tool_approval_requests("session-a", status="pending") == []


def test_full_access_runs_network_and_always_approval_tools_without_prompt(monkeypatch):
    _runtime(monkeypatch, permission_preset="full_access")
    _install(
        ("web_search_tool", "on_request", "network"),
        ("trigger_self_restart_tool", "always", "destructive"),
    )
    executor = ToolExecutor()
    calls = []
    executor.register_tool("web_search_tool", lambda **kwargs: calls.append(("network", kwargs)) or "network-ok")
    executor.register_tool(
        "trigger_self_restart_tool",
        lambda **kwargs: calls.append(("restart", kwargs)) or "restart-ok",
    )

    network, _ = executor.execute(
        "web_search_tool",
        {"query": "full access"},
        tool_call_id="call-network",
    )
    restart, _ = executor.execute(
        "trigger_self_restart_tool",
        {},
        tool_call_id="call-restart",
    )

    assert network == "network-ok"
    assert restart == "restart-ok"
    assert [item[0] for item in calls] == ["network", "restart"]
    assert tool_approvals.list_tool_approval_requests("session-a", status="pending") == []


def test_network_tool_waits_for_single_call_user_approval(monkeypatch):
    _runtime(monkeypatch)
    _install(("web_search_tool", "on_request", "network"))
    calls = []
    executor = ToolExecutor()
    executor.register_tool("web_search_tool", lambda **kwargs: calls.append(kwargs) or "network-ok")
    result_box = {}

    worker = threading.Thread(
        target=lambda: (
            _install(("web_search_tool", "on_request", "network")),
            result_box.setdefault(
                "value",
                executor.execute(
                    "web_search_tool",
                    {"query": "Codex approvals"},
                    tool_call_id="call-network",
                ),
            ),
        )
    )
    worker.start()
    request = _wait_for_pending()

    assert calls == []
    assert request["toolName"] == "web_search_tool"
    assert request["availableDecisions"] == ["accept", "acceptForSession", "decline", "cancel"]
    assert "query" not in request
    assert request["argumentsHash"]

    resolved = tool_approvals.resolve_tool_approval_request(
        "session-a",
        request["requestId"],
        decision="accept",
    )
    worker.join(timeout=2)

    assert resolved["status"] == "accepted"
    assert not worker.is_alive()
    assert result_box["value"] == ("network-ok", None)
    assert calls == [{"query": "Codex approvals"}]


def test_declined_approval_never_reaches_tool_implementation(monkeypatch):
    _runtime(monkeypatch)
    _install(("web_search_tool", "on_request", "network"))
    calls = []
    executor = ToolExecutor()
    executor.register_tool("web_search_tool", lambda **kwargs: calls.append(kwargs) or "unsafe")
    result_box = {}
    worker = threading.Thread(
        target=lambda: (
            _install(("web_search_tool", "on_request", "network")),
            result_box.setdefault(
                "value",
                executor.execute(
                    "web_search_tool",
                    {"query": "private"},
                    tool_call_id="call-decline",
                ),
            ),
        )
    )
    worker.start()
    request = _wait_for_pending()

    tool_approvals.resolve_tool_approval_request(
        "session-a",
        request["requestId"],
        decision="decline",
    )
    worker.join(timeout=2)

    result, action = result_box["value"]
    assert "用户拒绝" in result
    assert action is None
    assert calls == []


def test_approval_audit_is_bounded_and_excludes_raw_arguments(monkeypatch):
    _runtime(monkeypatch)
    _install(("web_search_tool", "on_request", "network"))
    events = []
    monkeypatch.setattr(
        tool_approvals,
        "_record_approval_event",
        lambda event_code, request, *, outcome: events.append(
            (event_code, outcome, request.public_projection())
        ),
    )
    result_box = {}
    worker = threading.Thread(
        target=lambda: (
            _install(("web_search_tool", "on_request", "network")),
            result_box.setdefault(
                "value",
                tool_authorization_service.authorize_tool_execution(
                    tool_name="web_search_tool",
                    tool_call_id="call-audit",
                    tool_args={"query": "secret query text"},
                ),
            ),
        )
    )
    worker.start()
    request = _wait_for_pending()
    tool_approvals.resolve_tool_approval_request(
        "session-a",
        request["requestId"],
        decision="decline",
    )
    worker.join(timeout=2)

    assert [(event, outcome) for event, outcome, _ in events] == [
        ("tool.approval.requested", "pending"),
        ("tool.approval.resolved", "declined"),
    ]
    assert all("secret query text" not in str(projection) for _, _, projection in events)


def test_accept_for_session_is_bound_to_same_tool_and_arguments(monkeypatch):
    _runtime(monkeypatch)
    _install(("web_search_tool", "on_request", "network"))
    calls = []
    executor = ToolExecutor()
    executor.register_tool("web_search_tool", lambda **kwargs: calls.append(kwargs) or "ok")
    first_box = {}
    first = threading.Thread(
        target=lambda: (
            _install(("web_search_tool", "on_request", "network")),
            first_box.setdefault(
                "value",
                executor.execute(
                    "web_search_tool",
                    {"query": "same"},
                    tool_call_id="call-first",
                ),
            ),
        )
    )
    first.start()
    request = _wait_for_pending()
    tool_approvals.resolve_tool_approval_request(
        "session-a",
        request["requestId"],
        decision="acceptForSession",
    )
    first.join(timeout=2)

    same, _ = executor.execute(
        "web_search_tool",
        {"query": "same"},
        tool_call_id="call-same",
    )
    assert same == "ok"
    assert tool_approvals.list_tool_approval_requests("session-a", status="pending") == []

    different_box = {}
    different = threading.Thread(
        target=lambda: (
            _install(("web_search_tool", "on_request", "network")),
            different_box.setdefault(
                "value",
                executor.execute(
                    "web_search_tool",
                    {"query": "different"},
                    tool_call_id="call-different",
                ),
            ),
        )
    )
    different.start()
    second_request = _wait_for_pending()
    assert second_request["argumentsHash"] != request["argumentsHash"]
    tool_approvals.resolve_tool_approval_request(
        "session-a",
        second_request["requestId"],
        decision="cancel",
    )
    different.join(timeout=2)

    assert calls == [{"query": "same"}, {"query": "same"}]
    assert "已取消" in different_box["value"][0]


def test_session_grant_is_invalidated_by_the_next_agent_config_revision(monkeypatch):
    _runtime(monkeypatch, permission_preset="request_approval", config_revision=3)
    _install(("web_search_tool", "on_request", "network"))
    first_box = {}
    first = threading.Thread(
        target=lambda: (
            _install(("web_search_tool", "on_request", "network")),
            first_box.setdefault(
                "value",
                tool_authorization_service.authorize_tool_execution(
                    tool_name="web_search_tool",
                    tool_call_id="call-grant",
                    tool_args={"query": "same"},
                ),
            ),
        )
    )
    first.start()
    request = _wait_for_pending()
    tool_approvals.resolve_tool_approval_request(
        "session-a",
        request["requestId"],
        decision="acceptForSession",
    )
    first.join(timeout=2)
    assert first_box["value"].allowed is True

    _runtime(
        monkeypatch,
        permission_preset="request_approval",
        config_revision=4,
        config_hash="config-hash-b",
    )
    _install(("web_search_tool", "on_request", "network"))
    second_box = {}
    second = threading.Thread(
        target=lambda: (
            _install(("web_search_tool", "on_request", "network")),
            second_box.setdefault(
                "value",
                tool_authorization_service.authorize_tool_execution(
                    tool_name="web_search_tool",
                    tool_call_id="call-next-revision",
                    tool_args={"query": "same"},
                ),
            ),
        )
    )
    second.start()
    next_request = _wait_for_pending()

    assert next_request["requestId"] != request["requestId"]
    assert next_request["configRevision"] == 4
    tool_approvals.resolve_tool_approval_request(
        "session-a",
        next_request["requestId"],
        decision="cancel",
    )
    second.join(timeout=2)


def test_turn_stop_cancels_waiting_approval(monkeypatch):
    _runtime(monkeypatch)
    _install(("web_search_tool", "on_request", "network"))
    stopped = threading.Event()
    result_box = {}

    worker = threading.Thread(
        target=lambda: (
            _install(("web_search_tool", "on_request", "network")),
            result_box.setdefault(
                "value",
                tool_authorization_service.authorize_tool_execution(
                    tool_name="web_search_tool",
                    tool_call_id="call-stop",
                    tool_args={"query": "cancel me"},
                    cancel_checker=lambda: "user_stop" if stopped.is_set() else "",
                ),
            ),
        )
    )
    worker.start()
    request = _wait_for_pending()
    stopped.set()
    worker.join(timeout=2)

    assert not worker.is_alive()
    assert result_box["value"].allowed is False
    assert result_box["value"].code == "approval_cancelled"
    assert tool_approvals.get_tool_approval_request("session-a", request["requestId"])["status"] == "cancelled"


def test_service_reset_fails_closed_for_pending_requests(monkeypatch):
    _runtime(monkeypatch)
    _install(("web_search_tool", "on_request", "network"))
    result_box = {}
    worker = threading.Thread(
        target=lambda: (
            _install(("web_search_tool", "on_request", "network")),
            result_box.setdefault(
                "value",
                tool_authorization_service.authorize_tool_execution(
                    tool_name="web_search_tool",
                    tool_call_id="call-reset",
                    tool_args={"query": "restart"},
                ),
            ),
        )
    )
    worker.start()
    _wait_for_pending()

    tool_approvals.reset_tool_approval_state()
    worker.join(timeout=2)

    assert not worker.is_alive()
    assert result_box["value"].allowed is False
    assert result_box["value"].code == "approval_cancelled"
