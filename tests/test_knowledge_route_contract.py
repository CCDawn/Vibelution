"""Team workflow knowledge JSON response contract regressions."""

from __future__ import annotations

from core.web.routes.team_workflows.knowledge_models import (
    CandidateGraphBuildResponse,
    CandidateSourceExtractionResponse,
    CoordinationStatusResponse,
    KnowledgeCollectionCompleteResponse,
    KnowledgeCollectionExtractResponse,
    KnowledgeCollectionIngestResponse,
    KnowledgeIngestionPrecheckResponse,
    KnowledgeIngestionStatusResponse,
    PaperNoteDraftResponse,
)


def test_knowledge_status_models_publish_known_schema_fields() -> None:
    expected_properties = {
        KnowledgeIngestionStatusResponse: {
            "schemaVersion",
            "teamId",
            "workflowId",
            "workflowKind",
            "scope",
            "status",
            "summary",
            "stages",
            "actionItems",
            "candidateBreakdown",
            "candidateGraphSummary",
            "officialBoundary",
            "knowledgeBases",
            "storage",
            "activeWorkRun",
            "latestWorkRun",
            "updatedAt",
        },
        CoordinationStatusResponse: {
            "schemaVersion",
            "teamId",
            "workflowId",
            "workflowKind",
            "scope",
            "status",
            "ownerAgentId",
            "summary",
            "queues",
            "actionItems",
            "communication",
            "coordinationPolicy",
            "storage",
            "updatedAt",
        },
    }

    for model, expected in expected_properties.items():
        properties = set(model.model_json_schema().get("properties") or {})
        assert expected <= properties, (
            f"{model.__name__} is missing fields: {sorted(expected - properties)}"
        )


def test_knowledge_status_models_keep_unknown_fields() -> None:
    payload = KnowledgeIngestionStatusResponse.model_validate(
        {
            "teamId": "team-1",
            "status": "ready",
            "officialBoundary": {"writesOfficialRag": False},
        }
    ).model_dump()

    assert payload["officialBoundary"] == {"writesOfficialRag": False}

    coordinated = CoordinationStatusResponse.model_validate(
        {
            "teamId": "team-1",
            "queues": {"pendingTransfers": [{"candidateId": "c-1"}]},
        }
    ).model_dump()
    assert coordinated["queues"]["pendingTransfers"] == [{"candidateId": "c-1"}]


def test_knowledge_status_models_keep_unknown_fields_without_injecting_defaults() -> None:
    payload = KnowledgeIngestionStatusResponse.model_validate(
        {
            "teamId": "team-1",
            "status": "in_progress",
            "futureHint": {"owner": "knowledge"},
        }
    ).model_dump(exclude_unset=True)

    assert payload == {
        "teamId": "team-1",
        "status": "in_progress",
        "futureHint": {"owner": "knowledge"},
    }


def test_knowledge_write_models_publish_known_schema_fields() -> None:
    expected_properties = {
        KnowledgeIngestionPrecheckResponse: {
            "candidate",
            "validation",
            "precheck",
            "status",
            "workflow",
            "reusedStewardPack",
            "ingestionFingerprint",
        },
        KnowledgeCollectionExtractResponse: {
            "schemaVersion",
            "teamId",
            "runId",
            "status",
            "recordCount",
            "candidateCount",
            "pendingRecordCount",
            "importedCount",
            "skippedCount",
            "failedCount",
            "workflow",
            "boundaries",
        },
        KnowledgeCollectionIngestResponse: {
            "schemaVersion",
            "teamId",
            "status",
            "executionMode",
            "accepted",
            "alreadyRunning",
            "activeWorkRun",
            "steps",
            "sourceQuality",
            "candidateGraph",
            "precheck",
            "sourceReview",
            "knowledgeSubmission",
            "knowledgeReview",
            "knowledgeStewardActivation",
            "reusedCandidateGraph",
            "reusedStewardPack",
            "ingestionFingerprint",
            "knowledgeBase",
            "statusSnapshot",
            "summary",
            "nextActions",
            "workflow",
        },
        KnowledgeCollectionCompleteResponse: {
            "schemaVersion",
            "teamId",
            "status",
            "executionMode",
            "accepted",
            "alreadyRunning",
            "activeWorkRun",
            "summary",
            "nextActions",
        },
        CandidateGraphBuildResponse: {
            "candidateGraph",
            "graph",
            "workflow",
            "reusedCandidateGraph",
            "ingestionFingerprint",
        },
        CandidateSourceExtractionResponse: {
            "candidate",
            "sourceExtraction",
            "validation",
            "workflow",
        },
        PaperNoteDraftResponse: {
            "candidate",
            "validation",
            "task",
            "modelResponse",
            "sourceCandidate",
            "workflow",
        },
    }

    for model, expected in expected_properties.items():
        properties = set(model.model_json_schema().get("properties") or {})
        assert expected <= properties, (
            f"{model.__name__} is missing fields: {sorted(expected - properties)}"
        )


def test_knowledge_write_models_keep_unknown_fields_without_injecting_defaults() -> None:
    background = KnowledgeCollectionIngestResponse.model_validate(
        {
            "teamId": "team-1",
            "status": "accepted",
            "executionMode": "background",
            "activeWorkRun": {"runId": "ingest-1"},
        }
    ).model_dump(exclude_unset=True)
    assert background == {
        "teamId": "team-1",
        "status": "accepted",
        "executionMode": "background",
        "activeWorkRun": {"runId": "ingest-1"},
    }

    sync = KnowledgeCollectionIngestResponse.model_validate(
        {
            "teamId": "team-1",
            "status": "blocked",
            "steps": [{"stageId": "source_review", "status": "blocked"}],
            "futureHint": {"owner": "knowledge-ingest"},
        }
    ).model_dump(exclude_unset=True)
    assert sync["futureHint"] == {"owner": "knowledge-ingest"}
    assert "executionMode" not in sync