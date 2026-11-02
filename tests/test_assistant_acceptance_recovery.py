"""Reject false recovery/cancel evidence without starting any real model."""
from copy import deepcopy
from contextlib import contextmanager
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import socket
import threading
from types import SimpleNamespace

import pytest

from scripts import acceptance_assistant_recovery as recovery


def event(kind, *, turn="turn-1", **extra):
    return {"eventType": kind, "sessionId": "session-1", "turnId": turn, **extra}


def result(name, args, value):
    return event("tool_result", toolCallId=name, payload={"toolCall": {
        "name": name, "arguments": args, "result": value}})


TASK = {"taskId": "task-1", "sessionId": "session-1", "turnId": "turn-1",
        "status": "cancelled", "reasonCode": "cancel_requested_confirmed",
        "stopRequestedAt": "2026-11-02T01:00:00Z", "stopSignalSentAt": "2026-11-02T01:00:01Z"}
DISPATCH = {"dispatchId": "dispatch-1", "nativeTaskId": "task-1"}
EVENTS = [event("turn_started"), event("user_message"), event("turn_interrupted")]
ROWS = [{"phase": "START", "seconds": 100.0, "pid": 123}]


@pytest.mark.parametrize("changed", ["dispatchId", "nativeTaskId", "sessionId", "turnId"])
def test_restart_requires_original_dispatch_task_session_and_turn(changed):
    expected = recovery.native_identity(DISPATCH, TASK)
    dispatch, task = dict(DISPATCH), dict(TASK)
    if changed in dispatch:
        dispatch[changed] = "other"
    else:
        task[changed] = "other"
    with pytest.raises(recovery.AcceptanceFailure):
        recovery.assert_same_identity(expected, dispatch, task)


@pytest.mark.parametrize("extra", [event("user_message"), event("turn_started", turn="turn-2")])
def test_recovery_cannot_hide_duplicate_native_admission_or_turn(extra):
    with pytest.raises(recovery.AcceptanceFailure, match="native_admission_or_turn_duplicated"):
        recovery.single_native_turn([*EVENTS, extra], TASK, "turn_interrupted")


@pytest.mark.parametrize("text", ["FINISH 500 123\n", "START 100 123\nSTART 101 123\n",
                                   "START nan 123\n", "START 100 123\nFINISH 430 124\n"])
def test_marker_rejects_replayed_or_fabricated_completion(tmp_path, text):
    path = tmp_path / "marker"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(recovery.AcceptanceFailure):
        recovery.marker_rows(path)


def test_marker_preserves_real_elapsed_time_and_tolerates_live_tail(tmp_path):
    path = tmp_path / "marker"
    path.write_text("START 100 123\nFINISH 430", encoding="utf-8")
    assert recovery.marker_rows(path) == ROWS
    path.write_text("START 100 123\nFINISH 430.25 123\n", encoding="utf-8")
    rows = recovery.marker_rows(path)
    assert rows[1]["seconds"] - rows[0]["seconds"] > recovery.LEASE_SECONDS


@pytest.mark.parametrize("marker_seconds,observed_seconds", [(35, 35), (330, 35), (35, 330), (300, 330)])
def test_short_or_marker_only_duration_is_never_long_task_evidence(marker_seconds, observed_seconds):
    rows = [ROWS[0], {"phase": "FINISH", "seconds": 100.0 + marker_seconds, "pid": 123}]
    with pytest.raises(recovery.AcceptanceFailure, match="real_long_task_did_not_exceed_lease"):
        recovery.long_duration(rows, observed_seconds)


@pytest.mark.parametrize("value", [{"status": "completed", "terminalSessionId": "terminal-1", "exitCode": 0},
                                  {"status": "running"},
                                  {"status": "running", "terminalSessionId": "terminal-1", "exitCode": 1}])
def test_host_fault_requires_real_still_running_terminal(value):
    with pytest.raises(recovery.AcceptanceFailure, match="probe_terminal_not_running"):
        recovery.running_terminal([result("exec_command", {"cmd": "unittest"}, value)], "unittest")


