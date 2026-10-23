from copy import deepcopy
import json
import threading
import time
from types import SimpleNamespace

import pytest

from core.authorization import tool_authorization_service
from core.infrastructure.tool_executor import ToolExecutor
from core.web.services import agent_directory_service
from core.web.services.session import tool_approvals


@pytest.fixture()
def _agent_directory_state(monkeypatch):
    def agent(agent_id, *, default_policy=False):
        policy_id = (
            agent_directory_service.DEFAULT_TOOL_POLICY_ID
            if default_policy
            else f"tool-{agent_id}"
        )
        return {
            "agentId": agent_id,
            "configRevision": 3,
            "configHash": f"config-hash-{agent_id}",
            "toolPolicyId": policy_id,
            "toolPolicy": {
                "policyId": policy_id,
                "policyVersion": 1,
                "allowedTools": ["exec_command", "web_search_tool"],
                "preferredTools": [],
                "blockedTools": [],
                "maxCallsPerTurn": 20,
                "perToolRules": {},
            },
        }

    state = {
        "agents": {
            "agent-a": agent("agent-a"),
            "agent-b": agent("agent-b"),
            "agent-default": agent("agent-default", default_policy=True),
        },
        "updates": [],
    }

    def get_agent(agent_id, **_kwargs):
        current = state["agents"].get(agent_id)
        return deepcopy(current) if current else None

    def list_agents(**_kwargs):
        return [deepcopy(item) for item in state["agents"].values()]

    def resolve_tool_policy_for_agent(agent_id, **_kwargs):
        current = state["agents"].get(agent_id)
        return deepcopy((current or {}).get("toolPolicy") or {})

    def update_agent_instance(
        agent_id,
        *,
        tool_policy=None,
        expected_config_revision=None,
        expected_tool_policy_fingerprint="",
        **_kwargs,
    ):
        current = state["agents"].get(agent_id)
        if current is None:
            raise agent_directory_service.AgentNotFoundError(f"Agent not found: {agent_id}")
        if (
            expected_config_revision is not None
            and current["configRevision"] != expected_config_revision
        ):
            raise agent_directory_service.AgentStateConflictError(
                "Agent configuration revision changed. Refresh and retry."
            )
        current_policy = deepcopy(current["toolPolicy"])
        if current["toolPolicyId"] == agent_directory_service.DEFAULT_TOOL_POLICY_ID:
            current["toolPolicyId"] = f"tool-{agent_id}"
            current_policy["policyId"] = current["toolPolicyId"]
        if (
            expected_tool_policy_fingerprint
            and agent_directory_service.tool_policy_fingerprint(current_policy)
            != expected_tool_policy_fingerprint
        ):
            raise agent_directory_service.AgentStateConflictError(
                "ToolPolicy changed after this editor was opened. Refresh and retry."
            )
        updated_policy = deepcopy(tool_policy or current_policy)
        updated_policy["policyVersion"] = int(current_policy.get("policyVersion") or 1) + 1
        current["toolPolicy"] = updated_policy
        current["configRevision"] += 1
        current["configHash"] = f"config-hash-{agent_id}-r{current['configRevision']}"
        state["updates"].append(deepcopy(current))
        return deepcopy(current)

    monkeypatch.setattr(agent_directory_service, "get_agent", get_agent)
    monkeypatch.setattr(agent_directory_service, "list_agents", list_agents)
    monkeypatch.setattr(
        agent_directory_service,
        "resolve_tool_policy_for_agent",
        resolve_tool_policy_for_agent,
    )
    monkeypatch.setattr(agent_directory_service, "update_agent_instance", update_agent_instance)
    monkeypatch.setattr(
        tool_approvals,
        "_canonical_agent_configs",
        lambda agent_id="": [
            deepcopy(item)
            for key, item in state["agents"].items()
            if not agent_id or key == agent_id
        ],
    )
    return state


@pytest.fixture(autouse=True)
def _reset_approval_state():
    tool_approvals.reset_tool_approval_state(clear_durable=False)
    tool_authorization_service.clear_execution_authorization()
    yield
    tool_approvals.reset_tool_approval_state(clear_durable=False)
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


def test_agent_private_memory_search_runs_without_per_call_approval(monkeypatch, _agent_directory_state):
    _runtime(monkeypatch, permission_preset="request_approval")
    _install(("search_agent_private_memory_tool", "never", "read"))
    calls = []
    executor = ToolExecutor()
    executor.register_tool(
        "search_agent_private_memory_tool",
        lambda **kwargs: calls.append(kwargs) or "private-memory-results",
    )

    result, action = executor.execute(
        "search_agent_private_memory_tool",
        {"query": "saved preference"},
        tool_call_id="call-private-memory-search",
    )

    assert result == "private-memory-results"
    assert action is None
    assert calls == [{"query": "saved preference"}]
    assert tool_approvals.list_tool_approval_requests("session-a", status="pending") == []


