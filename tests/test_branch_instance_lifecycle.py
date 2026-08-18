from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from core.launcher import app as launcher_app
from core.launcher import branch_instance_lifecycle as lifecycle
from core.launcher import service as launcher_service
from core.launcher.slot_identity import data_home_for_project, slot_id_for_project
from core.runtime_manager import instances_registry as registry


@pytest.fixture
def registry_path(tmp_path, monkeypatch):
    path = tmp_path / "Vibelution" / "instances.json"
    monkeypatch.setattr(registry, "instances_registry_path", lambda: path)
    return path


def _item(**overrides):
    item = {
        "id": "worktree:task",
        "kind": "worktree",
        "branch": "codex/task",
        "path": r"C:\repo\.worktrees\task",
        "current": False,
        "checkedOut": True,
        "alive": False,
        "port": 0,
        "controlPort": 0,
        "url": "",
    }
    item.update(overrides)
    return item


def test_overlay_uses_live_current_ports_and_registry_reservations(registry_path):
    registry.upsert_instance(
        "worktree:task",
        projectRoot=r"C:\repo\.worktrees\task",
        port=8003,
        controlPort=8768,
        url="http://127.0.0.1:8003",
    )
    payload = {
        "items": [
            {"id": "main", "kind": "main", "path": r"C:\repo", "current": True, "port": 0},
            {
                "id": "worktree:task",
                "kind": "worktree",
                "path": r"C:\repo\.worktrees\task",
                "current": False,
                "port": 0,
            },
        ]
    }

    overlayed = lifecycle.overlay_instance_ports(
        payload,
        launcher_state={
            "launcherControlPort": 8765,
            "workbench": {"backendPort": 8000, "url": "http://127.0.0.1:8000"},
        },
    )

    current, other = overlayed["items"]
    assert current["port"] == 8000
    assert current["controlPort"] == 8765
    assert current["url"] == "http://127.0.0.1:8000"
    assert other["port"] == 8003
    assert other["controlPort"] == 8768
    assert other["url"] == "http://127.0.0.1:8003"
    assert current["slotId"]
    assert current["slotKey"]
    assert current["dataHome"]
    assert other["slotId"]
    assert other["slotId"] != current["slotId"]
    assert other["dataHome"] != current["dataHome"]


def test_overlay_copies_live_window_pid_for_isolated_rows(registry_path):
    registry.upsert_instance(
        "worktree:task",
        projectRoot=r"C:\repo\.worktrees\task",
        port=8003,
        controlPort=8768,
        url="http://127.0.0.1:8003",
        windowPid=os.getpid(),
        windowTitle="branch+task 台",
    )
    payload = {
        "items": [
            {"id": "main", "kind": "main", "path": r"C:\repo", "current": True, "port": 0},
            {
                "id": "worktree:task",
                "kind": "worktree",
                "path": r"C:\repo\.worktrees\task",
                "current": False,
                "port": 0,
                "pids": {"backend": 0, "window": 0, "manager": 0},
            },
        ]
    }

    overlayed = lifecycle.overlay_instance_ports(
        payload,
        launcher_state={
            "launcherControlPort": 8765,
            "workbench": {"backendPort": 8000, "url": "http://127.0.0.1:8000"},
        },
    )

    _current, other = overlayed["items"]
    assert other["pids"]["window"] == os.getpid()


def test_retired_and_local_branch_cannot_start():
    with pytest.raises(lifecycle.BranchInstanceLifecycleError) as retired:
        lifecycle.assert_instance_operable(_item(kind="retired", checkedOut=False), "start")
    assert retired.value.code == "instance_not_startable"

    with pytest.raises(lifecycle.BranchInstanceLifecycleError) as local:
        lifecycle.assert_instance_operable(_item(kind="local_branch", checkedOut=False, path=""), "start")
    assert local.value.code == "instance_not_startable"