def test_terminal_cannot_be_treated_as_running_after_completed_poll():
    rows = [result("exec_command", {"cmd": "unittest"}, {"status": "running", "terminalSessionId": "t-1"}),
            result("write_stdin", {"session_id": "t-1"}, {"status": "completed", "exitCode": 0})]
    with pytest.raises(recovery.AcceptanceFailure, match="probe_terminal_already_completed"):
        recovery.running_terminal(rows, "unittest")


@pytest.mark.parametrize("case", ["http_ack_only", "stop_unconfirmed", "no_stop_signal", "running_worker", "current_phase_running",
                                  "completed_journal", "duplicate_admission", "finish_written", "live_process"])
def test_cancel_requires_confirmed_worker_journal_and_process_stop(case):
    task, events, detail, rows = deepcopy(TASK), deepcopy(EVENTS), {"running": False, "phase": "stopped"}, deepcopy(ROWS)
    alive = False
    if case == "http_ack_only":
        task.pop("reasonCode")
    elif case == "stop_unconfirmed":
        task["status"] = "stop_unconfirmed"
    elif case == "no_stop_signal":
        task.pop("stopSignalSentAt")
    elif case == "running_worker":
        detail["running"] = True
    elif case == "current_phase_running":
        detail = {"running": False, "currentPhase": "running"}
    elif case == "completed_journal":
        events[-1]["eventType"] = "turn_completed"
    elif case == "duplicate_admission":
        events.append(event("user_message"))
    elif case == "finish_written":
        rows.append({"phase": "FINISH", "seconds": 430.0, "pid": 123})
    elif case == "live_process":
        alive = True
    with pytest.raises(recovery.AcceptanceFailure):
        recovery.assert_confirmed_cancel(task, events, detail, rows, alive)


def test_confirmed_cancel_accepts_native_evidence():
    recovery.assert_confirmed_cancel(TASK, EVENTS, {"running": False, "phase": "stopped"}, ROWS, False)


def test_probe_uses_authorized_unittest_wait_instead_of_python_c():
    message = recovery.probe_message("project", "agent", "dispatch")
    assert recovery.WAIT_SECONDS == 330 and recovery.WAIT_SECONDS > recovery.LEASE_SECONDS
    assert "time.sleep(330)" in message and "timeout=600" in message
    assert "cmd逐字为python -m unittest test_recovery_probe -v" in message
    assert recovery.probe_source("recovery_probe.marker").count("    def test_") == 1
    compile(recovery.probe_source("recovery_probe.marker"), "test_recovery_probe.py", "exec")


def test_unittest_stdout_and_exit_are_aggregated_only_for_same_terminal():
    command = "python -m unittest test_recovery_probe -v"
    rows = [result("exec_command", {"cmd": command}, {"status": "running", "terminalSessionId": "t-1",
            "stderr": "Ran 1 test in 330.001s\n\nOK\n"}),
            result("write_stdin", {"session_id": "t-other"}, {"terminalSessionId": "t-other", "exitCode": 0})]
    assert recovery.terminal_evidence(rows, command, expected_tests=1)["testExitCode"] is None
    rows.append(result("write_stdin", {"session_id": "t-1"}, {"terminalSessionId": "t-1", "exitCode": 0}))
    assert recovery.terminal_evidence(rows, command, expected_tests=1)["testExitCode"] == 0


