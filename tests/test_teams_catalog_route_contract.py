"""Team catalog JSON response contract regressions."""

from __future__ import annotations

from core.web.routes.teams_catalog_models import (
    TeamAiSearchRunListResponse,
    TeamCanvasResponse,
    TeamDetailResponse,
    TeamListResponse,
)


def test_team_catalog_models_publish_known_schema_fields() -> None:
    expected_properties = {
        TeamListResponse: {
            "schemaVersion",
            "teams",
            "summary",
            "updatedAt",
            "storage",
            "systemTeamBootstrap",
        },
        TeamDetailResponse: {"teamId"},
        TeamCanvasResponse: {
            "schemaVersion",
            "canvasKind",
            "teamId",
            "updatedAt",
            "path",
            "viewport",
            "nodes",
            "edges",
            "validation",
        },
        TeamAiSearchRunListResponse: {
            "schemaVersion",
            "teamId",
            "runs",
            "summary",
            "storage",
            "updatedAt",
        },
    }

    for model, expected in expected_properties.items():
        properties = set(model.model_json_schema().get("properties") or {})
        assert expected <= properties, (
            f"{model.__name__} is missing fields: {sorted(expected - properties)}"
        )


def test_team_catalog_models_keep_unknown_fields() -> None:
    listed = TeamListResponse.model_validate(
        {
            "schemaVersion": 1,
            "teams": [{"teamId": "team-1", "memberCount": 3}],
            "systemTeamBootstrap": {"status": "ready"},
        }
    ).model_dump()
    assert listed["teams"][0]["memberCount"] == 3
    assert listed["systemTeamBootstrap"] == {"status": "ready"}

    canvas = TeamCanvasResponse.model_validate(
        {
            "teamId": "team-1",
            "nodes": [{"id": "n-1", "role": "lead"}],
            "validation": {"valid": True},
        }
    ).model_dump()
    assert canvas["nodes"] == [{"id": "n-1", "role": "lead"}]
    assert canvas["validation"] == {"valid": True}


def test_team_catalog_models_keep_unknown_fields_without_injecting_defaults() -> None:
    payload = TeamListResponse.model_validate(
        {
            "schemaVersion": 1,
            "teams": [{"teamId": "team-1"}],
            "futureHint": {"owner": "teams"},
        }
    ).model_dump(exclude_unset=True)

    assert payload == {
        "schemaVersion": 1,
        "teams": [{"teamId": "team-1"}],
        "futureHint": {"owner": "teams"},
    }
