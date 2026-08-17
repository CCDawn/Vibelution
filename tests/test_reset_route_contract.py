"""Retired reset JSON response contract regressions."""

from __future__ import annotations

from core.web.routes.reset_models import ResetMigratedResponse


def test_reset_migrated_response_publishes_known_schema_fields() -> None:
    properties = set(ResetMigratedResponse.model_json_schema().get("properties") or {})
    expected = {"code", "message", "launcherPath"}
    assert expected <= properties, (
        f"ResetMigratedResponse is missing fields: {sorted(expected - properties)}"
    )


def test_reset_migrated_response_keeps_unknown_fields() -> None:
    payload = ResetMigratedResponse.model_validate(
        {
            "code": "reset_migrated_to_launcher",
            "message": "moved",
            "launcherPath": "/launcher",
            "futureHint": {"owner": "launcher"},
        }
    ).model_dump()

    assert payload["futureHint"] == {"owner": "launcher"}
