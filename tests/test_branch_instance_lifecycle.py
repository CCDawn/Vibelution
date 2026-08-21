from __future__ import annotations

import json
import os
import sys
import threading
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


def test_launcher_script_resolves_workspace_env_before_sys_path():
    text = Path(__file__).resolve().parents[1].joinpath("scripts", "vibelution_launcher.py").read_text(encoding="utf-8")
    assert text.index("VIBELUTION_WORKSPACE_ROOT") < text.index("sys.path.insert")
    assert "SUPERVISOR_ROOT" in text