def test_isolated_start_allocates_ports_and_spawns_without_touching_current(registry_path, tmp_path, monkeypatch):
    monkeypatch.setattr(registry, "_port_is_free", lambda port, host: True)
    monkeypatch.setattr(lifecycle, "current_live_ports", lambda launcher_state=None: {8000, 8765})
    worktree = tmp_path / "task"
    worktree.mkdir()
    (worktree / "scripts").mkdir()
    (worktree / "scripts" / "vibelution_launcher.py").write_text("# launcher\n", encoding="utf-8")
    calls: list[tuple] = []

    def fake_spawn(root, action, backend_port, control_port, **kwargs):
        calls.append((Path(root), action, backend_port, control_port, kwargs))
        return {"returncode": 0}

    response = lifecycle.run_isolated_operation(
        _item(path=str(worktree)),
        "start",
        runner=fake_spawn,
    )

    assert response["accepted"] is True
    assert response["mode"] == "isolated_worktree"
    assert response["port"] == 8001
    assert response["controlPort"] == 8766
    assert calls == [(worktree, "start", 8001, 8766, {"short_name": "", "detach": True})]
    stored = registry.get_instance("worktree:task")
    assert stored["status"] == "starting"
    assert stored["desiredState"] == "open"
    assert stored["generation"] == 1
    assert stored["commandId"]
    assert stored["port"] == 8001
    assert stored["controlPort"] == 8766
    assert stored["slotId"] == slot_id_for_project(worktree)
    assert stored["dataHome"] == str(data_home_for_project(worktree))
    assert response["generation"] == 1


def test_isolated_stop_reuses_reserved_ports(registry_path, tmp_path):
    worktree = tmp_path / "task"
    worktree.mkdir()
    registry.upsert_instance("worktree:task", port=8004, controlPort=8769, projectRoot=str(worktree))
    calls: list[tuple] = []

    def fake_spawn(root, action, backend_port, control_port, **kwargs):
        calls.append((action, backend_port, control_port))
        return {"returncode": 0}

    response = lifecycle.run_isolated_operation(
        _item(path=str(worktree), port=8004, controlPort=8769),
        "stop",
        runner=fake_spawn,
    )

    assert response["accepted"] is True
    assert calls == [("stop", 8004, 8769)]
    assert registry.get_instance("worktree:task")["status"] == "closed"


def test_isolated_stop_clears_failed_registry_when_spawn_fails(registry_path, tmp_path):
    worktree = tmp_path / "task"
    worktree.mkdir()
    state_path = worktree / ".runtime" / "launcher" / "state.json"
    state_path.parent.mkdir(parents=True)
    state_path.write_text(
        '{"workbench": {"desiredState": "open", "observedState": "closed", "phase": "failed", "failureMessage": "上次启动失败"}}',
        encoding="utf-8",
    )
    registry.upsert_instance(
        "worktree:task",
        port=8004,
        controlPort=8769,
        projectRoot=str(worktree),
        status="failed",
    )

    def boom(*args, **kwargs):
        raise lifecycle.BranchInstanceLifecycleError("instance_lifecycle_failed", "stop failed")

    response = lifecycle.run_isolated_operation(
        _item(path=str(worktree), port=8004, controlPort=8769, alive=False),
        "stop",
        runner=boom,
    )

    assert response["accepted"] is True
    assert registry.get_instance("worktree:task")["status"] == "closed"
    payload = json.loads(state_path.read_text(encoding="utf-8"))
    assert payload["workbench"]["desiredState"] == "closed"
    assert payload["workbench"]["observedState"] == "closed"
    assert payload["workbench"]["phase"] == "steady"
    assert payload["workbench"]["failureMessage"] == ""


def test_isolated_stop_clears_failed_registry_for_retired_leftover(registry_path, tmp_path):
    missing = tmp_path / "gone-task"
    registry.upsert_instance(
        "worktree:task",
        port=8004,
        controlPort=8769,
        projectRoot=str(missing),
        status="failed",
    )

    response = lifecycle.run_isolated_operation(
        _item(
            id="retired:task",
            kind="retired",
            path=str(missing),
            checkedOut=False,
            alive=False,
            runtime={
                "lifecycleState": "error",
                "backend": {"alive": False, "healthy": False, "listening": False},
                "window": {"open": False},
            },
        ),
        "stop",
    )

    assert response["accepted"] is True
    assert response["instanceId"] == "worktree:task"
    assert registry.get_instance("worktree:task")["status"] == "closed"
    assert registry.get_instance("retired:task") == {}


