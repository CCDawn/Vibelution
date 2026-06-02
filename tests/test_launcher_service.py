from core.web.services import launcher_service


def test_launcher_status_exposes_guardian_adapter_migration_contract(monkeypatch):
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

    payload = launcher_service.get_launcher_status()

    guardian = payload["guardianAdapter"]
    assert guardian["schemaVersion"] == 1
    assert guardian["mode"] == "adapter_migration"
    assert guardian["targetMode"] == "standalone_launcher_guardian"
    assert guardian["ownedCount"] >= 2
    assert guardian["adapterCount"] >= 3
    responsibilities = {item["id"]: item for item in guardian["responsibilities"]}
    assert responsibilities["project_bundle_lifecycle"]["owner"] == "launcher_api"
    assert responsibilities["runtime_manager_daemon"]["status"] == "running"
    assert responsibilities["desktop_supervisor"]["adapter"] == "vibelution_launcher.ps1"
    assert responsibilities["backend_process"]["status"] == "running"
    assert responsibilities["browser_window"]["status"] == "managed"
    assert responsibilities["runtime_scene_logging"]["owner"] == "runtime_scene_service"
