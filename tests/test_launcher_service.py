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
