from __future__ import annotations

import json
from pathlib import Path

import core.web.services.workbench_ui_preferences_service as prefs


def test_workbench_ui_preferences_round_trip(tmp_path, monkeypatch):
    path = tmp_path / "ui-preferences.json"
    monkeypatch.setattr(prefs, "PREFERENCES_PATH", path)

    empty = prefs.load_workbench_ui_preferences()
    assert empty["paneLayouts"] == {}
    assert empty["shell"] == {}

    saved = prefs.save_workbench_ui_preferences(
        {
            "paneLayouts": {"chat": {"left": 360, "right": 280}},
            "shell": {
                "chatPanelWidths": {"leftPanelWidth": 360, "rightPanelWidth": 280},
                "topBarMode": "hidden",
            },
        }
    )
    assert saved["paneLayouts"]["chat"]["left"] == 360
    assert saved["shell"]["topBarMode"] == "hidden"
    assert path.is_file()

    reloaded = prefs.load_workbench_ui_preferences()
    assert reloaded["paneLayouts"]["chat"]["right"] == 280
    assert reloaded["shell"]["chatPanelWidths"]["leftPanelWidth"] == 360


def test_workbench_ui_preferences_merge_single_layout(tmp_path, monkeypatch):
    path = tmp_path / "ui-preferences.json"
    monkeypatch.setattr(prefs, "PREFERENCES_PATH", path)
    prefs.save_workbench_ui_preferences({"paneLayouts": {"chat": {"left": 300, "right": 220}}})
    prefs.save_workbench_ui_preferences(
        {"paneLayout": {"layoutId": "agents", "widths": {"sidebar": 412}}}
    )
    data = prefs.load_workbench_ui_preferences()
    assert data["paneLayouts"]["chat"]["left"] == 300
    assert data["paneLayouts"]["agents"]["sidebar"] == 412
    # File is valid JSON for operators/debugging.
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    assert raw["schemaVersion"] == 1
