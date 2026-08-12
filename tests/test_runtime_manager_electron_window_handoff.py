from __future__ import annotations

import subprocess
from pathlib import Path

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


def test_first_open_uses_packaged_electron_after_headless_backend_start(monkeypatch):
    launcher_calls: list[dict] = []
    bootstraps: list[dict] = []
    events: list[str] = []

    monkeypatch.setattr(workbench_controller, "_latest_active_electron_desktop_session", lambda: {})
    monkeypatch.setattr(workbench_controller, "_packaged_electron_desktop_executable", lambda: Path("Vibelution.exe"))
    monkeypatch.setattr(
        workbench_controller,
        "_run_waitable_launcher_process",
        lambda *args, **kwargs: launcher_calls.append({"args": args, "kwargs": kwargs})
        or subprocess.CompletedProcess(args=["launcher"], returncode=0, stdout="", stderr=""),
    )
    monkeypatch.setattr(
        workbench_controller,
        "_bootstrap_packaged_electron_workbench",
        lambda **kwargs: bootstraps.append(kwargs)
        or {"electronLaunchPid": 701, "desktopSessionId": "electron-session-first", "desktopSessionRevision": 3},
    )
    monkeypatch.setattr(
        workbench_controller,
        "_record_launcher_action_event",
        lambda event_type, **_kwargs: events.append(event_type),
    )

    result = workbench_controller.run_launcher_action("internal-start")

    assert result.returncode == 0
    assert "--no-browser" in launcher_calls[0]["args"][0]
    assert bootstraps == [{"env": launcher_calls[0]["kwargs"]["env"], "action": "internal-start"}]
    assert events == [
        "launcher.action.requested",
        "launcher.action.electron_first_start_succeeded",
        "launcher.action.completed",
    ]


def test_first_open_uses_edge_only_when_packaged_electron_is_missing(monkeypatch):
    launcher_calls: list[dict] = []
    events: list[str] = []

    monkeypatch.setattr(workbench_controller, "_latest_active_electron_desktop_session", lambda: {})
    monkeypatch.setattr(workbench_controller, "_packaged_electron_desktop_executable", lambda: None)
    monkeypatch.setattr(
        workbench_controller,
        "_run_waitable_launcher_process",
        lambda *args, **kwargs: launcher_calls.append({"args": args, "kwargs": kwargs})
        or subprocess.CompletedProcess(args=["launcher"], returncode=0, stdout="", stderr=""),
    )
    monkeypatch.setattr(
        workbench_controller,
        "_record_launcher_action_event",
        lambda event_type, **_kwargs: events.append(event_type),
    )

    result = workbench_controller.run_launcher_action("internal-start")

    assert result.returncode == 0
    assert "--no-browser" not in launcher_calls[0]["args"][0]
    assert events == [
        "launcher.action.requested",
        "launcher.action.edge_fallback_package_missing",
        "launcher.action.completed",
    ]


def test_first_open_does_not_silently_fall_back_to_edge_when_packaged_electron_fails(monkeypatch):
    launcher_calls: list[dict] = []

    monkeypatch.setattr(workbench_controller, "_latest_active_electron_desktop_session", lambda: {})
    monkeypatch.setattr(workbench_controller, "_packaged_electron_desktop_executable", lambda: Path("Vibelution.exe"))
    monkeypatch.setattr(
        workbench_controller,
        "_run_waitable_launcher_process",
        lambda *args, **kwargs: launcher_calls.append({"args": args, "kwargs": kwargs})
        or subprocess.CompletedProcess(args=["launcher"], returncode=0, stdout="", stderr=""),
    )
    monkeypatch.setattr(
        workbench_controller,
        "_bootstrap_packaged_electron_workbench",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("Electron registration failed")),
    )
    monkeypatch.setattr(workbench_controller, "_record_launcher_action_event", lambda *_args, **_kwargs: None)

    with pytest.raises(RuntimeError, match="Electron registration failed"):
        workbench_controller.run_launcher_action("internal-start")

    assert "--no-browser" in launcher_calls[0]["args"][0]


def test_explicit_headless_open_never_bootstraps_packaged_electron(monkeypatch):
    launcher_calls: list[dict] = []

    monkeypatch.setattr(workbench_controller, "_latest_active_electron_desktop_session", lambda: {})
    monkeypatch.setattr(workbench_controller, "_packaged_electron_desktop_executable", lambda: Path("Vibelution.exe"))
    monkeypatch.setattr(
        workbench_controller,
        "_run_waitable_launcher_process",
        lambda *args, **kwargs: launcher_calls.append({"args": args, "kwargs": kwargs})
        or subprocess.CompletedProcess(args=["launcher"], returncode=0, stdout="", stderr=""),
    )
    monkeypatch.setattr(
        workbench_controller,
        "_bootstrap_packaged_electron_workbench",
        lambda **_kwargs: pytest.fail("explicit headless open must not launch Electron"),
    )
    monkeypatch.setattr(workbench_controller, "_record_launcher_action_event", lambda *_args, **_kwargs: None)

    result = workbench_controller.run_launcher_action("internal-start", no_browser=True)

    assert result.returncode == 0
    assert "--no-browser" in launcher_calls[0]["args"][0]