def test_spawn_uses_pythonw_and_hidden_console(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "AppData" / "Local"))
    worktree = tmp_path / "task"
    scripts = worktree / "scripts"
    scripts.mkdir(parents=True)
    (scripts / "vibelution_launcher.py").write_text("# launcher\n", encoding="utf-8")
    pythonw = worktree / ".venv" / "Scripts" / "pythonw.exe"
    pythonw.parent.mkdir(parents=True)
    pythonw.write_text("", encoding="utf-8")
    captured: dict = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs

        class Result:
            returncode = 0
            stdout = "ok"
            stderr = ""

        return Result()

    monkeypatch.setattr(lifecycle.subprocess, "run", fake_run)

    result = lifecycle.spawn_worktree_launcher(worktree, "start", 8002, 8767)

    assert captured["command"][0].lower().endswith("pythonw.exe")
    assert captured["command"][1].endswith("vibelution_launcher.py")
    assert captured["command"][2:6] == ["--action", "start", "--port", "8002"]
    assert captured["command"][-1] == "--no-browser"
    assert captured["kwargs"]["cwd"] == str(worktree)
    assert captured["kwargs"]["env"]["VIBELUTION_PORT"] == "8002"
    assert captured["kwargs"]["env"]["VIBELUTION_LAUNCHER_PORT"] == "8767"
    assert captured["kwargs"]["env"]["VIBELUTION_DATA_HOME"] == str(data_home_for_project(worktree))
    assert captured["kwargs"]["env"]["VIBELUTION_WORKSPACE_ROOT"] == str(worktree.resolve())
    assert (tmp_path / "AppData" / "Local" / "Vibelution" / "slots").exists()
    if lifecycle.os.name == "nt":
        assert captured["kwargs"]["creationflags"] & lifecycle.subprocess.CREATE_NO_WINDOW
    assert result["returncode"] == 0


def test_resolve_no_console_python_prefers_supervisor_over_worktree_venv(tmp_path):
    worktree = tmp_path / "task"
    leftover = worktree / ".venv" / "Scripts" / "pythonw.exe"
    leftover.parent.mkdir(parents=True)
    leftover.write_text("", encoding="utf-8")
    supervisor_pythonw = Path(sys.executable).with_name("pythonw.exe")
    if not supervisor_pythonw.is_file():
        pytest.skip("current interpreter has no pythonw.exe sibling")
    resolved = Path(lifecycle.resolve_no_console_python(worktree))
    assert resolved == supervisor_pythonw.resolve()
    assert resolved != leftover.resolve()


def test_current_row_delegates_to_existing_start(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(
        lifecycle,
        "resolve_branch_instance",
        lambda instance_id: _item(id="main", kind="main", current=True, path=r"C:\repo"),
    )
    monkeypatch.setattr(
        launcher_service,
        "request_launcher_start",
        lambda: calls.append("start")
        or {"accepted": True, "operation": "start", "mode": "runtime_manager", "commandId": "cmd-1"},
    )

    response = launcher_service.request_branch_instance_operation("main", "start")

    assert calls == ["start"]
    assert response["operation"] == "start"
    assert response["instanceId"] == "main"
    assert response["mode"] == "runtime_manager"


def test_standalone_launcher_exposes_branch_instance_lifecycle_routes(monkeypatch):
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        launcher_service,
        "request_branch_instance_operation",
        lambda instance_id, operation, request_audit=None: calls.append((instance_id, operation))
        or {
            "accepted": True,
            "operation": operation,
            "instanceId": instance_id,
            "mode": "isolated_worktree",
            "port": 8001,
        },
    )
    client = TestClient(launcher_app.create_launcher_app())

    response = client.post(
        "/api/launcher/branch-instances/start",
        json={"instanceId": "worktree:task"},
    )

    assert response.status_code == 202
    assert response.json()["instanceId"] == "worktree:task"
    assert response.json()["port"] == 8001
    assert calls == [("worktree:task", "start")]


