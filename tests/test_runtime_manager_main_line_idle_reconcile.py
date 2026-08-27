from __future__ import annotations

import json
import os

from core.runtime_manager import daemon


def test_electron_owns_main_line_queue_when_marker_pid_is_alive(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(daemon, "RUNTIME_MANAGER_DIR", tmp_path)
    monkeypatch.setattr(
        daemon,
        "capture_process_identity",
        lambda pid: {"pid": pid, "createTime": 1_724_147_199.0, "executable": r"C:\\Vibelution\\Vibelution.exe"},
    )
    assert daemon.electron_owns_main_line_queue() is False
    assert daemon.should_run_workbench_idle_reconcile() is True

    (tmp_path / daemon.MAIN_LINE_QUEUE_OWNER_FILE).write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "owner": "electron",
                "pid": 4242,
                "executable": r"C:\\Vibelution\\Vibelution.exe",
                "updatedAt": "2026-08-20T10:00:00Z",
            }
        ),
        encoding="utf-8",
    )
    assert daemon.electron_owns_main_line_queue() is True
    assert daemon.should_run_workbench_idle_reconcile() is False


def test_electron_owns_main_line_queue_ignores_dead_or_invalid_marker(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(daemon, "RUNTIME_MANAGER_DIR", tmp_path)
    monkeypatch.setattr(daemon, "capture_process_identity", lambda pid: {})
    (tmp_path / daemon.MAIN_LINE_QUEUE_OWNER_FILE).write_text(
        json.dumps({"schemaVersion": 1, "owner": "electron", "pid": 4242}),
        encoding="utf-8",
    )
    assert daemon.electron_owns_main_line_queue() is False
    (tmp_path / daemon.MAIN_LINE_QUEUE_OWNER_FILE).write_text(
        json.dumps({"schemaVersion": 1, "owner": "python", "pid": os.getpid()}),
        encoding="utf-8",
    )
    assert daemon.electron_owns_main_line_queue() is False
    assert daemon.should_run_workbench_idle_reconcile() is True


def test_electron_owns_main_line_queue_rejects_pid_reused_after_marker(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(daemon, "RUNTIME_MANAGER_DIR", tmp_path)
    (tmp_path / daemon.MAIN_LINE_QUEUE_OWNER_FILE).write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "owner": "electron",
                "pid": 4242,
                "executable": r"C:\\Vibelution\\Vibelution.exe",
                "updatedAt": "2026-08-20T10:00:00Z",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        daemon,
        "capture_process_identity",
        lambda pid: {"pid": pid, "createTime": 1_787_220_001.0, "executable": r"C:\\Vibelution\\Vibelution.exe"},
    )

    assert daemon.electron_owns_main_line_queue() is False
    assert daemon.should_run_workbench_idle_reconcile() is True


def test_should_execute_workbench_queue_command_skips_when_electron_owns(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(daemon, "RUNTIME_MANAGER_DIR", tmp_path)
    monkeypatch.setattr(
        daemon,
        "capture_process_identity",
        lambda pid: {"pid": pid, "createTime": 1_724_147_199.0, "executable": r"C:\\Vibelution\\Vibelution.exe"},
    )
    (tmp_path / daemon.MAIN_LINE_QUEUE_OWNER_FILE).write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "owner": "electron",
                "pid": 4242,
                "executable": r"C:\\Vibelution\\Vibelution.exe",
                "updatedAt": "2026-08-20T10:00:00Z",
            }
        ),
        encoding="utf-8",
    )
    assert daemon.should_execute_workbench_queue_command("open_workbench") is False
    assert daemon.should_execute_workbench_queue_command("close_workbench") is False
    assert daemon.should_execute_workbench_queue_command("restart_workbench") is False
    assert daemon.should_execute_workbench_queue_command("force_close_workbench") is False
    assert daemon.should_execute_workbench_queue_command("toggle_workbench") is False
    assert daemon.should_execute_workbench_queue_command("hot_restart_workbench") is True
    assert daemon.should_execute_workbench_queue_command("start_supervised_run") is True


