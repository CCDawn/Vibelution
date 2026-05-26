import json
import http.client
import subprocess
import sys

import pytest

from core.runtime_manager import cli as runtime_cli
from core.runtime_manager import command_queue
from core.runtime_manager import daemon
from core.runtime_manager import constants
from core.runtime_manager import evolution_store
from core.runtime_manager import process_inventory
from core.runtime_manager import scene_logging
from core.runtime_manager import state_store
from core.runtime_manager import workbench_controller


def _repeat_last(items):
    values = list(items)
    iterator = iter(values)
    last = values[-1]

    def next_value():
        nonlocal last
        try:
            last = next(iterator)
        except StopIteration:
            pass
        return dict(last)

    return next_value


def _patch_command_queue_events(monkeypatch, events_path):
    def append_event(event_type, payload, *, events_path=None, ensure_dirs=None, suppress_io_errors=True):
        target_path = events_path or events_path
        if target_path is None:
            target_path = events_path
        target_path.open("a", encoding="utf-8").write(
            json.dumps({"type": event_type, "payload": payload}, ensure_ascii=False) + "\n"
        )
        return ""

    monkeypatch.setattr(command_queue, "append_runtime_manager_file_event", append_event)
    monkeypatch.setattr(command_queue, "record_runtime_manager_scene_event", lambda *args, **kwargs: None)


