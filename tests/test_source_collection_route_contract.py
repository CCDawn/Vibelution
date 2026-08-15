"""Source-collection catalog JSON response contract regressions."""

from __future__ import annotations

from core.web.routes.team_workflows.source_collection_catalog_models import (
    SourceCollectionSummaryResponse,
)


def test_source_collection_summary_publishes_known_schema_fields() -> None:
    properties = set(SourceCollectionSummaryResponse.model_json_schema().get("properties") or {})
    expected = {
        "schemaVersion",
        "teamId",
        "runId",
        "status",
        "run",
        "runStatus",
        "searchPlan",
        "scope",
        "summary",
        "stageCards",
        "stageCardSummary",
        "phaseCloseGate",
        "latestTasks",
        "stageRound",
        "activeWorkRun",
        "storageArtifacts",
        "boundaries",
        "updatedAt",
    }
    assert expected <= properties, (
        f"SourceCollectionSummaryResponse is missing fields: {sorted(expected - properties)}"
    )


def test_source_collection_summary_keeps_unknown_fields() -> None:
    payload = SourceCollectionSummaryResponse.model_validate(
        {
            "teamId": "team-1",
            "runId": "run-1",
            "stageCards": [{"stageId": "search", "status": "ready"}],
        }
    ).model_dump()

    assert payload["stageCards"] == [{"stageId": "search", "status": "ready"}]


def test_source_collection_summary_keeps_unknown_fields_without_injecting_defaults() -> None:
    payload = SourceCollectionSummaryResponse.model_validate(
        {
            "teamId": "team-1",
            "status": "idle",
            "futureHint": {"owner": "source_collection"},
        }
    ).model_dump(exclude_unset=True)

    assert payload == {
        "teamId": "team-1",
        "status": "idle",
        "futureHint": {"owner": "source_collection"},
    }
