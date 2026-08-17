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
    assert "chatPanelWidths" not in saved["shell"]
    assert path.is_file()

    reloaded = prefs.load_workbench_ui_preferences()
    assert reloaded["paneLayouts"]["chat"]["right"] == 280
    assert "chatPanelWidths" not in reloaded["shell"]


def test_workbench_ui_preferences_migrates_leftover_shell_chat_widths(tmp_path, monkeypatch):
    path = tmp_path / "ui-preferences.json"
    monkeypatch.setattr(prefs, "PREFERENCES_PATH", path)
    path.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "paneLayouts": {},
                "shell": {
                    "chatPanelWidths": {"leftPanelWidth": 412, "rightPanelWidth": 268},
                    "topBarMode": "full",
                },
            }
        ),
        encoding="utf-8",
    )

    loaded = prefs.load_workbench_ui_preferences()
    assert loaded["paneLayouts"]["chat"] == {"left": 412, "right": 268}
    assert "chatPanelWidths" not in loaded["shell"]
    assert loaded["shell"]["topBarMode"] == "full"
    persisted = json.loads(path.read_text(encoding="utf-8"))
    assert persisted["paneLayouts"]["chat"] == {"left": 412, "right": 268}
    assert "chatPanelWidths" not in persisted["shell"]


def test_workbench_ui_preferences_drops_damaged_leftover_chat_widths(tmp_path, monkeypatch):
    path = tmp_path / "ui-preferences.json"
    monkeypatch.setattr(prefs, "PREFERENCES_PATH", path)
    path.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "paneLayouts": {},
                "shell": {"chatPanelWidths": "nope", "topBarMode": "full"},
            }
        ),
        encoding="utf-8",
    )

    loaded = prefs.load_workbench_ui_preferences()
    assert "chat" not in loaded["paneLayouts"]
    assert "chatPanelWidths" not in loaded["shell"]
    assert loaded["shell"]["topBarMode"] == "full"


def test_workbench_ui_preferences_does_not_clobber_canonical_chat_layout(tmp_path, monkeypatch):
    path = tmp_path / "ui-preferences.json"
    monkeypatch.setattr(prefs, "PREFERENCES_PATH", path)
    prefs.save_workbench_ui_preferences({"paneLayouts": {"chat": {"left": 300, "right": 220}}})
    saved = prefs.save_workbench_ui_preferences(
        {"shell": {"chatPanelWidths": {"leftPanelWidth": 999, "rightPanelWidth": 888}}}
    )
    assert saved["paneLayouts"]["chat"] == {"left": 300, "right": 220}
    assert "chatPanelWidths" not in saved["shell"]


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
