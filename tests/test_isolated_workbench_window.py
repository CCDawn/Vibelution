from __future__ import annotations

import os

import pytest

from core.infrastructure.instance_display_name import workbench_window_title
from core.launcher.isolated_workbench_window import (
    instance_workbench_title,
    overlay_instance_window_pid,
    persist_instance_window_from_desktop_action,
)
from core.runtime_manager import instances_registry as registry


@pytest.fixture
def registry_path(tmp_path, monkeypatch):
    path = tmp_path / "Vibelution" / "instances.json"
    monkeypatch.setattr(registry, "instances_registry_path", lambda: path)
    return path


def test_instance_workbench_actions_are_allowed_desktop_actions():
    from core.launcher.lifecycle_intent_store import DESKTOP_ACTIONS

    assert "open_instance_workbench" in DESKTOP_ACTIONS
    assert "close_instance_workbench" in DESKTOP_ACTIONS


def test_instance_workbench_title_prefers_workbench_title():
    assert instance_workbench_title({"workbenchTitle": "branch+task 台", "shortName": "other"}) == "branch+task 台"
    assert instance_workbench_title({"shortName": "branch+task"}) == workbench_window_title("branch+task")


def test_overlay_instance_window_pid_ignores_current_and_dead_pids():
    current = {"current": True, "pids": {"backend": 1, "window": 0, "manager": 0}}
    overlay_instance_window_pid(current, {"windowPid": os.getpid()})
    assert current["pids"]["window"] == 0

    isolated = {"current": False, "pids": {"backend": 1, "window": 0, "manager": 0}}
    overlay_instance_window_pid(isolated, {"windowPid": os.getpid()})
    assert isolated["pids"]["window"] == os.getpid()

    dead = {"current": False, "pids": {"backend": 1, "window": 0, "manager": 0}}
    overlay_instance_window_pid(dead, {"windowPid": 1})
    assert dead["pids"]["window"] == 0


def test_persist_instance_window_from_desktop_ack(registry_path):
    persist_instance_window_from_desktop_action(
        {
            "action": "open_instance_workbench",
            "payload": {"instanceId": "worktree:task", "windowTitle": "branch+task 台"},
            "result": {"windowState": {"rendererProcessId": 4242, "open": True}},
        }
    )
    stored = registry.get_instance("worktree:task")
    assert stored["windowPid"] == 4242
    assert stored["windowTitle"] == "branch+task 台"

    persist_instance_window_from_desktop_action(
        {
            "action": "close_instance_workbench",
            "payload": {"instanceId": "worktree:task"},
            "result": {},
        }
    )
    assert registry.get_instance("worktree:task")["windowPid"] == 0
