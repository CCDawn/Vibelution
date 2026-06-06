import json
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from core.launcher import app as launcher_app
from core.launcher import service as launcher_service
from core.runtime_manager import work_run_store
from core.runtime_manager.work_run_store import WorkRunStore


def test_standalone_launcher_app_exposes_project_lifecycle_routes(monkeypatch):
    calls = []
    monkeypatch.setattr(
        launcher_service,
        "request_launcher_start",
        lambda: calls.append("start") or {"accepted": True, "operation": "start", "launcherMode": "standalone_control_plane"},
    )
    client = TestClient(launcher_app.create_launcher_app())

    response = client.post("/api/project/start")

    assert response.status_code == 202
    assert response.json()["operation"] == "start"
    assert calls == ["start"]


def test_standalone_launcher_app_exposes_project_status_route(monkeypatch):
    monkeypatch.setattr(
        launcher_service,
        "get_launcher_status",
        lambda: {"launcher": {"mode": "standalone_control_plane"}, "projectBundle": {"observedState": "closed"}},
    )
    client = TestClient(launcher_app.create_launcher_app())

    response = client.get("/api/project/status")

    assert response.status_code == 200
    assert response.json()["launcher"]["mode"] == "standalone_control_plane"


def test_standalone_launcher_app_serves_health_token_and_launcher_shell(monkeypatch, tmp_path):
    dist = tmp_path / "web" / "dist"
    dist.mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><title>Launcher</title>", encoding="utf-8")
    (dist / "asset.txt").write_text("asset-ok", encoding="utf-8")
    monkeypatch.setattr(launcher_app, "WEB_DIST", dist)
    monkeypatch.setattr(launcher_app, "WEB_INDEX", dist / "index.html")
    client = TestClient(launcher_app.create_launcher_app())

    health = client.get("/api/health")
    token = client.get("/api/control-token")
    shell = client.get("/launcher")
    asset = client.get("/asset.txt")

    assert health.status_code == 200
    assert health.json()["service"] == "launcher"
    assert token.status_code == 200
    assert token.json()["controlToken"]
    assert shell.status_code == 200
    assert "Launcher" in shell.text
    assert asset.status_code == 200
    assert asset.text == "asset-ok"


def test_standalone_launcher_app_reports_missing_shell_when_index_is_absent(monkeypatch, tmp_path):
    dist = tmp_path / "web" / "dist"
    dist.mkdir(parents=True)
    monkeypatch.setattr(launcher_app, "WEB_DIST", dist)
    monkeypatch.setattr(launcher_app, "WEB_INDEX", dist / "index.html")
    client = TestClient(launcher_app.create_launcher_app())

    response = client.get("/launcher")

    assert response.status_code == 503
    assert "not been built" in response.json()["message"]


def test_launcher_status_is_independent_from_web_runtime_service(monkeypatch, tmp_path):
    import core.web.services.runtime_service as runtime_service

    def fail_web_runtime_summary():
        raise AssertionError("standalone Launcher status must not call Web runtime_service")

    monkeypatch.setattr(runtime_service, "get_runtime_summary", fail_web_runtime_summary)
    monkeypatch.setattr(launcher_service, "STATE_PATH", tmp_path / ".runtime" / "runtime-manager" / "state.json")
    monkeypatch.setattr(launcher_service, "INBOX_DIR", tmp_path / ".runtime" / "runtime-manager" / "inbox")
    monkeypatch.setattr(launcher_service, "PROCESSING_DIR", tmp_path / ".runtime" / "runtime-manager" / "processing")
    monkeypatch.setattr(launcher_service, "RESULTS_DIR", tmp_path / ".runtime" / "runtime-manager" / "results")
    monkeypatch.setattr(launcher_service, "EVENTS_PATH", tmp_path / ".runtime" / "runtime-manager" / "events.jsonl")
    monkeypatch.setattr(launcher_service, "LAUNCHER_STATE_PATH", tmp_path / ".runtime" / "launcher" / "state.json")
    monkeypatch.setattr(launcher_service, "load_state", lambda: {})
    monkeypatch.setattr(launcher_service, "load_pid", lambda: 0)
    monkeypatch.setattr(launcher_service, "_is_process_alive", lambda pid: False)
    monkeypatch.setattr(
        launcher_service,
        "observe_workbench",
        lambda: {
            "observedState": "closed",
            "sessionRole": "workbench",
            "backendAlive": False,
            "backendHealthy": False,
            "browserWindowAlive": False,
            "browserManaged": True,
            "url": "http://127.0.0.1:8000",
        },
    )

    payload = launcher_service.get_launcher_status()

    assert payload["launcher"]["mode"] == "standalone_control_plane"
    assert payload["launcher"]["controlPlane"]["independent"] is True
    assert payload["projectBundle"]["observedState"] == "closed"


