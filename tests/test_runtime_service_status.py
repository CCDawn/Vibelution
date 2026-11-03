"""Runtime summary must use the current project lifecycle, not an orphaned RM file."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import os

import pytest

from core.web.services import runtime_service


@pytest.fixture
def isolated_summary(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(runtime_service, "get_web_language", lambda: "en")
    monkeypatch.setattr(runtime_service, "load_public_config", dict)
    monkeypatch.setattr(runtime_service, "get_active_session_summary", lambda **kwargs: {})
    monkeypatch.setattr(runtime_service, "_load_runtime_state", dict)
    monkeypatch.setattr(runtime_service, "_work_run_summary", dict)
    monkeypatch.setattr(runtime_service, "_mental_state_summary", lambda *args, **kwargs: {})
    monkeypatch.setattr(runtime_service, "_context_compression_summary", lambda *args, **kwargs: {})
    monkeypatch.setattr(runtime_service, "current_runtime_manager_pid", lambda root: 0)
    monkeypatch.setattr(runtime_service, "_pid_is_alive", lambda pid: False)
    monkeypatch.setattr(runtime_service.desktop_session_store, "latest_active_workbench_projection", dict)
    monkeypatch.setattr(runtime_service.desktop_session_store, "latest_active_window_provider_projection", lambda **kwargs: {})
    monkeypatch.setattr(runtime_service, "ensure_daemon_running", lambda *args, **kwargs: pytest.fail("Summary must not start a daemon"))
    monkeypatch.setattr(runtime_service, "submit_command", lambda *args, **kwargs: pytest.fail("Summary must not enqueue lifecycle work"))
    launcher_path = tmp_path / "launcher-state.json"
    runtime_path = tmp_path / "runtime-manager-state.json"
    monkeypatch.setattr(runtime_service, "LAUNCHER_STATE_PATH", launcher_path)
    monkeypatch.setattr(runtime_service, "load_runtime_manager_state", lambda: json.loads(runtime_path.read_text(encoding="utf-8")))
    return runtime_path, launcher_path


@pytest.mark.parametrize("phase", ["steady", "failed"])
@pytest.mark.parametrize("fresh_idle", [False, True])
def test_iss003_summary_maps_old_foreign_runtime_to_current_electron(isolated_summary, tmp_path, monkeypatch, phase, fresh_idle):
    runtime_path, launcher_path = isolated_summary
    old_at = (datetime.now(timezone.utc) - timedelta(days=60)).isoformat()
    state = {
        "projectRoot": str(tmp_path / "foreign"), "updatedAt": old_at,
        "lastError": {"at": old_at, "scope": "open_workbench", "message": "Old dirty-main failure"},
        "workbench": {"desiredState": "open", "observedState": "closed", "phase": "opening",
                      "backendPort": 8002, "url": "http://127.0.0.1:8002"},
    }
    if fresh_idle:
        state.update(projectRoot=str(tmp_path), updatedAt=datetime.now(timezone.utc).isoformat(),
                     command={"activeCommandId": "", "activeType": ""})
        state["workbench"]["lastTransitionAt"] = old_at
        monkeypatch.setattr(runtime_service, "current_runtime_manager_pid", lambda root: 6543)
    runtime_path.write_text(json.dumps(state), encoding="utf-8")
    failure = "Current Electron failure" if phase == "failed" else ""
    launcher_path.write_text(json.dumps({
        "runtimeProjectRoot": str(tmp_path), "lastSource": "electron_main",
        "updatedAt": (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(),
        "desiredState": "open", "observedState": "open", "phase": phase,
        "failureMessage": failure, "backendPid": os.getpid(), "backendPort": 8000,
        "url": "http://127.0.0.1:8000", "browserManaged": False,
        "windowManaged": True, "windowProvider": "electron", "browserWindowAlive": True,
    }), encoding="utf-8")
    monkeypatch.setenv("VIBELUTION_PORT", "8000")
    before = runtime_path.read_bytes(), launcher_path.read_bytes()

    payload = runtime_service.get_runtime_summary()

    assert payload["workbench"]["backendPort"] == 8000
    assert payload["workbench"]["url"] == "http://127.0.0.1:8000"
    assert payload["workbench"]["phase"] == phase
    assert payload["workbench"]["failureMessage"] == failure
    assert payload["lifecycleProof"]["overallState"] == ("failed" if failure else "ready")
    assert (runtime_path.read_bytes(), launcher_path.read_bytes()) == before


def test_iss003_summary_without_launcher_state_does_not_invent_failure(isolated_summary):
    runtime_path, launcher_path = isolated_summary
    runtime_path.write_text("{}", encoding="utf-8")
    assert not launcher_path.exists()

    payload = runtime_service.get_runtime_summary()

    assert payload["workbench"]["failureMessage"] == ""
    assert payload["lifecycleProof"]["overallState"] != "failed"
    assert not launcher_path.exists()


@pytest.mark.parametrize("old_port,old_url,host,expected_host", [
    (8002, "http://127.0.0.1:8002", "", "127.0.0.1"),
    (8001, "http://foreign.invalid:8002", "", "127.0.0.1"),
    (8001, "http://foreign.invalid:8001", "0.0.0.0", "127.0.0.1"),
    (8001, "http://foreign.invalid:8001", "localhost", "localhost"),
])
def test_iss003_summary_request_identity_uses_its_bound_port(monkeypatch, old_port, old_url, host, expected_host):
    monkeypatch.setenv("VIBELUTION_PORT", "8001")
    monkeypatch.setenv("VIBELUTION_HOST", host)
    old_endpoint = {"desiredState": "open", "backendPid": os.getpid(), "backendObserved": True,
                    "backendAlive": True, "backendPort": old_port, "url": old_url}

    observed = runtime_service._observe_backend_from_summary_request(old_endpoint)

    assert observed["backendPort"] == 8001
    assert observed["url"] == f"http://{expected_host}:8001"
    assert old_endpoint["backendPort"] == old_port
    assert old_endpoint["url"] == old_url


def test_iss003_foreign_snapshot_keeps_independently_verified_manager(isolated_summary, tmp_path, monkeypatch):
    runtime_path, _ = isolated_summary
    runtime_path.write_text(json.dumps({
        "projectRoot": str(tmp_path / "foreign"), "updatedAt": datetime.now(timezone.utc).isoformat(),
        "workbench": {"desiredState": "open", "observedState": "closed", "phase": "opening"},
    }), encoding="utf-8")
    monkeypatch.setattr(runtime_service, "current_runtime_manager_pid", lambda root: 6543)

    snapshot = runtime_service._load_runtime_manager_snapshot()

    assert snapshot["daemonRunning"] is True
    assert snapshot["managerPid"] == 6543
    assert snapshot["workbench"] == {}


def test_iss003_summary_keeps_failure_newer_than_its_last_transition(isolated_summary, tmp_path, monkeypatch):
    runtime_path, launcher_path = isolated_summary
    now = datetime.now(timezone.utc)
    failure = "Current command failed after the previous transition"
    runtime_path.write_text(json.dumps({
        "projectRoot": str(tmp_path), "updatedAt": now.isoformat(), "command": {"activeCommandId": ""},
        "lastError": {"at": now.isoformat(), "scope": "open_workbench", "message": failure},
        "workbench": {"desiredState": "open", "observedState": "open", "phase": "failed",
                      "lastTransitionAt": (now - timedelta(seconds=60)).isoformat(), "backendPort": 8000},
    }), encoding="utf-8")
    launcher_path.write_text(json.dumps({
        "runtimeProjectRoot": str(tmp_path), "lastSource": "electron_main",
        "updatedAt": (now - timedelta(seconds=30)).isoformat(),
        "desiredState": "open", "observedState": "open", "phase": "steady", "backendPort": 8000,
    }), encoding="utf-8")
    monkeypatch.setenv("VIBELUTION_PORT", "8000")

    payload = runtime_service.get_runtime_summary()

    assert payload["workbench"]["phase"] == "failed"
    assert payload["workbench"]["failureMessage"] == failure
    assert payload["lifecycleProof"]["overallState"] == "failed"


@pytest.mark.parametrize("reader", ["launcher", "summary"])
@pytest.mark.parametrize("persisted", ["missing", "corrupt"])
def test_iss003_readers_do_not_promote_load_state_defaults(
    isolated_summary, tmp_path, monkeypatch, reader, persisted
):
    from core.launcher import service as launcher_service
    from core.runtime_manager import state_store

    runtime_path, launcher_path = isolated_summary
    if persisted == "corrupt":
        runtime_path.write_text("{broken json", encoding="utf-8")
    monkeypatch.setattr(state_store, "STATE_PATH", runtime_path)
    monkeypatch.setattr(runtime_service, "load_runtime_manager_state", state_store.load_state)
    launcher_path.write_text(json.dumps({
        "runtimeProjectRoot": str(tmp_path), "lastSource": "electron_main",
        "updatedAt": (datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat(),
        "desiredState": "open", "observedState": "open", "phase": "steady",
        "backendPid": os.getpid(), "backendPort": 8000, "url": "http://127.0.0.1:8000",
        "browserManaged": False, "windowManaged": True, "windowProvider": "electron",
        "browserWindowAlive": True,
    }), encoding="utf-8")
    monkeypatch.setenv("VIBELUTION_PORT", "8000")
    if reader == "summary":
        payload = runtime_service.get_runtime_summary()
        assert payload["lifecycleProof"]["overallState"] == "ready"
        assert payload["workbench"]["backendPort"] == 8000
    else:
        monkeypatch.setattr(launcher_service, "PROJECT_ROOT", tmp_path)
        monkeypatch.setattr(launcher_service, "STATE_PATH", runtime_path)
        monkeypatch.setattr(launcher_service, "LAUNCHER_STATE_PATH", launcher_path)
        monkeypatch.setattr(launcher_service, "load_state", state_store.load_state)
        monkeypatch.setattr(launcher_service, "load_pid", lambda: 0)
        monkeypatch.setattr(launcher_service, "_is_process_alive", lambda pid: False)
        for name in ("INBOX_DIR", "PROCESSING_DIR", "RESULTS_DIR"):
            monkeypatch.setattr(launcher_service, name, tmp_path / name)
        monkeypatch.setattr(launcher_service, "launcher_active_work_runs", list)
        monkeypatch.setattr(launcher_service, "_control_plane_evidence", dict)
        monkeypatch.setattr(launcher_service, "_residual_processes_payload", lambda **kwargs: {"count": 0, "items": []})
        monkeypatch.setattr(launcher_service, "get_launcher_startup_settings", dict)
        monkeypatch.setattr(launcher_service, "get_workbench_window_mode_setting", dict)
        monkeypatch.setattr(launcher_service, "get_launcher_developer_mode_setting", dict)
        monkeypatch.setattr(launcher_service, "observe_workbench", lambda **kwargs: {
            "observedState": "open", "backendAlive": True, "backendHealthy": True,
            "backendPortListening": True, "backendPid": os.getpid(), "backendPort": 8000,
            "browserManaged": False,
        })
        payload = launcher_service.get_launcher_status()
        assert payload["overallState"] == "ready"
        assert payload["projectBundle"]["backend"]["port"] == 8000
    assert not runtime_path.exists() if persisted == "missing" else runtime_path.read_text(encoding="utf-8") == "{broken json"
