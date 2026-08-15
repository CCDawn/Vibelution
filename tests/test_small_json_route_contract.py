"""Usage, diagnostics, skills, and pet JSON response contract regressions."""

from __future__ import annotations

from core.web.routes.diagnostics_models import HealthDiagnosticsResponse
from core.web.routes.pet_models import PetActionResponse, PetSummaryResponse
from core.web.routes.skills_models import SkillLibraryDetailResponse, SkillLibraryResponse
from core.web.routes.usage_models import UsageSummaryResponse


def test_small_json_route_models_publish_known_schema_fields() -> None:
    expected_properties = {
        UsageSummaryResponse: {"scope", "filters", "updatedAt"},
        HealthDiagnosticsResponse: {"status", "summary"},
        SkillLibraryResponse: {"schemaVersion", "mode"},
        SkillLibraryDetailResponse: {"command", "name"},
        PetSummaryResponse: {"name", "avatarPreset"},
        PetActionResponse: {"action", "message"},
    }

    for model, expected in expected_properties.items():
        properties = set(model.model_json_schema().get("properties") or {})
        assert expected <= properties, (
            f"{model.__name__} is missing fields: {sorted(expected - properties)}"
        )


def test_small_json_route_models_keep_unknown_fields() -> None:
    payload = UsageSummaryResponse.model_validate(
        {
            "scope": "global",
            "filters": {"sessionId": ""},
            "updatedAt": "2026-08-16T00:00:00Z",
            "lastTokenUsage": {"totalTokens": 12},
        }
    ).model_dump()

    assert payload["lastTokenUsage"] == {"totalTokens": 12}
    assert HealthDiagnosticsResponse.model_validate(
        {"status": "ok", "summary": "fine", "counts": {"ok": 1}}
    ).model_dump()["counts"] == {"ok": 1}
