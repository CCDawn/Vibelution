import json
import subprocess
import sys

import pytest

from core.runtime_manager import cli as runtime_cli
from core.runtime_manager import command_queue
from core.runtime_manager import daemon
from core.runtime_manager import constants
from core.runtime_manager import evolution_store
from core.runtime_manager import process_inventory
from core.runtime_manager import state_store
from core.runtime_manager import workbench_controller


def test_print_status_reports_stale_runtime_manager_source(capsys):
    runtime_cli._print_status(
        {
            "daemonRunning": True,
            "managerPid": 100,
            "projectRoot": "C:/project",
            "statePath": "C:/project/.runtime/runtime-manager/state.json",
            "workbench": {
                "desiredState": "open",
                "observedState": "open",
                "phase": "steady",
                "backendPid": 200,
                "browserWindowPid": 300,
                "url": "http://127.0.0.1:8766",
            },
            "runtimeManager": {"sourceMatches": False},
        }
    )

    output = capsys.readouterr().out
    assert "source changed" in output


def test_cli_command_forwards_stop_manager(monkeypatch):
    calls = []

    monkeypatch.setattr(runtime_cli, "ensure_daemon_running", lambda: calls.append("ensure"))
    monkeypatch.setattr(
        runtime_cli,
        "submit_command",
        lambda command_type, args=None, requested_by="unknown": calls.append((command_type, args, requested_by))
        or {"commandId": "cmd-stop-manager"},
    )

    exit_code = runtime_cli.main(["command", "close_workbench", "--reason", "launcher_stop", "--stop-manager"])

    assert exit_code == 0
    assert calls == [
        "ensure",
        ("close_workbench", {"reason": "launcher_stop", "stopManager": True}, "cli"),
    ]


def test_cli_command_forwards_no_browser_without_stop_manager(monkeypatch):
    calls = []

    monkeypatch.setattr(runtime_cli, "ensure_daemon_running", lambda: calls.append("ensure"))
    monkeypatch.setattr(
        runtime_cli,
        "submit_command",
        lambda command_type, args=None, requested_by="unknown": calls.append((command_type, args, requested_by))
        or {"commandId": "cmd-no-browser"},
    )

    exit_code = runtime_cli.main(["command", "open_workbench", "--reason", "launcher_start", "--no-browser"])

    assert exit_code == 0
    assert calls == [
        "ensure",
        ("open_workbench", {"reason": "launcher_start", "noBrowser": True}, "cli"),
    ]


def test_load_runtime_snapshot_aligns_legacy_open_session(monkeypatch):
    monkeypatch.setattr(
        daemon,
        "load_state",
        lambda: {
            "stateVersion": 3,
            "workbench": {
                "desiredState": "closed",
                "observedState": "closed",
                "phase": "steady",
            },
            "command": {"activeCommandId": ""},
        },
    )
    monkeypatch.setattr(
        daemon,
        "observe_workbench",
        lambda: {
            "observedState": "open",
            "backendPid": 3200,
            "browserLaunchPid": 0,
            "browserWindowPid": 4500,
            "browserManaged": True,
            "sessionId": "legacy-session",
            "url": "http://127.0.0.1:8000",
        },
    )
    monkeypatch.setattr(daemon, "is_daemon_running", lambda: False)
    monkeypatch.setattr(daemon, "load_pid", lambda: 0)

    snapshot = daemon.load_runtime_snapshot()

    assert snapshot["runtimeState"] == "idle"
    assert snapshot["workbench"]["desiredState"] == "open"
    assert snapshot["workbench"]["observedState"] == "open"
    assert snapshot["workbench"]["phase"] == "steady"


def test_load_runtime_snapshot_preserves_failed_close_state(monkeypatch):
    monkeypatch.setattr(
        daemon,
        "load_state",
        lambda: {
            "stateVersion": 8,
            "workbench": {
                "desiredState": "closed",
                "observedState": "open",
                "phase": "failed",
                "failureMessage": "stop failed",
            },
            "command": {"activeCommandId": ""},
        },
    )
    monkeypatch.setattr(
        daemon,
        "observe_workbench",
        lambda: {
            "observedState": "open",
            "backendPid": 3200,
            "browserLaunchPid": 0,
            "browserWindowPid": 4500,
            "browserManaged": True,
            "sessionId": "legacy-session",
            "url": "http://127.0.0.1:8000",
        },
    )
    monkeypatch.setattr(daemon, "is_daemon_running", lambda: True)
    monkeypatch.setattr(daemon, "load_pid", lambda: 9912)

    snapshot = daemon.load_runtime_snapshot()

    assert snapshot["runtimeState"] == "running"
    assert snapshot["workbench"]["desiredState"] == "closed"
    assert snapshot["workbench"]["phase"] == "failed"
    assert snapshot["workbench"]["failureMessage"] == "stop failed"


def test_load_runtime_snapshot_recovers_failed_non_lifecycle_error_when_observation_matches(monkeypatch):
    monkeypatch.setattr(
        daemon,
        "load_state",
        lambda: {
            "stateVersion": 9,
            "workbench": {
                "desiredState": "open",
                "observedState": "open",
                "phase": "failed",
                "failureMessage": "missing supervised run",
            },
            "command": {"activeCommandId": ""},
            "lastError": {
                "scope": "stop_supervised_run",
                "message": "missing supervised run",
                "at": "2026-05-19T08:00:00+00:00",
            },
        },
    )
    monkeypatch.setattr(
        daemon,
        "observe_workbench",
        lambda: {
            "observedState": "open",
            "backendPid": 3200,
            "browserLaunchPid": 0,
            "browserWindowPid": 4500,
            "browserManaged": True,
            "sessionId": "managed-session",
            "url": "http://127.0.0.1:8000",
        },
    )
    monkeypatch.setattr(daemon, "is_daemon_running", lambda: True)
    monkeypatch.setattr(daemon, "load_pid", lambda: 9912)
    monkeypatch.setattr(daemon, "_process_source_signature", lambda: "sig-current")

    snapshot = daemon.load_runtime_snapshot()

    assert snapshot["workbench"]["phase"] == "steady"
    assert snapshot["workbench"]["failureMessage"] == ""
    assert "Workbench is open" in snapshot["workbench"]["statusLine"]


def test_handle_start_supervised_run_returns_snapshot(monkeypatch):
    runtime_daemon = daemon.RuntimeManagerDaemon()
    monkeypatch.setattr(daemon, "load_state", lambda: {"command": {}, "workbench": {}})
    monkeypatch.setattr(daemon, "save_state", lambda state: state)
    monkeypatch.setattr(daemon, "now_iso", lambda: "2026-05-19T08:00:00+00:00")
    monkeypatch.setattr(daemon, "observe_workbench", lambda: {"observedState": "closed"})
    monkeypatch.setattr(daemon, "build_evolution_summary", lambda: {"self": {}, "supervised": {}})
    monkeypatch.setattr(
        daemon.supervised_control_service,
        "_LOCAL_START_SUPERVISED_RUN",
        lambda payload: {"runId": "web-supervised-managed", "status": "queued", "payload": payload},
    )

    result = runtime_daemon._handle_start_supervised_run(
        command_id="cmd-1",
        args={"payload": {"sourceKind": "bundle", "bundleName": "managed_bundle"}},
    )

    assert result["ok"] is True
    assert result["runId"] == "web-supervised-managed"
    assert result["snapshot"]["status"] == "queued"