def test_session_attachment_staging_waits_for_per_call_approval(monkeypatch):
    _runtime(monkeypatch, permission_preset="request_approval")
    _install(("knowledge_stage_session_attachment_tool", "on_request", "write"))
    calls = []
    executor = ToolExecutor()
    executor.register_tool(
        "knowledge_stage_session_attachment_tool",
        lambda **kwargs: calls.append(kwargs) or "staged",
    )
    result_box = {}

    worker = threading.Thread(
        target=lambda: (
            _install(("knowledge_stage_session_attachment_tool", "on_request", "write")),
            result_box.setdefault(
                "value",
                executor.execute(
                    "knowledge_stage_session_attachment_tool",
                    {"attachment_id": "attachment-1"},
                    tool_call_id="call-stage-attachment",
                ),
            ),
        )
    )
    worker.start()
    request = _wait_for_pending()
    tool_approvals.resolve_tool_approval_request("session-a", request["requestId"], decision="accept")
    worker.join(timeout=2)

    assert result_box["value"] == ("staged", None)
    assert calls == [{"attachment_id": "attachment-1"}]
    assert request["toolName"] == "knowledge_stage_session_attachment_tool"


def test_request_approval_auto_approves_safe_readonly_git_cli(monkeypatch):
    """Models often call git via cli_tool; pure reads should not force a popup."""
    _runtime(monkeypatch, permission_preset="request_approval")
    _install(("exec_command", "on_request", "execute"))
    calls = []
    executor = ToolExecutor()
    executor.register_tool("exec_command", lambda **kwargs: calls.append(kwargs) or "main")

    result, action = executor.execute(
        "exec_command",
        {"cmd": "git branch -a", "cwd": "."},
        tool_call_id="call-git-branch",
    )

    assert result == "main"
    assert action is None
    assert calls == [{"cmd": "git branch -a", "cwd": "."}]
    assert tool_approvals.list_tool_approval_requests("session-a", status="pending") == []


def test_request_approval_still_prompts_for_mutating_git_cli(monkeypatch):
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
                    {"cmd": "git commit -m ok", "cwd": "."},
                    tool_call_id="call-git-commit",
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
    assert calls == [{"cmd": "git commit -m ok", "cwd": "."}]
    assert request["toolName"] == "exec_command"


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
    assert request["availableDecisions"] == [
        "accept",
        "acceptForSession",
        "acceptAlways",
        "decline",
        "cancel",
    ]
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


@pytest.mark.parametrize("decision", ["accept", "decline"])
def test_peer_message_capability_still_requires_native_approval(monkeypatch, decision):
    from dataclasses import replace
    from core.infrastructure.agent_session import reset_session_state
    from core.orchestration.agent_modes import AgentMode, resolve_mode_policy
    from core.orchestration.runtime_goal import build_runtime_goal_packet

    _runtime(monkeypatch)
    packet = build_runtime_goal_packet(
        resolve_mode_policy(AgentMode.CHAT, SimpleNamespace()), "Authorized team message"
    )
    reset_session_state().set_runtime_goal_packet(replace(packet, allow_subagents=False))
    executor = ToolExecutor()
    calls = []
    executor.register_tool("agent_message_tool", lambda **args: calls.append(args) or "delivered")
    args = {"content": "PING", "target_session": "peer-session", "target_agent": "peer-agent"}
    result_box = {}

    def execute():
        _install(("agent_message_tool", "on_request", "write"))
        result_box["value"] = executor.execute(
            "agent_message_tool", args, tool_call_id="call-peer-message"
        )

    worker = threading.Thread(target=execute)
    worker.start()
    try:
        request = _wait_for_pending()
        assert calls == []
        assert request["toolName"] == "agent_message_tool"
        tool_approvals.resolve_tool_approval_request(
            "session-a", request["requestId"], decision=decision
        )
    finally:
        worker.join(timeout=3)

    assert not worker.is_alive()
    result, action = result_box["value"]
    assert action is None
    if decision == "accept":
        assert calls == [args]
        assert result == "delivered"
    else:
        assert calls == []
        assert "用户拒绝" in result


def test_peer_message_capability_cannot_override_canonical_denial(monkeypatch):
    from dataclasses import replace
    from core.infrastructure.agent_session import reset_session_state
    from core.orchestration.agent_modes import AgentMode, resolve_mode_policy
    from core.orchestration.runtime_goal import build_runtime_goal_packet

    _runtime(monkeypatch)
    packet = build_runtime_goal_packet(
        resolve_mode_policy(AgentMode.CHAT, SimpleNamespace()), "Authorized team message"
    )
    reset_session_state().set_runtime_goal_packet(replace(packet, allow_subagents=False))
    _install()  # The turn's actual authorization decision contains no tools.
    executor = ToolExecutor()
    calls = []
    executor.register_tool("agent_message_tool", lambda **args: calls.append(args) or "delivered")

    result, action = executor.execute(
        "agent_message_tool", {"target_session": "peer-session", "content": "PING"},
        tool_call_id="call-peer-denied",
    )

    assert action is None
    assert "delivered" not in str(result)
    assert calls == []
    assert tool_approvals.list_tool_approval_requests("session-a", status="pending") == []


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


