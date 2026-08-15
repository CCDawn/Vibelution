"""Config shell and media response contract regressions."""

from __future__ import annotations

from core.web.routes.config_apply_shell_models import (
    ConfigImageUploadResponse,
    ConfigOpenEnvironmentResponse,
)


def test_config_shell_response_models_publish_known_schema_fields() -> None:
    expected_properties = {
        ConfigOpenEnvironmentResponse: {
            "opened",
            "focused",
            "method",
            "cleanup_ok",
            "cleanup_error",
        },
        ConfigImageUploadResponse: {
            "path",
            "url",
            "contentType",
            "sizeBytes",
        },
    }

    for model, expected in expected_properties.items():
        properties = set(model.model_json_schema().get("properties") or {})
        assert expected <= properties, (
            f"{model.__name__} is missing fields: {sorted(expected - properties)}"
        )


def test_config_shell_response_models_keep_unknown_fields() -> None:
    payload = ConfigImageUploadResponse.model_validate(
        {
            "path": "theme_backgrounds/background.png",
            "url": "/api/config/theme-background-image/background.png",
            "contentType": "image/png",
            "sizeBytes": 128,
            "futureEvidence": {"source": "operator"},
        }
    ).model_dump()

    assert payload["futureEvidence"] == {"source": "operator"}
