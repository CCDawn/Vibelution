from __future__ import annotations

import argparse
import contextlib
import importlib.util
import os
import subprocess
import sys
import time
import types
import uuid
from pathlib import Path

import pytest

import scripts.vibelution_desktop_entry as desktop_entry


DESKTOP_ENTRY_PY = Path(__file__).parents[1] / "scripts" / "vibelution_desktop_entry.py"


def _load_desktop_entry_py():
    module_name = f"vibelution_desktop_entry_under_test_{time.time_ns()}"
    spec = importlib.util.spec_from_file_location(module_name, DESKTOP_ENTRY_PY)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_desktop_entry_direct_execution_loads_local_windowless_helper(tmp_path):
    result = subprocess.run(
        [sys.executable, str(DESKTOP_ENTRY_PY), "--help"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "Open the Vibelution Launcher without a console window." in result.stdout


def test_desktop_entry_imports_safely_on_non_windows(monkeypatch):
    fake_os = types.ModuleType("os")
    fake_os.name = "posix"
    fake_os.environ = os.environ
    monkeypatch.setitem(sys.modules, "os", fake_os)
    entry = _load_desktop_entry_py()

    # Windows-only shell identity structures must not be constructed off-Windows;
    # importing on POSIX previously raised ValueError from _GUID.from_buffer_copy.
    assert entry.PKEY_APPUSERMODEL_ID is None
    assert entry.PKEY_APPUSERMODEL_RELAUNCH_DISPLAY_NAME is None
    assert entry.PKEY_APPUSERMODEL_RELAUNCH_ICON_RESOURCE is None
    assert entry.IID_IPROPERTY_STORE is None
    result = entry._apply_managed_browser_app_identity(0, "launcher")
    assert result["applied"] is False
    assert result["reason"] == "non_windows"
    assert result["appUserModelId"] == "Vibelution.Launcher"


@pytest.mark.skipif(os.name != "nt", reason="Windows shell identity contract is Windows-only")
def test_desktop_entry_windows_identity_runtime_contract():
    entry = _load_desktop_entry_py()

    assert isinstance(entry.PKEY_APPUSERMODEL_ID, entry._PROPERTYKEY)
    assert isinstance(entry.PKEY_APPUSERMODEL_RELAUNCH_DISPLAY_NAME, entry._PROPERTYKEY)
    assert isinstance(entry.PKEY_APPUSERMODEL_RELAUNCH_ICON_RESOURCE, entry._PROPERTYKEY)
    assert entry.PKEY_APPUSERMODEL_ID.fmtid.Data1 == 0x9F4C2855
    assert entry.PKEY_APPUSERMODEL_ID.pid == 5
    assert entry.PKEY_APPUSERMODEL_RELAUNCH_DISPLAY_NAME.pid == 4
    assert entry.PKEY_APPUSERMODEL_RELAUNCH_ICON_RESOURCE.pid == 3
    assert isinstance(entry.IID_IPROPERTY_STORE, entry._GUID)
    assert bytes(entry.IID_IPROPERTY_STORE) == uuid.UUID("886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99").bytes_le


def test_bootstrap_marks_untracked_healthy_launcher_port_as_attached(monkeypatch):
    states = iter(
        [
            {"launcherBackendPid": 0},
            {
                "launcherBackendPid": 0,
                "launcherControlPort": 8765,
                "sessionId": "launcher-session",
                "url": "http://127.0.0.1:8000",
            },
        ]
    )

    monkeypatch.setattr(desktop_entry, "_read_state", lambda: next(states))
    monkeypatch.setattr(desktop_entry, "_open_launcher", lambda args: None)
    monkeypatch.setattr(desktop_entry, "_launcher_control_port", lambda: 8765)
    monkeypatch.setattr(desktop_entry, "_launcher_control_url", lambda port: "http://127.0.0.1:8765/launcher")
    monkeypatch.setattr(desktop_entry, "_launcher_control_healthy", lambda port: True)

    result = desktop_entry._bootstrap_launcher(
        argparse.Namespace(workspace="", config="", no_browser=True, python_exe="")
    )

    assert result["mode"] == "attached"
    assert result["launcherBackendPid"] == 0


def test_electron_bootstrap_attaches_to_healthy_managed_launcher_without_replacing_it(monkeypatch):
    state = {
        "launcherAdapter": "python_headless",
        "launcherBackendPid": 4321,
        "launcherBackendLaunchPid": 4321,
        "launcherControlPort": 8765,
        "launcherControlSourceSignature": "older-source",
        "runtimeProjectRoot": str(desktop_entry.PROJECT_ROOT),
        "sessionId": "launcher-session",
        "url": "http://127.0.0.1:8002",
    }
    events: list[tuple[str, dict[str, object]]] = []

    monkeypatch.setattr(desktop_entry, "_read_state", lambda: dict(state))
    monkeypatch.setattr(desktop_entry, "_launcher_control_port", lambda: 8765)
    monkeypatch.setattr(desktop_entry, "_launcher_control_url", lambda port: "http://127.0.0.1:8765/launcher")
    monkeypatch.setattr(desktop_entry, "_launcher_control_healthy", lambda port: True)
    monkeypatch.setattr(desktop_entry, "_pid_alive", lambda pid: pid == 4321)
    monkeypatch.setattr(
        desktop_entry,
        "_open_launcher",
        lambda args: pytest.fail("healthy managed Launcher must not be replaced during Electron bootstrap"),
    )
    monkeypatch.setattr(
        desktop_entry,
        "_append_log",
        lambda event, **fields: events.append((event, fields)),
    )

    result = desktop_entry._bootstrap_launcher(
        argparse.Namespace(
            workspace=str(desktop_entry.PROJECT_ROOT),
            config="",
            no_browser=True,
            python_exe="",
            attach_healthy_launcher=True,
        )
    )

    assert result["mode"] == "attached"
    assert result["launcherBackendPid"] == 4321
    assert result["workbenchUrl"] == "http://127.0.0.1:8002"
    assert events == [
        (
            "desktop_entry_python.backend.attached_managed_healthy",
            {
                "port": 8765,
                "backend_pid": 4321,
                "reason": "electron_bootstrap",
                "source_signature_policy": "ignored_for_attach",
            },
        )
    ]


def test_electron_bootstrap_rejects_healthy_launcher_with_mismatched_workspace(monkeypatch):
    state = {
        "launcherAdapter": "python_headless",
        "launcherBackendPid": 4321,
        "launcherBackendLaunchPid": 4321,
        "launcherControlPort": 8765,
        "runtimeProjectRoot": "C:/different-project",
    }

    monkeypatch.setattr(desktop_entry, "_read_state", lambda: dict(state))
    monkeypatch.setattr(desktop_entry, "_launcher_control_port", lambda: 8765)
    monkeypatch.setattr(desktop_entry, "_launcher_control_healthy", lambda port: True)
    monkeypatch.setattr(desktop_entry, "_pid_alive", lambda pid: pid == 4321)
    monkeypatch.setattr(
        desktop_entry,
        "_open_launcher",
        lambda args: pytest.fail("identity mismatch must fail closed before ordinary bootstrap"),
    )

    with pytest.raises(RuntimeError, match="does not belong to this workspace"):
        desktop_entry._bootstrap_launcher(
            argparse.Namespace(
                workspace=str(desktop_entry.PROJECT_ROOT),
                config="",
                no_browser=True,
                python_exe="",
                attach_healthy_launcher=True,
            )
        )


def test_ordinary_bootstrap_keeps_existing_launcher_refresh_path(monkeypatch):
    states = iter(
        [
            {"launcherBackendPid": 4321},
            {
                "launcherBackendPid": 5678,
                "launcherControlPort": 8765,
                "sessionId": "replacement-launcher",
                "url": "http://127.0.0.1:8002",
            },
        ]
    )
    calls: list[argparse.Namespace] = []

    monkeypatch.setattr(desktop_entry, "_read_state", lambda: next(states))
    monkeypatch.setattr(desktop_entry, "_open_launcher", lambda args: calls.append(args))
    monkeypatch.setattr(desktop_entry, "_launcher_control_port", lambda: 8765)
    monkeypatch.setattr(desktop_entry, "_launcher_control_url", lambda port: "http://127.0.0.1:8765/launcher")
    monkeypatch.setattr(desktop_entry, "_launcher_control_healthy", lambda port: True)

    args = argparse.Namespace(workspace="", config="", no_browser=True, python_exe="")
    result = desktop_entry._bootstrap_launcher(args)

    assert calls == [args]
    assert result["mode"] == "started"
    assert result["launcherBackendPid"] == 5678


def test_ordinary_bootstrap_attaches_to_healthy_control_while_same_workspace_electron_is_active(monkeypatch):
    state = {
        "launcherAdapter": "python_headless",
        "launcherBackendPid": 4321,
        "launcherBackendLaunchPid": 4321,
        "launcherControlPort": 8765,
        "launcherControlSourceSignature": "older-source",
        "runtimeProjectRoot": str(desktop_entry.PROJECT_ROOT),
    }
    saved: list[dict[str, object]] = []
    events: list[tuple[str, dict[str, object]]] = []

    monkeypatch.setattr(desktop_entry, "_single_launcher_open_lock", lambda: contextlib.nullcontext(True))
    monkeypatch.setattr(desktop_entry, "_read_state", lambda: dict(state))
    monkeypatch.setattr(desktop_entry, "_launcher_control_port", lambda: 8765)
    monkeypatch.setattr(desktop_entry, "_launcher_control_healthy", lambda _port: True)
    monkeypatch.setattr(desktop_entry, "_pid_alive", lambda pid: pid == 4321)
    monkeypatch.setattr(desktop_entry, "_source_signature", lambda: "newer-source")
    monkeypatch.setattr(
        desktop_entry,
        "_active_electron_desktop_session_for_workspace",
        lambda _workspace: {"desktopSessionId": "electron-launcher-session-8952-msqairvx"},
    )
    monkeypatch.setattr(
        desktop_entry,
        "_replace_stale_launcher_control",
        lambda *_args, **_kwargs: pytest.fail("active Electron must keep the healthy control plane attached"),
    )
    monkeypatch.setattr(
        desktop_entry,
        "_save_launcher_state",
        lambda previous, **kwargs: saved.append({**previous, **kwargs}),
    )
    monkeypatch.setattr(desktop_entry, "_append_log", lambda event, **fields: events.append((event, fields)))

    desktop_entry._open_launcher(
        argparse.Namespace(
            workspace=str(desktop_entry.PROJECT_ROOT),
            config="",
            no_browser=True,
            python_exe="C:/Python/python.exe",
        )
    )

    assert saved[-1]["current_signature"] == "older-source"
    assert ("desktop_entry_python.backend.attached_active_electron", {
        "port": 8765,
        "backend_pid": 4321,
        "desktop_session_id": "electron-launcher-session-8952-msqairvx",
        "source_signature_policy": "preserved_until_controlled_restart",
    }) in events


def test_active_electron_session_helper_rejects_canonical_dead_process(monkeypatch):
    from core.launcher import desktop_session_store

    monkeypatch.setattr(
        desktop_session_store,
        "latest_active_desktop_session",
        lambda **_kwargs: {
            "desktopSessionId": "electron-launcher-session-8952-msqairvx",
            "revision": 33,
        },
    )
    monkeypatch.setattr(desktop_entry, "_pid_alive", lambda _pid: False)

    assert desktop_entry._active_electron_desktop_session_for_workspace(desktop_entry.PROJECT_ROOT) == {}


def test_launcher_state_records_workspace_identity_for_future_attach(tmp_path, monkeypatch):
    writes: list[dict[str, object]] = []

    monkeypatch.setattr(desktop_entry, "_write_state", lambda state: writes.append(dict(state)))
    monkeypatch.setattr(desktop_entry, "_select_no_console_python", lambda value: value)
    monkeypatch.setattr(desktop_entry, "LAUNCHER_BROWSER_PROFILE_DIR", tmp_path / "launcher-profile")

    desktop_entry._save_launcher_state(
        {},
        port=8765,
        backend_pid=4321,
        browser_pid=0,
        current_signature="signature",
        python_exe="C:/Python/python.exe",
    )

    assert writes[-1]["runtimeProjectRoot"] == str(desktop_entry.PROJECT_ROOT)


def test_workbench_port_prefers_ports_json_over_config(monkeypatch, tmp_path):
    ports_dir = tmp_path / ".runtime" / "launcher"
    ports_dir.mkdir(parents=True)
    (ports_dir / "ports.json").write_text('{"backendPort": 8002}', encoding="utf-8")

    monkeypatch.setattr(desktop_entry, "PROJECT_ROOT", tmp_path)
    monkeypatch.delenv("VIBELUTION_PORT", raising=False)
    monkeypatch.delenv("AGENT_WORKBENCH_BACKEND_PORT", raising=False)
    monkeypatch.setattr(
        desktop_entry,
        "_config_section",
        lambda name: {"backend_port": 8000} if name == "workbench" else {},
    )

    assert desktop_entry._workbench_port() == 8002


def test_bootstrap_workbench_url_falls_back_to_workbench_port(monkeypatch):
    states = iter(
        [
            {"launcherBackendPid": 0},
            {
                "launcherBackendPid": 0,
                "launcherControlPort": 8765,
                "sessionId": "launcher-session",
                "url": "",
            },
        ]
    )

    monkeypatch.setattr(desktop_entry, "_read_state", lambda: next(states))
    monkeypatch.setattr(desktop_entry, "_open_launcher", lambda args: None)
    monkeypatch.setattr(desktop_entry, "_launcher_control_port", lambda: 8765)
    monkeypatch.setattr(desktop_entry, "_launcher_control_url", lambda port: "http://127.0.0.1:8765/launcher")
    monkeypatch.setattr(desktop_entry, "_launcher_control_healthy", lambda port: True)
    monkeypatch.setattr(desktop_entry, "_workbench_port", lambda: 8002)

    result = desktop_entry._bootstrap_launcher(
        argparse.Namespace(workspace="", config="", no_browser=True, python_exe="")
    )

    assert result["workbenchUrl"] == "http://127.0.0.1:8002"


def test_lifecycle_bridge_parses_operations():
    args = desktop_entry.parse_args(["--action", "lifecycle", "--lifecycle-operation", "restart"])
    assert args.lifecycle_operation == "restart"

def test_lifecycle_bridge_dispatches_start(monkeypatch):
    entry = _load_desktop_entry_py()
    calls = []
    monkeypatch.setattr(entry, "_append_log", lambda *a, **k: None)

    class FakeService:
        class LauncherActiveWorkBlocked(Exception):
            def __init__(self, message, active_work_runs=None):
                super().__init__(message)
                self.message = message
                self.active_work_runs = active_work_runs or []

        @staticmethod
        def request_launcher_start():
            calls.append("start")
            return {"accepted": True, "operation": "start", "commandId": "cmd-1"}

        @staticmethod
        def request_launcher_stop(request_audit=None):
            calls.append("stop")
            return {"accepted": True, "operation": "stop", "commandId": "cmd-2"}

        @staticmethod
        def request_launcher_force_stop(request_audit=None):
            calls.append("force-stop")
            return {"accepted": True, "operation": "force-stop", "commandId": "cmd-3"}

        @staticmethod
        def request_launcher_restart(**kwargs):
            calls.append("restart")
            return {"accepted": True, "operation": "restart", "commandId": "cmd-4"}

        @staticmethod
        def request_launcher_rebuild_and_start():
            calls.append("rebuild-and-start")
            return {"accepted": True, "operation": "rebuild-and-start", "commandId": "cmd-5"}

    monkeypatch.setitem(sys.modules, "core.launcher", types.ModuleType("core.launcher"))
    launcher_module = types.ModuleType("core.launcher.service")
    launcher_module.LauncherActiveWorkBlocked = FakeService.LauncherActiveWorkBlocked
    launcher_module.request_launcher_start = FakeService.request_launcher_start
    launcher_module.request_launcher_stop = FakeService.request_launcher_stop
    launcher_module.request_launcher_force_stop = FakeService.request_launcher_force_stop
    launcher_module.request_launcher_restart = FakeService.request_launcher_restart
    launcher_module.request_launcher_rebuild_and_start = FakeService.request_launcher_rebuild_and_start
    monkeypatch.setitem(sys.modules, "core.launcher.service", launcher_module)

    for operation, expected_call in [
        ("start", "start"),
        ("stop", "stop"),
        ("force-stop", "force-stop"),
        ("restart", "restart"),
        ("rebuild-and-start", "rebuild-and-start"),
    ]:
        payload = entry._run_lifecycle_bridge(argparse.Namespace(lifecycle_operation=operation))
        assert payload["accepted"] is True
        assert calls[-1] == expected_call
        assert payload["schemaVersion"] == 1

def test_lifecycle_bridge_returns_active_work_block(monkeypatch):
    entry = _load_desktop_entry_py()
    monkeypatch.setattr(entry, "_append_log", lambda *a, **k: None)

    class Blocked(Exception):
        def __init__(self, message, active_work_runs=None):
            super().__init__(message)
            self.message = message
            self.active_work_runs = active_work_runs or [{"kind": "agent_turn"}]

    launcher_module = types.ModuleType("core.launcher.service")
    launcher_module.LauncherActiveWorkBlocked = Blocked
    launcher_module.request_launcher_stop = lambda request_audit=None: (_ for _ in ()).throw(Blocked("有进行中的任务"))
    monkeypatch.setitem(sys.modules, "core.launcher", types.ModuleType("core.launcher"))
    monkeypatch.setitem(sys.modules, "core.launcher.service", launcher_module)

    payload = entry._run_lifecycle_bridge(argparse.Namespace(lifecycle_operation="stop"))
    assert payload["accepted"] is False
    assert payload["code"] == "active_work_blocked"
    assert payload["operation"] == "stop"

def test_lifecycle_bridge_rejects_unknown_operation():
    entry = _load_desktop_entry_py()
    with pytest.raises(ValueError):
        entry._run_lifecycle_bridge(argparse.Namespace(lifecycle_operation="taskkill"))
