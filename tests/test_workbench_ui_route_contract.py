"""Workbench UI preference JSON response contract regressions."""

from __future__ import annotations

from fastapi.testclient import TestClient

from core.web.app import create_app
from core.web.control import CONTROL_TOKEN_HEADER, get_control_token
from core.web.routes.workbench_ui_models import (
    WorkbenchUiPreferencesResponse,
    WorkbenchUiPreferencesSaveResponse,
)
from core.web.services import workbench_ui_preferences_service as prefs


def test_workbench_ui_models_publish_known_schema_fields() -> None:
    expected_properties = {
        WorkbenchUiPreferencesResponse: {
            "schemaVersion",
            "paneLayouts",
            "shell",
            "updatedAt",
        },
        WorkbenchUiPreferencesSaveResponse: {"ok", "preferences"},
    }

    for model, expected in expected_properties.items():
        properties = set(model.model_json_schema().get("properties") or {})
        assert expected <= properties, (
            f"{model.__name__} is missing fields: {sorted(expected - properties)}"
        )


def test_workbench_ui_models_keep_unknown_fields() -> None:
    payload = WorkbenchUiPreferencesResponse.model_validate(
        {
            "schemaVersion": 1,
            "paneLayouts": {},
            "shell": {},
            "updatedAt": None,
            "futureChrome": {"dock": "left"},
        }
    ).model_dump()

    assert payload["futureChrome"] == {"dock": "left"}


def test_workbench_ui_preferences_http_round_trip(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(prefs, "PREFERENCES_PATH", tmp_path / "ui-preferences.json")
    client = TestClient(create_app(), headers={CONTROL_TOKEN_HEADER: get_control_token()})

    empty = client.get("/api/workbench/ui-preferences")
    assert empty.status_code == 200
    assert empty.json()["schemaVersion"] == 1
    assert empty.json()["paneLayouts"] == {}
    assert empty.json()["shell"] == {}

    saved = client.put(
        "/api/workbench/ui-preferences",
        json={
            "paneLayouts": {"chat": {"left": 360, "right": 280}},
            "shell": {"topBarMode": "hidden"},
        },
    )
    assert saved.status_code == 200
    payload = saved.json()
    assert payload["ok"] is True
    assert payload["preferences"]["paneLayouts"]["chat"]["left"] == 360
    assert payload["preferences"]["shell"]["topBarMode"] == "hidden"
    assert payload["preferences"]["updatedAt"]