@pytest.fixture(autouse=True)
def _block_real_process_termination(monkeypatch, tmp_path):
    events_path = tmp_path / "runtime-manager-events.jsonl"
    monkeypatch.setattr(daemon, "EVENTS_PATH", events_path)
    monkeypatch.setattr(command_queue, "EVENTS_PATH", events_path)
    monkeypatch.setattr(daemon, "record_runtime_manager_scene_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(command_queue, "record_runtime_manager_scene_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(daemon, "terminate_process_descendants", lambda *args, **kwargs: {"terminated": [], "remaining": []})
    monkeypatch.setattr(
        daemon,
        "terminate_unmanaged_workbench_processes",
        lambda *args, **kwargs: {"supported": True, "requested": [], "terminated": [], "remaining": []},
    )


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


def test_cli_command_forwards_run_id(monkeypatch):
    calls = []

    monkeypatch.setattr(runtime_cli, "ensure_daemon_running", lambda: calls.append("ensure"))
    monkeypatch.setattr(
        runtime_cli,
        "submit_command",
        lambda command_type, args=None, requested_by="unknown": calls.append((command_type, args, requested_by))
        or {"commandId": "cmd-run-id"},
    )

    exit_code = runtime_cli.main(
        ["command", "restart_self_evolution_run", "--run-id", "web-self-123", "--reason", "code_update"]
    )

    assert exit_code == 0
    assert calls == [
        "ensure",
        ("restart_self_evolution_run", {"reason": "code_update", "runId": "web-self-123"}, "cli"),
    ]


def test_backend_health_probe_treats_connection_reset_as_unhealthy(monkeypatch):
    def fake_urlopen(*args, **kwargs):
        raise ConnectionResetError(10054, "An existing connection was forcibly closed")

    monkeypatch.setattr(workbench_controller.urllib.request, "urlopen", fake_urlopen)

    assert workbench_controller._is_backend_healthy("http://127.0.0.1:8000") is False


def test_backend_health_probe_treats_http_protocol_error_as_unhealthy(monkeypatch):
    def fake_urlopen(*args, **kwargs):
        raise workbench_controller.http.client.HTTPException("bad status line")

    monkeypatch.setattr(workbench_controller.urllib.request, "urlopen", fake_urlopen)

    assert workbench_controller._is_backend_healthy("http://127.0.0.1:8000") is False


def test_launcher_action_passes_runtime_manager_process_protection(monkeypatch, tmp_path):
    calls = []

    monkeypatch.setattr(workbench_controller, "LAUNCHER_SCRIPT_PATH", tmp_path / "launcher.ps1")
    monkeypatch.setattr(workbench_controller, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(workbench_controller, "configured_backend_port", lambda: 8000)
    monkeypatch.setattr(workbench_controller.os, "getpid", lambda: 29960)
    monkeypatch.setattr(workbench_controller.os, "getppid", lambda: 31096)

    def fake_run(*args, **kwargs):
        calls.append({"args": args, "kwargs": kwargs})
        stdout_handle = kwargs["stdout"]
        stderr_handle = kwargs["stderr"]
        stdout_handle.write(b"[Vibelution] ok\n")
        stderr_handle.write(b"")
        return subprocess.CompletedProcess(args=args[0], returncode=0)

    monkeypatch.setattr(workbench_controller.subprocess, "run", fake_run)

    result = workbench_controller.run_launcher_action("internal-stop")

    assert result.returncode == 0
    assert calls
    env = calls[0]["kwargs"]["env"]
    assert env["VIBELUTION_PROTECTED_PROCESS_IDS"] == "29960;31096"


def test_launcher_error_detail_prioritizes_stderr_over_progress_stdout():
    detail = daemon._launcher_error_detail(
        subprocess.CompletedProcess(
            args=[],
            returncode=1,
            stdout="[Vibelution] Stopping Vibelution session (runtime manager stop)...\n",
            stderr="actual failure",
        ),
        "fallback",
    )

    assert "actual failure" in detail
    assert "Launcher progress before exit" in detail
    assert "Launcher exit code: 1" in detail


def test_workbench_controller_trusts_only_launcher_marked_backend(monkeypatch):
    monkeypatch.setattr(
        workbench_controller,
        "list_repo_runtime_processes",
        lambda project_root: [
            process_inventory.RuntimeProcess(
                pid=22416,
                parent_pid=1,
                kind="managed_workbench_backend",
                name="pythonw.exe",
                command_line="pythonw scripts/web_workbench.py --port 8000 --no-browser --managed-by-launcher",
                cwd=str(project_root),
                port=8000,
            ),
            process_inventory.RuntimeProcess(
                pid=49780,
                parent_pid=1,
                kind="unmanaged_workbench",
                name="python.exe",
                command_line="python scripts/web_workbench.py --port 8000 --no-browser",
                cwd=str(project_root),
                port=8000,
            ),
        ],
    )

    assert workbench_controller._pid_is_repo_workbench_backend(22416) is True
    assert workbench_controller._pid_is_repo_workbench_backend(49780) is False


def test_load_runtime_snapshot_aligns_legacy_open_session(monkeypatch):
    saved_states: list[dict] = []

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
    monkeypatch.setattr(daemon, "save_state", lambda state: saved_states.append(json.loads(json.dumps(state))) or state)

    snapshot = daemon.load_runtime_snapshot()

    assert snapshot["runtimeState"] == "idle"
    assert snapshot["workbench"]["desiredState"] == "open"
    assert snapshot["workbench"]["observedState"] == "open"
    assert snapshot["workbench"]["phase"] == "steady"


def test_load_runtime_snapshot_persists_stale_running_state_as_closed(monkeypatch):
    saved_states: list[dict] = []

    monkeypatch.setattr(
        daemon,
        "load_state",
        lambda: {
            "runtimeState": "running",
            "managerPid": 9912,
            "daemonRunning": True,
            "workbench": {
                "desiredState": "open",
                "observedState": "open",
                "phase": "steady",
                "backendPid": 3200,
                "browserWindowPid": 4500,
                "backendAlive": True,
                "backendHealthy": True,
                "backendObserved": True,
                "backendPortListening": True,
                "statusLine": "Workbench is open (backend PID=3200, window PID=4500)",
            },
            "command": {"activeCommandId": ""},
        },
    )
    monkeypatch.setattr(
        daemon,
        "observe_workbench",
        lambda: {
            "observedState": "closed",
            "backendPid": 0,
            "browserLaunchPid": 0,
            "browserWindowPid": 0,
            "browserManaged": True,
            "backendAlive": False,
            "backendHealthy": False,
            "backendObserved": False,
            "backendPort": 8000,
            "backendPortListening": False,
            "backendPortOwnerPid": 0,
            "backendPortOwnerTrusted": False,
            "backendPortConflict": False,
            "browserWindowAlive": False,
            "sessionId": "",
            "url": "http://127.0.0.1:8000",
            "lifecycleConsistency": "consistent",
        },
    )
    monkeypatch.setattr(daemon, "is_daemon_running", lambda: False)
    monkeypatch.setattr(daemon, "load_pid", lambda: 0)
    monkeypatch.setattr(daemon, "save_state", lambda state: saved_states.append(json.loads(json.dumps(state))) or state)

    snapshot = daemon.load_runtime_snapshot()

    assert snapshot["runtimeState"] == "idle"
    assert snapshot["managerPid"] == 0
    assert snapshot["daemonRunning"] is False
    assert snapshot["workbench"]["desiredState"] == "closed"
    assert snapshot["workbench"]["observedState"] == "closed"
    assert snapshot["workbench"]["backendPid"] == 0
    assert snapshot["workbench"]["browserWindowPid"] == 0
    assert snapshot["workbench"]["statusLine"] == "Workbench is closed."
    assert snapshot["lastError"] == {"scope": "", "message": "", "at": ""}
    assert saved_states
    assert saved_states[-1]["runtimeState"] == "idle"
    assert saved_states[-1]["workbench"]["observedState"] == "closed"


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


def test_daemon_unexpected_exit_marks_manager_not_running(monkeypatch):
    saved_states: list[dict] = []

    monkeypatch.setattr(
        daemon,
        "load_state",
        lambda: {
            "runtimeState": "running",
            "managerPid": 9912,
            "daemonRunning": True,
            "command": {"activeCommandId": ""},
            "workbench": {"desiredState": "open", "observedState": "open", "phase": "steady"},
        },
    )
    monkeypatch.setattr(daemon, "now_iso", lambda: "2026-05-24T08:00:00+00:00")
    monkeypatch.setattr(daemon, "save_state", lambda state: saved_states.append(json.loads(json.dumps(state))) or state)

    daemon._mark_daemon_not_running_after_exit(manager_pid=9912)

    assert saved_states[-1]["runtimeState"] == "idle"
    assert saved_states[-1]["managerPid"] == 0
    assert saved_states[-1]["daemonRunning"] is False
    assert saved_states[-1]["lastStoppedAt"] == "2026-05-24T08:00:00+00:00"
    assert saved_states[-1]["lastStoppedManagerPid"] == 9912


def test_daemon_unexpected_exit_does_not_overwrite_newer_manager(monkeypatch):
    saved_states: list[dict] = []

    monkeypatch.setattr(
        daemon,
        "load_state",
        lambda: {
            "runtimeState": "running",
            "managerPid": 2000,
            "daemonRunning": True,
            "command": {},
            "workbench": {},
        },
    )
    monkeypatch.setattr(daemon, "save_state", lambda state: saved_states.append(state) or state)

    daemon._mark_daemon_not_running_after_exit(manager_pid=9912)

    assert saved_states == []


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


def test_run_forever_marks_runtime_stopping_then_finalizes_idle_before_exit(monkeypatch):
    runtime_daemon = daemon.RuntimeManagerDaemon()
    saved_states: list[dict] = []
    loaded_state = {
        "runtimeState": "running",
        "startedAt": "2026-05-18T01:00:00+00:00",
        "command": {},
        "workbench": {},
    }

    monkeypatch.setattr(daemon, "ensure_runtime_manager_dirs", lambda: None)
    monkeypatch.setattr(daemon, "recover_processing_queue", lambda: None)
    monkeypatch.setattr(daemon, "save_pid", lambda pid: None)
    monkeypatch.setattr(daemon, "load_state", lambda: json.loads(json.dumps(loaded_state)))
    monkeypatch.setattr(daemon, "now_iso", lambda: "2026-05-19T08:00:00+00:00")
    monkeypatch.setattr(daemon, "observe_workbench", lambda: {"observedState": "closed"})
    monkeypatch.setattr(daemon, "build_evolution_summary", lambda: {"self": {}, "supervised": {}})
    monkeypatch.setattr(daemon, "_process_source_signature", lambda: "sig-current")

    def fake_save_state(state):
        loaded_state.clear()
        loaded_state.update(json.loads(json.dumps(state)))
        saved_states.append(json.loads(json.dumps(state)))
        return state

    monkeypatch.setattr(daemon, "save_state", fake_save_state)
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
    assert saved_states[-1]["runtimeState"] == "idle"
    assert saved_states[-1]["managerPid"] == 0
    assert saved_states[-1]["daemonRunning"] is False
    assert saved_states[-1]["lastStoppedManagerPid"] == runtime_daemon._pid
    assert saved_states[-1]["workbench"]["desiredState"] == "closed"
    assert saved_states[-1]["workbench"]["observedState"] == "closed"
    assert saved_states[-1]["workbench"]["phase"] == "steady"


def test_reconcile_observation_keeps_daemon_running_true_and_preserves_stopping(monkeypatch):
    runtime_daemon = daemon.RuntimeManagerDaemon()

    monkeypatch.setattr(
        daemon,
        "observe_workbench",
        lambda: {
            "observedState": "closed",
            "backendPid": 0,
            "browserLaunchPid": 0,
            "browserWindowPid": 0,
            "backendAlive": False,
            "backendHealthy": False,
            "backendObserved": False,
            "backendPort": 8000,
            "backendPortListening": False,
            "backendPortOwnerPid": 0,
            "backendPortOwnerTrusted": False,
            "backendPortConflict": False,
            "browserWindowAlive": False,
            "browserManaged": True,
            "sessionId": "",
            "url": "http://127.0.0.1:8000",
        },
    )
    monkeypatch.setattr(daemon, "residual_process_payload", lambda **kwargs: {"count": 0, "items": []})
    monkeypatch.setattr(daemon, "build_evolution_summary", lambda: {"self": {}, "supervised": {}})
    monkeypatch.setattr(daemon, "_process_source_signature", lambda: "sig-current")

    state = runtime_daemon._reconcile_observation(
        {
            "runtimeState": "stopping",
            "daemonRunning": False,
            "command": {},
            "workbench": {"desiredState": "closed", "observedState": "closed", "phase": "steady"},
        }
    )

    assert state["runtimeState"] == "stopping"
    assert state["daemonRunning"] is True
    assert state["managerPid"] == runtime_daemon._pid


def test_reconcile_observation_cleans_up_orphaned_browser(monkeypatch):
    runtime_daemon = daemon.RuntimeManagerDaemon()
    events: list[tuple[str, dict]] = []
    observations = _repeat_last(
        [
            {
                "observedState": "open",
                "backendPid": 0,
                "browserLaunchPid": 12132,
                "browserWindowPid": 12132,
                "backendAlive": False,
                "backendHealthy": False,
                "backendObserved": False,
                "backendPort": 8000,
                "backendPortListening": False,
                "backendPortOwnerPid": 0,
                "backendPortOwnerTrusted": False,
                "backendPortConflict": False,
                "browserWindowAlive": True,
                "browserManaged": True,
                "backendMissing": True,
                "frontendOrphaned": True,
                "lifecycleConsistency": "orphaned_browser",
                "sessionId": "stale-session",
                "url": "http://127.0.0.1:8000",
            },
            {
                "observedState": "closed",
                "backendPid": 0,
                "browserLaunchPid": 0,
                "browserWindowPid": 0,
                "backendAlive": False,
                "backendHealthy": False,
                "backendObserved": False,
                "backendPort": 8000,
                "backendPortListening": False,
                "backendPortOwnerPid": 0,
                "backendPortOwnerTrusted": False,
                "backendPortConflict": False,
                "browserWindowAlive": False,
                "browserManaged": True,
                "backendMissing": False,
                "frontendOrphaned": False,
                "lifecycleConsistency": "consistent",
                "sessionId": "",
                "url": "http://127.0.0.1:8000",
            },
        ]
    )

    monkeypatch.setattr(daemon, "observe_workbench", observations)
    monkeypatch.setattr(daemon, "residual_process_payload", lambda **kwargs: {"count": 0, "items": []})
    monkeypatch.setattr(daemon, "build_evolution_summary", lambda: {"self": {}, "supervised": {}})
    monkeypatch.setattr(daemon, "_process_source_signature", lambda: "sig-current")
    monkeypatch.setattr(daemon, "_append_event", lambda event_type, payload: events.append((event_type, payload)))
    monkeypatch.setattr(daemon, "close_workbench", lambda: subprocess.CompletedProcess(args=[], returncode=0, stdout="closed", stderr=""))

    state = runtime_daemon._reconcile_observation(
        {
            "runtimeState": "running",
            "command": {"activeCommandId": ""},
            "workbench": {"desiredState": "open", "observedState": "open", "phase": "steady"},
        }
    )

    workbench = state["workbench"]
    assert workbench["desiredState"] == "closed"
    assert workbench["observedState"] == "closed"
    assert workbench["phase"] == "steady"
    assert workbench["frontendOrphaned"] is False
    assert workbench["lifecycleConsistency"] == "consistent"
    assert workbench["failureMessage"] == ""
    assert [event_type for event_type, _ in events] == [
        "workbench.consistency.orphaned_browser_detected",
        "workbench.consistency.orphaned_browser_cleanup_requested",
        "workbench.consistency.orphaned_browser_cleanup_succeeded",
    ]
    assert events[0][1]["browserWindowPid"] == 12132


def test_reconcile_observation_does_not_fail_opening_orphaned_browser(monkeypatch):
    runtime_daemon = daemon.RuntimeManagerDaemon()
    events: list[tuple[str, dict]] = []

    monkeypatch.setattr(
        daemon,
        "observe_workbench",
        lambda: {
            "observedState": "open",
            "backendPid": 0,
            "browserLaunchPid": 12132,
            "browserWindowPid": 12132,
            "backendAlive": False,
            "backendHealthy": False,
            "backendObserved": False,
            "backendPort": 8000,
            "backendPortListening": False,
            "backendPortOwnerPid": 0,
            "backendPortOwnerTrusted": False,
            "backendPortConflict": False,
            "browserWindowAlive": True,
            "browserManaged": True,
            "backendMissing": True,
            "frontendOrphaned": True,
            "lifecycleConsistency": "orphaned_browser",
            "sessionId": "starting-session",
            "url": "http://127.0.0.1:8000",
        },
    )
    monkeypatch.setattr(daemon, "residual_process_payload", lambda **kwargs: {"count": 0, "items": []})
    monkeypatch.setattr(daemon, "build_evolution_summary", lambda: {"self": {}, "supervised": {}})
    monkeypatch.setattr(daemon, "_process_source_signature", lambda: "sig-current")
    monkeypatch.setattr(daemon, "_append_event", lambda event_type, payload: events.append((event_type, payload)))

    state = runtime_daemon._reconcile_observation(
        {
            "runtimeState": "running",
            "command": {"activeCommandId": "cmd-open", "activeType": "open_workbench"},
            "workbench": {
                "desiredState": "open",
                "observedState": "closed",
                "phase": "opening",
                "failureMessage": "",
            },
        }
    )

    workbench = state["workbench"]
    assert workbench["desiredState"] == "open"
    assert workbench["observedState"] == "open"
    assert workbench["phase"] == "opening"
    assert workbench["frontendOrphaned"] is True
    assert workbench["lifecycleConsistency"] == "orphaned_browser"
    assert workbench["failureMessage"] == ""
    assert events == []


def test_reconcile_observation_cleans_closed_residual_processes(monkeypatch):
    runtime_daemon = daemon.RuntimeManagerDaemon()
    events: list[tuple[str, dict]] = []
    observations = _repeat_last(
        [
            {
                "observedState": "closed",
                "backendPid": 0,
                "browserLaunchPid": 0,
                "browserWindowPid": 0,
                "backendAlive": False,
                "backendHealthy": False,
                "backendObserved": False,
                "backendPort": 8000,
                "backendPortListening": True,
                "backendPortOwnerPid": 53180,
                "backendPortOwnerKind": "unmanaged_workbench",
                "backendPortOwnerTrusted": False,
                "backendPortOwnerResidual": True,
                "backendPortConflict": False,
                "browserWindowAlive": False,
                "browserManaged": True,
                "backendMissing": False,
                "frontendOrphaned": False,
                "lifecycleConsistency": "residual_backend",
                "sessionId": "",
                "url": "http://127.0.0.1:8000",
            },
            {
                "observedState": "closed",
                "backendPid": 0,
                "browserLaunchPid": 0,
                "browserWindowPid": 0,
                "backendAlive": False,
                "backendHealthy": False,
                "backendObserved": False,
                "backendPort": 8000,
                "backendPortListening": False,
                "backendPortOwnerPid": 0,
                "backendPortOwnerKind": "",
                "backendPortOwnerTrusted": False,
                "backendPortOwnerResidual": False,
                "backendPortConflict": False,
                "browserWindowAlive": False,
                "browserManaged": True,
                "backendMissing": False,
                "frontendOrphaned": False,
                "lifecycleConsistency": "consistent",
                "sessionId": "",
                "url": "http://127.0.0.1:8000",
            },
        ]
    )
    residual_payloads = iter(
        [
            {
                "count": 2,
                "items": [
                    {"pid": 11956, "kind": "unmanaged_frontend_dev_server", "port": 5173},
                    {"pid": 53180, "kind": "unmanaged_workbench", "port": 8000},
                ],
            },
            {"count": 0, "items": []},
        ]
    )

    monkeypatch.setattr(daemon, "observe_workbench", observations)
    monkeypatch.setattr(daemon, "residual_process_payload", lambda **kwargs: next(residual_payloads))
    monkeypatch.setattr(daemon, "build_evolution_summary", lambda: {"self": {}, "supervised": {}})
    monkeypatch.setattr(daemon, "_process_source_signature", lambda: "sig-current")
    monkeypatch.setattr(daemon, "_append_event", lambda event_type, payload: events.append((event_type, payload)))
    monkeypatch.setattr(
        runtime_daemon,
        "_cleanup_residual_workbench_processes",
        lambda: {
            "supported": True,
            "requested": [11956, 53180],
            "terminated": [11956, 53180],
            "remaining": [],
        },
    )

    state = runtime_daemon._reconcile_observation(
        {
            "runtimeState": "running",
            "command": {"activeCommandId": ""},
            "workbench": {"desiredState": "closed", "observedState": "closed", "phase": "steady"},
        }
    )

    assert state["workbench"]["desiredState"] == "closed"
    assert state["residualProcesses"] == {"count": 0, "items": []}
    assert [event_type for event_type, _payload in events] == [
        "workbench.consistency.closed_residual_cleanup_requested",
        "workbench.consistency.closed_residual_cleanup_succeeded",
    ]
    assert events[0][1]["residualProcesses"]["count"] == 2
    assert events[1][1]["cleanup"]["terminated"] == [11956, 53180]


def test_reconcile_observation_clears_completed_active_command(monkeypatch):
    runtime_daemon = daemon.RuntimeManagerDaemon()
    events: list[tuple[str, dict]] = []

    monkeypatch.setattr(
        daemon,
        "observe_workbench",
        lambda: {
            "observedState": "open",
            "backendPid": 6288,
            "browserLaunchPid": 49564,
            "browserWindowPid": 49564,
            "backendAlive": True,
            "backendHealthy": True,
            "backendObserved": True,
            "backendPort": 8000,
            "backendPortListening": True,
            "backendPortOwnerPid": 6288,
            "backendPortOwnerKind": "managed_workbench_backend",
            "backendPortOwnerTrusted": True,
            "backendPortOwnerResidual": False,
            "backendPortConflict": False,
            "browserWindowAlive": True,
            "browserManaged": True,
            "backendMissing": False,
            "frontendOrphaned": False,
            "lifecycleConsistency": "consistent",
            "sessionId": "managed-session",
            "url": "http://127.0.0.1:8000",
        },
    )
    monkeypatch.setattr(daemon, "residual_process_payload", lambda **kwargs: {"count": 0, "items": []})
    monkeypatch.setattr(daemon, "build_evolution_summary", lambda: {"self": {}, "supervised": {}})
    monkeypatch.setattr(daemon, "_process_source_signature", lambda: "sig-current")
    monkeypatch.setattr(daemon, "_command_result_is_completed", lambda command_id: command_id == "cmd-open")
    monkeypatch.setattr(daemon, "_append_event", lambda event_type, payload: events.append((event_type, payload)))

    state = runtime_daemon._reconcile_observation(
        {
            "runtimeState": "running",
            "command": {
                "activeCommandId": "cmd-open",
                "activeType": "open_workbench",
                "requestedBy": "codex",
                "startedAt": "2026-05-26T07:13:22+00:00",
            },
            "workbench": {"desiredState": "open", "observedState": "open", "phase": "steady"},
        }
    )

    assert state["command"]["activeCommandId"] == ""
    assert state["command"]["activeType"] == ""
    assert events == [
        (
            "command.active_completed_cleared",
            {"commandId": "cmd-open", "activeType": "open_workbench", "requestedBy": "codex"},
        )
    ]


def test_submit_command_defers_open_while_runtime_manager_is_stopping(tmp_path, monkeypatch):
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
    monkeypatch.setattr(command_queue, "record_runtime_manager_scene_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(command_queue, "ensure_runtime_manager_dirs", lambda: None)
    monkeypatch.setattr(
        command_queue,
        "create_restart_intent",
        lambda *args, **kwargs: {
            "intentId": "intent-reopen",
            "target": args[0],
            "reason": kwargs.get("reason", ""),
            "payload": kwargs.get("payload", {}),
        },
    )
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
    assert result["ok"] is True
    assert result["deferredUntilShutdownComplete"] is True
    assert result["restartIntentId"] == "intent-reopen"
    assert result["runtimeManagerStopping"] is True
    assert result["stateVersion"] == 42
    event = json.loads(events_path.read_text(encoding="utf-8").splitlines()[-1])
    assert event["type"] == "command_queue.open_deferred_until_shutdown_complete"
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
    events = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines()]
    event = next(item for item in events if item["type"] == "command_queue.stale_shutdown_state_ignored")
    assert event["type"] == "command_queue.stale_shutdown_state_ignored"
    assert event["payload"]["stateManagerPid"] == 7711
    assert event["payload"]["currentManagerPid"] == 9912


def test_command_queue_records_queued_claimed_and_result_written_events(tmp_path, monkeypatch):
    inbox_dir = tmp_path / "inbox"
    processing_dir = tmp_path / "processing"
    results_dir = tmp_path / "results"
    events_path = tmp_path / "events.jsonl"
    for path in (inbox_dir, processing_dir, results_dir):
        path.mkdir(parents=True)
    scene_events: list[tuple[str, dict, dict]] = []

    monkeypatch.setattr(command_queue, "INBOX_DIR", inbox_dir)
    monkeypatch.setattr(command_queue, "PROCESSING_DIR", processing_dir)
    monkeypatch.setattr(command_queue, "RESULTS_DIR", results_dir)
    monkeypatch.setattr(command_queue, "EVENTS_PATH", events_path)
    monkeypatch.setattr(command_queue, "ensure_runtime_manager_dirs", lambda: None)
    monkeypatch.setattr(command_queue, "load_pid", lambda: 0)
    monkeypatch.setattr(command_queue, "_process_is_alive", lambda pid: False)
    monkeypatch.setattr(
        command_queue,
        "record_runtime_manager_scene_event",
        lambda event_type, payload, **kwargs: scene_events.append((event_type, payload, kwargs)) or True,
    )

    command = command_queue.submit_command(
        "open_workbench",
        args={"reason": "launcher_start", "token": "secret-value", "noBrowser": True},
        requested_by="launcher_ps",
    )
    claimed = command_queue.claim_next_command()
    assert claimed is not None
    processing_path, claimed_payload = claimed
    command_queue.complete_command(
        processing_path,
        {
            "commandId": claimed_payload["commandId"],
            "ok": True,
            "completed": True,
            "message": "Workbench opened.",
        },
    )

    file_events = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines()]
    assert [event["type"] for event in file_events] == [
        "command_queue.command_queued",
        "command_queue.command_claimed",
        "command_queue.command_result_written",
    ]
    queued_payload = file_events[0]["payload"]
    assert queued_payload["commandId"] == command["commandId"]
    assert queued_payload["args"] == {"argKeys": ["token"], "noBrowser": True, "reason": "launcher_start"}
    assert file_events[1]["payload"]["queuePath"] == f"{command['commandId']}.json"
    assert file_events[2]["payload"]["ok"] is True
    assert [event_type for event_type, _, _ in scene_events] == [event["type"] for event in file_events]
    assert {kwargs["phase"] for _, _, kwargs in scene_events} == {"queue"}
    assert all(kwargs["occurred_at"] for _, _, kwargs in scene_events)


def test_recover_processing_queue_completes_stale_satisfied_stop_manager_close(tmp_path, monkeypatch):
    inbox_dir = tmp_path / "inbox"
    processing_dir = tmp_path / "processing"
    results_dir = tmp_path / "results"
    events_path = tmp_path / "events.jsonl"
    for path in (inbox_dir, processing_dir, results_dir):
        path.mkdir(parents=True)

    old_close = {
        "commandId": "cmd_20260525T125402Z_4e072b74",
        "type": "close_workbench",
        "requestedBy": "web_ui",
        "requestedAt": "2026-05-25T12:54:02.877170+00:00",
        "args": {"reason": "web_close_button", "stopManager": True},
    }
    new_open = {
        "commandId": "cmd_20260525T141736Z_38094da2",
        "type": "open_workbench",
        "requestedBy": "launcher_ps",
        "requestedAt": "2026-05-25T14:17:36.134373+00:00",
        "args": {"reason": "launcher_start"},
    }
    (processing_dir / f"{old_close['commandId']}.json").write_text(json.dumps(old_close), encoding="utf-8")
    (inbox_dir / f"{new_open['commandId']}.json").write_text(json.dumps(new_open), encoding="utf-8")

    monkeypatch.setattr(command_queue, "INBOX_DIR", inbox_dir)
    monkeypatch.setattr(command_queue, "PROCESSING_DIR", processing_dir)
    monkeypatch.setattr(command_queue, "RESULTS_DIR", results_dir)
    monkeypatch.setattr(command_queue, "EVENTS_PATH", events_path)
    monkeypatch.setattr(command_queue, "ensure_runtime_manager_dirs", lambda: None)
    monkeypatch.setattr(
        command_queue,
        "load_state",
        lambda: {
            "stateVersion": 5857,
            "runtimeState": "idle",
            "managerPid": 0,
            "daemonRunning": False,
            "workbench": {"desiredState": "closed", "observedState": "closed", "phase": "steady"},
        },
    )

    command_queue.recover_processing_queue()
    claimed = command_queue.claim_next_command()

    assert claimed is not None
    _, claimed_payload = claimed
    assert claimed_payload["commandId"] == new_open["commandId"]
    skipped_result = json.loads((results_dir / f"{old_close['commandId']}.json").read_text(encoding="utf-8"))
    assert skipped_result["ok"] is True
    assert skipped_result["completed"] is True
    assert skipped_result["staleRecoveredCommand"] is True
    assert skipped_result["stopDaemon"] is False
    assert not (processing_dir / f"{old_close['commandId']}.json").exists()
    events = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines()]
    assert "command_queue.recovered_stale_close_completed" in [event["type"] for event in events]


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


