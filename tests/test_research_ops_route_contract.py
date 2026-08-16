"""Team workflow research-ops read JSON response contract regressions."""

from __future__ import annotations

from core.web.routes.team_workflows.research_ops_models import (
    OfficialModelEvidenceStatusResponse,
    PaperNoteChunkStatusResponse,
    ResearchOpsRouteResponse,
    SourceQualityStatusResponse,
)


def test_research_ops_read_models_publish_known_schema_fields() -> None:
    expected_properties = {
        PaperNoteChunkStatusResponse: {
            "schemaVersion",
            "teamId",
            "workflowId",
            "workflowKind",
            "status",
            "summary",
            "plans",
            "missingPlanSources",
            "actionItems",
            "officialBoundary",
            "storage",
            "updatedAt",
        },
        SourceQualityStatusResponse: {
            "schemaVersion",
            "teamId",
            "workflowId",
            "workflowKind",
            "scope",
            "status",
            "summary",
            "candidates",
            "actionItems",
            "screeningContract",
            "officialBoundary",
            "storage",
            "updatedAt",
        },
        OfficialModelEvidenceStatusResponse: {
            "schemaVersion",
            "teamId",
            "workflowId",
            "workflowKind",
            "scope",
            "status",
            "summary",
            "coverage",
            "providerCounts",
            "evidenceKindCounts",
            "recentEvidence",
            "actionItems",
            "officialBoundary",
            "storage",
            "updatedAt",
        },
    }

    for model, expected in expected_properties.items():
        properties = set(model.model_json_schema().get("properties") or {})
        assert expected <= properties, (
            f"{model.__name__} is missing fields: {sorted(expected - properties)}"
        )


def test_research_ops_read_models_keep_unknown_fields() -> None:
    paper_note = PaperNoteChunkStatusResponse.model_validate(
        {
            "teamId": "team-1",
            "status": "needs_plan",
            "plans": [{"planId": "plan-1", "chunkCount": 3}],
        }
    ).model_dump()
    assert paper_note["plans"][0]["chunkCount"] == 3

    source_quality = SourceQualityStatusResponse.model_validate(
        {
            "teamId": "team-1",
            "status": "needs_screening",
            "candidates": [{"candidateId": "c-1", "bucket": "pending"}],
        }
    ).model_dump()
    assert source_quality["candidates"][0]["bucket"] == "pending"

    evidence = OfficialModelEvidenceStatusResponse.model_validate(
        {
            "teamId": "team-1",
            "status": "needs_evidence",
            "coverage": [{"workflowNode": "stage1", "status": "missing"}],
        }
    ).model_dump()
    assert evidence["coverage"][0]["workflowNode"] == "stage1"


def test_research_ops_read_models_keep_unknown_fields_without_injecting_defaults() -> None:
    payload = SourceQualityStatusResponse.model_validate(
        {
            "teamId": "team-1",
            "status": "ready",
            "futureHint": {"owner": "research-ops"},
        }
    ).model_dump(exclude_unset=True)

    assert payload == {
        "teamId": "team-1",
        "status": "ready",
        "futureHint": {"owner": "research-ops"},
    }


def test_research_ops_write_catch_all_remains_empty_shell() -> None:
    properties = set(ResearchOpsRouteResponse.model_json_schema().get("properties") or {})
    assert properties == set()