def test_write_stdin_session_grant_is_bound_to_terminal_not_input_chars(monkeypatch):
    _runtime(monkeypatch)
    _install(("write_stdin", "on_request", "write"))
    calls = []
    executor = ToolExecutor()
    executor.register_tool("write_stdin", lambda **kwargs: calls.append(kwargs) or "ok")
    first_box = {}
    first = threading.Thread(
        target=lambda: (
            _install(("write_stdin", "on_request", "write")),
            first_box.setdefault(
                "value",
                executor.execute(
                    "write_stdin",
                    {"session_id": "sandbox-terminal-a", "chars": "READY\n"},
                    tool_call_id="call-stdin-first",
                ),
            ),
        )
    )
    first.start()
    request = _wait_for_pending()

    assert request["sessionGrantScope"] == {
        "kind": "terminal_session",
        "terminalSessionId": "sandbox-terminal-a",
    }
    assert request["argumentSummary"]["terminalSessionId"] == "sandbox-terminal-a"
    assert request["argumentSummary"]["stdinPreview"] == "READY\n"
    assert request["argumentSummary"]["stdinChars"] == 6

    tool_approvals.resolve_tool_approval_request(
        "session-a",
        request["requestId"],
        decision="acceptForSession",
    )
    first.join(timeout=2)

    same_terminal, _ = executor.execute(
        "write_stdin",
        {"session_id": "sandbox-terminal-a", "chars": "ORBIT-71\n"},
        tool_call_id="call-stdin-same-terminal",
    )

    assert same_terminal == "ok"
    assert tool_approvals.list_tool_approval_requests("session-a", status="pending") == []
    assert calls == [
        {"session_id": "sandbox-terminal-a", "chars": "READY\n"},
        {"session_id": "sandbox-terminal-a", "chars": "ORBIT-71\n"},
    ]


def test_exec_approval_summary_includes_command_and_cwd():
    summary = tool_approvals._argument_summary(
        "exec_command",
        {
            "cmd": '.\\.venv\\Scripts\\python.exe -c "print(123)"',
            "cwd": r"C:\workspace\repo",
        },
    )

    assert summary["commandPreview"] == '.\\.venv\\Scripts\\python.exe -c "print(123)"'
    assert summary["cwdPreview"] == r"C:\workspace\repo"


def test_assistant_management_approval_identifies_action_and_target_without_private_values():
    summary = tool_approvals._argument_summary(
        "personal_assistant_manage_tool",
        {"action": "session_create", "arguments_json": '{"agent_id":"agent-a","title":"Acceptance test"}'},
    )
    assert summary["assistantAction"] == "session_create"
    assert summary["assistantTargets"] == {"agent_id": "agent-a", "title": "Acceptance test"}
    private = tool_approvals._argument_summary(
        "personal_assistant_manage_tool",
        {"action": "agent_update", "arguments_json": json.dumps({"agent_id": "agent-a", "updates_json": json.dumps({"personaProfile": "PRIVATE PROMPT", "toolPolicy": "SECRET"})})},
    )
    assert private["assistantTargets"] == {"agent_id": "agent-a"}
    assert private["assistantChangedFields"] == ["personaProfile", "toolPolicy"]
    assert "PRIVATE PROMPT" not in str(private) and "SECRET" not in str(private)


@pytest.mark.parametrize("raw", ["{broken", "[]", '"secret"', "x" * 16001])
def test_assistant_management_approval_rejects_unparseable_details(raw):
    summary = tool_approvals._argument_summary(
        "personal_assistant_manage_tool", {"action": "session_delete", "arguments_json": raw},
    )
    assert summary["assistantArgumentsInvalid"] is True
    assert "assistantTargets" not in summary


def test_assistant_management_approval_bounds_fields_and_does_not_expand_other_tools():
    import json

    summary = tool_approvals._argument_summary("personal_assistant_manage_tool", {
        "action": "session_update", "arguments_json": json.dumps({
            "session_id": "session-a\nspoof", "title": "a\n" + "b" * 300, "password": "SECRET",
        }),
    })
    assert "session_id" not in summary["assistantTargets"]
    assert len(summary["assistantTargets"]["title"]) <= 120
    assert "\n" not in summary["assistantTargets"]["title"]
    assert summary["assistantDetailsOmitted"] is True
    assert "SECRET" not in str(summary)
    assert "assistantAction" not in tool_approvals._argument_summary(
        "another_tool", {"action": "session_create", "arguments_json": "{}"},
    )


def test_assistant_management_approval_projects_nested_workflow_roles_and_acl_defaults():
    first = {"team_id": "team-a", "flow_id": "flow-a", "payload": {
        "directorAgentId": "director-a", "developerAgentId": "developer-a", "reviewerAgentId": "reviewer-a",
        "repairFlowId": "repair-a", "validForSeconds": 3600, "acknowledgeAutomaticRecovery": True,
        "inputs": {"private": "SECRET"},
    }}
    summary = tool_approvals._argument_summary("personal_assistant_manage_tool", {
        "action": "workflow_recovery_bind", "arguments_json": json.dumps(first),
    })
    assert summary["assistantTargets"]["payload.developerAgentId"] == "developer-a"
    assert summary["assistantTargets"]["payload.validForSeconds"] == "3600"
    assert summary["assistantDetailsOmitted"] and "SECRET" not in str(summary)
    args = {"knowledge_base_id": "kb-a", "target_agent_id": "agent-a"}
    def acl():
        return tool_approvals._argument_summary("personal_assistant_manage_tool", {
            "action": "knowledge_acl_grant", "arguments_json": json.dumps(args),
        })
    assert acl()["assistantPermissions"] == ["propose", "read"]
    args["permissions_json"] = '["review"]'
    assert acl()["assistantPermissions"] == ["review"]
    args["permissions_json"] = '["SECRET"]'
    assert acl()["assistantArgumentsInvalid"] is True
    assert "SECRET" not in str(acl())


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