def test_submit_command_joins_active_open_workbench(tmp_path, monkeypatch):
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
            "stateVersion": 51,
            "runtimeState": "running",
            "managerPid": 9912,
            "command": {
                "activeCommandId": "cmd-active-open",
                "activeType": "open_workbench",
                "noBrowser": False,
            },
        },
    )

    command = command_queue.submit_command("open_workbench", args={"reason": "launcher_start"}, requested_by="launcher_ps")

    assert command["commandId"] == "cmd-active-open"
    assert list(inbox_dir.glob("*.json")) == []
    assert list(results_dir.glob("*.json")) == []
    event = json.loads(events_path.read_text(encoding="utf-8").splitlines()[-1])
    assert event["type"] == "command_queue.open_joined"
    assert event["payload"]["commandId"] == "cmd-active-open"


def test_submit_command_joins_pending_open_workbench(tmp_path, monkeypatch):
    inbox_dir = tmp_path / "inbox"
    processing_dir = tmp_path / "processing"
    results_dir = tmp_path / "results"
    events_path = tmp_path / "events.jsonl"
    for path in (inbox_dir, processing_dir, results_dir):
        path.mkdir(parents=True)
    (inbox_dir / "cmd-pending-open.json").write_text(
        json.dumps(
            {
                "commandId": "cmd-pending-open",
                "type": "open_workbench",
                "requestedBy": "launcher_ps",
                "args": {"reason": "launcher_start"},
            }
        ),
        encoding="utf-8",
    )

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
            "stateVersion": 52,
            "runtimeState": "running",
            "managerPid": 9912,
            "command": {"activeCommandId": "", "activeType": ""},
        },
    )

    command = command_queue.submit_command("open_workbench", args={"reason": "launcher_start"}, requested_by="launcher_ps")

    assert command["commandId"] == "cmd-pending-open"
    assert [path.name for path in inbox_dir.glob("*.json")] == ["cmd-pending-open.json"]
    assert list(results_dir.glob("*.json")) == []


def test_submit_command_does_not_join_headless_open_when_browser_is_requested(tmp_path, monkeypatch):
    inbox_dir = tmp_path / "inbox"
    processing_dir = tmp_path / "processing"
    results_dir = tmp_path / "results"
    events_path = tmp_path / "events.jsonl"
    for path in (inbox_dir, processing_dir, results_dir):
        path.mkdir(parents=True)
    (inbox_dir / "cmd-headless-open.json").write_text(
        json.dumps(
            {
                "commandId": "cmd-headless-open",
                "type": "open_workbench",
                "requestedBy": "launcher_ps",
                "args": {"reason": "launcher_start", "noBrowser": True},
            }
        ),
        encoding="utf-8",
    )

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
            "stateVersion": 53,
            "runtimeState": "running",
            "managerPid": 9912,
            "command": {"activeCommandId": "", "activeType": ""},
        },
    )

    command = command_queue.submit_command("open_workbench", args={"reason": "launcher_start"}, requested_by="launcher_ps")

    queued = sorted(path.name for path in inbox_dir.glob("*.json"))
    assert command["commandId"] != "cmd-headless-open"
    assert queued == ["cmd-headless-open.json", f"{command['commandId']}.json"]


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


def test_daemon_append_event_mirrors_runtime_scene_event(tmp_path, monkeypatch):
    events_path = tmp_path / "events.jsonl"
    scene_events: list[tuple[str, dict, dict]] = []

    monkeypatch.setattr(daemon, "EVENTS_PATH", events_path)
    monkeypatch.setattr(daemon, "ensure_runtime_manager_dirs", lambda: None)
    monkeypatch.setattr(
        daemon,
        "record_runtime_manager_scene_event",
        lambda event_type, payload, **kwargs: scene_events.append((event_type, payload, kwargs)) or True,
    )

    daemon._append_event(
        "workbench.open.verification_succeeded",
        {"commandId": "cmd-open", "ok": True, "backendPid": 1234},
    )

    file_event = json.loads(events_path.read_text(encoding="utf-8").splitlines()[-1])
    assert file_event["type"] == "workbench.open.verification_succeeded"
    assert file_event["payload"]["commandId"] == "cmd-open"
    assert scene_events == [
        (
            "workbench.open.verification_succeeded",
            {"commandId": "cmd-open", "ok": True, "backendPid": 1234},
            {"phase": "open", "occurred_at": file_event["at"]},
        )
    ]


