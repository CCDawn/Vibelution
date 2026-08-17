from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from core.runtime_manager import workbench_controller


def _active_electron_session() -> dict[str, str]:
    return {"desktopSessionId": "electron-session-1"}


def test_open_workbench_uses_desktop_action_without_restarting_healthy_backend(monkeypatch):
    submitted: list[dict] = []
    events: list[tuple[str, dict]] = []

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
        lambda **kwargs: submitted.append(kwargs) or {"status": "accepted", "intentId": "intent-open-1"},
    )
    confirmed: list[dict] = []
    monkeypatch.setattr(
        workbench_controller,
        "_await_electron_window_action_confirmed",
        lambda **kwargs: confirmed.append(kwargs) or {"desktopSessionId": "electron-session-1", "revision": 2},
    )
    monkeypatch.setattr(
        workbench_controller,
        "_record_launcher_action_event",
        lambda event_type, **kwargs: events.append((event_type, kwargs)),
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
    assert confirmed == [
        {
            "intent": {"status": "accepted", "intentId": "intent-open-1"},
            "session": {"desktopSessionId": "electron-session-1"},
            "action": "open_workbench",
        }
    ]
    assert [event_type for event_type, _payload in events] == [
        "launcher.action.requested",
        "launcher.action.electron_backend_reused",
        "launcher.action.electron_desktop_action_submitted",
        "launcher.action.completed",
        "launcher.action.startup_summary",
    ]
    requested_payload = next(payload for event_type, payload in events if event_type == "launcher.action.requested")
    summary_payload = next(payload for event_type, payload in events if event_type == "launcher.action.startup_summary")
    assert requested_payload["env"]["VIBELUTION_STARTUP_TRACE_ID"] == summary_payload["startup_trace_id"]
    assert summary_payload["outcome"] == "succeeded"


def test_latest_active_electron_session_rejects_live_lease_when_electron_pid_is_dead(monkeypatch):
    from core.launcher import desktop_session_store

    monkeypatch.setattr(
        desktop_session_store,
        "latest_active_desktop_session",
        lambda **_kwargs: {
            "desktopSessionId": "electron-launcher-session-8952-msqairvx",
            "revision": 33,
        },
    )
    monkeypatch.setattr(workbench_controller, "_is_process_alive", lambda _pid: False)

    assert workbench_controller._latest_active_electron_desktop_session() == {}


def test_desktop_action_acceptance_without_ack_fails_bounded(monkeypatch):
    from core.launcher import desktop_session_store, lifecycle_intent_store

    clock = iter([0.0, 0.0, 0.2])
    monkeypatch.setattr(workbench_controller.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(workbench_controller.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(
        lifecycle_intent_store,
        "get_lifecycle_intent",
        lambda _intent_id: {"intentId": "intent-focus-1", "status": "accepted"},
    )
    monkeypatch.setattr(
        desktop_session_store,
        "get_desktop_session",
        lambda _session_id: {
            "desktopSessionId": "electron-launcher-session-8952-msqairvx",
            "revision": 33,
            "windows": {"workbench": {"open": True}},
        },
    )
    monkeypatch.setattr(workbench_controller, "_is_process_alive", lambda _pid: True)

    with pytest.raises(RuntimeError, match="was not acknowledged"):
        workbench_controller._await_electron_window_action_confirmed(
            intent={"intentId": "intent-focus-1", "status": "accepted"},
            session={"desktopSessionId": "electron-launcher-session-8952-msqairvx", "revision": 33},
            action="focus_workbench",
            timeout_seconds=0.1,
        )


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
        lambda **kwargs: submitted.append(kwargs) or {"status": "accepted", "intentId": "intent-open-2"},
    )
    monkeypatch.setattr(
        workbench_controller,
        "_await_electron_window_action_confirmed",
        lambda **_kwargs: {"desktopSessionId": "electron-session-1", "revision": 2},
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
    assert len(bootstraps) == 1
    assert bootstraps[0]["env"] == launcher_calls[0]["kwargs"]["env"]
    assert bootstraps[0]["action"] == "internal-start"
    assert bootstraps[0]["no_browser"] is True
    assert bootstraps[0]["startup_telemetry"]["startupTraceId"].startswith("launcher-startup-")
    assert events == [
        "launcher.action.requested",
        "launcher.action.electron_first_start_succeeded",
        "launcher.action.completed",
        "launcher.action.startup_summary",
    ]


def test_first_open_fails_when_packaged_electron_is_missing(monkeypatch):
    launcher_calls: list[dict] = []

    monkeypatch.setattr(workbench_controller, "_latest_active_electron_desktop_session", lambda: {})
    monkeypatch.setattr(workbench_controller, "_packaged_electron_desktop_executable", lambda: None)
    monkeypatch.setattr(workbench_controller, "_live_electron_owner_pid", lambda: 0)
    monkeypatch.setattr(workbench_controller, "_electron_main_orchestrates_windows", lambda: False)
    monkeypatch.setattr(
        workbench_controller,
        "_run_waitable_launcher_process",
        lambda *args, **kwargs: launcher_calls.append({"args": args, "kwargs": kwargs})
        or subprocess.CompletedProcess(args=["launcher"], returncode=0, stdout="", stderr=""),
    )
    monkeypatch.setattr(workbench_controller, "_record_launcher_action_event", lambda *_args, **_kwargs: None)

    with pytest.raises(RuntimeError, match="Refusing Edge fallback"):
        workbench_controller.run_launcher_action("internal-start")

    assert launcher_calls == []


def test_live_electron_owner_signals_open_workbench_instead_of_edge(monkeypatch):
    launcher_calls: list[dict] = []
    signals: list[dict] = []
    events: list[str] = []

    monkeypatch.setattr(workbench_controller, "_latest_active_electron_desktop_session", lambda: {})
    monkeypatch.setattr(workbench_controller, "_packaged_electron_desktop_executable", lambda: None)
    monkeypatch.setattr(workbench_controller, "_live_electron_owner_pid", lambda: 44044)
    monkeypatch.setattr(workbench_controller, "_electron_main_orchestrates_windows", lambda: False)
    monkeypatch.setattr(
        workbench_controller,
        "_resolve_live_electron_executable",
        lambda _session=None: Path("C:/Vibelution.exe"),
    )
    monkeypatch.setattr(
        workbench_controller,
        "_run_waitable_launcher_process",
        lambda *args, **kwargs: launcher_calls.append({"args": args, "kwargs": kwargs})
        or subprocess.CompletedProcess(args=["launcher"], returncode=0, stdout="", stderr=""),
    )
    monkeypatch.setattr(
        workbench_controller,
        "_signal_live_electron_open_workbench",
        lambda **kwargs: signals.append(kwargs),
    )
    monkeypatch.setattr(
        workbench_controller,
        "_record_launcher_action_event",
        lambda event_type, **_kwargs: events.append(event_type),
    )

    result = workbench_controller.run_launcher_action("internal-start")

    assert result.returncode == 0
    assert "--no-browser" in launcher_calls[0]["args"][0]
    assert len(signals) == 1
    assert signals[0]["executable"] == Path("C:/Vibelution.exe")
    assert "launcher.action.electron_open_signaled" in events
    assert "launcher.action.edge_fallback_package_missing" not in events


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


def test_submit_electron_window_action_includes_observed_workbench_url(monkeypatch):
    captured: dict[str, object] = {}

    def fake_submit(payload, *, actor_context, active_work_runs, desktop_action_payload=None):
        captured["desktop_action_payload"] = desktop_action_payload
        return {"status": "accepted", "action": payload.get("action")}

    monkeypatch.setattr(
        "core.launcher.lifecycle_intent_store.submit_lifecycle_intent",
        fake_submit,
    )
    monkeypatch.setattr(
        workbench_controller,
        "observe_workbench",
        lambda **_kwargs: {
            "url": "http://127.0.0.1:8002/",
            "backendPort": 8002,
            "backendObserved": True,
            "backendHealthy": True,
            "backendPortListening": True,
            "launcherStatePresent": True,
        },
    )

    result = workbench_controller._submit_electron_window_action(
        action="open_workbench",
        reason="test:open",
        session={"desktopSessionId": "electron-session-1"},
    )

    assert result["status"] == "accepted"
    assert captured["desktop_action_payload"] == {
        "desktopSessionId": "electron-session-1",
        "workbenchUrl": "http://127.0.0.1:8002/",
        "backendPort": 8002,
    }


def test_submit_electron_window_action_omits_url_when_observation_fails(monkeypatch):
    captured: dict[str, object] = {}

    def fake_submit(payload, *, actor_context, active_work_runs, desktop_action_payload=None):
        captured["desktop_action_payload"] = desktop_action_payload
        return {"status": "accepted", "action": payload.get("action")}

    monkeypatch.setattr(
        "core.launcher.lifecycle_intent_store.submit_lifecycle_intent",
        fake_submit,
    )
    monkeypatch.setattr(
        workbench_controller,
        "observe_workbench",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("observe unavailable")),
    )

    result = workbench_controller._submit_electron_window_action(
        action="open_workbench",
        reason="test:open",
        session={"desktopSessionId": "electron-session-1"},
    )

    assert result["status"] == "accepted"
    assert captured["desktop_action_payload"] == {"desktopSessionId": "electron-session-1"}
    assert "workbenchUrl" not in captured["desktop_action_payload"]


def test_electron_desktop_action_payload_prefers_live_port_over_stale_url(monkeypatch):
    monkeypatch.setattr(
        workbench_controller,
        "observe_workbench",
        lambda **_kwargs: {
            "url": "http://127.0.0.1:8000",
            "backendPort": 8000,
            "backendObserved": False,
            "backendHealthy": False,
            "backendPortListening": False,
            "launcherStatePresent": True,
        },
    )
    monkeypatch.setattr(workbench_controller, "configured_backend_port", lambda: 8002)
    monkeypatch.setattr(
        workbench_controller,
        "_port_is_listening_socket",
        lambda port: int(port) == 8002,
    )

    payload = workbench_controller._electron_desktop_action_payload(
        action="open_workbench",
        session={"desktopSessionId": "electron-session-1"},
    )

    assert payload == {
        "desktopSessionId": "electron-session-1",
        "workbenchUrl": "http://127.0.0.1:8002",
        "backendPort": 8002,
    }


def test_electron_desktop_action_payload_omits_dead_url_when_no_live_port(monkeypatch):
    monkeypatch.setattr(
        workbench_controller,
        "observe_workbench",
        lambda **_kwargs: {
            "url": "http://127.0.0.1:8000",
            "backendPort": 8000,
            "backendObserved": False,
            "backendHealthy": False,
            "backendPortListening": False,
            "launcherStatePresent": True,
        },
    )
    monkeypatch.setattr(workbench_controller, "configured_backend_port", lambda: 8000)
    monkeypatch.setattr(workbench_controller, "_port_is_listening_socket", lambda _port: False)

    payload = workbench_controller._electron_desktop_action_payload(
        action="open_workbench",
        session={"desktopSessionId": "electron-session-1"},
    )

    assert payload == {"desktopSessionId": "electron-session-1"}
    assert "workbenchUrl" not in payload


def test_observe_workbench_retargets_stale_url_to_live_ports_json(monkeypatch):
    monkeypatch.setattr(
        workbench_controller,
        "_load_launcher_state",
        lambda: {
            "url": "http://127.0.0.1:8000",
            "host": "127.0.0.1",
            "backendPort": 8000,
            "port": 8000,
            "backendPid": 0,
            "backendLaunchPid": 0,
            "sessionRole": "workbench",
            "browserManaged": False,
        },
    )
    monkeypatch.setattr(workbench_controller, "configured_backend_port", lambda: 8002)
    monkeypatch.setattr(
        workbench_controller,
        "_port_is_listening_socket",
        lambda port: int(port) == 8002,
    )
    monkeypatch.setattr(workbench_controller, "_listening_pid_for_port", lambda port: 4242 if int(port) == 8002 else 0)
    monkeypatch.setattr(workbench_controller, "_is_process_alive", lambda _pid: False)
    monkeypatch.setattr(workbench_controller, "_is_backend_healthy", lambda _url: True)
    monkeypatch.setattr(workbench_controller, "_repo_workbench_backend_kind", lambda _pid: "managed_workbench_backend")
    monkeypatch.setattr(workbench_controller, "_is_browser_window_alive", lambda _pid: False)
    monkeypatch.setattr(
        workbench_controller,
        "window_provider_projection",
        lambda state: {
            "windowProfileDir": "",
            "browserManaged": False,
        },
    )
    monkeypatch.setattr(
        workbench_controller,
        "_with_active_electron_window_projection",
        lambda payload: payload,
    )

    snapshot = workbench_controller.observe_workbench(
        recover_browser_window=False,
        recover_browser_window_for_backend_observed=False,
    )

    assert snapshot["url"] == "http://127.0.0.1:8002"
    assert snapshot["backendPort"] == 8002
    assert snapshot["backendPortListening"] is True