def test_standalone_launcher_maps_not_startable_to_409(monkeypatch):
    def fail(instance_id, operation, request_audit=None):
        raise lifecycle.BranchInstanceLifecycleError("instance_not_startable", "未打开")

    monkeypatch.setattr(launcher_service, "request_branch_instance_operation", fail)
    client = TestClient(launcher_app.create_launcher_app())

    response = client.post(
        "/api/launcher/branch-instances/start",
        json={"instanceId": "branch:feature"},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "instance_not_startable"


def test_isolated_start_records_named_window_pid(registry_path, tmp_path, monkeypatch):
    monkeypatch.setattr(registry, "_port_is_free", lambda port, host: True)
    monkeypatch.setattr(lifecycle, "current_live_ports", lambda launcher_state=None: {8000, 8765})
    worktree = tmp_path / "task"
    worktree.mkdir()
    (worktree / "scripts").mkdir()
    (worktree / "scripts" / "vibelution_launcher.py").write_text("# launcher\n", encoding="utf-8")
    monkeypatch.setattr(
        lifecycle,
        "open_isolated_workbench_window",
        lambda item, **kwargs: {
            "provider": "electron",
            "windowPid": 4242,
            "title": "branch+task 台",
        },
    )

    response = lifecycle.run_isolated_operation(
        _item(path=str(worktree), shortName="branch+task", workbenchTitle="branch+task 台"),
        "start",
        runner=lambda *args, **kwargs: {"returncode": 0},
    )

    stored = registry.get_instance("worktree:task")
    assert response["accepted"] is True
    assert stored["status"] == "starting"
    assert int(stored.get("windowPid") or 0) == 0


def test_isolated_start_reopens_window_when_backend_already_alive(registry_path, tmp_path, monkeypatch):
    worktree = tmp_path / "task"
    worktree.mkdir()
    opened: list[dict] = []

    def fake_open(item, **kwargs):
        opened.append(dict(item))
        return {"provider": "electron", "windowPid": 7, "title": "branch+task 台"}

    monkeypatch.setattr(lifecycle, "open_isolated_workbench_window", fake_open)

    def boom(*args, **kwargs):
        raise AssertionError("already-running isolated start must not respawn the backend")

    response = lifecycle.run_isolated_operation(
        _item(
            path=str(worktree),
            alive=True,
            port=8004,
            controlPort=8769,
            shortName="branch+task",
            workbenchTitle="branch+task 台",
        ),
        "start",
        runner=boom,
    )

    assert response["accepted"] is True
    assert response["message"] == "已打开该分支工作台窗口。"
    assert opened[0]["url"] == "http://127.0.0.1:8004"
    assert registry.get_instance("worktree:task")["windowPid"] == 7


def test_spawn_sets_instance_short_name(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "AppData" / "Local"))
    worktree = tmp_path / "task"
    scripts = worktree / "scripts"
    scripts.mkdir(parents=True)
    (scripts / "vibelution_launcher.py").write_text("# launcher\n", encoding="utf-8")
    pythonw = worktree / ".venv" / "Scripts" / "pythonw.exe"
    pythonw.parent.mkdir(parents=True)
    pythonw.write_text("", encoding="utf-8")
    captured: dict = {}

    def fake_run(command, **kwargs):
        captured["env"] = kwargs["env"]

        class Result:
            returncode = 0
            stdout = "ok"
            stderr = ""

        return Result()

    monkeypatch.setattr(lifecycle.subprocess, "run", fake_run)
    lifecycle.spawn_worktree_launcher(worktree, "start", 8002, 8767, short_name="branch+task")
    assert captured["env"]["VIBELUTION_INSTANCE_SHORT_NAME"] == "branch+task"
    assert captured["env"]["VIBELUTION_ALLOW_DIRTY_LAUNCH"] == "1"
    assert captured["env"]["VIBELUTION_ALLOW_NON_MAIN_LAUNCH"] == "1"


