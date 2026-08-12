from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from core.launcher import app as launcher_app
from core.launcher import branch_instance_lifecycle as lifecycle
from core.launcher import service as launcher_service
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
    assert calls == [(worktree, "start", 8001, 8766, {})]
    stored = registry.get_instance("worktree:task")
    assert stored["status"] == "running"
    assert stored["port"] == 8001
    assert stored["controlPort"] == 8766


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


def test_spawn_uses_pythonw_and_hidden_console(tmp_path, monkeypatch):
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
    assert captured["kwargs"]["cwd"] == str(worktree)
    assert captured["kwargs"]["env"]["VIBELUTION_PORT"] == "8002"
    assert captured["kwargs"]["env"]["VIBELUTION_LAUNCHER_PORT"] == "8767"
    if lifecycle.os.name == "nt":
        assert captured["kwargs"]["creationflags"] & lifecycle.subprocess.CREATE_NO_WINDOW
    assert result["returncode"] == 0


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
