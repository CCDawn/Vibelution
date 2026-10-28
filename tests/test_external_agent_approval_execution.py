from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone
from types import SimpleNamespace
import json
import threading
import time

import pytest

from core.infrastructure.tool_executor import ToolExecutor
from core.web.services import agent_directory_service
from core.web.services.external_agent.approval_binding import (
    register_external_session, registered_external_task, unregister_external_session,
)
from core.web.services.session import tool_approvals
from tests.test_tool_approval_flow import _install, _runtime, _wait_for_pending
from tests.test_external_agent_task_service import FakeRuntime, _service
from core.web.services.external_agent.service import ExternalAgentAccessError, ExternalAgentConflictError


def _enable_real_binding(service):
    service.dependencies = replace(service.dependencies,
        register_approval_session=register_external_session,
        unregister_approval_session=unregister_external_session,
        registered_approval_task=registered_external_task)


def test_restart_missing_binding_stops_task_without_managed_continuation(tmp_path):
    runtime = FakeRuntime()
    service = _service(tmp_path, runtime)
    _enable_real_binding(service)
    started = service.start_task(owner_id="owner", adapter_connection_id="connection", capabilities=set(),
        agent_id="coder", task="bounded", permission_profile="read_only", client_request_id="restart-test",
        title="", runtime_revision="revision")
    record = service.store.get_task(started["taskId"])
    unregister_external_session(task_id=record["taskId"], session_id=record["sessionId"], agent_id="coder")
    runtime.details[record["sessionId"]]["phase"] = "needs_continue"
    result = service.get_task(owner_id="owner", task_id=record["taskId"])
    assert len(runtime.submit_calls) == 1
    assert runtime.stop_calls == [(record["sessionId"], record["turnId"])]
    assert result["status"] == "cancelled"
    assert result["error"]["code"] == "REAUTHORIZATION_REQUIRED"
    assert service.store.get_task(record["taskId"])["reasonCode"] == "restart_authorization_required_confirmed"


@pytest.mark.parametrize("failure", ["submit", "persist"])
def test_submit_exception_after_acceptance_retains_binding_until_stop_confirmation(tmp_path, failure):
    runtime = FakeRuntime()
    service = _service(tmp_path, runtime)
    _enable_real_binding(service)
    submit = runtime.submit_message
    def accepted_then_failed(*args, **kwargs):
        submit(*args, **kwargs)
        raise RuntimeError("lost acceptance")
    if failure == "submit":
        service.dependencies = replace(service.dependencies, submit_message=accepted_then_failed)
    else:
        transition = service.store.transition
        def fail_started_once(*args, **kwargs):
            if kwargs.get("reason_code") == "turn_started":
                raise RuntimeError("lost acceptance")
            return transition(*args, **kwargs)
        service.store.transition = fail_started_once
    with pytest.raises(RuntimeError, match="lost acceptance"):
        service.start_task(owner_id="owner", adapter_connection_id="connection", capabilities=set(),
            agent_id="coder", task="bounded", permission_profile="read_only", client_request_id="submit-test",
            title="", runtime_revision="revision")
    record = service.store.list_nonterminal()[0]
    assert record["status"] == "stop_unconfirmed"
    assert record["error"]["code"] == "SUBMISSION_UNCONFIRMED"
    assert registered_external_task(session_id=record["sessionId"], agent_id="coder") == record["taskId"]
    assert len(runtime.submit_calls) == 1 and len(runtime.stop_calls) == 1
    runtime.details[record["sessionId"]]["phase"] = "stopped"
    assert service.get_task(owner_id="owner", task_id=record["taskId"])["status"] == "cancelled"
    assert not registered_external_task(session_id=record["sessionId"], agent_id="coder")


def test_continuation_lost_acceptance_never_redispatches_or_drops_binding(tmp_path):
    runtime = FakeRuntime()
    service = _service(tmp_path, runtime)
    _enable_real_binding(service)
    started = service.start_task(owner_id="owner", adapter_connection_id="connection", capabilities=set(),
        agent_id="coder", task="bounded", permission_profile="read_only", client_request_id="continue-test",
        title="", runtime_revision="revision")
    record = service.store.get_task(started["taskId"])
    runtime.details[record["sessionId"]]["phase"] = "needs_continue"
    submit = runtime.submit_message
    def accepted_then_failed(*args, **kwargs):
        submit(*args, **kwargs)
        runtime.details[record["sessionId"]]["phase"] = "running"
        raise RuntimeError("lost continuation acceptance")
    service.dependencies = replace(service.dependencies, submit_message=accepted_then_failed)
    result = service.get_task(owner_id="owner", task_id=record["taskId"])
    assert result["status"] == "stop_unconfirmed"
    assert runtime.stop_calls == [(record["sessionId"], "")]
    assert registered_external_task(session_id=record["sessionId"], agent_id="coder") == record["taskId"]
    service.get_task(owner_id="owner", task_id=record["taskId"])
    assert len(runtime.submit_calls) == 2
    runtime.details[record["sessionId"]]["phase"] = "stopped"
    assert service.get_task(owner_id="owner", task_id=record["taskId"])["status"] == "cancelled"


