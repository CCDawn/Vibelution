"""Research workbench JSON response contract regressions."""

from __future__ import annotations

import ast
from pathlib import Path

from core.web.routes.research_models import (
    ResearchFlowCanvasResponse,
    ResearchKnowledgeBaseResponse,
    ResearchOrgMessageResponse,
    ResearchOrgProposalResponse,
    ResearchOrganizationGraphResponse,
    ResearchPromptsResponse,
    ThemeDiscoverySessionDeleteResponse,
    ThemeDiscoverySessionListResponse,
    ThemeDiscoverySessionResponse,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
ROUTE_FILE = REPO_ROOT / "core" / "web" / "routes" / "research.py"

JSON_ROUTE_FUNCTIONS = {
    "research_knowledge_base",
    "research_theme_discovery_sessions",
    "research_theme_discovery_session_create",
    "research_theme_discovery_session_detail",
    "research_theme_discovery_session_delete",
    "research_theme_discovery_broad_search",
    "research_theme_discovery_deep_search",
    "research_theme_discovery_extract_evidence",
    "research_theme_discovery_generate_themes",
    "research_theme_discovery_run_draft",
    "research_theme_discovery_select_theme",
    "research_theme_discovery_theme_card",
    "research_theme_discovery_approve_card",
    "research_theme_discovery_prompts",
    "research_theme_discovery_prompts_update",
    "research_theme_discovery_agent_templates_update",
    "research_theme_discovery_agent_templates_delete",
    "research_flow_canvas",
    "research_flow_canvas_update",
    "research_organization",
    "research_organization_update",
    "research_organization_message_create",
    "research_organization_proposal_create",
    "research_organization_proposal_apply",
    "research_organization_message_retry_wake",
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


def test_research_json_routes_declare_response_model() -> None:
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
    assert missing == [], f"research JSON routes must declare response_model: {missing}"


def test_research_models_publish_known_schema_fields() -> None:
    expected_properties = {
        ResearchKnowledgeBaseResponse: {"entries", "summary"},
        ThemeDiscoverySessionListResponse: {"sessions", "summary"},
        ThemeDiscoverySessionResponse: {"session", "summary", "candidateThemes", "searchRuns"},
        ThemeDiscoverySessionDeleteResponse: {"deleted", "sessionId", "sessions"},
        ResearchPromptsResponse: {"prompts", "agents"},
        ResearchFlowCanvasResponse: {"canvasKind", "nodes", "edges"},
        ResearchOrganizationGraphResponse: {"agents", "edges", "messages"},
        ResearchOrgMessageResponse: {"organization", "message"},
        ResearchOrgProposalResponse: {"organization", "proposal"},
    }

    for model, expected in expected_properties.items():
        properties = set(model.model_json_schema().get("properties") or {})
        assert expected <= properties, (
            f"{model.__name__} is missing fields: {sorted(expected - properties)}"
        )


def test_research_models_keep_unknown_fields_without_injecting_defaults() -> None:
    session = ThemeDiscoverySessionResponse.model_validate(
        {
            "session": {"sessionId": "rs-1", "selectedThemeId": "th-1"},
            "summary": {"candidateThemeCount": 5},
            "candidateThemes": [{"themeId": "th-1"}],
            "futureHint": True,
        }
    ).model_dump(exclude_unset=True)
    assert session["session"]["sessionId"] == "rs-1"
    assert session["futureHint"] is True
    assert "searchRuns" not in session

    org = ResearchOrganizationGraphResponse.model_validate(
        {"agents": [{"agentId": "ag-1", "role": "ceo"}]}
    ).model_dump(exclude_unset=True)
    assert org == {"agents": [{"agentId": "ag-1", "role": "ceo"}]}
    assert "messages" not in org
