from __future__ import annotations

import argparse
import importlib.util
import os
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
