"""Data-processing JSON response contract regressions."""

from __future__ import annotations

import ast
from pathlib import Path

from core.web.routes.data_processing_models import (
    DataProcessingCollectionAssignmentListResponse,
    DataProcessingCollectionAssignmentResponse,
    DataProcessingCollectionOutputResponse,
    DataProcessingProfileResponse,
    DataProcessingProfilesResponse,
    DataProcessingRecordListResponse,
    DataProcessingRecordResponse,
    DataProcessingRunListResponse,
    DataProcessingRunResponse,
    DataProcessingRunStatusResponse,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
ROUTE_FILE = REPO_ROOT / "core" / "web" / "routes" / "data_processing.py"

JSON_ROUTE_FUNCTIONS = {
    "data_processing_profiles",
    "data_processing_profile_detail",
    "data_processing_run_create",
    "data_processing_run_list",
    "data_processing_run_detail",
    "data_processing_records",
    "data_processing_record_create",
    "data_processing_collection_assignments",
    "data_processing_collection_assignment_create",
    "data_processing_collection_output_create",
    "data_processing_run_status",
}


def _is_router_decorator(decorator: ast.Call) -> bool:
    function = decorator.func
    return (
        isinstance(function, ast.Attribute)
        and isinstance(function.value, ast.Name)
        and function.value.id.lower().endswith("router")
    )


def _route_decorators() -> dict[str, ast.Call]:
    tree = ast.parse(ROUTE_FILE.read_text(encoding="utf-8"))
    found: dict[str, ast.Call] = {}
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            if isinstance(decorator, ast.Call) and _is_router_decorator(decorator):
                found[node.name] = decorator
    return found


def test_data_processing_json_routes_declare_response_model() -> None:
    decorators = _route_decorators()
    missing = []
    for name in sorted(JSON_ROUTE_FUNCTIONS):
        decorator = decorators.get(name)
        if decorator is None:
            missing.append(name)
            continue
        has_response_model = any(
            keyword.arg == "response_model"
            and not (isinstance(keyword.value, ast.Constant) and keyword.value.value is None)
            for keyword in decorator.keywords
        )
        has_exclude_unset = any(
            keyword.arg == "response_model_exclude_unset"
            and isinstance(keyword.value, ast.Constant)
            and keyword.value.value is True
            for keyword in decorator.keywords
        )
        if not has_response_model or not has_exclude_unset:
            missing.append(name)
    assert missing == [], f"data-processing JSON routes must declare response_model: {missing}"


def test_data_processing_models_publish_known_schema_fields() -> None:
    expected_properties = {
        DataProcessingProfilesResponse: {"schemaVersion", "defaultProfileId", "profiles"},
        DataProcessingProfileResponse: {"schemaVersion", "profileId", "displayName", "description"},
        DataProcessingRunResponse: {
            "schemaVersion",
            "runId",
            "profileId",
            "title",
            "status",
            "scope",
            "metadata",
            "createdAt",
            "updatedAt",
            "storage",
            "summary",
            "processingStatus",
        },
        DataProcessingRunListResponse: {"schemaVersion", "runs", "summary"},
        DataProcessingRunStatusResponse: {
            "schemaVersion",
            "runId",
            "profileId",
            "runStatus",
            "summary",
            "nextActions",
            "boundaries",
        },
        DataProcessingRecordListResponse: {"schemaVersion", "runId", "records", "summary"},
        DataProcessingRecordResponse: {
            "schemaVersion",
            "recordId",
            "runId",
            "sourceType",
            "sourceRef",
            "title",
            "status",
            "collectionTrace",
        },
        DataProcessingCollectionAssignmentListResponse: {
            "schemaVersion",
            "runId",
            "assignments",
            "summary",
        },
        DataProcessingCollectionAssignmentResponse: {
            "schemaVersion",
            "assignmentId",
            "runId",
            "agentRole",
            "agentId",
            "status",
            "scope",
        },
        DataProcessingCollectionOutputResponse: {"output", "createdRecords"},
    }

    for model, expected in expected_properties.items():
        properties = set(model.model_json_schema().get("properties") or {})
        assert expected <= properties, (
            f"{model.__name__} is missing fields: {sorted(expected - properties)}"
        )


def test_data_processing_models_keep_unknown_fields_without_injecting_defaults() -> None:
    profiles = DataProcessingProfilesResponse.model_validate(
        {"schemaVersion": 1, "futureCatalog": True}
    ).model_dump(exclude_unset=True)
    assert profiles == {"schemaVersion": 1, "futureCatalog": True}

    run = DataProcessingRunResponse.model_validate(
        {"runId": "dprun-1", "storage": {"runPath": "workspace/x"}, "customHint": True}
    ).model_dump(exclude_unset=True)
    assert run == {
        "runId": "dprun-1",
        "storage": {"runPath": "workspace/x"},
        "customHint": True,
    }

    listed = DataProcessingRunListResponse.model_validate(
        {"runs": [{"runId": "dprun-1", "extraRun": True}], "summary": {"filtered": True}}
    ).model_dump(exclude_unset=True)
    assert listed == {
        "runs": [{"runId": "dprun-1", "extraRun": True}],
        "summary": {"filtered": True},
    }

    status = DataProcessingRunStatusResponse.model_validate(
        {
            "runId": "dprun-1",
            "summary": {"recordCount": 1},
            "boundaries": {"writesKnowledgeGraph": False, "customBound": True},
        }
    ).model_dump(exclude_unset=True)
    assert status == {
        "runId": "dprun-1",
        "summary": {"recordCount": 1},
        "boundaries": {"writesKnowledgeGraph": False, "customBound": True},
    }

    output = DataProcessingCollectionOutputResponse.model_validate(
        {
            "createdRecords": [
                {"recordId": "dprec-1", "collectionTrace": {"agentRole": "source_finder"}}
            ]
        }
    ).model_dump(exclude_unset=True)
    assert output == {
        "createdRecords": [
            {"recordId": "dprec-1", "collectionTrace": {"agentRole": "source_finder"}}
        ]
    }