def test_accept_always_persists_in_agent_tool_policy_across_process_reset(
    monkeypatch,
    _agent_directory_state,
):
    monkeypatch.setattr(
        agent_directory_service,
        "resolve_tool_policy_for_agent",
        lambda *_args, **_kwargs: pytest.fail(
            "durable approval must not persist a runtime-effective ToolPolicy projection"
        ),
    )
    _runtime(monkeypatch, session_id="session-a")
    _install(("web_search_tool", "on_request", "network"))
    first_box = {}
    first = threading.Thread(
        target=lambda: (
            _install(("web_search_tool", "on_request", "network")),
            first_box.setdefault(
                "value",
                tool_authorization_service.authorize_tool_execution(
                    tool_name="web_search_tool",
                    tool_call_id="call-always-first",
                    tool_args={"query": "same"},
                ),
            ),
        )
    )
    first.start()
    request = _wait_for_pending("session-a")
    resolved = tool_approvals.resolve_tool_approval_request(
        "session-a",
        request["requestId"],
        decision="acceptAlways",
    )
    first.join(timeout=2)

    assert resolved["status"] == "accepted_always"
    assert first_box["value"].allowed is True
    grants = tool_approvals.list_durable_tool_approval_grants(agent_id="agent-a")
    assert len(grants) == 1
    assert grants[0]["toolName"] == "web_search_tool"
    persisted_agent = _agent_directory_state["agents"]["agent-a"]
    persisted_rule = persisted_agent["toolPolicy"]["perToolRules"]["web_search_tool"]
    assert persisted_rule["approvalGrants"] == [
        {
            "grantKey": grants[0]["grantKey"],
            "scope": grants[0]["scope"],
            "createdAt": grants[0]["createdAt"],
            "updatedAt": grants[0]["updatedAt"],
            "sourceSessionId": "session-a",
            "sourceRequestId": request["requestId"],
        }
    ]
    assert persisted_agent["configRevision"] == 4
    assert len(_agent_directory_state["updates"]) == 1

    # Drop only ephemeral process state; Agent ToolPolicy remains authoritative.
    tool_approvals.reset_tool_approval_state(clear_durable=False)

    _runtime(
        monkeypatch,
        session_id="session-b",
        config_revision=persisted_agent["configRevision"],
        config_hash=persisted_agent["configHash"],
    )
    _install(("web_search_tool", "on_request", "network"))
    second = tool_authorization_service.authorize_tool_execution(
        tool_name="web_search_tool",
        tool_call_id="call-always-second",
        tool_args={"query": "same"},
    )
    assert second.allowed is True
    assert second.code == "approved_for_agent"
    assert tool_approvals.list_tool_approval_requests("session-b", status="pending") == []


def test_accept_always_is_isolated_by_agent_and_arguments(
    monkeypatch,
    _agent_directory_state,
):
    _runtime(monkeypatch, session_id="session-a")
    _install(("web_search_tool", "on_request", "network"))
    first_box = {}
    first = threading.Thread(
        target=lambda: (
            _install(("web_search_tool", "on_request", "network")),
            first_box.setdefault(
                "value",
                tool_authorization_service.authorize_tool_execution(
                    tool_name="web_search_tool",
                    tool_call_id="call-iso-first",
                    tool_args={"query": "alpha"},
                ),
            ),
        )
    )
    first.start()
    request = _wait_for_pending()
    tool_approvals.resolve_tool_approval_request(
        "session-a",
        request["requestId"],
        decision="acceptAlways",
    )
    first.join(timeout=2)
    assert first_box["value"].allowed is True

    # Different arguments still require approval.
    different_box = {}
    different = threading.Thread(
        target=lambda: (
            _install(("web_search_tool", "on_request", "network")),
            different_box.setdefault(
                "value",
                tool_authorization_service.authorize_tool_execution(
                    tool_name="web_search_tool",
                    tool_call_id="call-iso-args",
                    tool_args={"query": "beta"},
                ),
            ),
        )
    )
    different.start()
    other_request = _wait_for_pending()
    assert other_request["argumentsHash"] != request["argumentsHash"]
    tool_approvals.resolve_tool_approval_request(
        "session-a",
        other_request["requestId"],
        decision="cancel",
    )
    different.join(timeout=2)
    assert different_box["value"].allowed is False

    # Different agent still requires approval for the same arguments.
    tool_approvals.reset_tool_approval_state(clear_durable=False)
    foreign_box = {}
    foreign = threading.Thread(
        target=lambda: foreign_box.setdefault(
            "value",
            tool_approvals.authorize_or_wait(
                session_id="session-a",
                turn_id="turn-a",
                agent_id="agent-b",
                call_id="call-iso-agent",
                tool_name="web_search_tool",
                tool_args={"query": "alpha"},
                approval="on_request",
                risk="network",
                decision_fingerprint="decision-b",
                config_revision=3,
                config_hash="config-hash-a",
                permission_preset="request_approval",
            ),
        )
    )
    foreign.start()
    foreign_request = _wait_for_pending()
    assert foreign_request["agentId"] == "agent-b"
    tool_approvals.resolve_tool_approval_request(
        "session-a",
        foreign_request["requestId"],
        decision="cancel",
    )
    foreign.join(timeout=2)
    assert foreign_box["value"].allowed is False
    assert foreign_box["value"].code == "approval_cancelled"