def test_runtime_manager_scene_event_backfills_recent_queue_events(tmp_path, monkeypatch):
    events_path = tmp_path / "events.jsonl"
    scene_dir = tmp_path / "logs" / "runtime_scenes" / "20260524T104120Z__scene-runtime"
    (scene_dir / "events").mkdir(parents=True)
    scene_dir.joinpath("manifest.json").write_text(
        json.dumps({"runtime_scene_id": "scene-runtime"}),
        encoding="utf-8",
    )
    events_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "type": "command_queue.command_queued",
                        "at": "2026-05-24T10:40:40+00:00",
                        "payload": {"commandId": "cmd-other", "type": "open_workbench"},
                    }
                ),
                json.dumps(
                    {
                        "type": "command_queue.command_queued",
                        "at": "2026-05-24T10:40:43+00:00",
                        "payload": {"commandId": "cmd-open", "type": "open_workbench"},
                    }
                ),
                json.dumps(
                    {
                        "type": "command_queue.command_claimed",
                        "at": "2026-05-24T10:40:52+00:00",
                        "payload": {"commandId": "cmd-open", "type": "open_workbench"},
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    recorded: list[dict] = []

    class FakeRuntimeSceneService:
        @staticmethod
        def _resolve_current_runtime_scene_dir():
            return scene_dir

        @staticmethod
        def _resolve_recent_completed_runtime_scene_dir():
            raise AssertionError("queued events should not use recent completed package fallback")

        @staticmethod
        def record_runtime_scene_event(component, phase, event_code, **kwargs):
            recorded.append(
                {
                    "component": component,
                    "phase": phase,
                    "eventCode": event_code,
                    "kwargs": kwargs,
                }
            )
            return {"accepted": True, "runtimeSceneId": "scene-runtime"}

    monkeypatch.setattr(scene_logging, "EVENTS_PATH", events_path)
    monkeypatch.setattr(scene_logging, "_BACKFILLED_SCENE_KEYS", set())
    monkeypatch.setattr(scene_logging, "_runtime_scene_service", lambda: FakeRuntimeSceneService)

    accepted = scene_logging.record_runtime_manager_scene_event(
        "command.completed",
        {"commandId": "cmd-open", "type": "open_workbench", "ok": True},
        phase="command",
        occurred_at="2026-05-24T10:41:27+00:00",
    )

    assert accepted is True
    assert [event["eventCode"] for event in recorded] == [
        "command_queue.command_queued",
        "command_queue.command_claimed",
        "command.completed",
    ]
    assert [event["phase"] for event in recorded] == ["queue", "queue", "command"]
    assert recorded[0]["kwargs"]["occurred_at"] == "2026-05-24T10:40:43+00:00"
    assert recorded[0]["kwargs"]["fields"]["runtimeManagerBackfill"] is True
    assert recorded[-1]["kwargs"]["fields"]["runtimeManagerEventAt"] == "2026-05-24T10:41:27+00:00"


def test_runtime_manager_queue_event_does_not_target_recent_completed_package(tmp_path, monkeypatch):
    events_path = tmp_path / "events.jsonl"
    scene_dir = tmp_path / "logs" / "runtime_scenes" / "20260524T111509Z__scene-failed"
    (scene_dir / "events").mkdir(parents=True)
    events_path.write_text("", encoding="utf-8")
    recorded: list[dict] = []

    class FakeRuntimeSceneService:
        @staticmethod
        def _resolve_current_runtime_scene_dir():
            return None

        @staticmethod
        def _resolve_recent_completed_runtime_scene_dir():
            return scene_dir

        @staticmethod
        def record_runtime_scene_event(component, phase, event_code, **kwargs):
            recorded.append({"phase": phase, "eventCode": event_code, "kwargs": kwargs})
            return {"accepted": False, "reason": "no_runtime_scene"}

    monkeypatch.setattr(scene_logging, "EVENTS_PATH", events_path)
    monkeypatch.setattr(scene_logging, "_BACKFILLED_SCENE_KEYS", set())
    monkeypatch.setattr(scene_logging, "_runtime_scene_service", lambda: FakeRuntimeSceneService)

    accepted = scene_logging.record_runtime_manager_scene_event(
        "command_queue.command_queued",
        {"commandId": "cmd-new", "type": "open_workbench"},
        phase="queue",
        occurred_at="2026-05-24T11:19:55+00:00",
    )

    assert accepted is False
    assert recorded == [
        {
            "phase": "queue",
            "eventCode": "command_queue.command_queued",
            "kwargs": {
                "message": "Runtime manager queue event: command_queue.command_queued",
                "level": "info",
                "outcome": "queued",
                "fields": {
                    "commandId": "cmd-new",
                    "type": "open_workbench",
                    "runtimeManagerEventAt": "2026-05-24T11:19:55+00:00",
                },
                "lifecycle": True,
                "occurred_at": "2026-05-24T11:19:55+00:00",
                "allow_recent_completed": False,
            },
        }
    ]


def test_runtime_manager_scene_event_backfills_to_recent_completed_package(tmp_path, monkeypatch):
    events_path = tmp_path / "events.jsonl"
    scene_dir = tmp_path / "logs" / "runtime_scenes" / "20260524T111509Z__scene-failed"
    (scene_dir / "events").mkdir(parents=True)
    scene_dir.joinpath("manifest.json").write_text(
        json.dumps({"runtime_scene_id": "scene-failed", "status": "failed"}),
        encoding="utf-8",
    )
    events_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "type": "command_queue.command_queued",
                        "at": "2026-05-24T11:14:37+00:00",
                        "payload": {"commandId": "cmd-failed", "type": "open_workbench"},
                    }
                ),
                json.dumps(
                    {
                        "type": "command_queue.command_queued",
                        "at": "2026-05-24T11:14:38+00:00",
                        "payload": {"commandId": "cmd-other", "type": "open_workbench"},
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    recorded: list[dict] = []

    class FakeRuntimeSceneService:
        @staticmethod
        def _resolve_current_runtime_scene_dir():
            return None

        @staticmethod
        def _resolve_recent_completed_runtime_scene_dir():
            return scene_dir

        @staticmethod
        def record_runtime_scene_event(component, phase, event_code, **kwargs):
            recorded.append({"phase": phase, "eventCode": event_code, "kwargs": kwargs})
            return {"accepted": True, "runtimeSceneId": "scene-failed"}

    monkeypatch.setattr(scene_logging, "EVENTS_PATH", events_path)
    monkeypatch.setattr(scene_logging, "_BACKFILLED_SCENE_KEYS", set())
    monkeypatch.setattr(scene_logging, "_runtime_scene_service", lambda: FakeRuntimeSceneService)

    accepted = scene_logging.record_runtime_manager_scene_event(
        "command.failed",
        {"commandId": "cmd-failed", "type": "open_workbench", "ok": False},
        phase="command",
        occurred_at="2026-05-24T11:15:17+00:00",
    )

    assert accepted is True
    assert [event["eventCode"] for event in recorded] == ["command_queue.command_queued", "command.failed"]
    assert recorded[0]["kwargs"]["fields"]["runtimeManagerBackfill"] is True
    assert all(event["kwargs"]["fields"]["commandId"] == "cmd-failed" for event in recorded)


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
        lambda args, **kwargs: popen_calls.append(args) or type("Proc", (), {"pid": 24680})(),
    )

    assert daemon.ensure_daemon_running(python_executable="python-test") is True
    assert terminated == [12345]
    assert events == [
        ("daemon.restart_requested", {"pid": 12345, "reason": "runtime_manager_source_changed"}),
        (
            "daemon.start_requested",
            {
                "launchPid": 24680,
                "pythonExecutable": "python-test",
                "sourcePythonExecutable": "python-test",
                "consoleWindowSuppressed": False,
                "consoleFallbackReason": "python_executable_missing",
            },
        ),
    ]
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


def test_ensure_daemon_running_prefers_pythonw_for_background_daemon(tmp_path, monkeypatch):
    python_exe = tmp_path / "Scripts" / "python.exe"
    pythonw_exe = tmp_path / "Scripts" / "pythonw.exe"
    python_exe.parent.mkdir()
    python_exe.write_text("", encoding="utf-8")
    pythonw_exe.write_text("", encoding="utf-8")
    running_checks = iter([False, True])
    popen_calls = []
    events: list[tuple[str, dict]] = []

    monkeypatch.setattr(daemon, "load_pid", lambda: 0)
    monkeypatch.setattr(daemon, "_is_process_alive", lambda pid: False)
    monkeypatch.setattr(daemon, "ensure_runtime_manager_dirs", lambda: None)
    monkeypatch.setattr(daemon, "is_daemon_running", lambda: next(running_checks))
    monkeypatch.setattr(daemon, "DAEMON_STDOUT_PATH", tmp_path / "daemon.out.log")
    monkeypatch.setattr(daemon, "DAEMON_STDERR_PATH", tmp_path / "daemon.err.log")
    monkeypatch.setattr(daemon, "_append_event", lambda event_type, payload: events.append((event_type, payload)))
    monkeypatch.setattr(
        daemon.subprocess,
        "Popen",
        lambda args, **kwargs: popen_calls.append(args) or type("Proc", (), {"pid": 13579})(),
    )

    assert daemon.ensure_daemon_running(python_executable=str(python_exe)) is True

    assert popen_calls == [[str(pythonw_exe.resolve()), "-m", "core.runtime_manager.cli", "daemon"]]
    assert events == [
        (
            "daemon.start_requested",
            {
                "launchPid": 13579,
                "pythonExecutable": str(pythonw_exe.resolve()),
                "sourcePythonExecutable": str(python_exe),
                "consoleWindowSuppressed": True,
                "consoleFallbackReason": "",
            },
        )
    ]


def test_ensure_daemon_running_logs_console_fallback_when_pythonw_missing(tmp_path, monkeypatch):
    python_exe = tmp_path / "Scripts" / "python.exe"
    python_exe.parent.mkdir()
    python_exe.write_text("", encoding="utf-8")
    running_checks = iter([False, True])
    popen_calls = []
    events: list[tuple[str, dict]] = []

    monkeypatch.setattr(daemon, "load_pid", lambda: 0)
    monkeypatch.setattr(daemon, "_is_process_alive", lambda pid: False)
    monkeypatch.setattr(daemon, "ensure_runtime_manager_dirs", lambda: None)
    monkeypatch.setattr(daemon, "is_daemon_running", lambda: next(running_checks))
    monkeypatch.setattr(daemon, "DAEMON_STDOUT_PATH", tmp_path / "daemon.out.log")
    monkeypatch.setattr(daemon, "DAEMON_STDERR_PATH", tmp_path / "daemon.err.log")
    monkeypatch.setattr(daemon, "_append_event", lambda event_type, payload: events.append((event_type, payload)))
    monkeypatch.setattr(
        daemon.subprocess,
        "Popen",
        lambda args, **kwargs: popen_calls.append(args) or type("Proc", (), {"pid": 13579})(),
    )

    assert daemon.ensure_daemon_running(python_executable=str(python_exe)) is True

    assert popen_calls == [[str(python_exe.resolve()), "-m", "core.runtime_manager.cli", "daemon"]]
    assert events == [
        (
            "daemon.start_requested",
            {
                "launchPid": 13579,
                "pythonExecutable": str(python_exe.resolve()),
                "sourcePythonExecutable": str(python_exe),
                "consoleWindowSuppressed": False,
                "consoleFallbackReason": "pythonw_sibling_missing",
            },
        )
    ]


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


def test_observe_workbench_reports_orphaned_browser(monkeypatch):
    monkeypatch.setattr(
        workbench_controller,
        "_load_launcher_state",
        lambda: {
            "url": "http://127.0.0.1:8000",
            "backendPid": 42608,
            "backendLaunchPid": 42608,
            "browserLaunchPid": 12132,
            "browserWindowPid": 12132,
            "browserManaged": True,
            "sessionId": "orphaned-browser",
        },
    )
    monkeypatch.setattr(workbench_controller, "_is_process_alive", lambda pid: pid == 12132)
    monkeypatch.setattr(workbench_controller, "_is_backend_healthy", lambda url: False)
    monkeypatch.setattr(workbench_controller, "_listening_pid_for_port", lambda port: 0)
    monkeypatch.setattr(workbench_controller, "_port_is_listening_socket", lambda port: False)

    observation = workbench_controller.observe_workbench()

    assert observation["observedState"] == "open"
    assert observation["backendObserved"] is False
    assert observation["browserWindowAlive"] is True
    assert observation["backendMissing"] is True
    assert observation["frontendOrphaned"] is True
    assert observation["lifecycleConsistency"] == "orphaned_browser"


def test_observe_workbench_reports_backend_launch_pid(monkeypatch):
    monkeypatch.setattr(
        workbench_controller,
        "_load_launcher_state",
        lambda: {
            "url": "http://127.0.0.1:8000",
            "backendPid": 25744,
            "backendLaunchPid": 43460,
            "browserLaunchPid": 39880,
            "browserWindowPid": 39880,
            "browserManaged": True,
            "sessionId": "managed-browser",
        },
    )
    monkeypatch.setattr(workbench_controller, "_is_process_alive", lambda pid: pid in {25744, 39880})
    monkeypatch.setattr(workbench_controller, "_is_backend_healthy", lambda url: True)
    monkeypatch.setattr(workbench_controller, "_listening_pid_for_port", lambda port: 25744)
    monkeypatch.setattr(workbench_controller, "_port_is_listening_socket", lambda port: True)

    observation = workbench_controller.observe_workbench()

    assert observation["observedState"] == "open"
    assert observation["backendPid"] == 25744
    assert observation["backendLaunchPid"] == 43460


def test_snapshot_residual_excluded_pids_includes_backend_launch_tree_root():
    excluded = daemon._snapshot_residual_excluded_pids(
        {
            "backendPid": 25744,
            "backendLaunchPid": 43460,
            "backendPortOwnerPid": 25744,
            "browserLaunchPid": 39880,
            "browserWindowPid": 39880,
        },
        manager_pid=45904,
    )

    assert {25744, 43460, 39880, 45904}.issubset(excluded)


def test_snapshot_residual_excluded_pids_includes_active_backend_parent(monkeypatch):
    monkeypatch.setattr(
        daemon,
        "list_repo_runtime_processes",
        lambda project_root=None: [
            process_inventory.RuntimeProcess(
                pid=44052,
                parent_pid=48240,
                kind="unmanaged_workbench",
                name="python.exe",
                command_line="python scripts/web_workbench.py --port 8000 --no-browser",
                cwd="C:/repo",
                port=8000,
            ),
            process_inventory.RuntimeProcess(
                pid=32344,
                parent_pid=44052,
                kind="unmanaged_workbench",
                name="python.exe",
                command_line="python scripts/web_workbench.py --port 8000 --no-browser",
                cwd="C:/repo",
                port=8000,
            ),
        ],
    )

    excluded = daemon._snapshot_residual_excluded_pids(
        {
            "backendPid": 32344,
            "backendLaunchPid": 32344,
            "backendPortOwnerPid": 32344,
            "browserWindowPid": 37160,
        },
        manager_pid=26360,
    )

    assert {32344, 44052, 37160, 26360}.issubset(excluded)


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


def test_run_launcher_action_uses_no_window_flags_without_detaching_powershell(monkeypatch):
    captured = {}

    def fake_run(*args, **kwargs):
        captured["kwargs"] = kwargs
        kwargs["stdout"].write(b"ok\n")
        kwargs["stdout"].flush()
        return subprocess.CompletedProcess(args=args[0], returncode=0)

    monkeypatch.setattr(workbench_controller.subprocess, "DETACHED_PROCESS", 0x00000008, raising=False)
    monkeypatch.setattr(workbench_controller.subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200, raising=False)
    monkeypatch.setattr(workbench_controller.subprocess, "CREATE_NO_WINDOW", 0x08000000, raising=False)
    monkeypatch.setattr(workbench_controller.subprocess, "run", fake_run)

    result = workbench_controller.run_launcher_action("internal-start")

    assert result.returncode == 0
    assert not captured["kwargs"]["creationflags"] & 0x00000008
    assert captured["kwargs"]["creationflags"] & 0x00000200
    assert captured["kwargs"]["creationflags"] & 0x08000000


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
    observations = _repeat_last(
        [
            {
                "observedState": "open",
                "launcherStatePresent": True,
                "browserManaged": False,
                "browserWindowAlive": False,
                "backendPid": 28888,
                "browserLaunchPid": 0,
                "browserWindowPid": 0,
                "backendHealthy": True,
                "backendObserved": True,
                "backendPortListening": True,
                "backendPortOwnerPid": 28888,
                "backendPortOwnerTrusted": True,
                "backendPortConflict": False,
                "sessionId": "headless-session",
                "url": "http://127.0.0.1:8000",
            },
            {
                "observedState": "open",
                "launcherStatePresent": True,
                "browserManaged": True,
                "browserWindowAlive": True,
                "backendPid": 28888,
                "browserLaunchPid": 4500,
                "browserWindowPid": 4500,
                "backendHealthy": True,
                "backendObserved": True,
                "backendPortListening": True,
                "backendPortOwnerPid": 28888,
                "backendPortOwnerTrusted": True,
                "backendPortConflict": False,
                "sessionId": "browser-session",
                "url": "http://127.0.0.1:8000",
            },
            {
                "observedState": "open",
                "launcherStatePresent": True,
                "browserManaged": True,
                "browserWindowAlive": True,
                "backendPid": 28888,
                "browserLaunchPid": 4500,
                "browserWindowPid": 4500,
                "backendHealthy": True,
                "backendObserved": True,
                "backendPortListening": True,
                "backendPortOwnerPid": 28888,
                "backendPortOwnerTrusted": True,
                "backendPortConflict": False,
                "sessionId": "browser-session",
                "url": "http://127.0.0.1:8000",
            },
        ]
    )
    monkeypatch.setattr(daemon, "observe_workbench", observations)
    monkeypatch.setattr(daemon, "build_evolution_summary", lambda: {"self": {}, "supervised": {}})

    opened = {}
    events = []

    def fake_open_workbench(*, no_browser: bool):
        opened["no_browser"] = no_browser
        return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")

    monkeypatch.setattr(daemon, "open_workbench", fake_open_workbench)
    monkeypatch.setattr(daemon, "_append_event", lambda event_type, payload: events.append((event_type, payload)))

    result = runtime_daemon._handle_open_workbench(command_id="cmd-open", args={})

    assert result["ok"] is True
    assert result["message"] == "Workbench opened."
    assert opened == {"no_browser": False}
    assert events == [
        (
            "workbench.open.verification_succeeded",
            {
                "attempts": 1,
                "commandId": "cmd-open",
                "noBrowser": False,
                "observedState": "open",
                "launcherStatePresent": True,
                "backendPid": 28888,
                "backendHealthy": True,
                "backendObserved": True,
                "backendPort": 0,
                "backendPortListening": True,
                "backendPortOwnerPid": 28888,
                "backendPortOwnerTrusted": True,
                "backendPortConflict": False,
                "browserManaged": True,
                "browserWindowPid": 4500,
                "browserWindowAlive": True,
                "url": "http://127.0.0.1:8000",
                "healthUrl": "",
            },
        )
    ]


def test_handle_open_workbench_fails_when_launcher_exits_before_workbench_is_ready(monkeypatch):
    runtime_daemon = daemon.RuntimeManagerDaemon()
    state = {
        "command": {},
        "workbench": {
            "desiredState": "closed",
            "observedState": "closed",
            "phase": "steady",
        },
    }
    saved_states = []
    events = []
    observations = _repeat_last(
        [
            {
                "observedState": "closed",
                "launcherStatePresent": False,
                "browserManaged": True,
                "browserWindowAlive": False,
                "backendPid": 0,
                "browserLaunchPid": 0,
                "browserWindowPid": 0,
                "backendHealthy": False,
                "backendObserved": False,
                "backendPort": 8000,
                "backendPortListening": False,
                "backendPortOwnerPid": 0,
                "backendPortOwnerTrusted": False,
                "backendPortConflict": False,
                "sessionId": "",
                "url": "http://127.0.0.1:8000",
            },
            {
                "observedState": "closed",
                "launcherStatePresent": False,
                "browserManaged": True,
                "browserWindowAlive": False,
                "backendPid": 0,
                "browserLaunchPid": 0,
                "browserWindowPid": 0,
                "backendHealthy": False,
                "backendObserved": False,
                "backendPort": 8000,
                "backendPortListening": False,
                "backendPortOwnerPid": 0,
                "backendPortOwnerTrusted": False,
                "backendPortConflict": False,
                "sessionId": "",
                "url": "http://127.0.0.1:8000",
            },
        ]
    )

    monkeypatch.setattr(daemon, "load_state", lambda: state)
    monkeypatch.setattr(daemon, "save_state", lambda next_state: saved_states.append(next_state) or next_state)
    monkeypatch.setattr(daemon, "observe_workbench", observations)
    monkeypatch.setattr(daemon, "build_evolution_summary", lambda: {"self": {}, "supervised": {}})
    monkeypatch.setattr(daemon, "residual_process_payload", lambda **kwargs: {"count": 0, "items": []})
    monkeypatch.setattr(daemon, "_append_event", lambda event_type, payload: events.append((event_type, payload)))
    monkeypatch.setattr(daemon, "_OPEN_VERIFICATION_TIMEOUT_SECONDS", 0)
    monkeypatch.setattr(
        daemon,
        "open_workbench",
        lambda *, no_browser: subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr=""),
    )

    result = runtime_daemon._handle_command(
        {
            "commandId": "cmd-open",
            "type": "open_workbench",
            "requestedBy": "test",
            "args": {"reason": "launcher_start"},
        }
    )

    assert result["ok"] is False
    assert result["errorType"] == "RuntimeError"
    assert "not ready" in result["message"]
    assert saved_states[-1]["workbench"]["phase"] == "failed"
    assert saved_states[-1]["workbench"]["desiredState"] == "open"
    assert saved_states[-1]["workbench"]["observedState"] == "closed"
    assert any(event_type == "workbench.open.verification_failed" for event_type, _payload in events)
    failed_payload = next(payload for event_type, payload in events if event_type == "workbench.open.verification_failed")
    assert failed_payload["commandId"] == "cmd-open"
    assert failed_payload["attempts"] == 1
    assert failed_payload["launcher"]["returnCode"] == 0