@pytest.mark.parametrize("runtime_source", ["external_agent_task:workspace_write", ""])
@pytest.mark.parametrize("mutate_at_freeze", [False, True])
def test_external_tool_executes_frozen_arguments_even_if_event_listener_mutates_them(monkeypatch, runtime_source, mutate_at_freeze):
    runtime = {"sessionId": "snapshot-session", "agentId": "snapshot-agent", "turnId": "turn-1",
               "runtimeToolSource": runtime_source}
    monkeypatch.setattr(agent_directory_service, "current_agent_runtime", lambda **_kwargs: runtime)
    register_external_session(task_id="task-1", session_id=runtime["sessionId"], agent_id=runtime["agentId"])
    if mutate_at_freeze:
        from core.web.services.external_agent import approval_binding
        original_freeze, calls_to_freeze = approval_binding.freeze_arguments, []
        def change_after_freeze(arguments):
            result = original_freeze(arguments)
            if not calls_to_freeze:
                arguments["payload"]["value"] = "changed after first snapshot"
            calls_to_freeze.append(True)
            return result
        monkeypatch.setattr(approval_binding, "freeze_arguments", change_after_freeze)
    executor = ToolExecutor()
    observed, called = [], []
    def authorize(_name, _call, args, **_kwargs):
        observed.append(deepcopy(args))
        return SimpleNamespace(allowed=True, enforced=False)
    monkeypatch.setattr(executor, "_check_canonical_execution_authorization", authorize)
    monkeypatch.setattr(executor, "_check_runtime_block", lambda *_args: None)
    monkeypatch.setattr(executor, "_check_readonly_subagent_block", lambda *_args: None)
    def publish(_event, payload):
        args = payload.get("args")
        if isinstance(args, dict) and isinstance(args.get("payload"), dict):
            args["payload"]["value"] = "mutated"
            executor.register_tool("external_snapshot_probe", lambda **kwargs: called.append({"replaced": True}) or "bad")
    monkeypatch.setattr(executor._event_bus, "publish", publish)
    def original_tool(payload, timeout=7):
        called.append({"payload": payload, "timeout": timeout})
        return "ok"
    executor.register_tool("external_snapshot_probe", original_tool)
    try:
        result, _ = executor.execute("external_snapshot_probe", {"payload": {"value": "original"}, "force": True}, tool_call_id="call-1")
    finally:
        unregister_external_session(task_id="task-1", session_id=runtime["sessionId"], agent_id=runtime["agentId"])
    assert result == "ok"
    assert observed == [{"payload": {"value": "original"}, "force": True}]
    assert called == [{"payload": {"value": "original"}, "timeout": 7}]