def _running_probe(monkeypatch, tmp_path, snapshots):
    """Exercise driver state transitions without starting a model or process."""
    workspace = tmp_path / "task-worktree"
    workspace.mkdir()
    (workspace / ".git").write_text("private fixture", encoding="utf-8")
    (workspace / "recovery_probe.marker").write_text("START 100 123\n", encoding="utf-8")
    command = "python -m unittest test_recovery_probe -v"
    running = {**TASK, "status": "running", "localWorkspacePath": str(workspace)}
    fixture = SimpleNamespace(source=tmp_path / "source", primary_project_id="project", assistant_events=lambda: [])
    states = iter([*snapshots, (dict(DISPATCH), running)])
    polls = []

    def dispatch_task(_fixture, dispatch_id, allowed_ids, agent_id):
        polls.append((dispatch_id, allowed_ids, agent_id))
        return next(states)

    def events(_fixture, task):
        assert task["status"] == "running", "queued tasks must not require journal or workspace evidence"
        return [event("turn_started"), event("user_message"), result("exec_command", {"cmd": command},
            {"status": "running", "terminalSessionId": "terminal-1"})]

    monkeypatch.setattr(recovery, "_dispatch_task", dispatch_task)
    monkeypatch.setattr(recovery, "_events", events)
    monkeypatch.setattr(recovery, "_process_identity", lambda pid: (pid, 123.0))
    monkeypatch.setattr(recovery, "_assistant_action", lambda *args: True)
    monkeypatch.setattr(recovery.base, "git", lambda *args: "a" * 40)
    monkeypatch.setattr(recovery.time, "sleep", lambda seconds: None)
    return fixture, command, polls


def test_queued_task_waits_for_workspace_and_reaches_same_running_identity(monkeypatch, tmp_path):
    queued = {"taskId": "task-1", "status": "queued", "sessionId": None,
              "turnId": None, "localWorkspacePath": None}
    snapshots = [(dict(DISPATCH), dict(queued)),
                 (dict(DISPATCH), {**queued, "sessionId": "session-1"}),
                 (dict(DISPATCH), {**queued, "sessionId": "session-1", "turnId": "turn-1"})]
    fixture, command, polls = _running_probe(monkeypatch, tmp_path, snapshots)
    record = {}
    dispatch, task, terminal, process = recovery._await_running(fixture, "dispatch-1", {"dispatch-1"}, "agent",
        command, "recovery_probe.marker", recovery.time.monotonic() + 30, record)
    assert recovery.native_identity(dispatch, task) == recovery.native_identity(DISPATCH, TASK)
    assert terminal == "terminal-1" and process == (123, 123.0)
    assert len(polls) == 4 and all(poll == ("dispatch-1", {"dispatch-1"}, "agent") for poll in polls)


@pytest.mark.parametrize("state", ["running", "awaiting_approval", "succeeded", "cancelled"])
def test_nonqueued_task_still_requires_materialized_workspace(monkeypatch, tmp_path, state):
    snapshots = [(dict(DISPATCH), {**TASK, "status": state, "localWorkspacePath": None})]
    fixture, command, _ = _running_probe(monkeypatch, tmp_path, snapshots)
    with pytest.raises(recovery.AcceptanceFailure, match="probe_workspace_missing"):
        recovery._await_running(fixture, "dispatch-1", {"dispatch-1"}, "agent", command,
            "recovery_probe.marker", recovery.time.monotonic() + 30, {})


@pytest.mark.parametrize("changed", ["dispatchId", "nativeTaskId", "sessionId", "turnId"])
def test_queued_task_identity_cannot_change_while_workspace_is_pending(monkeypatch, tmp_path, changed):
    queued = {**TASK, "status": "queued", "localWorkspacePath": None}
    dispatch, changed_task = dict(DISPATCH), dict(queued)
    if changed in dispatch:
        dispatch[changed] = "other"
        if changed == "nativeTaskId":
            changed_task["taskId"] = "other"
    else:
        changed_task[changed] = "other"
    fixture, command, _ = _running_probe(monkeypatch, tmp_path,
        [(dict(DISPATCH), queued), (dispatch, changed_task)])
    with pytest.raises(recovery.AcceptanceFailure, match="native_identity_changed"):
        recovery._await_running(fixture, "dispatch-1", {"dispatch-1"}, "agent", command,
            "recovery_probe.marker", recovery.time.monotonic() + 30, {})


@contextmanager
def _ack_upstream(status=200):
    """A small real HTTP origin tests the fault injector, never a model provider."""
    raw = b'{"taskId":"task-real","status":"running","_leaseId":"unit-private-lease"}'
    seen = {"posts": 0, "lookups": 0, "credentialMatched": True}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def respond(self, method):
            seen["posts" if method == "POST" else "lookups"] += 1
            seen["credentialMatched"] &= self.headers.get("Authorization") == "unit-private-authority"
            self.rfile.read(int(self.headers.get("Content-Length", "0")))
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_POST(self):
            self.respond("POST")

        def do_GET(self):
            self.respond("GET")

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.05), daemon=True)
    thread.start()
    try:
        yield "http://127.0.0.1:" + str(server.server_port), seen, raw
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
        assert not thread.is_alive()