def test_handle_command_hands_off_product_workbench_queue_to_electron(monkeypatch) -> None:
    runtime_daemon = daemon.RuntimeManagerDaemon()
    monkeypatch.setattr(daemon, "electron_owns_main_line_queue", lambda: True)
    monkeypatch.setattr(daemon, "load_state", lambda: {"command": {}, "workbench": {}, "stateVersion": 1})
    monkeypatch.setattr(daemon, "save_state", lambda state: state)
    monkeypatch.setattr(daemon, "_append_event", lambda *_args, **_kwargs: None)
    called = {"open": False}

    def boom(*, command_id: str, args: dict):
        called["open"] = True
        return {"ok": True, "commandId": command_id}

    monkeypatch.setattr(runtime_daemon, "_handle_open_workbench", boom)
    monkeypatch.setattr(
        runtime_daemon,
        "_hand_off_command_to_electron_control_plane",
        lambda _command_id, _command_type, _args: {"ok": True, "desktopLifecycle": "restart"},
    )
    result = runtime_daemon._handle_command(
        {
            "commandId": "cmd-open",
            "type": "restart_workbench",
            "requestedBy": "web_ui",
            "args": {},
        }
    )
    assert called["open"] is False
    assert result["ok"] is True
    assert result["code"] == "handed_off_to_electron"
    assert result["electronControlPlaneHandoff"]["ok"] is True


def test_handle_command_reports_failed_electron_handoff_as_lifecycle_failure(monkeypatch) -> None:
    runtime_daemon = daemon.RuntimeManagerDaemon()
    saved_states: list[dict] = []

    def fake_save_state(state):
        saved_states.append(json.loads(json.dumps(state)))
        return state

    monkeypatch.setattr(daemon, "electron_owns_main_line_queue", lambda: True)
    monkeypatch.setattr(daemon, "load_state", lambda: {"command": {}, "workbench": {}, "stateVersion": 1})
    monkeypatch.setattr(daemon, "save_state", fake_save_state)
    monkeypatch.setattr(daemon, "_append_event", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        runtime_daemon,
        "_hand_off_command_to_electron_control_plane",
        lambda _command_id, _command_type, _args: {"ok": False, "reason": "live electron desktop shell not found"},
    )
    result = runtime_daemon._handle_command(
        {
            "commandId": "cmd-restart-2",
            "type": "restart_workbench",
            "requestedBy": "web_ui",
            "args": {},
        }
    )
    assert result["ok"] is False
    assert result["errorType"] == "ElectronControlPlaneHandoffFailed"
    assert result["code"] == "control_plane_is_electron_handoff_failed"
    assert "hand-off to it failed" in result["message"]
    assert result["completed"] is True
    latest = saved_states[-1]
    assert latest["lastError"]["scope"] == "restart_workbench"


def test_handle_command_still_runs_hot_restart_when_electron_owns(monkeypatch) -> None:
    runtime_daemon = daemon.RuntimeManagerDaemon()
    monkeypatch.setattr(daemon, "electron_owns_main_line_queue", lambda: True)
    monkeypatch.setattr(daemon, "load_state", lambda: {"command": {}, "workbench": {}, "stateVersion": 1})
    monkeypatch.setattr(daemon, "save_state", lambda state: state)
    monkeypatch.setattr(daemon, "_append_event", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(runtime_daemon, "_reconcile_observation", lambda state, **_kwargs: state)
    called = {"hot": False}

    def fake_hot(*, command_id: str, args: dict):
        called["hot"] = True
        return {"ok": True, "commandId": command_id}

    monkeypatch.setattr(runtime_daemon, "_handle_hot_restart_workbench", fake_hot)
    result = runtime_daemon._handle_command(
        {
            "commandId": "cmd-hot",
            "type": "hot_restart_workbench",
            "requestedBy": "evolution",
            "args": {},
        }
    )
    assert called["hot"] is True
    assert result["ok"] is True


def test_handle_command_refuses_stop_manager_close_under_electron_control_plane(monkeypatch) -> None:
    runtime_daemon = daemon.RuntimeManagerDaemon()
    monkeypatch.setattr(daemon, "electron_owns_main_line_queue", lambda: True)
    monkeypatch.setattr(daemon, "load_state", lambda: {"command": {}, "workbench": {}, "stateVersion": 1})
    monkeypatch.setattr(daemon, "save_state", lambda state: state)
    monkeypatch.setattr(daemon, "_append_event", lambda *_args, **_kwargs: None)
    forwarded = {"count": 0}

    def fake_forward(_command_type):
        forwarded["count"] += 1
        return {"ok": True}

    monkeypatch.setattr(daemon, "forward_lifecycle_command_to_electron", fake_forward)
    result = runtime_daemon._handle_command(
        {
            "commandId": "cmd-shutdown",
            "type": "close_workbench",
            "requestedBy": "web_ui",
            "args": {"stopManager": True},
        }
    )
    assert result["ok"] is False
    assert result["errorType"] == "ElectronControlPlaneHandoffFailed"
    assert forwarded["count"] == 0