def test_unregistered_external_session_fails_closed(monkeypatch):
    monkeypatch.setattr(agent_directory_service, "current_agent_runtime", lambda **_kwargs: {
        "sessionId": "missing-session", "agentId": "agent", "turnId": "turn",
        "runtimeToolSource": "external_agent_task:workspace_write",
    })
    executor = ToolExecutor()
    called = []
    monkeypatch.setattr(executor, "_check_canonical_execution_authorization", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(executor, "_check_runtime_block", lambda *_args: None)
    monkeypatch.setattr(executor, "_check_readonly_subagent_block", lambda *_args: None)
    executor.register_tool("external_missing_probe", lambda: called.append(True) or "ok")
    executor.execute("external_missing_probe", {}, tool_call_id="call-1")
    assert called == []


def test_real_external_approval_binds_preview_decision_and_executed_arguments(monkeypatch):
    from core.web.services import agent_config_authority
    monkeypatch.setattr(agent_config_authority, "agent_config_hash", lambda agent: agent["configHash"])
    _runtime(monkeypatch)
    monkeypatch.setattr(agent_directory_service, "load_agent_record", lambda *_args, **_kwargs: {
        "agentId": "agent-a", "configRevision": 3, "configHash": "config-hash-a", "status": "active",
    })
    runtime = agent_directory_service.current_agent_runtime
    monkeypatch.setattr(agent_directory_service, "current_agent_runtime", lambda: {
        **runtime(), "runtimeToolSource": "external_agent_task:workspace_write",
    })
    register_external_session(task_id="task-a", session_id="session-a", agent_id="agent-a")
    executor = ToolExecutor()
    calls, result = [], {}
    def run_command(cmd, payload, timeout=7):
        calls.append({"cmd": cmd, "payload": payload, "timeout": timeout})
        return "ok"
    executor.register_tool("exec_command", run_command)
    def publish(_event, payload):
        args = payload.get("args")
        if isinstance(args, dict) and isinstance(args.get("payload"), dict):
            args["payload"]["value"] = "listener changed"
    monkeypatch.setattr(executor._event_bus, "publish", publish)
    def run():
        _install(("exec_command", "on_request", "execute"))
        result["value"] = executor.execute("exec_command", {
            "cmd": "echo ready", "payload": {"value": "123"}, "force": True,
        }, tool_call_id="call-a")
    thread = threading.Thread(target=run)
    try:
        thread.start()
        pending = _wait_for_pending()
        identity = dict(task_id="task-a", session_id="session-a", agent_id="agent-a",
                        turn_id="turn-a", request_id=pending["requestId"])
        preview = tool_approvals.preview_external_task_approval(**identity)
        assert json.loads(preview["argumentsJson"])["payload"] == {"value": 123}
        assert json.loads(preview["executionArgumentsJson"]) == {"cmd": "echo ready", "payload": {"value": 123}, "timeout": 7}
        deadlines = {"task_lease_expires_at": "2099-01-01T00:00:00Z", "task_deadline_at": "2099-01-01T00:00:00Z"}
        with pytest.raises(tool_approvals.ToolApprovalConflictError):
            tool_approvals.resolve_tool_approval_request("session-a", pending["requestId"], decision="accept")
        with pytest.raises(tool_approvals.ToolApprovalConflictError):
            tool_approvals.resolve_external_task_approval(**identity, **deadlines, decision="accept", expected_revision="0" * 64)
        with pytest.raises(tool_approvals.ToolApprovalConflictError):
            tool_approvals.preview_external_task_approval(**{**identity, "turn_id": "different-turn"})
        for invalid in (None, {"configRevision": 3}, {"configHash": "config-hash-a"},
                        {"configRevision": True, "configHash": "config-hash-a"},
                        {"configRevision": 3, "configHash": "changed"}):
            with monkeypatch.context() as patch_agent:
                patch_agent.setattr(agent_directory_service, "load_agent_record", lambda *_a, **_kw: invalid)
                with pytest.raises(tool_approvals.ToolApprovalConflictError):
                    tool_approvals.resolve_external_task_approval(**identity, **deadlines, decision="accept",
                                                                  expected_revision=preview["revision"])
        with pytest.raises(tool_approvals.ToolApprovalConflictError):
            tool_approvals.resolve_external_task_approval(**identity, **{**deadlines, "task_deadline_at": "2000-01-01T00:00:00Z"},
                                                          decision="accept", expected_revision=preview["revision"])
        class AdvancingClock:
            count = 0
            fromisoformat = staticmethod(datetime.fromisoformat)
            @classmethod
            def now(cls, _tz):
                cls.count += 1
                return datetime(2098 if cls.count == 1 else 2100, 1, 1, tzinfo=timezone.utc)
        with monkeypatch.context() as patch_clock:
            patch_clock.setattr(tool_approvals, "datetime", AdvancingClock)
            with pytest.raises(tool_approvals.ToolApprovalConflictError):
                tool_approvals.resolve_external_task_approval(**identity, **deadlines, decision="accept",
                                                              expected_revision=preview["revision"])
        tool_approvals.resolve_external_task_approval(**identity, **deadlines, decision="accept", expected_revision=preview["revision"])
        thread.join(timeout=3)
        assert not thread.is_alive()
        assert result["value"] == ("ok", None)
        assert calls == [{"cmd": "echo ready", "payload": {"value": 123}, "timeout": 7}]
        assert tool_approvals._REQUESTS[pending["requestId"]].external_arguments_json == ""
        assert tool_approvals._REQUESTS[pending["requestId"]].external_execution_arguments_json == ""
    finally:
        tool_approvals.reset_tool_approval_state(clear_durable=False)
        thread.join(timeout=3)
        unregister_external_session(task_id="task-a", session_id="session-a", agent_id="agent-a")


@pytest.mark.parametrize("fail_record", [False, True])
def test_task_service_registers_before_submit_and_requires_owner_bound_native_decision(tmp_path, monkeypatch, fail_record):
    from core.web.services import agent_config_authority
    monkeypatch.setattr(agent_config_authority, "agent_config_hash", lambda agent: agent["configHash"])
    runtime = FakeRuntime()
    runtime.agents[0].update(configRevision=3, configHash="hash-3")
    monkeypatch.setattr(agent_directory_service, "load_agent_record", runtime.get_agent)
    service = _service(tmp_path, runtime)
    outcome, workers = {}, []
    def submit(session_id, _content, **kwargs):
        task_id = kwargs["message_metadata"]["taskId"]
        from core.web.services.external_agent.approval_binding import external_session_task, freeze_arguments
        assert external_session_task(session_id=session_id, agent_id="coder") == task_id
        arguments = {"command": "actual command"}
        def wait():
            outcome["value"] = tool_approvals.authorize_or_wait(
                session_id=session_id, turn_id="turn-1", agent_id="coder", call_id="call-1",
                tool_name="cli_tool", tool_args=arguments, approval="always", risk="execute",
                decision_fingerprint="fingerprint", config_revision=3, config_hash="hash-3",
                permission_preset="request_approval", timeout_seconds=3,
                external_task_id=task_id, external_arguments_json=freeze_arguments(arguments),
                external_execution_arguments_json=freeze_arguments(arguments),
            )
        thread = threading.Thread(target=wait)
        workers.append(thread)
        thread.start()
        return {"turnId": "turn-1"}
    service.dependencies = replace(service.dependencies, submit_message=submit,
        register_approval_session=register_external_session, unregister_approval_session=unregister_external_session,
        preview_bound_approval=tool_approvals.preview_external_task_approval,
        resolve_bound_approval=tool_approvals.resolve_external_task_approval)
    try:
        started = service.start_task(owner_id="owner", adapter_connection_id="connection", capabilities=set(),
            agent_id="coder", task="bounded", permission_profile="workspace_write", client_request_id="request",
            title="", runtime_revision="revision")
        task_id = started["taskId"]
        approval_id = _wait_for_pending("session-1")["requestId"]
        with pytest.raises(ExternalAgentAccessError):
            service.preview_task_approval(owner_id="wrong", task_id=task_id, approval_id=approval_id)
        preview = service.preview_task_approval(owner_id="owner", task_id=task_id, approval_id=approval_id)
        assert json.loads(preview["executionArgumentsJson"]) == {"command": "actual command"}
        runtime.agents[0]["configRevision"] = 4
        with pytest.raises(ExternalAgentConflictError):
            service.resolve_task_approval_bound(owner_id="owner", task_id=task_id,
                approval_id=approval_id, decision="accept", expected_revision=preview["revision"])
        runtime.agents[0]["configRevision"] = 3
        if fail_record:
            def fail_transition(*_args, **_kwargs):
                raise OSError("synthetic record failure")
            monkeypatch.setattr(service, "_transition", fail_transition)
            with pytest.raises(ExternalAgentConflictError) as failure:
                service.resolve_task_approval_bound(owner_id="owner", task_id=task_id,
                    approval_id=approval_id, decision="accept", expected_revision=preview["revision"])
            assert failure.value.code == "APPROVAL_UNCONFIRMED"
        else:
            response = service.resolve_task_approval_bound(owner_id="owner", task_id=task_id,
                approval_id=approval_id, decision="accept", expected_revision=preview["revision"])
            assert response["decision"] == "accept"
        workers[0].join(timeout=3)
        assert outcome["value"].allowed
        if fail_record:
            with pytest.raises(ExternalAgentConflictError):
                service.resolve_task_approval_bound(owner_id="owner", task_id=task_id,
                    approval_id=approval_id, decision="accept", expected_revision=preview["revision"])
        else:
            assert service.resolve_task_approval_bound(owner_id="owner", task_id=task_id,
                approval_id=approval_id, decision="accept", expected_revision=preview["revision"]) == response
    finally:
        tool_approvals.reset_tool_approval_state(clear_durable=False)
        for thread in workers:
            thread.join(timeout=3)
        if "task_id" in locals():
            unregister_external_session(task_id=task_id, session_id="session-1", agent_id="coder")


def test_expired_native_request_cannot_be_accepted_before_waiter_observes_timeout():
    from core.web.services.external_agent.approval_binding import freeze_arguments
    register_external_session(task_id="task-timeout", session_id="session-timeout", agent_id="agent-timeout")
    args = {"cmd": "echo ready"}
    result = {}
    thread = threading.Thread(target=lambda: result.setdefault("value", tool_approvals.authorize_or_wait(
        session_id="session-timeout", turn_id="turn-1", agent_id="agent-timeout", call_id="call-1",
        tool_name="exec_command", tool_args=args, approval="always", risk="execute", decision_fingerprint="f",
        config_revision=1, config_hash="hash", permission_preset="request_approval", timeout_seconds=2,
        external_task_id="task-timeout", external_arguments_json=freeze_arguments(args),
        external_execution_arguments_json=freeze_arguments(args))))
    try:
        thread.start()
        request_id = _wait_for_pending("session-timeout")["requestId"]
        identity = dict(task_id="task-timeout", session_id="session-timeout", agent_id="agent-timeout",
                        turn_id="turn-1", request_id=request_id)
        preview = tool_approvals.preview_external_task_approval(**identity)
        with tool_approvals._LOCK:
            tool_approvals._REQUESTS[request_id].expires_at = time.monotonic() - 1
            with pytest.raises(tool_approvals.ToolApprovalConflictError):
                tool_approvals.resolve_external_task_approval(**identity, decision="accept",
                    expected_revision=preview["revision"], task_lease_expires_at="2099-01-01T00:00:00Z",
                    task_deadline_at="2099-01-01T00:00:00Z")
        thread.join(timeout=3)
        assert result["value"].code == "approval_timeout"
    finally:
        tool_approvals.reset_tool_approval_state(clear_durable=False)
        thread.join(timeout=3)
        unregister_external_session(task_id="task-timeout", session_id="session-timeout", agent_id="agent-timeout")


def test_concurrent_bound_decisions_have_only_one_winner(monkeypatch):
    from core.web.services.external_agent.approval_binding import freeze_arguments
    from core.web.services import agent_config_authority
    monkeypatch.setattr(agent_config_authority, "agent_config_hash", lambda agent: agent["configHash"])
    monkeypatch.setattr(agent_directory_service, "load_agent_record", lambda *_args, **_kwargs: {
        "agentId": "agent-race", "configRevision": 1, "configHash": "hash", "status": "active",
    })
    register_external_session(task_id="task-race", session_id="session-race", agent_id="agent-race")
    args = {"cmd": "echo ready"}
    outcome = {}
    thread = threading.Thread(target=lambda: outcome.setdefault("value", tool_approvals.authorize_or_wait(
        session_id="session-race", turn_id="turn-1", agent_id="agent-race", call_id="call-1",
        tool_name="exec_command", tool_args=args, approval="always", risk="execute", decision_fingerprint="f",
        config_revision=1, config_hash="hash", permission_preset="request_approval", timeout_seconds=3,
        external_task_id="task-race", external_arguments_json=freeze_arguments(args),
        external_execution_arguments_json=freeze_arguments(args))))
    resolvers = []
    try:
        thread.start()
        request_id = _wait_for_pending("session-race")["requestId"]
        identity = dict(task_id="task-race", session_id="session-race", agent_id="agent-race",
                        turn_id="turn-1", request_id=request_id)
        revision = tool_approvals.preview_external_task_approval(**identity)["revision"]
        barrier, results = threading.Barrier(3), []
        def resolve(decision):
            barrier.wait()
            try:
                tool_approvals.resolve_external_task_approval(**identity, decision=decision, expected_revision=revision,
                    task_lease_expires_at="2099-01-01T00:00:00Z", task_deadline_at="2099-01-01T00:00:00Z")
                results.append((decision, "won"))
            except tool_approvals.ToolApprovalConflictError:
                results.append((decision, "conflict"))
        resolvers = [threading.Thread(target=resolve, args=(decision,)) for decision in ("accept", "decline")]
        for resolver in resolvers:
            resolver.start()
        barrier.wait()
        for resolver in resolvers:
            resolver.join(timeout=3)
        thread.join(timeout=3)
        assert sorted(result for _, result in results) == ["conflict", "won"]
        assert outcome["value"].allowed == (("accept", "won") in results)
    finally:
        tool_approvals.reset_tool_approval_state(clear_durable=False)
        thread.join(timeout=3)
        for resolver in resolvers:
            resolver.join(timeout=3)
        unregister_external_session(task_id="task-race", session_id="session-race", agent_id="agent-race")


def test_preview_and_bound_decision_http_require_both_control_and_task_capability(monkeypatch):
    from tests.test_external_agent_routes import _client, _headers
    from core.web.control import CONTROL_TOKEN_HEADER
    client, service = _client(monkeypatch)
    service.preview_task_approval = lambda **kwargs: {"taskId": kwargs["task_id"], "argumentsJson": "{}"}
    service.resolve_task_approval_bound = lambda **kwargs: {"status": "ok", "decision": kwargs["decision"]}
    path = "/api/v1/external-agent/tasks/task-1/approvals/approval-1"
    headers = _headers()
    assert client.get(path + "/preview").status_code == 403
    assert client.get(path + "/preview", headers={CONTROL_TOKEN_HEADER: headers[CONTROL_TOKEN_HEADER]}).status_code == 403
    preview = client.get(path + "/preview", headers=headers)
    assert preview.status_code == 200
    assert preview.headers["cache-control"] == "no-store"
    assert client.post(path + "/resolve-bound", headers=headers, json={"decision": "accept"}).status_code == 422
    assert client.post(path + "/resolve-bound", json={"decision": "accept", "expected_revision": "a" * 64}).status_code == 403
    response = client.post(path + "/resolve-bound", headers=headers,
                           json={"decision": "accept", "expected_revision": "a" * 64})
    assert response.status_code == 200


def test_rebuilt_services_serialize_same_task_without_retaining_idle_locks(tmp_path):
    import gc
    import weakref

    first, second = _service(tmp_path, FakeRuntime()), _service(tmp_path, FakeRuntime())
    other = _service(tmp_path / "other", FakeRuntime())
    lock = first._task_lock("same-task")
    assert lock is second._task_lock("same-task")
    assert lock is second._task_lock(" same-task ")
    if __import__("os").name == "nt":
        assert lock is second._task_lock("SAME-TASK")
    assert lock is not other._task_lock("same-task")
    entered = threading.Event()
    def use_rebuilt_service():
        with second._task_lock("same-task"):
            entered.set()
    with lock:
        worker = threading.Thread(target=use_rebuilt_service)
        worker.start()
        assert not entered.wait(0.05)
    worker.join(timeout=2)
    assert entered.is_set()
    reference = weakref.ref(lock)
    del lock
    gc.collect()
    assert reference() is None


@pytest.mark.parametrize("expired_field", ["deadlineAt", "leaseExpiresAt"])
def test_task_preview_rejects_expired_lease_before_reconcile(tmp_path, expired_field):
    service = _service(tmp_path, FakeRuntime())
    started = service.start_task(owner_id="owner", adapter_connection_id="connection", capabilities=set(),
        agent_id="coder", task="bounded", permission_profile="workspace_write", client_request_id="request",
        title="", runtime_revision="revision")
    record = service.store.get_task(started["taskId"])
    service.store.transition(started["taskId"], status="running", expected_revision=record["revision"],
                             fields={expired_field: "2000-01-01T00:00:00Z"})
    with pytest.raises(ExternalAgentConflictError):
        service.preview_task_approval(owner_id="owner", task_id=started["taskId"], approval_id="approval")


@pytest.mark.parametrize("writer", ["canonical", "raw_registry", "team_role", "team_roster", "bad_roster", "unreadable_roster", "missing_team_id", "empty_team_id", "duplicate_team_id", "invalid_team_id", "invalid_team_status"])
def test_config_change_after_preview_before_native_decision_is_rejected(tmp_path, monkeypatch, writer):
    from tests.helpers.system_agent_state import _mark_config_agent_instances_present
    from tests.test_agent_config_workspace_service import _use_tmp_project_root
    from core.web.services.external_agent.approval_binding import freeze_arguments

    _use_tmp_project_root(tmp_path, monkeypatch)
    _mark_config_agent_instances_present()
    from core.web.services import team_service
    with team_service._TEAM_LOCK:
        team_service._save_index({"schemaVersion": 1, "teams": []})
    agent = agent_directory_service.create_agent_instance(display_name="Approval race agent", primary_mode="chat")
    agent_id = agent["agentId"]
    identity = dict(task_id="task-config-race", session_id="session-config-race", agent_id=agent_id, turn_id="turn-1")
    register_external_session(task_id=identity["task_id"], session_id=identity["session_id"], agent_id=agent_id)
    args, outcome, result = {"cmd": "echo ready"}, {}, {}
    waiter = threading.Thread(target=lambda: outcome.setdefault("value", tool_approvals.authorize_or_wait(
        session_id=identity["session_id"], turn_id="turn-1", agent_id=agent_id, call_id="call-1",
        tool_name="exec_command", tool_args=args, approval="always", risk="execute", decision_fingerprint="fingerprint",
        config_revision=agent["configRevision"], config_hash=agent["configHash"], permission_preset="request_approval",
        timeout_seconds=5, external_task_id=identity["task_id"], external_arguments_json=freeze_arguments(args),
        external_execution_arguments_json=freeze_arguments(args))))
    entered, release = threading.Event(), threading.Event()
    resolver = None
    try:
        waiter.start()
        identity["request_id"] = _wait_for_pending(identity["session_id"])["requestId"]
        preview = tool_approvals.preview_external_task_approval(**identity)
        original = tool_approvals._external_binding_locked
        def pause_after_native_snapshot(**kwargs):
            value = original(**kwargs)
            entered.set()
            assert release.wait(3)
            return value
        monkeypatch.setattr(tool_approvals, "_external_binding_locked", pause_after_native_snapshot)
        def resolve():
            try:
                tool_approvals.resolve_external_task_approval(**identity, decision="accept",
                    expected_revision=preview["revision"], task_lease_expires_at="2099-01-01T00:00:00Z",
                    task_deadline_at="2099-01-01T00:00:00Z")
                result["value"] = "accepted"
            except tool_approvals.ToolApprovalConflictError:
                result["value"] = "conflict"
        resolver = threading.Thread(target=resolve)
        resolver.start()
        assert entered.wait(3)
        if writer == "canonical":
            updated = agent_directory_service.update_agent_instance(agent_id, permission_preset="full_access")
            assert updated["configRevision"] != agent["configRevision"]
        elif writer == "raw_registry":
            state = agent_directory_service.load_state()
            row = next(item for item in state["agents"] if item["agentId"] == agent_id)
            row["permissionPreset"] = "full_access"
            agent_directory_service.save_registry_payload(state)
            updated = agent_directory_service.load_agent_record(agent_id)
            assert updated["configRevision"] == agent["configRevision"]
            assert updated["configHash"] == agent["configHash"]
        elif writer == "team_role":
            updated = agent_directory_service.update_agent_instance(agent_id, role_key="research_team_member")
            assert updated["configRevision"] == agent["configRevision"]
            assert updated["configHash"] == agent["configHash"]
        elif writer == "team_roster":
            with team_service._TEAM_LOCK:
                team_service._save_index({"schemaVersion": 1, "teams": [
                    {"teamId": "team-test", "status": "active", "members": [{"agentId": agent_id}]},
                ]})
            updated = agent_directory_service.load_agent_record(agent_id)
            assert updated["configRevision"] == agent["configRevision"]
            assert updated["configHash"] == agent["configHash"]
        elif writer == "bad_roster":
            with team_service._TEAM_LOCK:
                team_service._teams_index_path(seed=False).write_text("{bad", encoding="utf-8")
        elif writer in {"missing_team_id", "empty_team_id", "duplicate_team_id", "invalid_team_id", "invalid_team_status"}:
            row = {"teamId": "team-test", "status": "active", "members": [{"agentId": agent_id}]}
            if writer == "missing_team_id":
                del row["teamId"]
            elif writer == "empty_team_id":
                row["teamId"] = " "
            elif writer == "invalid_team_id":
                row["teamId"] = "../invalid"
            elif writer == "invalid_team_status":
                row["status"] = "archived "
            rows = [row]
            if writer == "duplicate_team_id":
                rows.insert(0, {"teamId": "TEAM-TEST", "status": "archived", "members": []})
            with team_service._TEAM_LOCK:
                team_service._save_index({"schemaVersion": 1, "teams": rows})
        else:
            from core.web.services.team import team_store
            def inaccessible(**_kwargs):
                raise PermissionError("synthetic inaccessible roster")
            monkeypatch.setattr(team_store, "read_index_snapshot", inaccessible)
        release.set()
        resolver.join(timeout=3)
        assert not resolver.is_alive()
        assert result["value"] == "conflict"
        assert tool_approvals.get_tool_approval_request(identity["session_id"], identity["request_id"])["status"] == "pending"
        with agent_directory_service._STATE_LOCK:
            blocked_resolver = threading.Thread(target=resolve)
            started = time.monotonic()
            blocked_resolver.start()
            blocked_resolver.join(timeout=3.5)
            assert not blocked_resolver.is_alive()
            assert 1.8 <= time.monotonic() - started < 3.5
            assert result["value"] == "conflict"
    finally:
        release.set()
        tool_approvals.reset_tool_approval_state(clear_durable=False)
        waiter.join(timeout=3)
        if resolver is not None:
            resolver.join(timeout=3)
        unregister_external_session(task_id=identity["task_id"], session_id=identity["session_id"], agent_id=agent_id)


def test_config_writer_waits_until_native_decision_linearizes(tmp_path, monkeypatch):
    from tests.helpers.system_agent_state import _mark_config_agent_instances_present
    from tests.test_agent_config_workspace_service import _use_tmp_project_root
    from core.web.services.external_agent.approval_binding import freeze_arguments

    _use_tmp_project_root(tmp_path, monkeypatch)
    _mark_config_agent_instances_present()
    agent = agent_directory_service.create_agent_instance(display_name="Approval lock agent", primary_mode="chat")
    agent_id = agent["agentId"]
    identity = dict(task_id="task-config-lock", session_id="session-config-lock", agent_id=agent_id, turn_id="turn-1")
    register_external_session(task_id=identity["task_id"], session_id=identity["session_id"], agent_id=agent_id)
    args, outcome, result = {"cmd": "echo ready"}, {}, {}
    waiter = threading.Thread(target=lambda: outcome.setdefault("value", tool_approvals.authorize_or_wait(
        session_id=identity["session_id"], turn_id="turn-1", agent_id=agent_id, call_id="call-1",
        tool_name="exec_command", tool_args=args, approval="always", risk="execute", decision_fingerprint="f",
        config_revision=agent["configRevision"], config_hash=agent["configHash"], permission_preset="request_approval",
        timeout_seconds=5, external_task_id=identity["task_id"], external_arguments_json=freeze_arguments(args),
        external_execution_arguments_json=freeze_arguments(args))))
    from core.web.services import team_service
    # A new project with no Team index is the Team authority's empty state.
    assert not team_service._teams_index_path(seed=False).exists()
    entered, release, writer_started, writer_locked, team_started, team_locked = (threading.Event() for _ in range(6))
    resolver = writer = team_writer = None
    try:
        waiter.start()
        identity["request_id"] = _wait_for_pending(identity["session_id"])["requestId"]
        revision = tool_approvals.preview_external_task_approval(**identity)["revision"]
        original = agent_directory_service.load_agent_record
        def pause_inside_state_lock(*args, **kwargs):
            record = original(*args, **kwargs)
            entered.set()
            assert release.wait(3)
            return record
        monkeypatch.setattr(agent_directory_service, "load_agent_record", pause_inside_state_lock)
        def resolve():
            result["value"] = tool_approvals.resolve_external_task_approval(**identity, decision="accept",
                expected_revision=revision, task_lease_expires_at="2099-01-01T00:00:00Z",
                task_deadline_at="2099-01-01T00:00:00Z")
        resolver = threading.Thread(target=resolve)
        resolver.start()
        assert entered.wait(3)
        def update():
            writer_started.set()
            with agent_directory_service._STATE_LOCK:
                writer_locked.set()
                agent_directory_service.update_agent_instance(agent_id, permission_preset="full_access")
        writer = threading.Thread(target=update)
        writer.start()
        assert writer_started.wait(3)
        assert not writer_locked.wait(0.2)
        def add_to_team():
            team_started.set()
            with team_service._TEAM_LOCK:
                team_locked.set()
                team_service._save_index({"schemaVersion": 1, "teams": [
                    {"teamId": "team-test", "status": "active", "members": [{"agentId": agent_id}]},
                ]})
        team_writer = threading.Thread(target=add_to_team)
        team_writer.start()
        assert team_started.wait(3)
        assert not team_locked.wait(0.2)
        release.set()
        resolver.join(timeout=3)
        writer.join(timeout=3)
        team_writer.join(timeout=3)
        waiter.join(timeout=3)
        assert not resolver.is_alive() and not writer.is_alive() and not team_writer.is_alive()
        assert result["value"]["decision"] == "accept"
        assert outcome["value"].allowed and writer_locked.is_set() and team_locked.is_set()
        assert agent_directory_service.get_agent(agent_id)["configRevision"] > agent["configRevision"]
    finally:
        release.set()
        tool_approvals.reset_tool_approval_state(clear_durable=False)
        waiter.join(timeout=3)
        if resolver is not None:
            resolver.join(timeout=3)
        if writer is not None:
            writer.join(timeout=3)
        if team_writer is not None:
            team_writer.join(timeout=3)
        unregister_external_session(task_id=identity["task_id"], session_id=identity["session_id"], agent_id=agent_id)