def test_isolated_start_is_busy_while_in_flight(registry_path, tmp_path, monkeypatch):
    monkeypatch.setattr(registry, "_port_is_free", lambda port, host: True)
    monkeypatch.setattr(lifecycle, "current_live_ports", lambda launcher_state=None: {8000, 8765})
    worktree = tmp_path / "task"
    worktree.mkdir()
    registry.upsert_instance("worktree:task", status="starting", generation=3, projectRoot=str(worktree))

    with pytest.raises(lifecycle.BranchInstanceLifecycleError) as busy:
        lifecycle.run_isolated_operation(
            _item(path=str(worktree)),
            "start",
            runner=lambda *args, **kwargs: {"returncode": 0, "pid": 9},
        )
    assert busy.value.code == "instance_busy"
    assert busy.value.status_code == 409


def test_observe_error_matches_generation(registry_path):
    registry.upsert_instance("worktree:task", status="starting", generation=4, desiredState="open", phase="starting")
    stale = lifecycle.observe_isolated_transition("worktree:task", "observe-error", generation=3, message="stale")
    assert registry.get_instance("worktree:task")["status"] == "starting"
    assert stale["status"] == "starting"

    lifecycle.observe_isolated_transition("worktree:task", "observe-error", generation=4, message="HTTP timeout")
    stored = registry.get_instance("worktree:task")
    assert stored["status"] == "failed"
    assert stored["failureMessage"] == "HTTP timeout"


def test_stop_reaps_spawn_pid_before_stop_script(registry_path, tmp_path):
    worktree = tmp_path / "task"
    worktree.mkdir()
    registry.upsert_instance(
        "worktree:task",
        port=8004,
        controlPort=8769,
        projectRoot=str(worktree),
        status="starting",
        generation=2,
        spawnPid=424242,
    )
    reaped: list[int] = []
    calls: list[tuple] = []

    def fake_spawn(root, action, backend_port, control_port, **kwargs):
        calls.append((action, backend_port, kwargs.get("detach")))
        return {"returncode": 0}

    response = lifecycle.run_isolated_operation(
        _item(path=str(worktree), port=8004, controlPort=8769),
        "stop",
        runner=fake_spawn,
        terminate_pid=lambda pid: reaped.append(pid) or {"supported": True, "rootPid": pid},
    )

    assert response["accepted"] is True
    assert reaped == [424242]
    assert calls[0][0] == "stop"
    assert calls[0][2] is False
    assert registry.get_instance("worktree:task")["status"] == "closed"
    assert registry.get_instance("worktree:task")["spawnPid"] == 0


def test_spawn_detached_start_uses_current_supervisor_script(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "AppData" / "Local"))
    worktree = tmp_path / "task"
    (worktree / ".venv" / "Scripts").mkdir(parents=True)
    pythonw = worktree / ".venv" / "Scripts" / "pythonw.exe"
    pythonw.write_text("", encoding="utf-8")
    captured: dict = {}

    class FakeProcess:
        pid = 77

    def fake_popen(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return FakeProcess()

    monkeypatch.setattr(lifecycle.subprocess, "Popen", fake_popen)
    result = lifecycle.spawn_worktree_launcher(worktree, "start", 8002, 8767, detach=True)
    assert captured["command"][0].lower().endswith("pythonw.exe")
    assert captured["command"][1] == str(lifecycle.PYTHON_LAUNCHER_SCRIPT_PATH)
    assert captured["kwargs"]["cwd"] == str(worktree)
    if lifecycle.os.name == "nt":
        flags = int(captured["kwargs"]["creationflags"])
        assert flags & lifecycle.subprocess.DETACHED_PROCESS
        assert not (flags & int(getattr(lifecycle.subprocess, "CREATE_NO_WINDOW", 0)))
    assert result["pid"] == 77


def test_launcher_script_resolves_workspace_env_before_sys_path():
    text = Path(__file__).resolve().parents[1].joinpath("scripts", "vibelution_launcher.py").read_text(encoding="utf-8")
    assert text.index("VIBELUTION_WORKSPACE_ROOT") < text.index("sys.path.insert")
    assert "SUPERVISOR_ROOT" in text