def test_standalone_launcher_active_work_guard_reads_runtime_manager_store(tmp_path, monkeypatch):
    work_runs_dir = tmp_path / ".runtime" / "runtime-manager" / "work_runs"
    store = WorkRunStore(root=work_runs_dir)
    store.persist_snapshot(
        "chat_turn",
        {
            "runId": "chat-turn-live",
            "runKind": "chat_turn",
            "sessionId": "session-live",
            "status": "running",
        },
        active_run_id="chat-turn-live",
    )
    events = []
    monkeypatch.setattr(work_run_store, "WORK_RUNS_DIR", work_runs_dir)
    monkeypatch.setattr(launcher_service, "ensure_daemon_running", lambda: (_ for _ in ()).throw(AssertionError("must not queue")))
    monkeypatch.setattr(
        launcher_service,
        "append_runtime_manager_file_event",
        lambda event_code, payload, **kwargs: events.append((event_code, payload)) or "2026-06-06T00:00:00+00:00",
    )

    try:
        launcher_service.request_launcher_restart()
    except launcher_service.LauncherActiveWorkBlocked as exc:
        blocked = exc
    else:
        raise AssertionError("expected active work to block restart")

    assert blocked.message == "有进行中的任务，无法重启 Vibelution。请等待任务完成或先停止任务。"
    assert blocked.active_work_runs == [
        {
            "kind": "chat_turn",
            "runId": "chat-turn-live",
            "status": "running",
            "sessionId": "session-live",
        }
    ]
    assert "launcher.bundle.restart.blocked_active_work" in [event[0] for event in events]


def test_launcher_active_work_guard_scans_parallel_chat_turn_snapshots(tmp_path, monkeypatch):
    work_runs_dir = tmp_path / ".runtime" / "runtime-manager" / "work_runs"
    store = WorkRunStore(root=work_runs_dir)
    store.persist_snapshot(
        "chat_turn",
        {
            "runId": "chat-turn-alpha",
            "runKind": "chat_turn",
            "sessionId": "session-alpha",
            "status": "running",
        },
        active_run_id="chat-turn-alpha",
    )
    store.persist_snapshot(
        "chat_turn",
        {
            "runId": "chat-turn-beta",
            "runKind": "chat_turn",
            "sessionId": "session-beta",
            "status": "running",
        },
        active_run_id="chat-turn-alpha",
    )
    monkeypatch.setattr(work_run_store, "WORK_RUNS_DIR", work_runs_dir)

    active = launcher_service.launcher_active_work_runs()

    assert {item["runId"] for item in active} == {"chat-turn-alpha", "chat-turn-beta"}


def test_launcher_active_work_guard_ignores_stale_non_current_snapshots(tmp_path, monkeypatch):
    work_runs_dir = tmp_path / ".runtime" / "runtime-manager" / "work_runs"
    stale_at = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    store = WorkRunStore(root=work_runs_dir)
    store.persist_snapshot(
        "chat_turn",
        {
            "runId": "chat-turn-stale",
            "runKind": "chat_turn",
            "sessionId": "session-stale",
            "status": "running",
            "updatedAt": stale_at,
        },
        active_run_id="",
    )
    monkeypatch.setattr(work_run_store, "WORK_RUNS_DIR", work_runs_dir)

    assert launcher_service.launcher_active_work_runs() == []


