"""Computer Use JSON response contract regressions."""

from __future__ import annotations

from core.web.routes.computer_use_models import ComputerUseSessionResponse


def test_computer_use_session_publishes_known_schema_fields() -> None:
    properties = set(ComputerUseSessionResponse.model_json_schema().get("properties") or {})
    expected = {
        "sessionId",
        "status",
        "summary",
        "screenshotUrl",
        "needsConfirmation",
        "error",
        "mode",
        "targetUrl",
        "allowedDomains",
        "actionCount",
        "requestedActions",
        "steps",
        "createdAt",
        "updatedAt",
        "durationMs",
    }
    assert expected <= properties, (
        f"ComputerUseSessionResponse is missing fields: {sorted(expected - properties)}"
    )


def test_computer_use_session_keeps_unknown_fields() -> None:
    payload = ComputerUseSessionResponse.model_validate(
        {
            "sessionId": "cu-1",
            "status": "completed",
            "futureTrace": {"provider": "open-computer-use"},
        }
    ).model_dump()

    assert payload["futureTrace"] == {"provider": "open-computer-use"}
