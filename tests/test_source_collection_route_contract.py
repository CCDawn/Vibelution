"""Source-collection catalog JSON response contract regressions."""

from __future__ import annotations

from core.web.routes.team_workflows.source_collection_catalog_models import (
    SourceCollectionSummaryResponse,
)
from core.web.routes.team_workflows.source_collection_write_models import (
    SourceCollectionAgentSessionContextResponse,
    SourceCollectionCandidateSourceResponse,
    SourceCollectionRunStartResponse,
    SourceCollectionSearchExecuteResponse,
    SourceCollectionSourceCandidateImportResponse,
    SourceCollectionStageSessionTaskResponse,
    SourceCollectionStageWritebackResponse,
    SourceCollectionStorageOpenResponse,
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
    ).model_dump(exclude_unset=True, exclude_none=True)

    assert payload["stageCards"] == [{"stageId": "search", "status": "ready"}]


def test_source_collection_summary_drops_nested_unknowns_and_raw_ingestion_errors() -> None:
    payload = SourceCollectionSummaryResponse.model_validate(
        {
            "stageCards": [
                {
                    "stageId": "ingestion",
                    "latestTask": {
                        "taskId": "task-1",
                        "storagePath": "C:/private/source-collection/run.json",
                        "materializedKnowledgeIngestion": {
                            "status": "failed",
                            "formalKnowledgeItemCount": 0,
                            "failed": [
                                {
                                    "reason": "knowledge_ingestion_failed",
                                    "error": "C:/private/source-collection/private-error.txt",
                                    "storagePath": "C:/private/source-collection/private-error.txt",
                                }
                            ],
                            "unknownDiagnostic": "must not cross the catalog boundary",
                        },
                    },
                }
            ]
        }
    ).model_dump(exclude_unset=True, exclude_none=True)

    latest_task = payload["stageCards"][0]["latestTask"]
    assert "storagePath" not in latest_task
    ingestion = latest_task["materializedKnowledgeIngestion"]
    assert "unknownDiagnostic" not in ingestion
    assert "error" not in ingestion["failed"][0]
    assert "storagePath" not in ingestion["failed"][0]


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


def test_source_collection_write_models_publish_known_schema_fields() -> None:
    expected_properties = {
        SourceCollectionCandidateSourceResponse: {
            "candidate",
            "validation",
            "workflow",
        },
        SourceCollectionSourceCandidateImportResponse: {
            "created",
            "candidate",
            "dataRecordRef",
            "validation",
            "workflow",
        },
        SourceCollectionRunStartResponse: {
            "run",
            "searchPlan",
            "storageArtifacts",
            "researchProjectId",
            "experimentName",
            "assignments",
            "assignmentCount",
            "promptCachePolicy",
            "workflow",
            "nextActions",
            "boundaries",
        },
        SourceCollectionSearchExecuteResponse: {
            "schemaVersion",
            "teamId",
            "runId",
            "status",
            "provider",
            "executedQueryCount",
            "skippedQueryCount",
            "failedQueryCount",
            "resultCount",
            "recordCount",
            "outputCount",
            "importedCount",
            "run",
            "runStatus",
            "storageArtifacts",
            "assignments",
            "boundaries",
            "nextActions",
        },
        SourceCollectionAgentSessionContextResponse: {
            "schemaVersion",
            "teamId",
            "runId",
            "stageId",
            "agentId",
            "agentRole",
            "sessionId",
            "researchProjectId",
            "experimentName",
            "sessionTitle",
            "sessionAttempt",
            "sessionCreated",
            "retryOfSessionId",
            "chatRoute",
            "contextKey",
            "created",
            "alreadyPresent",
            "message",
        },
        SourceCollectionStageSessionTaskResponse: {
            "schemaVersion",
            "teamId",
            "runId",
            "stageId",
            "agentId",
            "agentRole",
            "sessionId",
            "researchProjectId",
            "experimentName",
            "sessionTitle",
            "sessionAttempt",
            "sessionCreated",
            "retryOfSessionId",
            "chatRoute",
            "taskId",
            "idempotencyKey",
            "created",
            "alreadyPresent",
            "task",
            "turn",
            "writebackContract",
            "boundaries",
        },
        SourceCollectionStorageOpenResponse: {
            "schemaVersion",
            "teamId",
            "runId",
            "target",
            "path",
            "openedPath",
            "targetExists",
            "storageArtifacts",
        },
        SourceCollectionStageWritebackResponse: {
            "schemaVersion",
            "teamId",
            "runId",
            "taskId",
            "stageId",
            "agentId",
            "agentRole",
            "task",
            "writeback",
            "boundaries",
        },
    }

    for model, expected in expected_properties.items():
        properties = set(model.model_json_schema().get("properties") or {})
        assert expected <= properties, (
            f"{model.__name__} is missing fields: {sorted(expected - properties)}"
        )


def test_source_collection_write_models_keep_unknown_fields_without_injecting_defaults() -> None:
    background = SourceCollectionSearchExecuteResponse.model_validate(
        {
            "teamId": "team-1",
            "runId": "run-1",
            "status": "accepted",
            "executionMode": "background",
            "accepted": True,
            "activeWorkRun": {"runId": "work-1"},
        }
    ).model_dump(exclude_unset=True)
    assert background == {
        "teamId": "team-1",
        "runId": "run-1",
        "status": "accepted",
        "executionMode": "background",
        "accepted": True,
        "activeWorkRun": {"runId": "work-1"},
    }

    duplicate = SourceCollectionSourceCandidateImportResponse.model_validate(
        {
            "created": False,
            "duplicate": True,
            "duplicateReason": "imported_from_data_record",
            "duplicateOfCandidateId": "cand-1",
            "candidate": {"candidateId": "cand-1"},
        }
    ).model_dump(exclude_unset=True)
    assert duplicate["duplicateReason"] == "imported_from_data_record"
    assert "workflow" not in duplicate