def _proxy_request(proxy, method, path, payload=None):
    port = int(proxy.url.rsplit(":", 1)[1])
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
    try:
        body = None if payload is None else json.dumps(payload).encode()
        connection.request(method, path, body=body, headers={"Authorization": "unit-private-authority"})
        response = connection.getresponse()
        return response.status, response.read()
    finally:
        connection.close()


def test_proxy_loses_only_first_real_success_and_forwards_lookup_bytes_unchanged():
    with _ack_upstream() as (upstream, seen, raw):
        with recovery.LostAcknowledgementProxy(upstream, "probe") as proxy:
            with pytest.raises((http.client.HTTPException, OSError)):
                _proxy_request(proxy, "POST", recovery.LOCAL_TASK_PREFIX + "tasks", {"client_request_id": "probe"})
            status, body = _proxy_request(proxy, "GET", recovery.LOCAL_TASK_PREFIX + "task-request?client_request_id=probe")
            assert status == 200 and body == raw
            # Retried POSTs are permitted, but the original native ID is required.
            status, body = _proxy_request(proxy, "POST", recovery.LOCAL_TASK_PREFIX + "tasks", {"client_request_id": "probe"})
            assert status == 200 and body == raw
            proof = proxy.evidence()
            recovery.assert_lost_ack_proof(proof, "task-real", 1)
            assert proof["taskPostAttempts"] == 2 and proof["taskPostSuccessCount"] == 2
            assert proof["requestLookupAttempts"] == 1 and proof["droppedAckCount"] == 1
            assert "unit-private" not in json.dumps(proof)
        assert proxy.closed and seen == {"posts": 2, "lookups": 1, "credentialMatched": True}


@pytest.mark.parametrize("method,path", [("GET", "/api/v1/launcher-assistant-management/directory/agents"),
                                       ("POST", "/api/v1/launcher-assistant-management/binding")])
def test_proxy_preserves_native_management_discovery_without_injecting_another_fault(method, path):
    with _ack_upstream() as (upstream, seen, raw):
        with recovery.LostAcknowledgementProxy(upstream, "probe") as proxy:
            status, body = _proxy_request(proxy, method, path, {} if method == "POST" else None)
            assert status == 200 and body == raw and seen["credentialMatched"]
            proof = proxy.evidence()
            assert proof["forwardedRequestCount"] == 1
            assert proof["proxyErrorCount"] == proof["droppedAckCount"] == proof["taskPostAttempts"] == 0


def test_proxy_does_not_claim_dropped_ack_for_rejected_post():
    with _ack_upstream(status=409) as (upstream, _, raw):
        with recovery.LostAcknowledgementProxy(upstream, "probe") as proxy:
            status, body = _proxy_request(proxy, "POST", recovery.LOCAL_TASK_PREFIX + "tasks", {"client_request_id": "probe"})
            assert status == 409 and body == raw
            proof = proxy.evidence()
            assert proof["taskPostAttempts"] == 1 and proof["droppedAckCount"] == proof["taskPostSuccessCount"] == 0
            with pytest.raises(recovery.AcceptanceFailure, match="ack_proxy_did_not_drop_real_acceptance"):
                recovery.assert_lost_ack_proof(proof, "task-real", 1)


@pytest.mark.parametrize("upstream", ["http://example.com:80", "https://127.0.0.1:443", "http://127.0.0.1:80/path",
                                       "http://user@127.0.0.1:80", "http://127.0.0.1:80?query=1"])
def test_proxy_refuses_nonprivate_or_ambiguous_upstream(upstream):
    with pytest.raises(recovery.AcceptanceFailure, match="ack_proxy_requires_loopback_upstream"):
        recovery.LostAcknowledgementProxy(upstream, "probe")