def test_launcher_active_work_guard_keeps_current_active_snapshot_even_if_old(tmp_path, monkeypatch):
    work_runs_dir = tmp_path / ".runtime" / "runtime-manager" / "work_runs"
    stale_at = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    store = WorkRunStore(root=work_runs_dir)
    store.persist_snapshot(
        "chat_turn",
        {
            "runId": "chat-turn-current",
            "runKind": "chat_turn",
            "sessionId": "session-current",
            "status": "running",
            "updatedAt": stale_at,
        },
        active_run_id="chat-turn-current",
    )
    monkeypatch.setattr(work_run_store, "WORK_RUNS_DIR", work_runs_dir)

    assert launcher_service.launcher_active_work_runs()[0]["runId"] == "chat-turn-current"


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
    monkeypatch.setattr(launcher_service, "LAUNCHER_STATE_PATH", launcher_state_path)
    monkeypatch.setattr(
        launcher_service,
        "load_state",
        lambda: {
            "runtimeState": "idle",
            "managerPid": 2001,
            "stateVersion": 3,
            "workbench": {
                "desiredState": "open",
                "observedState": "open",
                "phase": "steady",
                "url": "http://127.0.0.1:8000",
            },
        },
    )
    monkeypatch.setattr(launcher_service, "load_pid", lambda: 2001)
    monkeypatch.setattr(launcher_service, "_is_process_alive", lambda pid: int(pid) in {2001, 4444})
    monkeypatch.setattr(
        launcher_service,
        "observe_workbench",
        lambda: {
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
        },
    )

    payload = launcher_service.get_launcher_status()

    guardian = payload["guardianAdapter"]
    assert guardian["schemaVersion"] == 1
    assert guardian["mode"] == "standalone_control_plane"
    assert guardian["targetMode"] == "standalone_launcher_guardian"
    assert guardian["ownedCount"] >= 3
    assert guardian["adapterCount"] >= 2
    assert guardian["supervisor"]["pid"] == 4444
    assert guardian["supervisor"]["alive"] is True
    assert guardian["supervisor"]["status"] == "running"
    assert guardian["supervisor"]["stdoutPath"].endswith("raw/supervisor.log")
    assert guardian["supervisor"]["stderrPath"].endswith("raw/supervisor.stderr.log")
    assert guardian["supervisor"]["runtimeSceneId"] == "scene-a"
    responsibilities = {item["id"]: item for item in guardian["responsibilities"]}
    assert responsibilities["project_bundle_lifecycle"]["owner"] == "standalone_launcher"
    assert responsibilities["runtime_manager_daemon"]["status"] == "running"
    assert responsibilities["desktop_supervisor"]["adapter"] == "vibelution_launcher"
    assert responsibilities["desktop_supervisor"]["status"] == "running"
    assert responsibilities["backend_process"]["status"] == "running"
    assert responsibilities["browser_window"]["status"] == "managed"
    assert responsibilities["runtime_scene_logging"]["owner"] == "runtime_manager_events"