def test_handle_open_workbench_retries_stale_browser_only_session(monkeypatch):
    runtime_daemon = daemon.RuntimeManagerDaemon()
    state = {
        "command": {},
        "workbench": {
            "desiredState": "closed",
            "observedState": "closed",
            "phase": "steady",
        },
    }
    events: list[tuple[str, dict]] = []
    open_calls: list[bool] = []
    observations = _repeat_last(
        [
            {
                "observedState": "open",
                "launcherStatePresent": True,
                "browserManaged": True,
                "browserWindowAlive": True,
                "backendPid": 0,
                "browserLaunchPid": 38028,
                "browserWindowPid": 38028,
                "backendHealthy": False,
                "backendObserved": False,
                "backendPort": 8000,
                "backendPortListening": False,
                "backendPortOwnerPid": 0,
                "backendPortOwnerTrusted": False,
                "backendPortConflict": False,
                "sessionId": "stale-browser-session",
                "url": "http://127.0.0.1:8000",
                "healthUrl": "http://127.0.0.1:8000/api/health",
            },
            {
                "observedState": "open",
                "launcherStatePresent": True,
                "browserManaged": True,
                "browserWindowAlive": True,
                "backendPid": 0,
                "browserLaunchPid": 38028,
                "browserWindowPid": 38028,
                "backendHealthy": False,
                "backendObserved": False,
                "backendPort": 8000,
                "backendPortListening": False,
                "backendPortOwnerPid": 0,
                "backendPortOwnerTrusted": False,
                "backendPortConflict": False,
                "sessionId": "stale-browser-session",
                "url": "http://127.0.0.1:8000",
                "healthUrl": "http://127.0.0.1:8000/api/health",
            },
            {
                "observedState": "open",
                "launcherStatePresent": True,
                "browserManaged": True,
                "browserWindowAlive": True,
                "backendPid": 0,
                "browserLaunchPid": 38028,
                "browserWindowPid": 38028,
                "backendHealthy": False,
                "backendObserved": False,
                "backendPort": 8000,
                "backendPortListening": False,
                "backendPortOwnerPid": 0,
                "backendPortOwnerTrusted": False,
                "backendPortConflict": False,
                "sessionId": "stale-browser-session",
                "url": "http://127.0.0.1:8000",
                "healthUrl": "http://127.0.0.1:8000/api/health",
            },
            {
                "observedState": "open",
                "launcherStatePresent": True,
                "browserManaged": True,
                "browserWindowAlive": True,
                "backendPid": 49972,
                "browserLaunchPid": 33676,
                "browserWindowPid": 33676,
                "backendHealthy": True,
                "backendObserved": True,
                "backendPort": 8000,
                "backendPortListening": True,
                "backendPortOwnerPid": 51780,
                "backendPortOwnerTrusted": True,
                "backendPortConflict": False,
                "sessionId": "fresh-browser-session",
                "url": "http://127.0.0.1:8000",
                "healthUrl": "http://127.0.0.1:8000/api/health",
            },
        ]
    )

    monkeypatch.setattr(daemon, "load_state", lambda: state)
    monkeypatch.setattr(daemon, "save_state", lambda next_state: next_state)
    monkeypatch.setattr(daemon, "observe_workbench", observations)
    monkeypatch.setattr(daemon, "build_evolution_summary", lambda: {"self": {}, "supervised": {}})
    monkeypatch.setattr(daemon, "_append_event", lambda event_type, payload: events.append((event_type, payload)))
    monkeypatch.setattr(daemon, "_OPEN_VERIFICATION_TIMEOUT_SECONDS", 0)

    def fake_open_workbench(*, no_browser: bool):
        open_calls.append(no_browser)
        return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")

    monkeypatch.setattr(daemon, "open_workbench", fake_open_workbench)

    result = runtime_daemon._handle_open_workbench(command_id="cmd-open", args={})

    assert result["ok"] is True
    assert result["message"] == "Workbench opened."
    assert open_calls == [False, False]
    assert [event_type for event_type, _payload in events] == [
        "workbench.open.stale_session_retry",
        "workbench.open.verification_succeeded",
    ]
    retry_payload = events[0][1]
    assert retry_payload["commandId"] == "cmd-open"
    assert retry_payload["backendHealthy"] is False
    assert retry_payload["browserWindowAlive"] is True
    assert retry_payload["attempts"] == 1
    success_payload = events[1][1]
    assert success_payload["backendHealthy"] is True
    assert success_payload["browserWindowPid"] == 33676
    assert success_payload["retry"] == "stale_session_cleanup"


