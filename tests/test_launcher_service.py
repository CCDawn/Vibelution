import json

from core.web.services import launcher_service


def test_launcher_status_exposes_guardian_adapter_migration_contract(tmp_path, monkeypatch):
    launcher_state_path = tmp_path / ".runtime" / "launcher" / "state.json"
    launcher_state_path.parent.mkdir(parents=True, exist_ok=True)
    launcher_state_path.write_text(
        json.dumps(
            {
                "supervisorPid": 4444,
                "supervisorStdout": "logs/runtime_scenes/scene-a/raw/supervisor.log",
                "supervisorStderr": "logs/runtime_scenes/scene-a/raw/supervisor.stderr.log",
                "runtimeSceneId": "scene-a",
                "runtimeSceneDir": "logs/runtime_scenes/scene-a",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        launcher_service,
        "get_runtime_summary",
        lambda: {
            "workbench": {
                "desiredState": "open",
                "observedState": "open",
                "phase": "steady",
                "backendPid": 3001,
                "backendAlive": True,
                "backendHealthy": True,
                "backendPort": 8000,
                "backendPortListening": True,
                "browserManaged": True,
                "browserWindowPid": 4001,
                "browserWindowAlive": True,
                "url": "http://127.0.0.1:8000",
                "statusLine": "Workbench is running.",
            },
            "runtimeManager": {"running": True, "runtimeState": "idle", "managerPid": 2001},
            "lifecycleProof": {"overallState": "running", "overallLabel": "ready"},
        },
    )
    monkeypatch.setattr(launcher_service, "LAUNCHER_STATE_PATH", launcher_state_path)
    monkeypatch.setattr(launcher_service, "_is_process_alive", lambda pid: int(pid) == 4444)

    payload = launcher_service.get_launcher_status()

    guardian = payload["guardianAdapter"]
    assert guardian["schemaVersion"] == 1
    assert guardian["mode"] == "adapter_migration"
    assert guardian["targetMode"] == "standalone_launcher_guardian"
    assert guardian["ownedCount"] >= 2
    assert guardian["adapterCount"] >= 3
    assert guardian["supervisor"]["pid"] == 4444
    assert guardian["supervisor"]["alive"] is True
    assert guardian["supervisor"]["status"] == "running"
    assert guardian["supervisor"]["stdoutPath"].endswith("raw/supervisor.log")
    assert guardian["supervisor"]["stderrPath"].endswith("raw/supervisor.stderr.log")
    assert guardian["supervisor"]["runtimeSceneId"] == "scene-a"
    responsibilities = {item["id"]: item for item in guardian["responsibilities"]}
    assert responsibilities["project_bundle_lifecycle"]["owner"] == "launcher_api"
    assert responsibilities["runtime_manager_daemon"]["status"] == "running"
    assert responsibilities["desktop_supervisor"]["adapter"] == "vibelution_launcher.ps1"
    assert responsibilities["desktop_supervisor"]["status"] == "running"
    assert responsibilities["backend_process"]["status"] == "running"
    assert responsibilities["browser_window"]["status"] == "managed"
    assert responsibilities["runtime_scene_logging"]["owner"] == "runtime_scene_service"


def test_launcher_supervisor_snapshot_reports_recorded_dead_pid(tmp_path, monkeypatch):
    launcher_state_path = tmp_path / ".runtime" / "launcher" / "state.json"
    launcher_state_path.parent.mkdir(parents=True, exist_ok=True)
    launcher_state_path.write_text(json.dumps({"supervisorPid": 5555}), encoding="utf-8")
    monkeypatch.setattr(launcher_service, "LAUNCHER_STATE_PATH", launcher_state_path)
    monkeypatch.setattr(launcher_service, "_is_process_alive", lambda pid: False)

    supervisor = launcher_service._launcher_supervisor_snapshot()

    assert supervisor["pid"] == 5555
    assert supervisor["alive"] is False
    assert supervisor["status"] == "stopped"
    assert "no longer alive" in supervisor["detail"]


def test_launcher_supervisor_reattach_queues_guarded_open_workbench(tmp_path, monkeypatch):
    launcher_state_path = tmp_path / ".runtime" / "launcher" / "state.json"
    launcher_state_path.parent.mkdir(parents=True, exist_ok=True)
    launcher_state_path.write_text(
        json.dumps(
            {
                "sessionId": "session-a",
                "supervisorPid": 5555,
                "runtimeSceneId": "scene-a",
                "runtimeSceneDir": "logs/runtime_scenes/scene-a",
            }
        ),
        encoding="utf-8",
    )
    calls = []
    events = []
    monkeypatch.setattr(launcher_service, "LAUNCHER_STATE_PATH", launcher_state_path)
    monkeypatch.setattr(launcher_service, "_is_process_alive", lambda pid: False)
    monkeypatch.setattr(
        launcher_service,
        "get_runtime_summary",
        lambda: {
            "workbench": {
                "observedState": "open",
                "backendAlive": True,
                "backendHealthy": True,
                "browserWindowAlive": True,
            }
        },
    )
    monkeypatch.setattr(launcher_service, "ensure_daemon_running", lambda: calls.append(("ensure",)))
    monkeypatch.setattr(
        launcher_service,
        "submit_command",
        lambda command_type, *, args, requested_by: calls.append((command_type, args, requested_by)) or {"commandId": "cmd-reattach"},
    )
    monkeypatch.setattr(
        launcher_service,
        "record_runtime_scene_event",
        lambda component, phase, event_code, **kwargs: events.append((component, phase, event_code, kwargs)),
        raising=False,
    )

    payload = launcher_service.request_launcher_supervisor_reattach()

    assert payload["accepted"] is True
    assert payload["operation"] == "supervisor_reattach"
    assert payload["commandId"] == "cmd-reattach"
    assert calls[0] == ("ensure",)
    assert calls[1] == (
        "open_workbench",
        {"reason": "launcher_supervisor_reattach", "source": "launcher_api", "noBrowser": False},
        "launcher_api",
    )
    assert "launcher.supervisor.reattach.requested" in [event[2] for event in events]
    assert "launcher.supervisor.reattach.accepted" in [event[2] for event in events]


def test_launcher_supervisor_reattach_blocks_when_state_is_incomplete(tmp_path, monkeypatch):
    launcher_state_path = tmp_path / ".runtime" / "launcher" / "state.json"
    launcher_state_path.parent.mkdir(parents=True, exist_ok=True)
    launcher_state_path.write_text(json.dumps({"supervisorPid": 0}), encoding="utf-8")
    events = []
    monkeypatch.setattr(launcher_service, "LAUNCHER_STATE_PATH", launcher_state_path)
    monkeypatch.setattr(launcher_service, "_is_process_alive", lambda pid: False)
    monkeypatch.setattr(
        launcher_service,
        "get_runtime_summary",
        lambda: {
            "workbench": {
                "observedState": "closed",
                "backendAlive": False,
                "backendHealthy": False,
                "browserWindowAlive": False,
            }
        },
    )
    monkeypatch.setattr(launcher_service, "ensure_daemon_running", lambda: (_ for _ in ()).throw(AssertionError("must not queue")))
    monkeypatch.setattr(
        launcher_service,
        "record_runtime_scene_event",
        lambda component, phase, event_code, **kwargs: events.append((component, phase, event_code, kwargs)),
        raising=False,
    )

    payload = launcher_service.request_launcher_supervisor_reattach()

    assert payload["accepted"] is False
    assert payload["operation"] == "supervisor_reattach"
    assert "session_id_missing" in payload["blockers"]
    assert "runtime_scene_missing" in payload["blockers"]
    assert "backend_not_alive" in payload["blockers"]
    assert "launcher.supervisor.reattach.blocked" in [event[2] for event in events]
