"""Research-loop JSON response contract regressions."""

from __future__ import annotations

import ast
from pathlib import Path

from core.web.routes.research_loop_models import (
    ResearchLoopCreateResponse,
    ResearchLoopDecisionResponse,
    ResearchLoopEvidenceResponse,
    ResearchLoopStatusResponse,
    ResearchLoopTemplatesResponse,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
ROUTE_FILE = REPO_ROOT / "core" / "web" / "routes" / "research_loop.py"

JSON_ROUTE_FUNCTIONS = {
    "team_research_loop_templates",
    "team_research_loop_status",
    "team_research_loop_create",
    "team_research_loop_evidence_record",
    "team_research_loop_decision_record",
    "team_research_loop_iteration_design_materialize",
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


def test_research_loop_json_routes_declare_response_model() -> None:
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
    assert missing == [], f"research-loop JSON routes must declare response_model: {missing}"


def test_research_loop_models_publish_known_schema_fields() -> None:
    expected_properties = {
        ResearchLoopTemplatesResponse: {
            "schemaVersion",
            "defaultTemplateId",
            "templates",
            "boundaries",
        },
        ResearchLoopStatusResponse: {
            "schemaVersion",
            "storeKind",
            "teamId",
            "team",
            "activeLoopId",
            "activeLoop",
            "loops",
            "historicalEmptyLoops",
            "pendingDesignProposals",
            "summary",
            "templates",
            "storagePath",
            "nextActions",
            "boundaries",
            "researchProjectId",
        },
        ResearchLoopCreateResponse: {"loop", "status", "boundaries"},
        ResearchLoopEvidenceResponse: {
            "evidence",
            "loop",
            "status",
            "idempotency",
            "boundaries",
        },
        ResearchLoopDecisionResponse: {
            "decision",
            "iterationProposal",
            "nextDesignDraft",
            "loop",
            "status",
            "boundaries",
            "idempotentReplay",
        },
    }

    for model, expected in expected_properties.items():
        properties = set(model.model_json_schema().get("properties") or {})
        assert expected <= properties, (
            f"{model.__name__} is missing fields: {sorted(expected - properties)}"
        )


def test_research_loop_models_keep_unknown_fields_without_injecting_defaults() -> None:
    templates = ResearchLoopTemplatesResponse.model_validate(
        {"schemaVersion": 1, "customBoundary": {"sandboxRunner": False}}
    ).model_dump(exclude_unset=True)
    assert templates == {
        "schemaVersion": 1,
        "customBoundary": {"sandboxRunner": False},
    }

    status = ResearchLoopStatusResponse.model_validate(
        {
            "teamId": "team-1",
            "summary": {"readyForIterationCount": 1, "customCount": 2},
            "futureHint": True,
        }
    ).model_dump(exclude_unset=True)
    assert status == {
        "teamId": "team-1",
        "summary": {"readyForIterationCount": 1, "customCount": 2},
        "futureHint": True,
    }

    created = ResearchLoopCreateResponse.model_validate(
        {"loop": {"loopId": "loop-1", "executionPolicy": {"autoExecution": False}}}
    ).model_dump(exclude_unset=True)
    assert created == {
        "loop": {"loopId": "loop-1", "executionPolicy": {"autoExecution": False}}
    }

    evidence = ResearchLoopEvidenceResponse.model_validate(
        {"evidence": {"evidenceId": "ev-1", "customMetric": "0.84"}}
    ).model_dump(exclude_unset=True)
    assert evidence == {"evidence": {"evidenceId": "ev-1", "customMetric": "0.84"}}

    decision = ResearchLoopDecisionResponse.model_validate(
        {
            "loop": {"loopId": "loop-1", "decisions": [{"decisionId": "d1"}]},
            "iterationProposal": {"nextTemplateId": "dataset_benchmark"},
            "payload": {"createdByAgent": "Research Coordination Agent"},
        }
    ).model_dump(exclude_unset=True)
    assert decision == {
        "loop": {"loopId": "loop-1", "decisions": [{"decisionId": "d1"}]},
        "iterationProposal": {"nextTemplateId": "dataset_benchmark"},
        "payload": {"createdByAgent": "Research Coordination Agent"},
    }