@pytest.mark.parametrize("path", ["/api/config", "/api/v1/external-agent/tasks", "http://example.com/api/control-token",
                                   recovery.LOCAL_TASK_PREFIX + "tasks/../config"])
def test_proxy_does_not_forward_outside_native_task_transport(path):
    assert not recovery.LostAcknowledgementProxy._allowed_path("POST", path)


@pytest.mark.parametrize("change", ["no_lookup", "different_lookup_id", "multiple_native_ids", "duplicate_records", "proxy_error"])
def test_ack_proof_rejects_missing_lookup_or_duplicate_native_admission(change):
    proof = {"taskPostSuccessCount": 1, "droppedAckCount": 1, "requestLookupSuccessCount": 1,
             "postNativeTaskIds": ["task-real"], "lookupNativeTaskIds": ["task-real"], "proxyErrorCount": 0}
    records = 1
    if change == "no_lookup":
        proof["requestLookupSuccessCount"] = 0
    elif change == "different_lookup_id":
        proof["lookupNativeTaskIds"] = ["different-task"]
    elif change == "multiple_native_ids":
        proof["postNativeTaskIds"].append("different-task")
    elif change == "duplicate_records":
        records = 2
    else:
        proof["proxyErrorCount"] = 1
    with pytest.raises(recovery.AcceptanceFailure):
        recovery.assert_lost_ack_proof(proof, "task-real", records)


@pytest.mark.parametrize("stop_fails", [False, True])
def test_probe_failure_stops_owned_proxy_and_restores_descriptor_after_host_stop(tmp_path, stop_fails):
    source = tmp_path / "source"
    source.mkdir()
    (source / "README.md").write_text("Private test fixture\n", encoding="utf-8")
    runtime = tmp_path / "runtime"
    descriptor = runtime / "launcher" / "state.json"
    descriptor.parent.mkdir(parents=True)
    with _ack_upstream() as (upstream, _, _):
        original = json.dumps({"url": upstream, "runtimeProjectRoot": str(source), "runtimeSourceCommit": "abc"}).encode()
        descriptor.write_bytes(original)
        state = {"stopped": False, "stops": 0}

        def stop():
            state["stops"] += 1
            if stop_fails and state["stops"] == 2:
                raise recovery.AcceptanceFailure("injected_stop_failure")
            state["stopped"] = True

        def force_stop():
            state["stopped"] = True
            state["forced"] = True

        def start():
            state["stopped"] = False
            assert json.loads(descriptor.read_bytes())["url"] != upstream

        def send(*_args, **_kwargs):
            raise recovery.AcceptanceFailure("injected_probe_failure")

        fixture = SimpleNamespace(home=tmp_path, source=source, primary_project_id="project",
            backends={"project": SimpleNamespace(runtime_root=runtime, root=source, url=upstream)}, stop_host=stop, start_host=start,
            send=send, force_stop_host_after_failure=force_stop,
            host_process=SimpleNamespace(poll=lambda: 0 if state["stopped"] else None))
        record = {}
        with pytest.raises(recovery.AcceptanceFailure, match="injected_stop_failure" if stop_fails else "injected_probe_failure"):
            recovery._run_lost_ack(fixture, record, recovery.time.monotonic() + 30, "agent", set())
        assert state["stopped"] and state["stops"] == 2
        assert record["proxyStopped"] and record["descriptorRestored"]
        assert descriptor.read_bytes() == original
        assert state.get("forced", False) is stop_fails


def test_proxy_context_releases_its_socket_when_probe_raises():
    with _ack_upstream() as (upstream, _, _):
        proxy = recovery.LostAcknowledgementProxy(upstream, "probe")
        with pytest.raises(recovery.AcceptanceFailure, match="injected_probe_failure"):
            with proxy:
                port = int(proxy.url.rsplit(":", 1)[1])
                raise recovery.AcceptanceFailure("injected_probe_failure")
        assert proxy.closed
        with pytest.raises(OSError):
            socket.create_connection(("127.0.0.1", port), timeout=0.2)