def test_run_forever_refreshes_manager_started_at(monkeypatch):
    class StopLoop(Exception):
        pass

    runtime_daemon = daemon.RuntimeManagerDaemon()
    saved_states: list[dict] = []
    timestamps = iter(["2026-05-19T08:00:00+00:00", "2026-05-19T08:00:01+00:00"])

    monkeypatch.setattr(daemon, "ensure_runtime_manager_dirs", lambda: None)
    monkeypatch.setattr(daemon, "recover_processing_queue", lambda: None)
    monkeypatch.setattr(daemon, "save_pid", lambda pid: None)
    monkeypatch.setattr(
        daemon,
        "load_state",
        lambda: {
            "startedAt": "2026-05-18T01:00:00+00:00",
            "command": {},
            "workbench": {},
        },
    )
    monkeypatch.setattr(daemon, "now_iso", lambda: next(timestamps))
    monkeypatch.setattr(daemon, "observe_workbench", lambda: {"observedState": "closed"})
    monkeypatch.setattr(daemon, "build_evolution_summary", lambda: {"self": {}, "supervised": {}})
    monkeypatch.setattr(daemon, "_process_source_signature", lambda: "sig-current")
    monkeypatch.setattr(daemon, "save_state", lambda state: saved_states.append(json.loads(json.dumps(state))) or state)

    def stop_after_startup():
        raise StopLoop()

    monkeypatch.setattr(daemon, "claim_next_command", stop_after_startup)

    with pytest.raises(StopLoop):
        runtime_daemon.run_forever()

    assert saved_states[0]["startedAt"] == "2026-05-19T08:00:00+00:00"
    assert saved_states[0]["runtimeManager"]["sourceSignature"] == "sig-current"


def test_run_forever_cleans_descendants_before_completing_stop_daemon(monkeypatch):
    runtime_daemon = daemon.RuntimeManagerDaemon()
    order: list[str] = []

    monkeypatch.setattr(daemon, "ensure_runtime_manager_dirs", lambda: None)
    monkeypatch.setattr(daemon, "recover_processing_queue", lambda: None)
    monkeypatch.setattr(daemon, "save_pid", lambda pid: None)
    monkeypatch.setattr(
        daemon,
        "load_state",
        lambda: {
            "startedAt": "2026-05-18T01:00:00+00:00",
            "command": {},
            "workbench": {},
        },
    )
    monkeypatch.setattr(daemon, "now_iso", lambda: "2026-05-19T08:00:00+00:00")
    monkeypatch.setattr(daemon, "observe_workbench", lambda: {"observedState": "closed"})
    monkeypatch.setattr(daemon, "build_evolution_summary", lambda: {"self": {}, "supervised": {}})
    monkeypatch.setattr(daemon, "_process_source_signature", lambda: "sig-current")
    monkeypatch.setattr(daemon, "save_state", lambda state: state)

    commands = iter(
        [
            (
                "cmd-path",
                {
                    "commandId": "cmd-stop",
                    "type": "close_workbench",
                    "requestedBy": "test",
                    "args": {"stopManager": True},
                },
            )
        ]
    )
    monkeypatch.setattr(daemon, "claim_next_command", lambda: next(commands))
    monkeypatch.setattr(
        runtime_daemon,
        "_handle_command",
        lambda payload: {
            "commandId": payload["commandId"],
            "accepted": True,
            "completed": True,
            "ok": True,
            "message": "closed",
            "stopDaemon": True,
        },
    )
    monkeypatch.setattr(
        daemon,
        "_prepare_daemon_shutdown",
        lambda: order.append("cleanup") or {"closedEvolutionRuns": [], "descendantCleanup": {"terminated": [991]}},
    )
    monkeypatch.setattr(
        daemon,
        "complete_command",
        lambda path, result: order.append(f"complete:{result['descendantCleanup']['terminated'][0]}"),
    )
    monkeypatch.setattr(daemon, "_append_event", lambda event_type, payload: order.append(event_type))
    monkeypatch.setattr(daemon, "clear_pid", lambda pid: order.append("clear_pid"))
    def fake_exit(code: int = 0):
        order.append(f"exit:{code}")
        raise SystemExit(code)

    monkeypatch.setattr(daemon, "_exit_current_process", fake_exit)

    with pytest.raises(SystemExit) as exit_info:
        runtime_daemon.run_forever()

    assert order[:3] == ["cleanup", "daemon.stopped", "complete:991"]
    assert order[-3:] == ["clear_pid", "exit:0", "clear_pid"]
    assert exit_info.value.code == 0


def test_run_forever_marks_runtime_stopping_before_stop_result(monkeypatch):
    runtime_daemon = daemon.RuntimeManagerDaemon()
    saved_states: list[dict] = []

    monkeypatch.setattr(daemon, "ensure_runtime_manager_dirs", lambda: None)
    monkeypatch.setattr(daemon, "recover_processing_queue", lambda: None)
    monkeypatch.setattr(daemon, "save_pid", lambda pid: None)
    monkeypatch.setattr(
        daemon,
        "load_state",
        lambda: {
            "runtimeState": "running",
            "startedAt": "2026-05-18T01:00:00+00:00",
            "command": {},
            "workbench": {},
        },
    )
    monkeypatch.setattr(daemon, "now_iso", lambda: "2026-05-19T08:00:00+00:00")
    monkeypatch.setattr(daemon, "observe_workbench", lambda: {"observedState": "closed"})
    monkeypatch.setattr(daemon, "build_evolution_summary", lambda: {"self": {}, "supervised": {}})
    monkeypatch.setattr(daemon, "_process_source_signature", lambda: "sig-current")
    monkeypatch.setattr(daemon, "save_state", lambda state: saved_states.append(json.loads(json.dumps(state))) or state)
    monkeypatch.setattr(
        daemon,
        "claim_next_command",
        lambda: (
            "cmd-path",
            {
                "commandId": "cmd-stop",
                "type": "close_workbench",
                "requestedBy": "test",
                "args": {"stopManager": True},
            },
        ),
    )
    monkeypatch.setattr(
        runtime_daemon,
        "_handle_command",
        lambda payload: {
            "commandId": payload["commandId"],
            "accepted": True,
            "completed": True,
            "ok": True,
            "message": "closed",
            "stopDaemon": True,
        },
    )
    monkeypatch.setattr(daemon, "_prepare_daemon_shutdown", lambda: {"closedEvolutionRuns": [], "descendantCleanup": {}})
    monkeypatch.setattr(daemon, "complete_command", lambda path, result: None)
    monkeypatch.setattr(daemon, "_append_event", lambda event_type, payload: None)
    monkeypatch.setattr(daemon, "clear_pid", lambda pid: None)

    def fake_exit(code: int = 0):
        raise SystemExit(code)

    monkeypatch.setattr(daemon, "_exit_current_process", fake_exit)

    with pytest.raises(SystemExit):
        runtime_daemon.run_forever()

    assert any(state.get("runtimeState") == "stopping" for state in saved_states)


