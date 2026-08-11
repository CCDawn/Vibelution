from __future__ import annotations

import subprocess

import pytest

from core.runtime_manager import workbench_controller


def _active_electron_session() -> dict[str, str]:
    return {"desktopSessionId": "electron-session-1"}


def test_open_workbench_uses_desktop_action_without_restarting_healthy_backend(monkeypatch):
    submitted: list[dict] = []
    events: list[str] = []

    monkeypatch.setattr(
        workbench_controller,
        "_latest_active_electron_desktop_session",
        _active_electron_session,
    )
    monkeypatch.setattr(
        workbench_controller,
        "observe_workbench",
        lambda **_kwargs: {
            "backendHealthy": True,
            "backendObserved": True,
            "backendPortConflict": False,
        },
    )
    monkeypatch.setattr(
        workbench_controller,
        "_run_waitable_launcher_process",
        lambda *_args, **_kwargs: pytest.fail("healthy backend must not be restarted"),
    )
    monkeypatch.setattr(
        workbench_controller,
        "_submit_electron_window_action",
        lambda **kwargs: submitted.append(kwargs) or {"status": "accepted"},
    )
    monkeypatch.setattr(
        workbench_controller,
        "_record_launcher_action_event",
        lambda event_type, **_kwargs: events.append(event_type),
    )

    result = workbench_controller.run_launcher_action("internal-start")

    assert result.returncode == 0
    assert submitted == [
        {
            "action": "open_workbench",
            "reason": "internal-start:electron_window_provider",
            "session": {"desktopSessionId": "electron-session-1"},
        }
    ]
    assert events == [
        "launcher.action.requested",
        "launcher.action.electron_backend_reused",
        "launcher.action.electron_desktop_action_submitted",
        "launcher.action.completed",
    ]


def test_open_workbench_starts_backend_before_desktop_action_when_not_ready(monkeypatch):
    launcher_calls: list[dict] = []
    submitted: list[dict] = []

    monkeypatch.setattr(
        workbench_controller,
        "_latest_active_electron_desktop_session",
        _active_electron_session,
    )
    monkeypatch.setattr(
        workbench_controller,
        "observe_workbench",
        lambda **_kwargs: {
            "backendHealthy": False,
            "backendObserved": False,
            "backendPortConflict": False,
        },
    )
    monkeypatch.setattr(
        workbench_controller,
        "_run_waitable_launcher_process",
        lambda *args, **kwargs: launcher_calls.append({"args": args, "kwargs": kwargs})
        or subprocess.CompletedProcess(args=["launcher"], returncode=0),
    )
    monkeypatch.setattr(
        workbench_controller,
        "_submit_electron_window_action",
        lambda **kwargs: submitted.append(kwargs) or {"status": "accepted"},
    )
    monkeypatch.setattr(workbench_controller, "_record_launcher_action_event", lambda *_args, **_kwargs: None)

    result = workbench_controller.run_launcher_action("internal-start")

    assert result.returncode == 0
    assert len(launcher_calls) == 1
    assert submitted[0]["action"] == "open_workbench"