def test_accept_always_merges_onto_live_agent_when_request_revision_is_stale(
    monkeypatch,
    _agent_directory_state,
):
    """Turn-frozen request revision lags after a prior acceptAlways; grant still persists."""
    _runtime(monkeypatch, session_id="session-a")
    _install(("web_search_tool", "on_request", "network"))
    result_box = {}
    worker = threading.Thread(
        target=lambda: (
            _install(("web_search_tool", "on_request", "network")),
            result_box.setdefault(
                "value",
                tool_authorization_service.authorize_tool_execution(
                    tool_name="web_search_tool",
                    tool_call_id="call-always-stale",
                    tool_args={"query": "stale"},
                ),
            ),
        )
    )
    worker.start()
    request = _wait_for_pending()
    # Simulate another durable grant / config write that advanced the Agent revision
    # while this approval request still carries the older turn snapshot revision.
    _agent_directory_state["agents"]["agent-a"]["configRevision"] = 4
    _agent_directory_state["agents"]["agent-a"]["configHash"] = "config-hash-agent-a-r4"

    resolved = tool_approvals.resolve_tool_approval_request(
        "session-a",
        request["requestId"],
        decision="acceptAlways",
    )
    worker.join(timeout=2)

    assert resolved["status"] == "accepted_always"
    assert result_box["value"].allowed is True
    grants = tool_approvals.list_durable_tool_approval_grants(agent_id="agent-a")
    assert len(grants) == 1
    assert grants[0]["toolName"] == "web_search_tool"
    assert _agent_directory_state["agents"]["agent-a"]["configRevision"] == 5


def test_consecutive_accept_always_with_different_args_does_not_409(
    monkeypatch,
    _agent_directory_state,
):
    """Reproduce chat mid-turn chain: always on call A then always on call B."""
    _runtime(monkeypatch, session_id="session-a", config_revision=14)
    _agent_directory_state["agents"]["agent-a"]["configRevision"] = 14
    _agent_directory_state["agents"]["agent-a"]["configHash"] = "config-hash-agent-a-r14"

    def run_call(call_id: str, query: str):
        _install(("web_search_tool", "on_request", "network"))
        box = {}
        worker = threading.Thread(
            target=lambda: (
                _install(("web_search_tool", "on_request", "network")),
                box.setdefault(
                    "value",
                    tool_authorization_service.authorize_tool_execution(
                        tool_name="web_search_tool",
                        tool_call_id=call_id,
                        tool_args={"query": query},
                    ),
                ),
            )
        )
        worker.start()
        request = _wait_for_pending("session-a")
        resolved = tool_approvals.resolve_tool_approval_request(
            "session-a",
            request["requestId"],
            decision="acceptAlways",
        )
        worker.join(timeout=2)
        return resolved, box["value"]

    first_resolved, first_outcome = run_call("call-always-a", "alpha")
    assert first_resolved["status"] == "accepted_always"
    assert first_outcome.allowed is True
    assert _agent_directory_state["agents"]["agent-a"]["configRevision"] == 15

    # Second call still uses turn snapshot revision 14 (runtime context is frozen).
    second_resolved, second_outcome = run_call("call-always-b", "beta")
    assert second_resolved["status"] == "accepted_always"
    assert second_outcome.allowed is True
    grants = tool_approvals.list_durable_tool_approval_grants(agent_id="agent-a")
    assert {item["scope"].get("argumentsHash") for item in grants if item.get("scope")}
    assert len(grants) == 2
    assert _agent_directory_state["agents"]["agent-a"]["configRevision"] == 16


def test_accept_always_fails_closed_when_agent_disappears_mid_write(
    monkeypatch,
    _agent_directory_state,
):
    _runtime(monkeypatch, session_id="session-a")
    _install(("web_search_tool", "on_request", "network"))
    result_box = {}
    worker = threading.Thread(
        target=lambda: (
            _install(("web_search_tool", "on_request", "network")),
            result_box.setdefault(
                "value",
                tool_authorization_service.authorize_tool_execution(
                    tool_name="web_search_tool",
                    tool_call_id="call-always-missing",
                    tool_args={"query": "gone"},
                ),
            ),
        )
    )
    worker.start()
    request = _wait_for_pending()
    del _agent_directory_state["agents"]["agent-a"]

    with pytest.raises(
        tool_approvals.ToolApprovalConflictError,
        match="not found",
    ):
        tool_approvals.resolve_tool_approval_request(
            "session-a",
            request["requestId"],
            decision="acceptAlways",
        )

    pending = tool_approvals.get_tool_approval_request("session-a", request["requestId"])
    assert pending["status"] == "pending"
    tool_approvals.resolve_tool_approval_request(
        "session-a",
        request["requestId"],
        decision="cancel",
    )
    worker.join(timeout=2)
    assert result_box["value"].allowed is False