def test_handle_open_workbench_no_browser_succeeds_when_backend_is_ready(monkeypatch):
    runtime_daemon = daemon.RuntimeManagerDaemon()
    state = {
        "command": {},
        "workbench": {
            "desiredState": "closed",
            "observedState": "closed",
            "phase": "steady",
        },
    }
    observations = _repeat_last(
        [
            {
                "observedState": "closed",
                "launcherStatePresent": False,
                "browserManaged": True,
                "browserWindowAlive": False,
                "backendPid": 0,
                "browserLaunchPid": 0,
                "browserWindowPid": 0,
                "backendHealthy": False,
                "backendObserved": False,
                "backendPort": 8000,
                "backendPortListening": False,
                "backendPortOwnerPid": 0,
                "backendPortOwnerTrusted": False,
                "backendPortConflict": False,
                "sessionId": "",
                "url": "http://127.0.0.1:8000",
            },
            {
                "observedState": "closed",
                "launcherStatePresent": False,
                "browserManaged": True,
                "browserWindowAlive": False,
                "backendPid": 0,
                "browserLaunchPid": 0,
                "browserWindowPid": 0,
                "backendHealthy": False,
                "backendObserved": False,
                "backendPort": 8000,
                "backendPortListening": False,
                "backendPortOwnerPid": 0,
                "backendPortOwnerTrusted": False,
                "backendPortConflict": False,
                "sessionId": "",
                "url": "http://127.0.0.1:8000",
            },
            {
                "observedState": "open",
                "launcherStatePresent": True,
                "browserManaged": False,
                "browserWindowAlive": False,
                "backendPid": 28888,
                "browserLaunchPid": 0,
                "browserWindowPid": 0,
                "backendHealthy": True,
                "backendObserved": True,
                "backendPort": 8000,
                "backendPortListening": True,
                "backendPortOwnerPid": 28888,
                "backendPortOwnerTrusted": True,
                "backendPortConflict": False,
                "sessionId": "headless-session",
                "url": "http://127.0.0.1:8000",
            },
            {
                "observedState": "open",
                "launcherStatePresent": True,
                "browserManaged": False,
                "browserWindowAlive": False,
                "backendPid": 28888,
                "browserLaunchPid": 0,
                "browserWindowPid": 0,
                "backendHealthy": True,
                "backendObserved": True,
                "backendPort": 8000,
                "backendPortListening": True,
                "backendPortOwnerPid": 28888,
                "backendPortOwnerTrusted": True,
                "backendPortConflict": False,
                "sessionId": "headless-session",
                "url": "http://127.0.0.1:8000",
            },
        ]
    )

    monkeypatch.setattr(daemon, "load_state", lambda: state)
    monkeypatch.setattr(daemon, "save_state", lambda next_state: next_state)
    monkeypatch.setattr(daemon, "observe_workbench", observations)
    monkeypatch.setattr(daemon, "build_evolution_summary", lambda: {"self": {}, "supervised": {}})
    events = []
    monkeypatch.setattr(
        daemon,
        "open_workbench",
        lambda *, no_browser: subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr=""),
    )
    monkeypatch.setattr(daemon, "_append_event", lambda event_type, payload: events.append((event_type, payload)))

    result = runtime_daemon._handle_open_workbench(command_id="cmd-open", args={"noBrowser": True})

    assert result["ok"] is True
    assert result["message"] == "Workbench opened."
    assert events[0][0] == "workbench.open.verification_succeeded"
    assert events[0][1]["commandId"] == "cmd-open"
    assert events[0][1]["noBrowser"] is True
    assert events[0][1]["attempts"] == 1


def test_open_verification_timeout_is_extended_for_slow_startups():
    assert daemon._OPEN_VERIFICATION_TIMEOUT_SECONDS >= 45


def test_handle_open_workbench_waits_for_delayed_backend_observation(monkeypatch):
    runtime_daemon = daemon.RuntimeManagerDaemon()
    state = {
        "command": {},
        "workbench": {
            "desiredState": "closed",
            "observedState": "closed",
            "phase": "steady",
        },
    }
    observations = _repeat_last(
        [
            {
                "observedState": "closed",
                "launcherStatePresent": False,
                "browserManaged": True,
                "browserWindowAlive": False,
                "backendPid": 0,
                "browserLaunchPid": 0,
                "browserWindowPid": 0,
                "backendHealthy": False,
                "backendObserved": False,
                "backendPort": 8000,
                "backendPortListening": False,
                "backendPortOwnerPid": 0,
                "backendPortOwnerTrusted": False,
                "backendPortConflict": False,
                "sessionId": "",
                "url": "http://127.0.0.1:8000",
            },
            {
                "observedState": "closed",
                "launcherStatePresent": False,
                "browserManaged": True,
                "browserWindowAlive": False,
                "backendPid": 0,
                "browserLaunchPid": 0,
                "browserWindowPid": 0,
                "backendHealthy": False,
                "backendObserved": False,
                "backendPort": 8000,
                "backendPortListening": False,
                "backendPortOwnerPid": 0,
                "backendPortOwnerTrusted": False,
                "backendPortConflict": False,
                "sessionId": "",
                "url": "http://127.0.0.1:8000",
            },
            {
                "observedState": "closed",
                "launcherStatePresent": False,
                "browserManaged": True,
                "browserWindowAlive": False,
                "backendPid": 0,
                "browserLaunchPid": 0,
                "browserWindowPid": 0,
                "backendHealthy": False,
                "backendObserved": False,
                "backendPort": 8000,
                "backendPortListening": False,
                "backendPortOwnerPid": 0,
                "backendPortOwnerTrusted": False,
                "backendPortConflict": False,
                "sessionId": "",
                "url": "http://127.0.0.1:8000",
            },
            {
                "observedState": "open",
                "launcherStatePresent": True,
                "browserManaged": False,
                "browserWindowAlive": False,
                "backendPid": 28888,
                "browserLaunchPid": 0,
                "browserWindowPid": 0,
                "backendHealthy": True,
                "backendObserved": True,
                "backendPort": 8000,
                "backendPortListening": True,
                "backendPortOwnerPid": 28888,
                "backendPortOwnerTrusted": True,
                "backendPortConflict": False,
                "sessionId": "headless-session",
                "url": "http://127.0.0.1:8000",
            },
        ]
    )
    sleeps = []

    monkeypatch.setattr(daemon, "load_state", lambda: state)
    monkeypatch.setattr(daemon, "save_state", lambda next_state: next_state)
    monkeypatch.setattr(daemon, "observe_workbench", observations)
    monkeypatch.setattr(daemon, "build_evolution_summary", lambda: {"self": {}, "supervised": {}})
    fake_time = type(
        "FakeTime",
        (),
        {"monotonic": staticmethod(lambda: 0.0), "sleep": staticmethod(lambda seconds: sleeps.append(seconds))},
    )
    monkeypatch.setattr(daemon, "time", fake_time)
    monkeypatch.setattr(
        daemon,
        "open_workbench",
        lambda *, no_browser: subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr=""),
    )
    events = []
    monkeypatch.setattr(daemon, "_append_event", lambda event_type, payload: events.append((event_type, payload)))

    result = runtime_daemon._handle_open_workbench(command_id="cmd-open", args={"noBrowser": True})

    assert result["ok"] is True
    assert result["message"] == "Workbench opened."
    assert sleeps == [daemon._OPEN_VERIFICATION_POLL_INTERVAL_SECONDS]
    assert events[0][0] == "workbench.open.verification_succeeded"
    assert events[0][1]["attempts"] == 2


def test_handle_open_workbench_restarts_healthy_headless_session_when_browser_requested(monkeypatch):
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
        _repeat_last(
            [
                {
                    "observedState": "open",
                    "launcherStatePresent": True,
                    "browserManaged": False,
                    "browserWindowAlive": False,
                    "backendPid": 28888,
                    "browserLaunchPid": 0,
                    "browserWindowPid": 0,
                    "backendHealthy": True,
                    "backendObserved": True,
                    "backendPortListening": True,
                    "backendPortOwnerPid": 28888,
                    "backendPortOwnerTrusted": True,
                    "backendPortConflict": False,
                    "sessionId": "headless-session",
                    "url": "http://127.0.0.1:8000",
                },
                {
                    "observedState": "open",
                    "launcherStatePresent": True,
                    "browserManaged": True,
                    "browserWindowAlive": True,
                    "backendPid": 28888,
                    "browserLaunchPid": 4500,
                    "browserWindowPid": 4500,
                    "backendHealthy": True,
                    "backendObserved": True,
                    "backendPortListening": True,
                    "backendPortOwnerPid": 28888,
                    "backendPortOwnerTrusted": True,
                    "backendPortConflict": False,
                    "sessionId": "browser-session",
                    "url": "http://127.0.0.1:8000",
                },
            ]
        ),
    )
    monkeypatch.setattr(daemon, "build_evolution_summary", lambda: {"self": {}, "supervised": {}})

    opened = {}
    events = []

    def fake_open_workbench(*, no_browser: bool):
        opened["no_browser"] = no_browser
        return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")

    monkeypatch.setattr(daemon, "open_workbench", fake_open_workbench)
    monkeypatch.setattr(daemon, "_append_event", lambda event_type, payload: events.append((event_type, payload)))

    result = runtime_daemon._handle_open_workbench(command_id="cmd-open", args={})

    assert result["ok"] is True
    assert result["message"] == "Workbench opened."
    assert opened == {"no_browser": False}
    assert events[0][0] == "workbench.open.verification_succeeded"


def test_handle_open_workbench_refocuses_existing_browser_session(monkeypatch):
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
    monkeypatch.setattr(daemon, "build_evolution_summary", lambda: {"self": {}, "supervised": {}})
    monkeypatch.setattr(
        daemon,
        "observe_workbench",
        lambda: {
            "observedState": "open",
            "launcherStatePresent": True,
            "browserManaged": True,
            "browserWindowAlive": True,
            "backendPid": 28888,
            "browserLaunchPid": 4500,
            "browserWindowPid": 4500,
            "backendHealthy": True,
            "backendObserved": True,
            "backendPortListening": True,
            "backendPortOwnerPid": 28888,
            "backendPortOwnerTrusted": True,
            "backendPortConflict": False,
            "sessionId": "browser-session",
            "url": "http://127.0.0.1:8000",
        },
    )

    opened = {}
    events: list[tuple[str, dict]] = []

    def fake_open_workbench(*, no_browser: bool):
        opened["no_browser"] = no_browser
        return subprocess.CompletedProcess(args=[], returncode=0, stdout="Focused existing workbench.\n", stderr="")

    monkeypatch.setattr(daemon, "open_workbench", fake_open_workbench)
    monkeypatch.setattr(daemon, "_append_event", lambda event_type, payload: events.append((event_type, payload)))

    result = runtime_daemon._handle_open_workbench(command_id="cmd-open", args={})

    assert result["ok"] is True
    assert result["message"] == "Workbench is already open."
    assert opened == {"no_browser": False}
    assert events == [
        (
            "workbench.open.already_satisfied",
            {
                "commandId": "cmd-open",
                "noBrowser": False,
                "focusRequested": True,
                "observedState": "open",
                "backendPid": 28888,
                "backendHealthy": True,
                "backendObserved": True,
                "browserManaged": True,
                "browserWindowPid": 4500,
                "browserWindowAlive": True,
                "sessionId": "browser-session",
                "url": "http://127.0.0.1:8000",
            },
        ),
        (
            "workbench.open.focus_requested",
            {
                "commandId": "cmd-open",
                "returnCode": 0,
                "stdout": "Focused existing workbench.",
                "stderr": "",
            },
        ),
    ]


