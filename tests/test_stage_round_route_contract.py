"""Research stage-round JSON response contract regressions."""

from __future__ import annotations

from core.web.routes.team_workflows.stage_rounds_models import (
    ResearchStageRoundStartResponse,
    ResearchStageRoundStatusResponse,
)


def test_stage_round_models_publish_known_schema_fields() -> None:
    expected_properties = {
        ResearchStageRoundStatusResponse: {
            "schemaVersion",
            "teamId",
            "status",
            "currentStage",
            "phases",
            "activeRounds",
            "latestRound",
            "roundCount",
            "storagePath",
            "boundaries",
            "updatedAt",
        },
        ResearchStageRoundStartResponse: {"created"},
    }

    for model, expected in expected_properties.items():
        properties = set(model.model_json_schema().get("properties") or {})
        assert expected <= properties, (
            f"{model.__name__} is missing fields: {sorted(expected - properties)}"
        )


def test_stage_round_status_keeps_unknown_fields() -> None:
    payload = ResearchStageRoundStatusResponse.model_validate(
        {
            "teamId": "team-1",
            "status": "active",
            "phases": [{"stageType": "knowledge_collection"}],
        }
    ).model_dump()

    assert payload["phases"] == [{"stageType": "knowledge_collection"}]


def test_stage_round_status_keeps_unknown_fields_without_injecting_defaults() -> None:
    payload = ResearchStageRoundStatusResponse.model_validate(
        {
            "teamId": "team-1",
            "status": "idle",
            "futureHint": {"owner": "stage_rounds"},
        }
    ).model_dump(exclude_unset=True)

    assert payload == {
        "teamId": "team-1",
        "status": "idle",
        "futureHint": {"owner": "stage_rounds"},
    }