def test_accept_always_materializes_agent_owned_policy_from_default(
    _agent_directory_state,
):
    tool_approvals._add_durable_grant(
        agent_id="agent-default",
        tool_name="web_search_tool",
        grant_key="grant-default",
        scope={"kind": "arguments", "argumentsHash": "hash-default"},
        source_session_id="session-default",
        source_request_id="approval-default",
        expected_config_revision=3,
    )

    persisted = _agent_directory_state["agents"]["agent-default"]
    assert persisted["toolPolicyId"] == "tool-agent-default"
    assert persisted["toolPolicy"]["policyId"] == "tool-agent-default"
    grants = persisted["toolPolicy"]["perToolRules"]["web_search_tool"][
        "approvalGrants"
    ]
    assert [item["grantKey"] for item in grants] == ["grant-default"]


def test_accept_always_persists_through_real_agent_directory_authority(
    tmp_path,
    monkeypatch,
):
    from tests.helpers.system_agent_state import _mark_config_agent_instances_present
    from tests.test_agent_config_workspace_service import _use_tmp_project_root

    _use_tmp_project_root(tmp_path, monkeypatch)
    _mark_config_agent_instances_present()
    agent = agent_directory_service.create_agent_instance(
        display_name="Durable approval Agent",
        primary_mode="chat",
    )

    tool_approvals._add_durable_grant(
        agent_id=agent["agentId"],
        tool_name="web_search_tool",
        grant_key="grant-real-directory",
        scope={"kind": "arguments", "argumentsHash": "hash-real-directory"},
        source_session_id="session-real-directory",
        source_request_id="approval-real-directory",
        expected_config_revision=agent["configRevision"],
    )

    persisted = tool_approvals._canonical_agent_configs(agent["agentId"])[0]
    assert persisted["configRevision"] == agent["configRevision"] + 1
    assert persisted["toolPolicyId"] == f"tool-{agent['agentId']}"
    rule = persisted["toolPolicy"]["perToolRules"]["web_search_tool"]
    assert [item["grantKey"] for item in rule["approvalGrants"]] == [
        "grant-real-directory"
    ]


def test_url_host_scope_parses_host_and_falls_back_to_exact_arguments():
    # Origin 级（scheme+host+port）：批准一个页面只授权用户看到的精确 origin，
    # 不跨 scheme、不跨端口授权同一公网 host。
    assert tool_approvals._url_host_scope(
        "web_fetch_tool",
        {"url": "https://Docs.Example.com/guide/intro"},
    ) == {"kind": "url_origin", "origin": "https://docs.example.com"}
    assert tool_approvals._url_host_scope(
        "web_fetch_tool",
        {"url": "http://docs.example.com:8080/panel"},
    ) == {"kind": "url_origin", "origin": "http://docs.example.com:8080"}
    assert (
        tool_approvals._url_host_scope(
            "web_fetch_tool",
            {"url": "https://docs.example.com:8443/other"},
        )
        != tool_approvals._url_host_scope(
            "web_fetch_tool",
            {"url": "https://docs.example.com/base"},
        )
    )
    assert tool_approvals._url_host_scope(
        "web_fetch_tool",
        {"url": "file:///etc/hosts"},
    ) is None
    assert tool_approvals._url_host_scope("web_fetch_tool", {"query": "no url"}) is None
    assert tool_approvals._url_host_scope(
        "web_search_tool",
        {"url": "https://docs.example.com/guide/intro"},
    ) is None


def _wait_for_web_fetch_always_grant(monkeypatch, *, call_id: str, url: str):
    """Approve one web_fetch URL with acceptAlways and return the resolved request."""

    _install(("web_fetch_tool", "on_request", "network"))
    box = {}
    worker = threading.Thread(
        target=lambda: (
            _install(("web_fetch_tool", "on_request", "network")),
            box.setdefault(
                "value",
                tool_authorization_service.authorize_tool_execution(
                    tool_name="web_fetch_tool",
                    tool_call_id=call_id,
                    tool_args={"url": url},
                ),
            ),
        )
    )
    worker.start()
    request = _wait_for_pending()
    resolved = tool_approvals.resolve_tool_approval_request(
        "session-a",
        request["requestId"],
        decision="acceptAlways",
    )
    worker.join(timeout=2)
    assert resolved["status"] == "accepted_always"
    assert box["value"].allowed is True
    return request


