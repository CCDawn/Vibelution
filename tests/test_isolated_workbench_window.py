from __future__ import annotations

import json
import os
from contextlib import contextmanager
from pathlib import Path

import pytest

from core.infrastructure import atomic_io
from core.infrastructure.instance_display_name import workbench_window_title
from core.launcher.isolated_workbench_window import (
    instance_workbench_title,
    overlay_instance_window_pid,
    persist_instance_window_from_desktop_action,
)
from core.launcher import isolated_workbench_window as isolated
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


def test_close_isolated_window_uses_test_provider_and_clears_registry(registry_path):
    registry.upsert_instance("worktree:task", windowPid=4242)

    result = isolated.close_isolated_workbench_window({"id": "worktree:task"})

    assert result == {"provider": "test", "windowPid": 0}
    assert registry.get_instance("worktree:task")["windowPid"] == 0


def test_default_close_submits_electron_desktop_action(monkeypatch):
    monkeypatch.setattr(isolated, "_electron_desktop_shell_available", lambda: True)
    monkeypatch.setattr(
        isolated,
        "_submit_instance_window_action",
        lambda *_args, **_kwargs: {"intentId": "intent-close-1"},
    )

    result = isolated._default_close({"id": "worktree:task"})

    assert result == {"provider": "electron", "windowPid": 0, "intentId": "intent-close-1"}


def test_write_worktree_window_pid_preserves_state_and_uses_atomic_writer(tmp_path, monkeypatch):
    runtime_root = tmp_path / "runtime"
    state_path = runtime_root / "launcher" / "state.json"
    state_path.parent.mkdir(parents=True)
    state_path.write_text(json.dumps({"backendPid": 123, "status": "open"}), encoding="utf-8")
    monkeypatch.setattr(isolated, "resolve_project_runtime_home", lambda _worktree: runtime_root)
    calls: list[tuple[Path, dict]] = []

    def recording_atomic_write(path, payload, **kwargs):
        calls.append((Path(path), dict(payload)))
        atomic_io.atomic_write_json(path, payload, **kwargs)

    monkeypatch.setattr(isolated, "atomic_write_json", recording_atomic_write)
    isolated._write_worktree_window_pid(tmp_path / "worktree", 4242)

    persisted = json.loads(state_path.read_text(encoding="utf-8"))
    assert persisted == {"backendPid": 123, "status": "open", "browserWindowPid": 4242, "windowPid": 4242}
    assert calls == [(state_path, persisted)]
    assert not Path(f"{state_path}.lockdir").exists()


def test_write_worktree_window_pid_is_fail_safe_when_state_lock_times_out(tmp_path, monkeypatch):
    runtime_root = tmp_path / "runtime"
    state_path = runtime_root / "launcher" / "state.json"
    state_path.parent.mkdir(parents=True)
    original = {"backendPid": 123, "windowPid": 7}
    state_path.write_text(json.dumps(original), encoding="utf-8")
    monkeypatch.setattr(isolated, "resolve_project_runtime_home", lambda _worktree: runtime_root)

    @contextmanager
    def timeout_lock(*_args, **_kwargs):
        raise TimeoutError("state lock busy")
        yield  # pragma: no cover

    monkeypatch.setattr(isolated.instance_lock, "hold_instance_lock", timeout_lock)
    monkeypatch.setattr(
        isolated,
        "atomic_write_json",
        lambda *_args, **_kwargs: pytest.fail("must not overwrite state when lock cannot be claimed"),
    )

    isolated._write_worktree_window_pid(tmp_path / "worktree", 4242)

    assert json.loads(state_path.read_text(encoding="utf-8")) == original