def test_launcher_status_exposes_control_plane_evidence(tmp_path, monkeypatch):
    runtime_dir = tmp_path / ".runtime" / "runtime-manager"
    inbox_dir = runtime_dir / "inbox"
    processing_dir = runtime_dir / "processing"
    results_dir = runtime_dir / "results"
    for directory in (inbox_dir, processing_dir, results_dir):
        directory.mkdir(parents=True, exist_ok=True)
    state_path = runtime_dir / "state.json"
    events_path = runtime_dir / "events.jsonl"
    state_path.write_text(
        json.dumps(
            {
                "stateVersion": 7,
                "runtimeState": "running",
                "managerPid": 3210,
                "updatedAt": "2026-06-03T00:00:00+00:00",
                "command": {
                    "activeCommandId": "cmd-active",
                    "activeType": "open_workbench",
                    "requestedBy": "launcher_api",
                    "startedAt": "2026-06-03T00:00:01+00:00",
                    "noBrowser": False,
                },
            }
        ),
        encoding="utf-8",
    )
    (inbox_dir / "cmd-pending.json").write_text(
        json.dumps(
            {
                "commandId": "cmd-pending",
                "type": "restart_workbench",
                "requestedBy": "launcher_api",
                "requestedAt": "2026-06-03T00:00:02+00:00",
                "args": {
                    "reason": "launcher_restart",
                    "source": "launcher_api",
                    "deferredUntilActiveWorkClear": True,
                    "queuedBecauseActiveWork": True,
                    "queuedActiveWorkCount": 2,
                    "deferUntil": "2026-06-03T00:00:12+00:00",
                    "activeWorkDeferCount": 1,
                    "lastActiveWorkCount": 2,
                },
            }
        ),
        encoding="utf-8",
    )
    (processing_dir / "cmd-processing.json").write_text(
        json.dumps({"commandId": "cmd-processing", "type": "close_workbench", "requestedBy": "web_ui"}),
        encoding="utf-8",
    )
    (results_dir / "cmd-result.json").write_text(
        json.dumps(
            {
                "commandId": "cmd-result",
                "ok": True,
                "completed": True,
                "message": "Workbench opened.",
                "stateVersion": 8,
            }
        ),
        encoding="utf-8",
    )
    events_path.write_text(
        "\n".join(
            [
                json.dumps({"type": "command.completed", "at": "2026-06-03T00:00:03+00:00", "payload": {"commandId": "cmd-result", "ok": True, "message": "done"}}),
                json.dumps({"type": "daemon.stopped", "at": "2026-06-03T00:00:04+00:00", "payload": {"commandId": "cmd-stop"}}),
                json.dumps(
                    {
                        "type": "command_queue.processing_recovered",
                        "at": "2026-06-03T00:00:05+00:00",
                        "payload": {"commandId": "cmd-recovered", "type": "restart_workbench"},
                    }
                ),
                json.dumps(
                    {
                        "type": "command_queue.command_result_written",
                        "at": "2026-06-03T00:00:06+00:00",
                        "payload": {"commandId": "cmd-recovered", "ok": True, "message": "Workbench restarted."},
                    }
                ),
            ]
        ),
        encoding="utf-8",
    )
    (results_dir / "cmd-recovered.json").write_text(
        json.dumps(
            {
                "commandId": "cmd-recovered",
                "ok": True,
                "completed": True,
                "message": "Workbench restarted.",
                "stateVersion": 9,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(launcher_service, "STATE_PATH", state_path)
    monkeypatch.setattr(launcher_service, "INBOX_DIR", inbox_dir)
    monkeypatch.setattr(launcher_service, "PROCESSING_DIR", processing_dir)
    monkeypatch.setattr(launcher_service, "RESULTS_DIR", results_dir)
    monkeypatch.setattr(launcher_service, "EVENTS_PATH", events_path)
    monkeypatch.setattr(launcher_service, "LAUNCHER_STATE_PATH", tmp_path / ".runtime" / "launcher" / "state.json")
    monkeypatch.setattr(launcher_service, "_is_process_alive", lambda pid: False)
    monkeypatch.setattr(launcher_service, "load_state", lambda: json.loads(state_path.read_text(encoding="utf-8")))
    monkeypatch.setattr(launcher_service, "load_pid", lambda: 3210)
    monkeypatch.setattr(launcher_service, "observe_workbench", lambda: {})

    payload = launcher_service.get_launcher_status()

    evidence = payload["controlPlaneEvidence"]
    assert evidence["schemaVersion"] == 1
    assert evidence["state"]["stateVersion"] == 7
    assert evidence["state"]["activeCommand"]["commandId"] == "cmd-active"
    assert evidence["queue"]["pendingCount"] == 1
    assert evidence["queue"]["processingCount"] == 1
    assert evidence["queue"]["pending"][0]["reason"] == "launcher_restart"
    assert evidence["queue"]["pending"][0]["deferredUntilActiveWorkClear"] is True
    assert evidence["restartQueue"]["pending"] is True
    assert evidence["restartQueue"]["pendingCount"] == 1
    assert evidence["restartQueue"]["commandId"] == "cmd-pending"
    assert evidence["restartQueue"]["lastActiveWorkCount"] == 2
    assert "2" in evidence["restartQueue"]["statusLine"]
    assert evidence["results"]["recent"][0]["commandId"] in {"cmd-result", "cmd-recovered"}
    assert evidence["events"]["recent"][0]["type"] == "command_queue.command_result_written"
    assert evidence["recovery"]["active"] is True
    assert evidence["recovery"]["commandId"] == "cmd-recovered"
    assert evidence["recovery"]["commandType"] == "restart_workbench"
    assert evidence["recovery"]["resultOk"] is True
    assert "Workbench restarted." in evidence["recovery"]["statusLine"]


def test_launcher_status_shows_control_surface_when_project_window_is_closed(tmp_path, monkeypatch):
    launcher_state_path = tmp_path / ".runtime" / "launcher" / "state.json"
    launcher_state_path.parent.mkdir(parents=True, exist_ok=True)
    launcher_state_path.write_text(
        json.dumps(
            {
                "sessionRole": "launcher_control_surface",
                "url": "http://127.0.0.1:8000",
                "backendPid": 10952,
                "browserManaged": False,
                "browserWindowPid": 0,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(launcher_service, "LAUNCHER_STATE_PATH", launcher_state_path)
    monkeypatch.setattr(launcher_service, "_is_process_alive", lambda pid: False)
    monkeypatch.setattr(
        launcher_service,
        "load_state",
        lambda: {
            "runtimeState": "running",
            "managerPid": 3210,
            "stateVersion": 10,
            "workbench": {
                "sessionRole": "launcher_control_surface",
                "desiredState": "closed",
                "observedState": "closed",
                "phase": "steady",
                "url": "http://127.0.0.1:8000",
            },
        },
    )
    monkeypatch.setattr(launcher_service, "load_pid", lambda: 3210)
    monkeypatch.setattr(
        launcher_service,
        "observe_workbench",
        lambda: {
            "sessionRole": "launcher_control_surface",
            "observedState": "closed",
            "backendPid": 10952,
            "backendAlive": False,
            "backendHealthy": False,
            "backendPort": 8000,
            "backendPortListening": False,
            "browserManaged": False,
            "browserWindowPid": 0,
            "browserWindowAlive": False,
            "url": "http://127.0.0.1:8000",
        },
    )

    payload = launcher_service.get_launcher_status()

    bundle = payload["projectBundle"]
    assert bundle["sessionRole"] == "launcher_control_surface"
    assert bundle["desiredState"] == "closed"
    assert bundle["observedState"] == "closed"
    assert bundle["browser"]["managed"] is False
    assert "Launcher 控制台正在运行" in bundle["statusLine"]


def test_launcher_status_keeps_project_open_when_launcher_control_surface_stays_alive(tmp_path, monkeypatch):
    launcher_state_path = tmp_path / ".runtime" / "launcher" / "state.json"
    launcher_state_path.parent.mkdir(parents=True, exist_ok=True)
    launcher_state_path.write_text(
        json.dumps(
            {
                "sessionRole": "launcher_control_surface",
                "url": "http://127.0.0.1:8000",
                "backendPid": 10952,
                "browserManaged": False,
                "browserWindowPid": 0,
                "workbenchBrowserWindowPid": 4001,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(launcher_service, "LAUNCHER_STATE_PATH", launcher_state_path)
    monkeypatch.setattr(launcher_service, "_is_process_alive", lambda pid: int(pid) in {3210, 4001, 10952})
    monkeypatch.setattr(
        launcher_service,
        "load_state",
        lambda: {
            "runtimeState": "running",
            "managerPid": 3210,
            "stateVersion": 10,
            "workbench": {
                "sessionRole": "launcher_control_surface",
                "desiredState": "closed",
                "observedState": "closed",
                "phase": "steady",
                "url": "http://127.0.0.1:8000",
            },
        },
    )
    monkeypatch.setattr(launcher_service, "load_pid", lambda: 3210)
    monkeypatch.setattr(
        launcher_service,
        "observe_workbench",
        lambda: {
            "sessionRole": "launcher_control_surface",
            "observedState": "closed",
            "backendPid": 10952,
            "backendAlive": True,
            "backendHealthy": True,
            "backendPort": 8000,
            "backendPortListening": True,
            "browserManaged": True,
            "browserWindowPid": 4001,
            "browserWindowAlive": True,
            "url": "http://127.0.0.1:8000",
        },
    )

    payload = launcher_service.get_launcher_status()

    bundle = payload["projectBundle"]
    assert bundle["sessionRole"] == "workbench"
    assert bundle["desiredState"] == "open"
    assert bundle["observedState"] == "open"
    assert bundle["backend"]["alive"] is True
    assert bundle["browser"]["alive"] is True
    assert bundle["statusLine"] == "工作台正在运行。"


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
        "load_state",
        lambda: {
            "workbench": {
                "desiredState": "open",
                "observedState": "open",
                "phase": "steady",
            }
        },
    )
    monkeypatch.setattr(
        launcher_service,
        "observe_workbench",
        lambda: {
            "observedState": "open",
            "backendAlive": True,
            "backendHealthy": True,
            "browserWindowAlive": True,
        },
    )
    monkeypatch.setattr(launcher_service, "load_pid", lambda: 0)
    monkeypatch.setattr(launcher_service, "ensure_daemon_running", lambda: calls.append(("ensure",)))
    monkeypatch.setattr(
        launcher_service,
        "submit_command",
        lambda command_type, *, args, requested_by: calls.append((command_type, args, requested_by)) or {"commandId": "cmd-reattach"},
    )
    monkeypatch.setattr(
        launcher_service,
        "append_runtime_manager_file_event",
        lambda event_code, payload, **kwargs: events.append((event_code, payload)),
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
    assert "launcher.supervisor.reattach.requested" in [event[0] for event in events]
    assert "launcher.supervisor.reattach.accepted" in [event[0] for event in events]


def test_launcher_supervisor_reattach_blocks_when_state_is_incomplete(tmp_path, monkeypatch):
    launcher_state_path = tmp_path / ".runtime" / "launcher" / "state.json"
    launcher_state_path.parent.mkdir(parents=True, exist_ok=True)
    launcher_state_path.write_text(json.dumps({"supervisorPid": 0}), encoding="utf-8")
    events = []
    monkeypatch.setattr(launcher_service, "LAUNCHER_STATE_PATH", launcher_state_path)
    monkeypatch.setattr(launcher_service, "_is_process_alive", lambda pid: False)
    monkeypatch.setattr(launcher_service, "load_state", lambda: {"workbench": {"observedState": "closed"}})
    monkeypatch.setattr(
        launcher_service,
        "observe_workbench",
        lambda: {
            "observedState": "closed",
            "backendAlive": False,
            "backendHealthy": False,
            "browserWindowAlive": False,
        },
    )
    monkeypatch.setattr(launcher_service, "ensure_daemon_running", lambda: (_ for _ in ()).throw(AssertionError("must not queue")))
    monkeypatch.setattr(
        launcher_service,
        "append_runtime_manager_file_event",
        lambda event_code, payload, **kwargs: events.append((event_code, payload)),
    )

    payload = launcher_service.request_launcher_supervisor_reattach()

    assert payload["accepted"] is False
    assert payload["operation"] == "supervisor_reattach"
    assert "session_id_missing" in payload["blockers"]
    assert "runtime_scene_missing" in payload["blockers"]
    assert "backend_not_alive" in payload["blockers"]
    assert "launcher.supervisor.reattach.blocked" in [event[0] for event in events]