def test_submit_command_rejects_open_while_runtime_manager_is_stopping(tmp_path, monkeypatch):
    inbox_dir = tmp_path / "inbox"
    processing_dir = tmp_path / "processing"
    results_dir = tmp_path / "results"
    events_path = tmp_path / "events.jsonl"
    for path in (inbox_dir, processing_dir, results_dir):
        path.mkdir(parents=True)

    monkeypatch.setattr(command_queue, "INBOX_DIR", inbox_dir)
    monkeypatch.setattr(command_queue, "PROCESSING_DIR", processing_dir)
    monkeypatch.setattr(command_queue, "RESULTS_DIR", results_dir)
    monkeypatch.setattr(command_queue, "EVENTS_PATH", events_path)
    monkeypatch.setattr(command_queue, "ensure_runtime_manager_dirs", lambda: None)
    monkeypatch.setattr(command_queue, "load_pid", lambda: 9912)
    monkeypatch.setattr(command_queue, "_process_is_alive", lambda pid: True)
    monkeypatch.setattr(
        command_queue,
        "load_state",
        lambda: {
            "stateVersion": 42,
            "runtimeState": "stopping",
            "managerPid": 9912,
            "command": {
                "activeCommandId": "",
                "activeType": "",
                "stopManager": False,
            },
        },
    )

    command = command_queue.submit_command("open_workbench", args={"reason": "launcher_start"}, requested_by="launcher_ps")
    result_path = results_dir / f"{command['commandId']}.json"

    assert list(inbox_dir.glob("*.json")) == []
    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert result["ok"] is False
    assert result["errorType"] == "RuntimeManagerStoppingError"
    assert result["runtimeManagerStopping"] is True
    assert result["stateVersion"] == 42
    event = json.loads(events_path.read_text(encoding="utf-8").splitlines()[-1])
    assert event["type"] == "command_queue.command_rejected_shutdown"
    assert event["payload"]["managerPid"] == 9912


def test_submit_command_ignores_stale_shutdown_state_from_previous_runtime_manager(tmp_path, monkeypatch):
    inbox_dir = tmp_path / "inbox"
    processing_dir = tmp_path / "processing"
    results_dir = tmp_path / "results"
    events_path = tmp_path / "events.jsonl"
    for path in (inbox_dir, processing_dir, results_dir):
        path.mkdir(parents=True)

    monkeypatch.setattr(command_queue, "INBOX_DIR", inbox_dir)
    monkeypatch.setattr(command_queue, "PROCESSING_DIR", processing_dir)
    monkeypatch.setattr(command_queue, "RESULTS_DIR", results_dir)
    monkeypatch.setattr(command_queue, "EVENTS_PATH", events_path)
    monkeypatch.setattr(command_queue, "ensure_runtime_manager_dirs", lambda: None)
    monkeypatch.setattr(command_queue, "load_pid", lambda: 9912)
    monkeypatch.setattr(command_queue, "_process_is_alive", lambda pid: True)
    monkeypatch.setattr(
        command_queue,
        "load_state",
        lambda: {
            "stateVersion": 99,
            "runtimeState": "stopping",
            "managerPid": 7711,
            "command": {
                "activeCommandId": "cmd-old-close",
                "activeType": "close_workbench",
                "stopManager": True,
            },
        },
    )

    command = command_queue.submit_command("open_workbench", args={"reason": "launcher_start"}, requested_by="launcher_ps")

    queued = list(inbox_dir.glob("*.json"))
    assert len(queued) == 1
    assert queued[0].name == f"{command['commandId']}.json"
    assert list(results_dir.glob("*.json")) == []
    queued_payload = json.loads(queued[0].read_text(encoding="utf-8"))
    assert queued_payload["type"] == "open_workbench"
    event = json.loads(events_path.read_text(encoding="utf-8").splitlines()[-1])
    assert event["type"] == "command_queue.stale_shutdown_state_ignored"
    assert event["payload"]["stateManagerPid"] == 7711
    assert event["payload"]["currentManagerPid"] == 9912


def test_submit_command_treats_duplicate_stop_manager_close_as_idempotent(tmp_path, monkeypatch):
    inbox_dir = tmp_path / "inbox"
    processing_dir = tmp_path / "processing"
    results_dir = tmp_path / "results"
    events_path = tmp_path / "events.jsonl"
    for path in (inbox_dir, processing_dir, results_dir):
        path.mkdir(parents=True)

    monkeypatch.setattr(command_queue, "INBOX_DIR", inbox_dir)
    monkeypatch.setattr(command_queue, "PROCESSING_DIR", processing_dir)
    monkeypatch.setattr(command_queue, "RESULTS_DIR", results_dir)
    monkeypatch.setattr(command_queue, "EVENTS_PATH", events_path)
    monkeypatch.setattr(command_queue, "ensure_runtime_manager_dirs", lambda: None)
    monkeypatch.setattr(command_queue, "load_pid", lambda: 9912)
    monkeypatch.setattr(command_queue, "_process_is_alive", lambda pid: True)
    monkeypatch.setattr(
        command_queue,
        "load_state",
        lambda: {
            "stateVersion": 43,
            "runtimeState": "running",
            "managerPid": 9912,
            "command": {
                "activeCommandId": "cmd-active-close",
                "activeType": "close_workbench",
                "stopManager": True,
            },
        },
    )

    command = command_queue.submit_command(
        "close_workbench",
        args={"reason": "launcher_stop", "stopManager": True},
        requested_by="launcher_ps",
    )
    result = json.loads((results_dir / f"{command['commandId']}.json").read_text(encoding="utf-8"))

    assert list(inbox_dir.glob("*.json")) == []
    assert result["ok"] is True
    assert result["runtimeManagerStopping"] is True
    assert result["message"] == "Runtime manager shutdown is already in progress."


