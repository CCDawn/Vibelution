"""Research template-baseline route contract tests.

两层契约：
1. DTO 模型契约——payload 在边界拒绝缺字段请求，响应模型保留未知键。
2. HTTP 路由契约——URL 注册、payload 原样透传到 service、响应形状与
   错误映射（404/409/422）。service 一律 monkeypatch，业务语义由
   service 侧测试覆盖。
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from pydantic import ValidationError

from core.web.app import create_app
from core.web.control import CONTROL_TOKEN_HEADER, get_control_token
from core.web.routes.team_workflows import research_templates as rt_routes
from core.web.routes.team_workflows.research_templates_models import (
    TemplateBaselineCreatePayload,
)
from core.web.services.team_service import TeamNotFoundError
from core.web.services.team_workflow.research_templates import (
    ResearchTemplateBaselineNotFoundError,
)


def _client() -> TestClient:
    return TestClient(create_app(), headers={CONTROL_TOKEN_HEADER: get_control_token()})


# ---------------------------------------------------------------------------
# DTO model contract
# ---------------------------------------------------------------------------


def test_create_payload_requires_template_id() -> None:
    try:
        TemplateBaselineCreatePayload()
    except ValidationError:
        return
    raise AssertionError("templateId must be required")


def test_create_payload_accepts_scope_fields() -> None:
    payload = TemplateBaselineCreatePayload(
        templateId="tpl-1",
        question="SCI-096",
        approvedBy="agent-1",
        content={"metric": "accuracy"},
    )
    data = payload.model_dump()
    assert data["templateId"] == "tpl-1"
    assert data["question"] == "SCI-096"
    assert data["content"] == {"metric": "accuracy"}


# ---------------------------------------------------------------------------
# HTTP route contract
# ---------------------------------------------------------------------------


def test_create_route_passes_payload_through(monkeypatch) -> None:
    captured: list[tuple[str, dict]] = []

    def fake_create(team_id, payload):
        captured.append((team_id, dict(payload)))
        return {
            "schemaVersion": 1,
            "teamId": team_id,
            "status": "created",
            "baseline": {"baselineId": "baseline-tpl-1-v1", "status": "frozen"},
        }

    monkeypatch.setattr(rt_routes.research_templates, "create_template_baseline", fake_create)
    client = _client()
    response = client.post(
        "/api/teams/team-1/workflow-orchestration/template-baselines",
        json={"templateId": "tpl-1", "question": "SCI-096", "approvedBy": "agent-1"},
    )

    assert response.status_code == 201, response.text
    data = response.json()
    assert data["status"] == "created"
    assert data["baseline"]["baselineId"] == "baseline-tpl-1-v1"
    assert captured and captured[0][0] == "team-1"
    assert captured[0][1]["templateId"] == "tpl-1"
    assert captured[0][1]["question"] == "SCI-096"


def test_create_route_maps_team_not_found(monkeypatch) -> None:
    def fake_create(team_id, payload):
        raise TeamNotFoundError("Team not found.")

    monkeypatch.setattr(rt_routes.research_templates, "create_template_baseline", fake_create)
    client = _client()
    response = client.post(
        "/api/teams/team-1/workflow-orchestration/template-baselines",
        json={"templateId": "tpl-1", "approvedBy": "agent-1"},
    )
    assert response.status_code == 404


def test_create_route_maps_contract_error(monkeypatch) -> None:
    from core.research.workflow.contracts import ContractValidationError

    def fake_create(team_id, payload):
        raise ContractValidationError("templateId is required")

    monkeypatch.setattr(rt_routes.research_templates, "create_template_baseline", fake_create)
    client = _client()
    response = client.post(
        "/api/teams/team-1/workflow-orchestration/template-baselines",
        json={"templateId": "tpl-1", "approvedBy": "agent-1"},
    )
    assert response.status_code == 422


def test_create_route_maps_baseline_conflict(monkeypatch) -> None:
    from core.web.services.team_workflow.research_templates import (
        ResearchTemplateError,
    )

    def fake_create(team_id, payload):
        raise ResearchTemplateError("frozen baseline id cannot be reused")

    monkeypatch.setattr(rt_routes.research_templates, "create_template_baseline", fake_create)
    client = _client()
    response = client.post(
        "/api/teams/team-1/workflow-orchestration/template-baselines",
        json={"templateId": "tpl-1", "approvedBy": "agent-1"},
    )
    assert response.status_code == 409


def test_list_route_returns_service_projection(monkeypatch) -> None:
    def fake_list(team_id):
        return {
            "schemaVersion": 1,
            "teamId": team_id,
            "baselines": [{"baselineId": "baseline-tpl-1-v1"}],
        }

    monkeypatch.setattr(rt_routes.research_templates, "list_template_baselines", fake_list)
    client = _client()
    response = client.get("/api/teams/team-1/workflow-orchestration/template-baselines")
    assert response.status_code == 200, response.text
    assert response.json()["baselines"][0]["baselineId"] == "baseline-tpl-1-v1"


def test_get_route_returns_frozen_view(monkeypatch) -> None:
    def fake_view(team_id, baseline_id):
        return {
            "schemaVersion": 1,
            "teamId": team_id,
            "baselineId": baseline_id,
            "status": "frozen",
        }

    monkeypatch.setattr(rt_routes.research_templates, "frozen_template_view", fake_view)
    client = _client()
    response = client.get(
        "/api/teams/team-1/workflow-orchestration/template-baselines/baseline-tpl-1-v1"
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "frozen"


def test_get_route_maps_baseline_not_found(monkeypatch) -> None:
    def fake_view(team_id, baseline_id):
        raise ResearchTemplateBaselineNotFoundError("missing")

    monkeypatch.setattr(rt_routes.research_templates, "frozen_template_view", fake_view)
    client = _client()
    response = client.get(
        "/api/teams/team-1/workflow-orchestration/template-baselines/missing-1"
    )
    assert response.status_code == 404
