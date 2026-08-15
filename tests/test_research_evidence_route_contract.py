"""Research-evidence JSON response contract regressions."""

from __future__ import annotations

import ast
from pathlib import Path

from core.web.routes.research_evidence_models import (
    ClaimEvidenceCoverageResponse,
    ClaimEvidenceItemResponse,
    ClaimEvidenceListResponse,
    ClaimEvidenceReconcileResponse,
    ResearchQuestionTreeListResponse,
    ResearchQuestionTreeResponse,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
ROUTE_FILE = REPO_ROOT / "core" / "web" / "routes" / "research_evidence.py"

JSON_ROUTE_FUNCTIONS = {
    "create_claim_evidence",
    "get_claim_evidence",
    "review_claim_evidence",
    "get_claim_evidence_coverage",
    "legacy_evidence_projection",
    "reconcile_source_revision",
    "create_research_question_tree",
    "list_research_question_trees",
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


def test_research_evidence_json_routes_declare_response_model() -> None:
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
    assert missing == [], f"research-evidence JSON routes must declare response_model: {missing}"


def test_research_evidence_models_publish_known_schema_fields() -> None:
    expected_properties = {
        ClaimEvidenceItemResponse: {"schemaVersion", "team", "evidence", "boundaries"},
        ClaimEvidenceListResponse: {"schemaVersion", "team", "evidence", "summary", "boundaries"},
        ClaimEvidenceCoverageResponse: {
            "evidenceGatePassed",
            "formalKnowledgeWriteAllowed",
            "boundaries",
        },
        ClaimEvidenceReconcileResponse: {"schemaVersion", "team", "result", "boundaries"},
        ResearchQuestionTreeResponse: {"schemaVersion", "team", "questionTree", "boundaries"},
        ResearchQuestionTreeListResponse: {
            "schemaVersion",
            "team",
            "questionTrees",
            "summary",
            "boundaries",
        },
    }

    for model, expected in expected_properties.items():
        properties = set(model.model_json_schema().get("properties") or {})
        assert expected <= properties, (
            f"{model.__name__} is missing fields: {sorted(expected - properties)}"
        )


def test_research_evidence_models_keep_unknown_fields_without_injecting_defaults() -> None:
    item = ClaimEvidenceItemResponse.model_validate(
        {
            "evidence": {"claimEvidenceId": "ce-1", "reviewStatus": "accepted"},
            "futureHint": True,
        }
    ).model_dump(exclude_unset=True)
    assert item == {
        "evidence": {"claimEvidenceId": "ce-1", "reviewStatus": "accepted"},
        "futureHint": True,
    }
    assert "schemaVersion" not in item

    coverage = ClaimEvidenceCoverageResponse.model_validate(
        {
            "evidenceGatePassed": True,
            "formalKnowledgeWriteAllowed": False,
            "counterEvidencePresent": False,
        }
    ).model_dump(exclude_unset=True)
    assert coverage == {
        "evidenceGatePassed": True,
        "formalKnowledgeWriteAllowed": False,
        "counterEvidencePresent": False,
    }
    assert "summary" not in coverage
