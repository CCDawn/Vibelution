from __future__ import annotations

import argparse

import scripts.vibelution_desktop_entry as desktop_entry


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