def test_handle_open_workbench_logs_focus_failure_for_existing_browser_session(monkeypatch):
    runtime_daemon = daemon.RuntimeManagerDaemon()
    state = {
        "command": {},
        "workbench": {
            "desiredState": "open",
            "observedState": "open",
            "phase": "steady",
        },
    }
    observation = {
        "observedState": "open",
        "launcherStatePresent": True,
        "browserManaged": True,
        "browserWindowAlive": True,
        "backendPid": 28888,
        "browserLaunchPid": 4500,
        "browserWindowPid": 4500,
        "backendHealthy": True,
        "backendObserved": True,
        "backendPortListening": True,
        "backendPortOwnerPid": 28888,
        "backendPortOwnerTrusted": True,
        "backendPortConflict": False,
        "sessionId": "browser-session",
        "url": "http://127.0.0.1:8000",
    }
    events: list[tuple[str, dict]] = []

    monkeypatch.setattr(daemon, "load_state", lambda: state)
    monkeypatch.setattr(daemon, "save_state", lambda next_state: next_state)
    monkeypatch.setattr(daemon, "observe_workbench", lambda: observation)
    monkeypatch.setattr(daemon, "build_evolution_summary", lambda: {"self": {}, "supervised": {}})
    monkeypatch.setattr(daemon, "_append_event", lambda event_type, payload: events.append((event_type, payload)))
    monkeypatch.setattr(
        daemon,
        "open_workbench",
        lambda *, no_browser: subprocess.CompletedProcess(
            args=[],
            returncode=1,
            stdout="",
            stderr="No managed browser window was available to focus.",
        ),
    )

    with pytest.raises(RuntimeError, match="No managed browser window"):
        runtime_daemon._handle_open_workbench(command_id="cmd-open", args={})

    assert [event_type for event_type, _ in events] == [
        "workbench.open.already_satisfied",
        "workbench.open.focus_failed",
    ]
    assert events[1][1] == {
        "commandId": "cmd-open",
        "returnCode": 1,
        "detail": "No managed browser window was available to focus.\nLauncher exit code: 1",
    }


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
        _repeat_last(
            [
                {
                    "observedState": "open",
                    "launcherStatePresent": True,
                    "browserManaged": True,
                    "browserWindowAlive": True,
                    "backendPid": 28888,
                    "browserLaunchPid": 29999,
                    "browserWindowPid": 29999,
                    "backendAlive": True,
                    "backendHealthy": True,
                    "backendObserved": True,
                    "backendPortListening": True,
                    "backendPortOwnerPid": 28888,
                    "sessionId": "managed-session",
                    "url": "http://127.0.0.1:8000",
                },
                {
                    "observedState": "closed",
                    "launcherStatePresent": False,
                    "browserManaged": True,
                    "browserWindowAlive": False,
                    "backendPid": 0,
                    "browserLaunchPid": 0,
                    "browserWindowPid": 0,
                    "backendAlive": False,
                    "backendHealthy": False,
                    "backendObserved": False,
                    "backendPortListening": False,
                    "backendPortOwnerPid": 0,
                    "sessionId": "",
                    "url": "http://127.0.0.1:8000",
                },
            ]
        ),
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
        _repeat_last(
            [
                {
                    "observedState": "open",
                    "launcherStatePresent": True,
                    "browserManaged": True,
                    "browserWindowAlive": True,
                    "backendPid": 28888,
                    "browserLaunchPid": 29999,
                    "browserWindowPid": 29999,
                    "backendAlive": True,
                    "backendHealthy": True,
                    "backendObserved": True,
                    "backendPortListening": True,
                    "backendPortOwnerPid": 28888,
                    "sessionId": "managed-session",
                    "url": "http://127.0.0.1:8000",
                },
                {
                    "observedState": "closed",
                    "launcherStatePresent": False,
                    "browserManaged": True,
                    "browserWindowAlive": False,
                    "backendPid": 0,
                    "browserLaunchPid": 0,
                    "browserWindowPid": 0,
                    "backendAlive": False,
                    "backendHealthy": False,
                    "backendObserved": False,
                    "backendPortListening": False,
                    "backendPortOwnerPid": 0,
                    "sessionId": "",
                    "url": "http://127.0.0.1:8000",
                },
            ]
        ),
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
        _repeat_last(
            [
                {
                    "observedState": "open",
                    "launcherStatePresent": True,
                    "browserManaged": True,
                    "browserWindowAlive": True,
                    "backendPid": 28888,
                    "browserLaunchPid": 29999,
                    "browserWindowPid": 29999,
                    "backendAlive": True,
                    "backendHealthy": True,
                    "backendObserved": True,
                    "backendPortListening": True,
                    "backendPortOwnerPid": 28888,
                    "sessionId": "managed-session",
                    "url": "http://127.0.0.1:8000",
                },
                {
                    "observedState": "closed",
                    "launcherStatePresent": False,
                    "browserManaged": True,
                    "browserWindowAlive": False,
                    "backendPid": 0,
                    "browserLaunchPid": 0,
                    "browserWindowPid": 0,
                    "backendAlive": False,
                    "backendHealthy": False,
                    "backendObserved": False,
                    "backendPortListening": False,
                    "backendPortOwnerPid": 0,
                    "sessionId": "",
                    "url": "http://127.0.0.1:8000",
                },
            ]
        ),
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


def test_handle_close_workbench_claims_deferred_reopen_intent(monkeypatch):
    runtime_daemon = daemon.RuntimeManagerDaemon()
    state = {
        "command": {"activeCommandId": "cmd-close"},
        "workbench": {
            "desiredState": "open",
            "observedState": "open",
            "phase": "steady",
        },
    }
    events: list[tuple[str, dict]] = []
    intent = {
        "intentId": "intent-reopen",
        "target": "workbench",
        "reason": "launcher_start",
        "requestedBy": "launcher_ps",
        "sourceCommandId": "cmd-open",
        "payload": {"action": "reopen_after_close", "noBrowser": True},
    }

    monkeypatch.setattr(daemon, "load_state", lambda: state)
    monkeypatch.setattr(daemon, "save_state", lambda next_state: next_state)
    monkeypatch.setattr(daemon, "now_iso", lambda: "2026-05-19T09:00:00+00:00")
    monkeypatch.setattr(
        daemon,
        "observe_workbench",
        _repeat_last(
            [
                {
                    "observedState": "open",
                    "launcherStatePresent": True,
                    "browserManaged": True,
                    "browserWindowAlive": True,
                    "backendPid": 28888,
                    "browserLaunchPid": 29999,
                    "browserWindowPid": 29999,
                    "backendAlive": True,
                    "backendHealthy": True,
                    "backendObserved": True,
                    "backendPortListening": True,
                    "backendPortOwnerPid": 28888,
                    "sessionId": "managed-session",
                    "url": "http://127.0.0.1:8000",
                },
                {
                    "observedState": "closed",
                    "launcherStatePresent": False,
                    "browserManaged": True,
                    "browserWindowAlive": False,
                    "backendPid": 0,
                    "browserLaunchPid": 0,
                    "browserWindowPid": 0,
                    "backendAlive": False,
                    "backendHealthy": False,
                    "backendObserved": False,
                    "backendPortListening": False,
                    "backendPortOwnerPid": 0,
                    "sessionId": "",
                    "url": "http://127.0.0.1:8000",
                },
            ]
        ),
    )
    monkeypatch.setattr(daemon, "build_evolution_summary", lambda: {"self": {}, "supervised": {}})
    monkeypatch.setattr(
        daemon,
        "close_workbench",
        lambda: subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr=""),
    )
    monkeypatch.setattr(daemon, "_close_active_evolution_runs_for_shutdown", lambda: [])
    monkeypatch.setattr(daemon, "_claim_workbench_reopen_intent", lambda: intent)
    monkeypatch.setattr(daemon, "_append_event", lambda event_type, payload: events.append((event_type, payload)))

    result = runtime_daemon._handle_close_workbench(command_id="cmd-close", args={"stopManager": True})

    assert result["ok"] is True
    assert result["stopDaemon"] is False
    assert result["runDeferredWorkbenchOpen"] is True
    assert result["restartIntent"]["intentId"] == "intent-reopen"
    assert ("workbench.reopen_after_close.claimed", daemon._workbench_reopen_intent_event_payload(intent, command_id="cmd-close")) in events


def test_handle_restart_self_evolution_run_creates_restart_intent(monkeypatch):
    runtime_daemon = daemon.RuntimeManagerDaemon()
    state = {
        "command": {"activeCommandId": "cmd-restart"},
        "workbench": {
            "desiredState": "open",
            "observedState": "open",
            "phase": "steady",
        },
    }

    monkeypatch.setattr(daemon, "load_state", lambda: state)
    monkeypatch.setattr(daemon, "save_state", lambda next_state: next_state)
    monkeypatch.setattr(
        daemon,
        "observe_workbench",
        lambda: {
            "observedState": "open",
            "backendPid": 28888,
            "backendAlive": True,
            "backendHealthy": True,
            "backendObserved": True,
            "backendPortListening": True,
            "backendPortOwnerPid": 28888,
            "browserManaged": True,
            "browserWindowAlive": True,
            "browserWindowPid": 29999,
        },
    )
    monkeypatch.setattr(daemon, "build_evolution_summary", lambda: {"self": {}, "supervised": {}})
    monkeypatch.setattr(
        daemon.self_evolution_control_service,
        "_LOCAL_REQUEST_SELF_EVOLUTION_RESTART",
        lambda run_id="", reason="": {
            "intentId": "intent-self",
            "target": "self_evolution_run",
            "reason": reason,
            "snapshot": {"runId": run_id, "status": "running"},
        },
    )

    result = runtime_daemon._handle_restart_self_evolution_run(
        command_id="cmd-restart",
        args={"runId": "web-self-123", "payload": {"reason": "code_update"}},
    )

    assert result["ok"] is True
    assert result["runId"] == "web-self-123"
    assert result["restartIntent"]["intentId"] == "intent-self"
    assert result["restartIntent"]["reason"] == "code_update"