def test_web_fetch_accept_always_grants_host_level_reuse(
    monkeypatch,
    _agent_directory_state,
):
    """One acceptAlways on a web_fetch URL authorizes later paths on the same host."""
    _runtime(monkeypatch, session_id="session-a")
    _wait_for_web_fetch_always_grant(
        monkeypatch,
        call_id="call-fetch-first",
        url="https://docs.example.com/guide/intro",
    )

    grants = tool_approvals.list_durable_tool_approval_grants(agent_id="agent-a")
    host_grants = [
        item for item in grants if item["scope"].get("kind") == "url_origin"
    ]
    assert len(host_grants) == 1
    assert host_grants[0]["scope"] == {
        "kind": "url_origin",
        "origin": "https://docs.example.com",
    }
    # The legacy exact-arguments grant is still recorded alongside the host grant.
    assert len(grants) == 2

    # Same host, different path: no approval request, no wait.
    same_host = tool_authorization_service.authorize_tool_execution(
        tool_name="web_fetch_tool",
        tool_call_id="call-fetch-same-host",
        tool_args={"url": "https://docs.example.com/api/reference#auth"},
    )
    assert same_host.allowed is True
    assert same_host.code == "approved_for_session"
    assert tool_approvals.list_tool_approval_requests("session-a", status="pending") == []

    # The durable host grant also survives an ephemeral-state reset (new session).
    tool_approvals.reset_tool_approval_state(clear_durable=False)
    persisted_agent = _agent_directory_state["agents"]["agent-a"]
    _runtime(
        monkeypatch,
        session_id="session-b",
        config_revision=persisted_agent["configRevision"],
        config_hash=persisted_agent["configHash"],
    )
    _install(("web_fetch_tool", "on_request", "network"))
    across = tool_authorization_service.authorize_tool_execution(
        tool_name="web_fetch_tool",
        tool_call_id="call-fetch-across-session",
        tool_args={"url": "https://docs.example.com/another/page"},
    )
    assert across.allowed is True
    assert across.code == "approved_for_agent"
    assert tool_approvals.list_tool_approval_requests("session-b", status="pending") == []


def test_web_fetch_host_grant_does_not_cross_hosts_or_agents(
    monkeypatch,
    _agent_directory_state,
):
    _runtime(monkeypatch, session_id="session-a")
    _wait_for_web_fetch_always_grant(
        monkeypatch,
        call_id="call-fetch-first",
        url="https://docs.example.com/guide/intro",
    )

    # A different host still requires fresh approval.
    other_box = {}
    other = threading.Thread(
        target=lambda: (
            _install(("web_fetch_tool", "on_request", "network")),
            other_box.setdefault(
                "value",
                tool_authorization_service.authorize_tool_execution(
                    tool_name="web_fetch_tool",
                    tool_call_id="call-fetch-other-host",
                    tool_args={"url": "https://other-site.example.net/page"},
                ),
            ),
        )
    )
    other.start()
    other_request = _wait_for_pending()
    tool_approvals.resolve_tool_approval_request(
        "session-a",
        other_request["requestId"],
        decision="cancel",
    )
    other.join(timeout=2)
    assert other_box["value"].allowed is False
    assert other_box["value"].code == "approval_cancelled"

    # A different agent gains nothing from agent-a's host grant.
    tool_approvals.reset_tool_approval_state(clear_durable=False)
    foreign_box = {}
    foreign = threading.Thread(
        target=lambda: foreign_box.setdefault(
            "value",
            tool_approvals.authorize_or_wait(
                session_id="session-a",
                turn_id="turn-a",
                agent_id="agent-b",
                call_id="call-fetch-foreign-agent",
                tool_name="web_fetch_tool",
                tool_args={"url": "https://docs.example.com/guide/intro"},
                approval="on_request",
                risk="network",
                decision_fingerprint="decision-b",
                config_revision=3,
                config_hash="config-hash-a",
                permission_preset="request_approval",
            ),
        )
    )
    foreign.start()
    foreign_request = _wait_for_pending()
    assert foreign_request["agentId"] == "agent-b"
    tool_approvals.resolve_tool_approval_request(
        "session-a",
        foreign_request["requestId"],
        decision="cancel",
    )
    foreign.join(timeout=2)
    assert foreign_box["value"].allowed is False


def test_approval_timeout_message_declares_terminal_rejection(monkeypatch):
    """Timeout is a terminal fail-closed denial; the model must not retry blind."""
    outcome = tool_approvals.authorize_or_wait(
        session_id="session-a",
        turn_id="turn-a",
        agent_id="agent-a",
        call_id="call-timeout",
        tool_name="web_fetch_tool",
        tool_args={"url": "https://docs.example.com/slow"},
        approval="on_request",
        risk="network",
        decision_fingerprint="decision-a",
        config_revision=3,
        config_hash="config-hash-a",
        permission_preset="request_approval",
        timeout_seconds=0.2,
    )

    assert outcome.allowed is False
    assert outcome.code == "approval_timeout"
    assert "终态拒绝" in outcome.message
    assert "禁止以相同参数重试" in outcome.message
    assert "结束回合" in outcome.message