def test_reject_pending_commands_for_shutdown_removes_stale_open_from_inbox(tmp_path, monkeypatch):
    inbox_dir = tmp_path / "inbox"
    processing_dir = tmp_path / "processing"
    results_dir = tmp_path / "results"
    for path in (inbox_dir, processing_dir, results_dir):
        path.mkdir(parents=True)
    command_path = inbox_dir / "cmd-open.json"
    command_path.write_text(
        json.dumps(
            {
                "commandId": "cmd-open",
                "type": "open_workbench",
                "requestedBy": "launcher_ps",
                "args": {"reason": "launcher_start"},
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(command_queue, "INBOX_DIR", inbox_dir)
    monkeypatch.setattr(command_queue, "RESULTS_DIR", results_dir)
    monkeypatch.setattr(command_queue, "ensure_runtime_manager_dirs", lambda: None)

    cleanup = command_queue.reject_pending_commands_for_shutdown(shutdown_state={"stateVersion": 44})

    assert cleanup["count"] == 1
    assert cleanup["items"] == [{"commandId": "cmd-open", "type": "open_workbench", "status": "completed"}]
    assert list(inbox_dir.glob("*.json")) == []
    result = json.loads((results_dir / "cmd-open.json").read_text(encoding="utf-8"))
    assert result["ok"] is False
    assert result["errorType"] == "RuntimeManagerStoppingError"
    assert result["stateVersion"] == 44


def test_prepare_daemon_shutdown_records_rejected_pending_commands(monkeypatch):
    events: list[tuple[str, dict]] = []

    monkeypatch.setattr(daemon, "_close_active_evolution_runs_for_shutdown", lambda: [])
    monkeypatch.setattr(daemon, "terminate_process_descendants", lambda *args, **kwargs: {"terminated": []})
    monkeypatch.setattr(daemon, "load_state", lambda: {"stateVersion": 45})
    monkeypatch.setattr(
        daemon,
        "reject_pending_commands_for_shutdown",
        lambda shutdown_state=None: {
            "count": 2,
            "items": [
                {"commandId": "cmd-open", "type": "open_workbench", "status": "completed"},
                {"commandId": "cmd-bad", "type": "restart_workbench", "status": "failed", "error": "locked"},
            ],
        },
    )
    monkeypatch.setattr(daemon, "_append_event", lambda event_type, payload: events.append((event_type, payload)))

    cleanup = daemon._prepare_daemon_shutdown()

    assert cleanup["rejectedPendingCommands"]["count"] == 2
    assert events == [
        (
            "daemon.shutdown.rejected_pending_commands",
            {
                "count": 2,
                "commands": [
                    {"commandId": "cmd-open", "type": "open_workbench", "status": "completed"},
                    {"commandId": "cmd-bad", "type": "restart_workbench", "status": "failed"},
                ],
            },
        )
    ]


def test_handle_command_reports_exception_type(monkeypatch):
    runtime_daemon = daemon.RuntimeManagerDaemon()
    monkeypatch.setattr(daemon, "load_state", lambda: {"command": {}, "workbench": {}})
    monkeypatch.setattr(daemon, "save_state", lambda state: state)
    monkeypatch.setattr(daemon, "observe_workbench", lambda: {"observedState": "closed"})
    monkeypatch.setattr(daemon, "build_evolution_summary", lambda: {"self": {}, "supervised": {}})

    def boom(*, command_id: str, args: dict):
        raise ValueError("bad payload")

    monkeypatch.setattr(runtime_daemon, "_handle_start_supervised_run", boom)

    result = runtime_daemon._handle_command(
        {
            "commandId": "cmd-err",
            "type": "start_supervised_run",
            "requestedBy": "test",
            "args": {},
        }
    )

    assert result["ok"] is False
    assert result["errorType"] == "ValueError"


def test_non_lifecycle_command_failure_does_not_mark_workbench_failed(monkeypatch):
    runtime_daemon = daemon.RuntimeManagerDaemon()
    saved_states: list[dict] = []
    state = {
        "command": {"activeCommandId": "cmd-err", "activeType": "stop_supervised_run"},
        "workbench": {
            "desiredState": "open",
            "observedState": "open",
            "phase": "steady",
            "failureMessage": "",
        },
    }
    monkeypatch.setattr(daemon, "load_state", lambda: json.loads(json.dumps(state)))
    monkeypatch.setattr(daemon, "save_state", lambda payload: saved_states.append(payload) or payload)
    monkeypatch.setattr(
        daemon,
        "observe_workbench",
        lambda: {
            "observedState": "open",
            "backendPid": 3200,
            "browserLaunchPid": 0,
            "browserWindowPid": 4500,
            "browserManaged": True,
        },
    )
    monkeypatch.setattr(daemon, "build_evolution_summary", lambda: {"self": {}, "supervised": {}})

    def boom(*, command_id: str, args: dict):
        raise daemon.supervised_control_service.SupervisedRunNotFoundError("missing supervised run")

    monkeypatch.setattr(runtime_daemon, "_handle_stop_supervised_run", boom)

    result = runtime_daemon._handle_command(
        {
            "commandId": "cmd-err",
            "type": "stop_supervised_run",
            "requestedBy": "test",
            "args": {"runId": "missing"},
        }
    )

    assert result["ok"] is False
    assert result["errorType"] == "SupervisedRunNotFoundError"
    assert saved_states[-1]["lastError"]["scope"] == "stop_supervised_run"
    assert saved_states[-1]["workbench"]["phase"] == "steady"
    assert saved_states[-1]["workbench"]["failureMessage"] == ""


def test_is_process_alive_windows_with_real_process():
    import os
    import sys
    import time

    if os.name != "nt":
        return

    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(2)"])
    try:
        deadline = time.time() + 2.0
        while time.time() < deadline and not daemon._is_process_alive(proc.pid):
            time.sleep(0.05)
        assert daemon._is_process_alive(proc.pid) is True
    finally:
        proc.terminate()
        proc.wait(timeout=5)

    assert daemon._is_process_alive(proc.pid) is False


def test_ensure_daemon_running_restarts_stale_source_signature(monkeypatch, tmp_path):
    events: list[tuple[str, dict]] = []
    terminated: list[int] = []
    popen_calls: list[list[str]] = []
    running_checks = iter([False, True])

    monkeypatch.setattr(daemon, "load_pid", lambda: 12345)
    monkeypatch.setattr(daemon, "_is_process_alive", lambda pid: pid == 12345)
    monkeypatch.setattr(
        daemon,
        "load_state",
        lambda: {
            "runtimeManager": {"sourceSignature": "old-signature"},
            "command": {"activeCommandId": "", "startedAt": ""},
        },
    )
    monkeypatch.setattr(daemon, "_process_source_signature", lambda: "new-signature")
    monkeypatch.setattr(daemon, "_append_event", lambda event_type, payload: events.append((event_type, payload)))
    monkeypatch.setattr(daemon, "_terminate_daemon_process", lambda pid: terminated.append(pid))
    monkeypatch.setattr(daemon, "ensure_runtime_manager_dirs", lambda: None)
    monkeypatch.setattr(daemon, "is_daemon_running", lambda: next(running_checks))
    monkeypatch.setattr(daemon, "DAEMON_STDOUT_PATH", tmp_path / "daemon.out.log")
    monkeypatch.setattr(daemon, "DAEMON_STDERR_PATH", tmp_path / "daemon.err.log")
    monkeypatch.setattr(
        daemon.subprocess,
        "Popen",
        lambda args, **kwargs: popen_calls.append(args),
    )

    assert daemon.ensure_daemon_running(python_executable="python-test") is True
    assert terminated == [12345]
    assert events == [("daemon.restart_requested", {"pid": 12345, "reason": "runtime_manager_source_changed"})]
    assert popen_calls == [["python-test", "-m", "core.runtime_manager.cli", "daemon"]]


def test_ensure_daemon_running_keeps_current_source_signature(monkeypatch):
    monkeypatch.setattr(daemon, "load_pid", lambda: 12345)
    monkeypatch.setattr(daemon, "_is_process_alive", lambda pid: True)
    monkeypatch.setattr(
        daemon,
        "load_state",
        lambda: {
            "runtimeManager": {"sourceSignature": "same-signature"},
            "command": {"activeCommandId": "", "startedAt": ""},
        },
    )
    monkeypatch.setattr(daemon, "_process_source_signature", lambda: "same-signature")

    assert daemon.ensure_daemon_running() is False


def test_load_launcher_state_supports_utf8_bom(tmp_path, monkeypatch):
    launcher_state_path = tmp_path / "state.json"
    launcher_state_path.write_text(
        json.dumps({"backendPid": 28888, "browserManaged": False}),
        encoding="utf-8-sig",
    )
    monkeypatch.setattr(workbench_controller, "LAUNCHER_STATE_PATH", launcher_state_path)

    state = workbench_controller._load_launcher_state()

    assert state["backendPid"] == 28888
    assert state["browserManaged"] is False


def test_observe_workbench_drops_stale_backend_pid(monkeypatch):
    monkeypatch.setattr(
        workbench_controller,
        "_load_launcher_state",
        lambda: {
            "url": "http://127.0.0.1:8000",
            "backendPid": 40904,
            "browserLaunchPid": 0,
            "browserWindowPid": 0,
            "browserManaged": False,
            "sessionId": "stale-no-browser",
        },
    )
    monkeypatch.setattr(workbench_controller, "_is_process_alive", lambda pid: False)
    monkeypatch.setattr(workbench_controller, "_is_backend_healthy", lambda url: False)
    monkeypatch.setattr(workbench_controller, "_listening_pid_for_port", lambda port: 0)
    monkeypatch.setattr(workbench_controller, "_port_is_listening_socket", lambda port: False)

    observation = workbench_controller.observe_workbench()

    assert observation["observedState"] == "closed"
    assert observation["backendPid"] == 0
    assert observation["backendAlive"] is False
    assert observation["backendObserved"] is False


def test_run_launcher_action_passes_configured_port_to_launcher_env(monkeypatch):
    captured = {}

    def fake_run(*args, **kwargs):
        captured["kwargs"] = kwargs
        kwargs["stdout"].write(b"ok\n")
        kwargs["stdout"].flush()
        return subprocess.CompletedProcess(args=args[0], returncode=0)

    monkeypatch.setattr(workbench_controller, "configured_backend_port", lambda: 9101)
    monkeypatch.setattr(workbench_controller.subprocess, "run", fake_run)

    result = workbench_controller.run_launcher_action("internal-start")

    assert result.returncode == 0
    assert captured["kwargs"]["env"]["VIBELUTION_PORT"] == "9101"


def test_handle_open_workbench_restarts_headless_session(monkeypatch):
    runtime_daemon = daemon.RuntimeManagerDaemon()
    state = {
        "command": {},
        "workbench": {
            "desiredState": "open",
            "observedState": "open",
            "phase": "steady",
        },
    }

    monkeypatch.setattr(daemon, "load_state", lambda: state)
    monkeypatch.setattr(daemon, "save_state", lambda next_state: next_state)
    monkeypatch.setattr(daemon, "now_iso", lambda: "2026-05-19T09:00:00+00:00")
    monkeypatch.setattr(
        daemon,
        "observe_workbench",
        lambda: {
            "observedState": "open",
            "launcherStatePresent": True,
            "browserManaged": False,
            "browserWindowAlive": False,
            "backendPid": 28888,
            "browserLaunchPid": 0,
            "browserWindowPid": 0,
            "sessionId": "headless-session",
            "url": "http://127.0.0.1:8000",
        },
    )
    monkeypatch.setattr(daemon, "build_evolution_summary", lambda: {"self": {}, "supervised": {}})

    opened = {}

    def fake_open_workbench(*, no_browser: bool):
        opened["no_browser"] = no_browser
        return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")

    monkeypatch.setattr(daemon, "open_workbench", fake_open_workbench)

    result = runtime_daemon._handle_open_workbench(command_id="cmd-open", args={})

    assert result["ok"] is True
    assert result["message"] == "Workbench opened."
    assert opened == {"no_browser": False}


def test_run_launcher_action_uses_devnull_stdio(monkeypatch):
    captured = {}

    def fake_run(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        kwargs["stdout"].write(b"launcher stdout\n")
        kwargs["stdout"].flush()
        kwargs["stderr"].write(b"launcher stderr\n")
        kwargs["stderr"].flush()
        return subprocess.CompletedProcess(args=args[0], returncode=0)

    monkeypatch.setattr(workbench_controller.subprocess, "run", fake_run)

    result = workbench_controller.run_launcher_action("internal-start", no_browser=True)

    assert result.returncode == 0
    assert result.stdout == "launcher stdout\n"
    assert result.stderr == "launcher stderr\n"
    assert captured["args"][0][-2:] == ["internal-start", "-NoBrowser"]
    assert captured["kwargs"]["stdin"] is subprocess.DEVNULL
    assert "capture_output" not in captured["kwargs"]
    assert "text" not in captured["kwargs"]
    assert captured["kwargs"]["stdout"] is not None
    assert captured["kwargs"]["stderr"] is not None


def test_handle_restart_workbench_surfaces_launcher_error(monkeypatch):
    runtime_daemon = daemon.RuntimeManagerDaemon()
    state = {
        "command": {},
        "workbench": {
            "desiredState": "open",
            "observedState": "open",
            "phase": "steady",
        },
    }

    monkeypatch.setattr(daemon, "load_state", lambda: state)
    monkeypatch.setattr(daemon, "save_state", lambda next_state: next_state)
    monkeypatch.setattr(daemon, "now_iso", lambda: "2026-05-19T09:00:00+00:00")
    monkeypatch.setattr(
        daemon,
        "observe_workbench",
        lambda: {
            "observedState": "open",
            "launcherStatePresent": True,
            "browserManaged": True,
            "browserWindowAlive": True,
            "backendPid": 28888,
            "browserLaunchPid": 29999,
            "browserWindowPid": 29999,
            "sessionId": "managed-session",
            "url": "http://127.0.0.1:8000",
        },
    )
    monkeypatch.setattr(daemon, "build_evolution_summary", lambda: {"self": {}, "supervised": {}})
    monkeypatch.setattr(
        daemon,
        "restart_workbench",
        lambda **kwargs: subprocess.CompletedProcess(args=[], returncode=1, stdout=None, stderr="launcher failed"),
    )

    with pytest.raises(RuntimeError, match="launcher failed"):
        runtime_daemon._handle_restart_workbench(command_id="cmd-restart", args={})


def test_handle_close_workbench_records_shutdown_source(monkeypatch):
    runtime_daemon = daemon.RuntimeManagerDaemon()
    saved_states: list[dict] = []
    state = {
        "command": {"activeCommandId": "cmd-close"},
        "workbench": {
            "desiredState": "open",
            "observedState": "open",
            "phase": "steady",
        },
    }

    monkeypatch.setattr(daemon, "load_state", lambda: state)
    monkeypatch.setattr(daemon, "save_state", lambda next_state: saved_states.append(json.loads(json.dumps(next_state))) or next_state)
    monkeypatch.setattr(daemon, "now_iso", lambda: "2026-05-19T09:00:00+00:00")
    monkeypatch.setattr(
        daemon,
        "observe_workbench",
        lambda: {
            "observedState": "open",
            "launcherStatePresent": True,
            "browserManaged": True,
            "browserWindowAlive": True,
            "backendPid": 28888,
            "browserLaunchPid": 29999,
            "browserWindowPid": 29999,
            "sessionId": "managed-session",
            "url": "http://127.0.0.1:8000",
        },
    )
    monkeypatch.setattr(daemon, "build_evolution_summary", lambda: {"self": {}, "supervised": {}})
    monkeypatch.setattr(
        daemon,
        "close_workbench",
        lambda: subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr=""),
    )
    closed_calls = []
    monkeypatch.setattr(
        daemon,
        "_close_active_evolution_runs_for_shutdown",
        lambda: closed_calls.append("closed") or [],
    )

    result = runtime_daemon._handle_close_workbench(
        command_id="cmd-close",
        args={"reason": "web_close_button", "source": "web_ui"},
    )

    assert result["ok"] is True
    assert closed_calls == ["closed"]
    assert saved_states[0]["workbench"]["lastReason"] == "web_close_button"
    assert saved_states[0]["workbench"]["lastSource"] == "web_ui"


def test_handle_close_workbench_closes_active_evolution_runs(monkeypatch):
    runtime_daemon = daemon.RuntimeManagerDaemon()
    state = {
        "command": {"activeCommandId": "cmd-close"},
        "workbench": {
            "desiredState": "open",
            "observedState": "open",
            "phase": "steady",
        },
    }

    monkeypatch.setattr(daemon, "load_state", lambda: state)
    monkeypatch.setattr(daemon, "save_state", lambda next_state: next_state)
    monkeypatch.setattr(daemon, "now_iso", lambda: "2026-05-19T09:00:00+00:00")
    monkeypatch.setattr(
        daemon,
        "observe_workbench",
        lambda: {
            "observedState": "open",
            "launcherStatePresent": True,
            "browserManaged": True,
            "browserWindowAlive": True,
            "backendPid": 28888,
            "browserLaunchPid": 29999,
            "browserWindowPid": 29999,
            "sessionId": "managed-session",
            "url": "http://127.0.0.1:8000",
        },
    )
    monkeypatch.setattr(daemon, "build_evolution_summary", lambda: {"self": {}, "supervised": {}})
    monkeypatch.setattr(
        daemon,
        "close_workbench",
        lambda: subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr=""),
    )
    monkeypatch.setattr(
        daemon,
        "_close_active_evolution_runs_for_shutdown",
        lambda: [
            {"kind": "self_evolution_run", "runId": "web-self-active", "status": "cancelled"},
            {"kind": "supervised_evolution_run", "runId": "web-supervised-active", "status": "cancelled"},
        ],
    )

    result = runtime_daemon._handle_close_workbench(command_id="cmd-close", args={"stopManager": True})

    assert result["ok"] is True
    assert result["closedEvolutionRuns"] == [
        {"kind": "self_evolution_run", "runId": "web-self-active", "status": "cancelled"},
        {"kind": "supervised_evolution_run", "runId": "web-supervised-active", "status": "cancelled"},
    ]
    assert result["stopDaemon"] is True


def test_handle_close_workbench_does_not_short_circuit_when_backend_port_is_still_owned(monkeypatch):
    runtime_daemon = daemon.RuntimeManagerDaemon()
    state = {
        "command": {"activeCommandId": "cmd-close"},
        "workbench": {
            "desiredState": "closed",
            "observedState": "closed",
            "phase": "steady",
        },
    }
    close_calls = []

    monkeypatch.setattr(daemon, "load_state", lambda: state)
    monkeypatch.setattr(daemon, "save_state", lambda next_state: next_state)
    monkeypatch.setattr(daemon, "now_iso", lambda: "2026-05-19T09:00:00+00:00")
    monkeypatch.setattr(
        daemon,
        "observe_workbench",
        lambda: {
            "observedState": "closed",
            "launcherStatePresent": True,
            "browserManaged": True,
            "browserWindowAlive": False,
            "backendPid": 19964,
            "backendAlive": False,
            "backendHealthy": False,
            "backendObserved": True,
            "backendPort": 8766,
            "backendPortListening": True,
            "backendPortOwnerPid": 52396,
            "browserLaunchPid": 5168,
            "browserWindowPid": 5168,
            "sessionId": "managed-session",
            "url": "http://127.0.0.1:8766",
        },
    )
    monkeypatch.setattr(daemon, "build_evolution_summary", lambda: {"self": {}, "supervised": {}})

    def fake_close_workbench():
        close_calls.append("close")
        return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")

    monkeypatch.setattr(daemon, "close_workbench", fake_close_workbench)

    result = runtime_daemon._handle_close_workbench(command_id="cmd-close", args={})

    assert result["ok"] is True
    assert result["message"] == "Workbench closed."
    assert close_calls == ["close"]


def test_handle_close_workbench_cleans_residual_processes_and_can_stop_daemon(monkeypatch):
    runtime_daemon = daemon.RuntimeManagerDaemon()
    state = {
        "command": {"activeCommandId": "cmd-close"},
        "workbench": {
            "desiredState": "open",
            "observedState": "open",
            "phase": "steady",
        },
    }
    cleanup_calls: list[dict] = []

    monkeypatch.setattr(daemon, "load_state", lambda: state)
    monkeypatch.setattr(daemon, "save_state", lambda next_state: next_state)
    monkeypatch.setattr(daemon, "now_iso", lambda: "2026-05-19T09:00:00+00:00")
    monkeypatch.setattr(
        daemon,
        "observe_workbench",
        lambda: {
            "observedState": "closed",
            "launcherStatePresent": False,
            "browserManaged": True,
            "browserWindowAlive": False,
            "backendPid": 0,
            "backendAlive": False,
            "backendHealthy": False,
            "backendObserved": False,
            "backendPort": 8766,
            "backendPortListening": False,
            "backendPortOwnerPid": 0,
            "browserLaunchPid": 0,
            "browserWindowPid": 0,
            "sessionId": "",
            "url": "http://127.0.0.1:8766",
        },
    )
    monkeypatch.setattr(daemon, "build_evolution_summary", lambda: {"self": {}, "supervised": {}})
    monkeypatch.setattr(
        daemon,
        "close_workbench",
        lambda: subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr=""),
    )

    def fake_cleanup(**kwargs):
        cleanup_calls.append(kwargs)
        return {"supported": True, "requested": [49780], "terminated": [49780], "remaining": []}

    monkeypatch.setattr(daemon, "terminate_unmanaged_workbench_processes", fake_cleanup)

    result = runtime_daemon._handle_close_workbench(
        command_id="cmd-close",
        args={"stopManager": True},
    )

    assert result["ok"] is True
    assert result["stopDaemon"] is True
    assert result["residualCleanup"]["terminated"] == [49780]
    assert cleanup_calls
    assert runtime_daemon._pid in cleanup_calls[0]["exclude_pids"]


def test_handle_close_workbench_cleans_residual_processes_when_already_closed(monkeypatch):
    runtime_daemon = daemon.RuntimeManagerDaemon()
    state = {
        "command": {"activeCommandId": "cmd-close"},
        "workbench": {
            "desiredState": "closed",
            "observedState": "closed",
            "phase": "steady",
        },
    }
    cleanup_calls = []
    close_calls = []

    monkeypatch.setattr(daemon, "load_state", lambda: state)
    monkeypatch.setattr(daemon, "save_state", lambda next_state: next_state)
    monkeypatch.setattr(
        daemon,
        "observe_workbench",
        lambda: {
            "observedState": "closed",
            "backendAlive": False,
            "backendHealthy": False,
            "backendObserved": False,
            "backendPortListening": False,
            "backendPortOwnerPid": 0,
            "browserWindowAlive": False,
        },
    )
    monkeypatch.setattr(daemon, "build_evolution_summary", lambda: {"self": {}, "supervised": {}})
    monkeypatch.setattr(
        daemon,
        "close_workbench",
        lambda: close_calls.append("close") or subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr=""),
    )
    monkeypatch.setattr(
        runtime_daemon,
        "_cleanup_residual_workbench_processes",
        lambda: cleanup_calls.append("cleanup") or {"supported": True, "requested": [49128], "terminated": [49128], "remaining": []},
    )

    result = runtime_daemon._handle_close_workbench(
        command_id="cmd-close",
        args={"stopManager": True},
    )

    assert result["ok"] is True
    assert result["message"] == "Workbench is already closed."
    assert result["stopDaemon"] is True
    assert result["residualCleanup"]["terminated"] == [49128]
    assert cleanup_calls == ["cleanup"]
    assert close_calls == []


