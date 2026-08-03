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