def _run_expiry_race(monkeypatch, *, cancel_reason: str, tag: str):
    """E3 过期边界竞态：决议恰在过期判定的同一轮询窗口内落账。

    用可控单调钟构造确定性序列：cancel_checker 在第一次被轮询时先把 pending
    请求 resolve 成 accept（模拟用户恰好点击批准），随后把钟拨过 expires_at
    再返回。修复前过期分支不看 status 是否仍 pending，无条件返回
    approval_timeout，把已落账的批准吞成终态拒绝。
    """

    session_id = f"session-race-{tag}"
    clock = {"now": 1000.0}
    monkeypatch.setattr(tool_approvals.time, "monotonic", lambda: clock["now"])

    def checker():
        pending = tool_approvals.list_tool_approval_requests(session_id, status="pending")
        if pending:
            tool_approvals.resolve_tool_approval_request(
                session_id,
                pending[0]["requestId"],
                decision="accept",
            )
            clock["now"] = 1000.0 + 10.0
        return cancel_reason

    return tool_approvals.authorize_or_wait(
        session_id=session_id,
        turn_id=f"turn-race-{tag}",
        agent_id="agent-race",
        call_id=f"call-expiry-race-{tag}",
        tool_name="web_fetch_tool",
        tool_args={"url": "https://docs.example.com/race"},
        approval="on_request",
        risk="network",
        decision_fingerprint="decision-race",
        config_revision=3,
        config_hash="config-hash-a",
        permission_preset="request_approval",
        timeout_seconds=0.1,
        cancel_checker=checker,
    )


def test_expiry_race_returns_concurrent_accept_not_timeout(monkeypatch):
    """过期判定窗口内到达的 accept 必须按批准返回，不得吞成 approval_timeout。"""

    outcome = _run_expiry_race(monkeypatch, cancel_reason="", tag="expiry")

    assert outcome.allowed is True
    assert outcome.code == "approved"


def test_cancel_race_returns_concurrent_accept_not_cancelled(monkeypatch):
    """取消判定窗口内到达的 accept 同型：按批准返回，不得吞成 approval_cancelled。"""

    outcome = _run_expiry_race(monkeypatch, cancel_reason="user requested stop", tag="cancel")

    assert outcome.allowed is True
    assert outcome.code == "approved"


def test_non_approval_denial_in_approval_flow_carries_rule_id_and_reason(monkeypatch):
    """审批协商之外的授权拒绝返回可审计结构：gateId=code，决策规则带 ruleId+reasonCode。"""

    _runtime(monkeypatch)
    _install(("web_search_tool", "on_request", "network"))
    context = tool_authorization_service.current_execution_authorization()
    assert context is not None
    context.deny_rules = (
        ("unassigned_tool", "not_assigned", "tool-agent-a:policy.allowedTools:not_assigned"),
    )

    denied = tool_authorization_service.authorize_tool_execution(
        tool_name="unassigned_tool",
        tool_call_id="call-auditable",
    )

    assert denied.allowed is False
    assert denied.code == "tool_not_executable"
    assert denied.reason_code == "not_assigned"
    assert denied.rule_id == "tool-agent-a:policy.allowedTools:not_assigned"

    # 审批链工具被正常协商放行时，结果不携带决策级 deny 规则（规则不适用）。
    _install(("web_search_tool", "never", "network"))
    allowed = tool_authorization_service.authorize_tool_execution(
        tool_name="web_search_tool",
        tool_call_id="call-allowed",
        tool_args={"query": "ok"},
    )

    assert allowed.allowed is True
    assert allowed.rule_id == ""
    assert allowed.reason_code == ""


def test_declined_approval_does_not_burn_call_budget(monkeypatch, _agent_directory_state):
    """E5：额度在审批等待前预扣，被拒调用没执行任何工具——必须退款。

    额度上限设为 1：修复前第一次被拒就把 call_count 顶到 1，第二次调用
    直接撞 call_budget_exhausted 熔断（零执行烧穿预算），且不会再出现
    第二个待审批请求。
    """

    _runtime(monkeypatch)
    _install(("web_search_tool", "on_request", "network"))
    calls = []
    executor = ToolExecutor()
    executor.register_tool("web_search_tool", lambda **kwargs: calls.append(kwargs) or "ok")
    result_box = {}

    def _worker():
        _install(("web_search_tool", "on_request", "network"))
        context = tool_authorization_service.current_execution_authorization()
        context.max_calls_per_turn = 1
        result_box["context"] = context
        result_box["first"] = executor.execute(
            "web_search_tool", {"query": "one"}, tool_call_id="call-decline-budget-1",
        )
        result_box["second"] = executor.execute(
            "web_search_tool", {"query": "two"}, tool_call_id="call-decline-budget-2",
        )

    worker = threading.Thread(target=_worker)
    worker.start()
    first_request = _wait_for_pending()
    tool_approvals.resolve_tool_approval_request(
        "session-a", first_request["requestId"], decision="decline",
    )
    second_request = _wait_for_pending()
    tool_approvals.resolve_tool_approval_request(
        "session-a", second_request["requestId"], decision="decline",
    )
    worker.join(timeout=2)

    first_result, _first_action = result_box["first"]
    second_result, second_action = result_box["second"]
    assert "用户拒绝" in first_result
    # 第二次仍须到达审批，而不是零执行就撞额度熔断
    assert "用户拒绝" in second_result
    assert "额度已用尽" not in second_result
    assert second_action is None
    assert calls == []
    # 两次被拒的调用都退了款
    assert result_box["context"].call_count == 0