def test_observe_workbench_treats_repo_port_owner_as_open_when_tracked_pid_is_dead(tmp_path, monkeypatch):
    launcher_state_path = tmp_path / "state.json"
    launcher_state_path.write_text(
        json.dumps(
            {
                "backendPid": 19964,
                "browserWindowPid": 5168,
                "browserManaged": True,
                "url": "http://127.0.0.1:8766",
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(workbench_controller, "LAUNCHER_STATE_PATH", launcher_state_path)
    monkeypatch.setattr(workbench_controller, "_is_process_alive", lambda pid: False)
    monkeypatch.setattr(workbench_controller, "_is_backend_healthy", lambda url: False)
    monkeypatch.setattr(workbench_controller, "_listening_pid_for_port", lambda port: 52396)
    monkeypatch.setattr(workbench_controller, "_port_is_listening_socket", lambda port: False)
    monkeypatch.setattr(workbench_controller, "_pid_is_repo_workbench_backend", lambda pid: pid == 52396)

    observation = workbench_controller.observe_workbench()

    assert observation["observedState"] == "open"
    assert observation["backendObserved"] is True
    assert observation["backendPortListening"] is True
    assert observation["backendPortOwnerPid"] == 52396
    assert observation["backendPortOwnerTrusted"] is True
    assert observation["backendPortConflict"] is False


def test_observe_workbench_does_not_treat_external_port_owner_as_open(tmp_path, monkeypatch):
    launcher_state_path = tmp_path / "state.json"
    launcher_state_path.write_text(
        json.dumps(
            {
                "backendPid": 19964,
                "browserWindowPid": 0,
                "browserManaged": True,
                "url": "http://127.0.0.1:8766",
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(workbench_controller, "LAUNCHER_STATE_PATH", launcher_state_path)
    monkeypatch.setattr(workbench_controller, "_is_process_alive", lambda pid: False)
    monkeypatch.setattr(workbench_controller, "_is_backend_healthy", lambda url: True)
    monkeypatch.setattr(workbench_controller, "_listening_pid_for_port", lambda port: 52396)
    monkeypatch.setattr(workbench_controller, "_port_is_listening_socket", lambda port: True)
    monkeypatch.setattr(workbench_controller, "_pid_is_repo_workbench_backend", lambda pid: False)

    observation = workbench_controller.observe_workbench()

    assert observation["observedState"] == "closed"
    assert observation["backendObserved"] is False
    assert observation["backendPortListening"] is True
    assert observation["backendPortOwnerPid"] == 52396
    assert observation["backendPortOwnerTrusted"] is False
    assert observation["backendPortConflict"] is True


def test_listening_pid_for_port_prefers_psutil(monkeypatch):
    class LocalAddress:
        port = 8766

    class Connection:
        laddr = LocalAddress()
        status = "LISTEN"
        pid = 52396

    class FakePsutil:
        @staticmethod
        def net_connections(kind):
            assert kind == "tcp"
            return [Connection()]

    monkeypatch.setitem(sys.modules, "psutil", FakePsutil)
    monkeypatch.setattr(workbench_controller.os, "name", "nt", raising=False)
    monkeypatch.setattr(workbench_controller, "_listening_pid_for_port_windows", lambda port: 0)

    assert workbench_controller._listening_pid_for_port(8766) == 52396


def test_residual_process_payload_reports_only_unmanaged_workbench(monkeypatch, tmp_path):
    class FakeProc:
        def __init__(self, info):
            self.info = info

    repo = tmp_path / "repo"
    repo.mkdir()
    other = tmp_path / "other"
    other.mkdir()
    monkeypatch.setattr(
        process_inventory.psutil,
        "process_iter",
        lambda attrs: iter(
            [
                FakeProc(
                    {
                        "pid": 49780,
                        "ppid": 1,
                        "name": "python.exe",
                        "cmdline": ["python", "scripts/web_workbench.py", "--port", "8001", "--no-browser"],
                        "cwd": str(repo),
                    }
                ),
                FakeProc(
                    {
                        "pid": 18860,
                        "ppid": 1,
                        "name": "python.exe",
                        "cmdline": ["python", "-m", "core.runtime_manager.cli", "daemon"],
                        "cwd": str(repo),
                    }
                ),
                FakeProc(
                    {
                        "pid": 3000,
                        "ppid": 1,
                        "name": "python.exe",
                        "cmdline": ["python", "scripts/web_workbench.py", "--port", "9001", "--no-browser"],
                        "cwd": str(other),
                    }
                ),
            ]
        ),
    )

    payload = process_inventory.residual_process_payload(project_root=repo, exclude_pids={18860})

    assert payload["count"] == 1
    assert payload["items"][0]["pid"] == 49780
    assert payload["items"][0]["port"] == 8001


def test_residual_process_payload_reports_unmanaged_frontend_dev_server(monkeypatch, tmp_path):
    class FakeProc:
        def __init__(self, info):
            self.info = info

    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setattr(
        process_inventory.psutil,
        "process_iter",
        lambda attrs: iter(
            [
                FakeProc(
                    {
                        "pid": 51517,
                        "ppid": 1,
                        "name": "python.exe",
                        "cmdline": ["python", "-m", "http.server", "5173", "-d", "frontend"],
                        "cwd": str(repo),
                    }
                ),
                FakeProc(
                    {
                        "pid": 51518,
                        "ppid": 1,
                        "name": "node.exe",
                        "cmdline": ["node", "node_modules/.bin/vite", "--host", "127.0.0.1"],
                        "cwd": str(repo),
                    }
                ),
            ]
        ),
    )

    payload = process_inventory.residual_process_payload(project_root=repo)

    assert payload["count"] == 2
    assert {item["kind"] for item in payload["items"]} == {"unmanaged_frontend_dev_server"}
    assert {item["pid"] for item in payload["items"]} == {51517, 51518}
    assert {item["port"] for item in payload["items"]} == {5173}


def test_residual_process_payload_ignores_inline_diagnostics_mentioning_frontend_tools(monkeypatch, tmp_path):
    class FakeProc:
        def __init__(self, info):
            self.info = info

    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setattr(
        process_inventory.psutil,
        "process_iter",
        lambda attrs: iter(
            [
                FakeProc(
                    {
                        "pid": 51519,
                        "ppid": 1,
                        "name": "python.exe",
                        "cmdline": [
                            "python",
                            "-c",
                            "print('diagnose http.server vite 5173 frontend')",
                        ],
                        "cwd": str(repo),
                    }
                ),
            ]
        ),
    )

    payload = process_inventory.residual_process_payload(project_root=repo)

    assert payload == {"count": 0, "items": []}


def test_residual_process_payload_ignores_adjacent_repo_prefix_match(monkeypatch, tmp_path):
    class FakeProc:
        def __init__(self, info):
            self.info = info

    repo = tmp_path / "repo"
    repo.mkdir()
    adjacent_repo = tmp_path / "repo-backup"
    adjacent_repo.mkdir()
    monkeypatch.setattr(
        process_inventory.psutil,
        "process_iter",
        lambda attrs: iter(
            [
                FakeProc(
                    {
                        "pid": 49780,
                        "ppid": 1,
                        "name": "python.exe",
                        "cmdline": [
                            "python",
                            str(adjacent_repo / "scripts" / "web_workbench.py"),
                            "--port",
                            "8001",
                            "--no-browser",
                        ],
                        "cwd": "",
                    }
                ),
            ]
        ),
    )

    payload = process_inventory.residual_process_payload(project_root=repo)

    assert payload == {"count": 0, "items": []}


def test_residual_process_payload_uses_command_line_path_when_cwd_is_unavailable(monkeypatch, tmp_path):
    class FakeProc:
        def __init__(self, info):
            self.info = info

    repo = tmp_path / "repo"
    script_path = repo / "scripts" / "web_workbench.py"
    script_path.parent.mkdir(parents=True)
    script_path.write_text("", encoding="utf-8")
    monkeypatch.setattr(
        process_inventory.psutil,
        "process_iter",
        lambda attrs: iter(
            [
                FakeProc(
                    {
                        "pid": 49780,
                        "ppid": 1,
                        "name": "python.exe",
                        "cmdline": ["python", str(script_path), "--port", "8001", "--no-browser"],
                        "cwd": "",
                    }
                ),
            ]
        ),
    )

    payload = process_inventory.residual_process_payload(project_root=repo)

    assert payload["count"] == 1
    assert payload["items"][0]["pid"] == 49780
    assert payload["items"][0]["port"] == 8001


def test_atomic_write_text_retries_permission_error(tmp_path, monkeypatch):
    target_path = tmp_path / "state.json"
    replace_calls = {"count": 0}
    sleep_calls = []
    real_replace = state_store.os.replace

    monkeypatch.setattr(state_store, "ensure_runtime_manager_dirs", lambda: None)

    def flaky_replace(src: str, dst: str):
        replace_calls["count"] += 1
        if replace_calls["count"] == 1:
            raise PermissionError("locked")
        return real_replace(src, dst)

    monkeypatch.setattr(state_store.os, "replace", flaky_replace)
    monkeypatch.setattr(state_store.time, "sleep", lambda seconds: sleep_calls.append(seconds))

    state_store._atomic_write_text(target_path, "hello")

    assert target_path.read_text(encoding="utf-8") == "hello"
    assert replace_calls["count"] == 2
    assert sleep_calls == [0.05]


def test_atomic_write_text_waits_out_longer_permission_error(tmp_path, monkeypatch):
    target_path = tmp_path / "state.json"
    replace_calls = {"count": 0}
    sleep_calls = []
    real_replace = state_store.os.replace

    monkeypatch.setattr(state_store, "ensure_runtime_manager_dirs", lambda: None)

    def flaky_replace(src: str, dst: str):
        replace_calls["count"] += 1
        if replace_calls["count"] <= 8:
            raise PermissionError("locked")
        return real_replace(src, dst)

    monkeypatch.setattr(state_store.os, "replace", flaky_replace)
    monkeypatch.setattr(state_store.time, "sleep", lambda seconds: sleep_calls.append(seconds))

    state_store._atomic_write_text(target_path, "hello")

    assert target_path.read_text(encoding="utf-8") == "hello"
    assert replace_calls["count"] == 9
    assert sleep_calls[:3] == [0.05, 0.1, 0.15000000000000002]
    assert sleep_calls[-1] == 0.25


def test_atomic_write_text_falls_back_to_in_place_write_after_replace_timeout(tmp_path, monkeypatch):
    target_path = tmp_path / "state.json"
    replace_calls = {"count": 0}
    monotonic_values = iter([0.0, state_store.WRITE_RETRY_TIMEOUT_SECONDS + 0.1])

    monkeypatch.setattr(state_store, "ensure_runtime_manager_dirs", lambda: None)
    monkeypatch.setattr(state_store.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(state_store.time, "monotonic", lambda: next(monotonic_values))

    def always_locked_replace(src: str, dst: str):
        replace_calls["count"] += 1
        raise PermissionError("locked")

    monkeypatch.setattr(state_store.os, "replace", always_locked_replace)

    state_store._atomic_write_text(target_path, "hello")

    assert target_path.read_text(encoding="utf-8") == "hello"
    assert replace_calls["count"] == 1


def test_load_state_retries_transient_json_decode_error(tmp_path, monkeypatch):
    state_path = tmp_path / "state.json"
    state_path.write_text('{"runtimeState": "running"}', encoding="utf-8")
    real_json_loads = state_store.json.loads
    load_calls = {"count": 0}
    sleep_calls = []

    monkeypatch.setattr(state_store, "STATE_PATH", state_path)
    monkeypatch.setattr(state_store.time, "sleep", lambda seconds: sleep_calls.append(seconds))

    def flaky_json_loads(raw: str):
        load_calls["count"] += 1
        if load_calls["count"] == 1:
            raise json.JSONDecodeError("transient", raw, 0)
        return real_json_loads(raw)

    monkeypatch.setattr(state_store.json, "loads", flaky_json_loads)

    payload = state_store.load_state()

    assert payload["runtimeState"] == "running"
    assert load_calls["count"] == 2
    assert sleep_calls == [0.05]


def test_evolution_store_atomic_write_retries_permission_error(tmp_path, monkeypatch):
    target_path = tmp_path / "snapshot.json"
    replace_calls = {"count": 0}
    sleep_calls = []
    real_replace = evolution_store.os.replace

    monkeypatch.setattr(evolution_store, "ensure_evolution_store_dirs", lambda: None)

    def flaky_replace(src: str, dst: str):
        replace_calls["count"] += 1
        if replace_calls["count"] <= 3:
            raise PermissionError("locked")
        return real_replace(src, dst)

    monkeypatch.setattr(evolution_store.os, "replace", flaky_replace)
    monkeypatch.setattr(evolution_store.time, "sleep", lambda seconds: sleep_calls.append(seconds))

    evolution_store._atomic_write_json(target_path, {"ok": True})

    assert json.loads(target_path.read_text(encoding="utf-8")) == {"ok": True}
    assert replace_calls["count"] == 4
    assert sleep_calls == [0.05, 0.1, 0.15000000000000002]


def test_evolution_store_is_isolated_from_real_runtime_during_pytest():
    real_runtime_root = constants.PROJECT_ROOT / ".runtime" / "runtime-manager"
    run_id = "pytest-runtime-store-isolation-sentinel"
    original_index = evolution_store.load_run_index("self")
    target_path = real_runtime_root / "evolution" / "self" / "runs" / f"{run_id}.json"
    assert not target_path.exists()

    try:
        evolution_store.persist_run_snapshot(
            "self",
            {
                "runId": run_id,
                "status": "queued",
                "startedAt": "2026-05-21T00:00:00Z",
                "updatedAt": "2026-05-21T00:00:00Z",
            },
            active_run_id=run_id,
        )

        assert not target_path.exists()
    finally:
        if target_path.exists():
            target_path.unlink()
        evolution_store.save_run_index(
            "self",
            active_run_id=str(original_index.get("activeRunId") or ""),
            latest_run_id=str(original_index.get("latestRunId") or ""),
        )


def test_evolution_store_delete_snapshot_clears_active_and_repoints_latest(tmp_path, monkeypatch):
    runs_dir = tmp_path / "supervised" / "runs"
    index_path = tmp_path / "supervised" / "index.json"

    def fake_kind_paths(kind: str):
        assert kind == "supervised"
        return runs_dir, index_path

    monkeypatch.setattr(evolution_store, "_kind_paths", fake_kind_paths)
    runs_dir.mkdir(parents=True, exist_ok=True)

    old = {
        "runId": "old-run",
        "status": "cancelled",
        "startedAt": "2026-05-18T11:00:00Z",
        "updatedAt": "2026-05-18T11:00:00Z",
    }
    active = {
        "runId": "active-run",
        "status": "queued",
        "startedAt": "2026-05-18T12:00:00Z",
        "updatedAt": "2026-05-18T12:00:00Z",
    }
    evolution_store.persist_run_snapshot("supervised", old, active_run_id="")
    evolution_store.persist_run_snapshot("supervised", active, active_run_id="active-run")

    result = evolution_store.delete_run_snapshot("supervised", "active-run")

    assert result["deleted"] is True
    assert result["clearedActive"] is True
    assert result["clearedLatest"] is True
    assert result["activeRunId"] == ""
    assert result["latestRunId"] == "old-run"
    assert evolution_store.load_run_snapshot("supervised", "active-run") is None
    assert evolution_store.load_latest_run_snapshot("supervised")["runId"] == "old-run"


def test_evolution_store_delete_corrupt_index_only_run_clears_index(tmp_path, monkeypatch):
    runs_dir = tmp_path / "supervised" / "runs"
    index_path = tmp_path / "supervised" / "index.json"

    def fake_kind_paths(kind: str):
        assert kind == "supervised"
        return runs_dir, index_path

    monkeypatch.setattr(evolution_store, "_kind_paths", fake_kind_paths)
    runs_dir.mkdir(parents=True, exist_ok=True)

    evolution_store.save_run_index("supervised", active_run_id="missing-run", latest_run_id="missing-run")

    result = evolution_store.delete_run_snapshot("supervised", "missing-run")

    assert result["deleted"] is False
    assert result["clearedActive"] is True
    assert result["clearedLatest"] is True
    assert result["activeRunId"] == ""
    assert result["latestRunId"] == ""


def test_clear_pid_keeps_newer_owner(tmp_path, monkeypatch):
    pid_path = tmp_path / "daemon.pid"
    monkeypatch.setattr(state_store, "PID_PATH", pid_path)

    state_store.save_pid(200)
    state_store.clear_pid(100)
    assert pid_path.read_text(encoding="utf-8") == "200"

    state_store.clear_pid(200)
    assert not pid_path.exists()