def test_daemon_processes_pending_self_evolution_restart_intent(monkeypatch):
    runtime_daemon = daemon.RuntimeManagerDaemon()
    events: list[tuple[str, dict]] = []
    completions: list[tuple[str, str, str]] = []
    intent = {
        "intentId": "intent-self",
        "target": "self_evolution_run",
        "reason": "code_update",
        "payload": {"runId": "web-self-123"},
    }

    monkeypatch.setattr(daemon, "claim_next_restart_intent", lambda target="": intent if target == "self_evolution_run" else None)
    monkeypatch.setattr(
        daemon.self_evolution_control_service,
        "_LOCAL_FULFILL_SELF_EVOLUTION_RESTART",
        lambda claimed: {
            "runId": "web-self-123",
            "message": "queued",
            "snapshot": {"runId": "web-self-123", "status": "queued"},
        },
    )
    monkeypatch.setattr(
        daemon,
        "complete_restart_intent",
        lambda intent_id, status="completed", message="": completions.append((intent_id, status, message)) or {},
    )
    monkeypatch.setattr(daemon, "_append_event", lambda event_type, payload: events.append((event_type, payload)))

    runtime_daemon._process_self_evolution_restart_intent()

    assert completions == [("intent-self", "completed", "queued")]
    assert events == [
        (
            "self_evolution.restarted_from_intent",
            {
                "intentId": "intent-self",
                "runId": "web-self-123",
                "status": "queued",
                "reason": "code_update",
            },
        )
    ]


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
        _repeat_last(
            [
                {
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
                {
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
            ]
        ),
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


def test_handle_close_workbench_includes_active_backend_in_residual_cleanup(monkeypatch):
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
    observations = _repeat_last(
        [
            {
                "observedState": "open",
                "launcherStatePresent": True,
                "browserManaged": False,
                "browserWindowAlive": False,
                "backendPid": 2748,
                "backendLaunchPid": 2748,
                "backendAlive": True,
                "backendHealthy": True,
                "backendObserved": True,
                "backendPort": 8000,
                "backendPortListening": True,
                "backendPortOwnerPid": 33556,
                "backendPortOwnerTrusted": True,
                "backendPortConflict": False,
                "browserLaunchPid": 0,
                "browserWindowPid": 0,
                "sessionId": "managed-session",
                "url": "http://127.0.0.1:8000",
            },
            {
                "observedState": "closed",
                "launcherStatePresent": False,
                "browserManaged": False,
                "browserWindowAlive": False,
                "backendPid": 0,
                "backendLaunchPid": 0,
                "backendAlive": False,
                "backendHealthy": False,
                "backendObserved": False,
                "backendPort": 8000,
                "backendPortListening": False,
                "backendPortOwnerPid": 0,
                "backendPortOwnerTrusted": False,
                "backendPortConflict": False,
                "browserLaunchPid": 0,
                "browserWindowPid": 0,
                "sessionId": "",
                "url": "http://127.0.0.1:8000",
            },
        ]
    )

    monkeypatch.setattr(daemon, "load_state", lambda: state)
    monkeypatch.setattr(daemon, "save_state", lambda next_state: next_state)
    monkeypatch.setattr(daemon, "observe_workbench", observations)
    monkeypatch.setattr(daemon, "build_evolution_summary", lambda: {"self": {}, "supervised": {}})
    monkeypatch.setattr(
        daemon,
        "close_workbench",
        lambda: subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr=""),
    )

    def fake_cleanup(**kwargs):
        cleanup_calls.append(kwargs)
        return {"supported": True, "requested": [2748, 33556], "terminated": [2748, 33556], "remaining": []}

    monkeypatch.setattr(daemon, "terminate_unmanaged_workbench_processes", fake_cleanup)

    result = runtime_daemon._handle_close_workbench(command_id="cmd-close", args={})

    assert result["ok"] is True
    assert cleanup_calls
    assert 2748 not in cleanup_calls[0]["exclude_pids"]
    assert 33556 not in cleanup_calls[0]["exclude_pids"]
    assert runtime_daemon._pid in cleanup_calls[0]["exclude_pids"]


def test_handle_close_workbench_fails_when_post_close_verification_still_sees_browser(monkeypatch):
    runtime_daemon = daemon.RuntimeManagerDaemon()
    state = {
        "command": {"activeCommandId": "cmd-close"},
        "workbench": {
            "desiredState": "open",
            "observedState": "open",
            "phase": "steady",
        },
    }
    observations = _repeat_last(
        [
            {
                "observedState": "open",
                "launcherStatePresent": True,
                "browserManaged": True,
                "browserWindowAlive": True,
                "backendPid": 6544,
                "backendLaunchPid": 6544,
                "backendAlive": True,
                "backendHealthy": True,
                "backendObserved": True,
                "backendPort": 8000,
                "backendPortListening": True,
                "backendPortOwnerPid": 14916,
                "backendPortOwnerTrusted": True,
                "backendPortConflict": False,
                "browserLaunchPid": 40736,
                "browserWindowPid": 40736,
                "sessionId": "managed-session",
                "url": "http://127.0.0.1:8000",
            },
            {
                "observedState": "open",
                "launcherStatePresent": True,
                "browserManaged": True,
                "browserWindowAlive": True,
                "backendPid": 0,
                "backendLaunchPid": 6544,
                "backendAlive": False,
                "backendHealthy": False,
                "backendObserved": False,
                "backendPort": 8000,
                "backendPortListening": False,
                "backendPortOwnerPid": 0,
                "backendPortOwnerTrusted": False,
                "backendPortConflict": False,
                "browserLaunchPid": 40736,
                "browserWindowPid": 40736,
                "sessionId": "managed-session",
                "url": "http://127.0.0.1:8000",
            },
        ]
    )
    events: list[tuple[str, dict]] = []

    monkeypatch.setattr(daemon, "load_state", lambda: state)
    monkeypatch.setattr(daemon, "save_state", lambda next_state: next_state)
    monkeypatch.setattr(daemon, "now_iso", lambda: "2026-05-24T05:30:00+00:00")
    monkeypatch.setattr(daemon, "observe_workbench", observations)
    monkeypatch.setattr(daemon, "build_evolution_summary", lambda: {"self": {}, "supervised": {}})
    monkeypatch.setattr(daemon, "_append_event", lambda event_type, payload: events.append((event_type, payload)))
    monkeypatch.setattr(daemon, "_CLOSE_VERIFICATION_TIMEOUT_SECONDS", 0)
    monkeypatch.setattr(
        daemon,
        "close_workbench",
        lambda: subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr=""),
    )
    monkeypatch.setattr(
        runtime_daemon,
        "_cleanup_residual_workbench_processes",
        lambda: {"supported": True, "requested": [], "terminated": [], "remaining": []},
    )

    result = runtime_daemon._handle_command(
        {
            "commandId": "cmd-close",
            "type": "close_workbench",
            "requestedBy": "test",
            "args": {},
        }
    )

    assert result["ok"] is False
    assert result["errorType"] == "RuntimeError"
    assert "not fully stopped" in result["message"]
    assert any(event_type == "workbench.close.verification_failed" for event_type, _payload in events)
    failed_payload = next(payload for event_type, payload in events if event_type == "workbench.close.verification_failed")
    assert failed_payload["commandId"] == "cmd-close"
    assert failed_payload["browserWindowPid"] == 40736
    assert failed_payload["attempts"] == 1


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
    monkeypatch.setattr(
        workbench_controller,
        "_repo_workbench_backend_kind",
        lambda pid: "managed_workbench_backend" if pid == 52396 else "",
    )

    observation = workbench_controller.observe_workbench()

    assert observation["observedState"] == "open"
    assert observation["backendObserved"] is True
    assert observation["backendPortListening"] is True
    assert observation["backendPortOwnerPid"] == 52396
    assert observation["backendPortOwnerKind"] == "managed_workbench_backend"
    assert observation["backendPortOwnerTrusted"] is True
    assert observation["backendPortOwnerResidual"] is False
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
    monkeypatch.setattr(workbench_controller, "_repo_workbench_backend_kind", lambda pid: "")

    observation = workbench_controller.observe_workbench()

    assert observation["observedState"] == "closed"
    assert observation["backendObserved"] is False
    assert observation["backendPortListening"] is True
    assert observation["backendPortOwnerPid"] == 52396
    assert observation["backendPortOwnerKind"] == ""
    assert observation["backendPortOwnerTrusted"] is False
    assert observation["backendPortOwnerResidual"] is False
    assert observation["backendPortConflict"] is True


def test_observe_workbench_reports_unmanaged_repo_port_owner_as_residual(tmp_path, monkeypatch):
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
    monkeypatch.setattr(
        workbench_controller,
        "_repo_workbench_backend_kind",
        lambda pid: "unmanaged_workbench" if pid == 52396 else "",
    )

    observation = workbench_controller.observe_workbench()

    assert observation["observedState"] == "closed"
    assert observation["backendObserved"] is False
    assert observation["backendHealthy"] is True
    assert observation["backendPortListening"] is True
    assert observation["backendPortOwnerPid"] == 52396
    assert observation["backendPortOwnerKind"] == "unmanaged_workbench"
    assert observation["backendPortOwnerTrusted"] is False
    assert observation["backendPortOwnerResidual"] is True
    assert observation["backendPortConflict"] is False
    assert observation["lifecycleConsistency"] == "residual_backend"


def test_snapshot_residual_exclusions_keep_untrusted_residual_port_owner(monkeypatch):
    monkeypatch.setattr(daemon.os, "getpid", lambda: 700)
    monkeypatch.setattr(daemon, "list_repo_runtime_processes", lambda project_root: [])

    excluded = daemon._snapshot_residual_excluded_pids(
        {
            "backendPid": 0,
            "backendLaunchPid": 0,
            "backendPortOwnerPid": 52396,
            "backendPortOwnerTrusted": False,
            "backendPortOwnerResidual": True,
            "browserLaunchPid": 0,
            "browserWindowPid": 0,
        },
        manager_pid=701,
    )

    assert 700 in excluded
    assert 701 in excluded
    assert 52396 not in excluded


def test_snapshot_residual_exclusions_keep_trusted_port_owner_out_of_residuals(monkeypatch):
    monkeypatch.setattr(daemon.os, "getpid", lambda: 700)
    monkeypatch.setattr(daemon, "list_repo_runtime_processes", lambda project_root: [])

    excluded = daemon._snapshot_residual_excluded_pids(
        {
            "backendPid": 0,
            "backendLaunchPid": 0,
            "backendPortOwnerPid": 52396,
            "backendPortOwnerTrusted": True,
            "backendPortOwnerResidual": False,
            "browserLaunchPid": 0,
            "browserWindowPid": 0,
        },
        manager_pid=701,
    )

    assert 52396 in excluded


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


def test_residual_process_payload_uses_configured_port_for_workbench_without_port_arg(monkeypatch, tmp_path):
    class FakeProc:
        def __init__(self, info):
            self.info = info

    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setattr(process_inventory, "configured_backend_port", lambda: 8000)
    monkeypatch.setattr(
        process_inventory.psutil,
        "process_iter",
        lambda attrs: iter(
            [
                FakeProc(
                    {
                        "pid": 31832,
                        "ppid": 50404,
                        "name": "python.exe",
                        "cmdline": ["python", "scripts/web_workbench.py", "--no-browser"],
                        "cwd": str(repo),
                    }
                ),
            ]
        ),
    )

    payload = process_inventory.residual_process_payload(project_root=repo)

    assert payload["count"] == 1
    assert payload["items"][0]["pid"] == 31832
    assert payload["items"][0]["kind"] == "unmanaged_workbench"
    assert payload["items"][0]["port"] == 8000


def test_residual_process_payload_ignores_launcher_managed_backend(monkeypatch, tmp_path):
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
                        "pid": 22416,
                        "ppid": 1,
                        "name": "pythonw.exe",
                        "cmdline": [
                            str(repo / ".venv" / "Scripts" / "pythonw.exe"),
                            "scripts/web_workbench.py",
                            "--port",
                            "8001",
                            "--no-browser",
                            "--managed-by-launcher",
                        ],
                        "cwd": str(repo),
                    }
                ),
                FakeProc(
                    {
                        "pid": 49780,
                        "ppid": 1,
                        "name": "python.exe",
                        "cmdline": ["python", "scripts/web_workbench.py", "--port", "8001", "--no-browser"],
                        "cwd": str(repo),
                    }
                ),
            ]
        ),
    )

    payload = process_inventory.residual_process_payload(project_root=repo)
    processes = process_inventory.list_repo_runtime_processes(project_root=repo)

    assert {item.kind for item in processes} == {"managed_workbench_backend", "unmanaged_workbench"}
    assert payload["count"] == 1
    assert payload["items"][0]["pid"] == 49780


def test_residual_process_payload_ignores_descendants_of_active_backend(monkeypatch, tmp_path):
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
                        "pid": 13492,
                        "ppid": 1,
                        "name": "cmd.exe",
                        "cmdline": [
                            "cmd.exe",
                            "/d",
                            "/s",
                            "/c",
                            str(repo / ".venv" / "Scripts" / "python.exe"),
                            "scripts/web_workbench.py",
                            "--port",
                            "8000",
                            "--no-browser",
                        ],
                        "cwd": str(repo),
                    }
                ),
                FakeProc(
                    {
                        "pid": 31408,
                        "ppid": 13492,
                        "name": "python.exe",
                        "cmdline": [
                            str(repo / ".venv" / "Scripts" / "python.exe"),
                            "scripts/web_workbench.py",
                            "--port",
                            "8000",
                            "--no-browser",
                        ],
                        "cwd": str(repo),
                    }
                ),
                FakeProc(
                    {
                        "pid": 41160,
                        "ppid": 31408,
                        "name": "python.exe",
                        "cmdline": [
                            "python.exe",
                            "scripts/web_workbench.py",
                            "--port",
                            "8000",
                            "--no-browser",
                        ],
                        "cwd": str(repo),
                    }
                ),
                FakeProc(
                    {
                        "pid": 49780,
                        "ppid": 1,
                        "name": "python.exe",
                        "cmdline": ["python", "scripts/web_workbench.py", "--port", "8001", "--no-browser"],
                        "cwd": str(repo),
                    }
                ),
            ]
        ),
    )

    payload = process_inventory.residual_process_payload(project_root=repo, exclude_pids={13492, 31408})

    assert payload["count"] == 1
    assert payload["items"][0]["pid"] == 49780


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


def test_daemon_exit_marks_matching_manager_not_running(monkeypatch):
    state = {
        "runtimeState": "running",
        "managerPid": 321,
        "daemonRunning": True,
    }
    saved_states = []

    monkeypatch.setattr(daemon, "load_state", lambda: dict(state))
    monkeypatch.setattr(daemon, "save_state", lambda next_state: saved_states.append(dict(next_state)))
    monkeypatch.setattr(daemon, "now_iso", lambda: "2026-05-24T15:00:00+00:00")

    daemon._mark_daemon_not_running_after_exit(manager_pid=321)

    assert saved_states[-1]["runtimeState"] == "idle"
    assert saved_states[-1]["managerPid"] == 0
    assert saved_states[-1]["daemonRunning"] is False
    assert saved_states[-1]["lastStoppedManagerPid"] == 321


def test_daemon_exit_keeps_newer_manager_owner(monkeypatch):
    state = {
        "runtimeState": "running",
        "managerPid": 654,
        "daemonRunning": True,
    }
    saved_states = []

    monkeypatch.setattr(daemon, "load_state", lambda: dict(state))
    monkeypatch.setattr(daemon, "save_state", lambda next_state: saved_states.append(dict(next_state)))

    daemon._mark_daemon_not_running_after_exit(manager_pid=321)

    assert saved_states == []


def test_backend_health_probe_treats_low_level_http_errors_as_unhealthy(monkeypatch):
    def raise_http_exception(*_args, **_kwargs):
        raise http.client.HTTPException("connection closed")

    monkeypatch.setattr(workbench_controller.urllib.request, "urlopen", raise_http_exception)

    assert workbench_controller._is_backend_healthy("http://127.0.0.1:8766") is False
