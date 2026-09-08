import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.web.routes.team_workflows.operator_optimization import router
from core.web.services import team_service, team_workflow_orchestration_service as service
from core.web.services.team_workflow.operator_optimization.commands import authorize_campaign
from core.web.services.team_workflow.operator_optimization.store import create_campaign
from core.web.services.team_workflow.research_runtime.operator_authorization import server_operator_scope
from tests._support.team_workflow.cases_experiment import _use_tmp_project_root


def setup_team(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    team = team_service.create_team(name="Operator API")["teamId"]
    return team, service.get_active_research_project(team)["projectId"]


def test_public_campaign_api_is_independent_and_explicitly_project_scoped(tmp_path, monkeypatch):
    team, project = setup_team(tmp_path, monkeypatch)
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    path = f"/teams/{team}/workflow-orchestration/research-projects/{project}/operator-experiments"
    response = client.post(path, json={"title": "Softmax", "idempotencyKey": "one"})
    assert response.status_code == 200, response.text
    campaign = response.json()
    assert campaign["researchProjectId"] == project
    assert campaign["baselineRunId"] == ""
    assert client.get(path).json()["campaigns"][0] == campaign
    other = service.create_research_project(team, {"name": "Other"})["project"]["projectId"]
    service.activate_research_project(team, other)
    assert client.get(path + "/" + campaign["optimizationCampaignId"]).json() == campaign
    assert client.get(path.replace(project, other) + "/" + campaign["optimizationCampaignId"]).status_code == 404
    assert client.post(path, json={"title": "Softmax", "idempotencyKey": "two", "budget": {"authorized": True}}).status_code == 422


def test_budget_authorization_requires_server_role_and_replays_once(tmp_path, monkeypatch):
    team, project = setup_team(tmp_path, monkeypatch)
    campaign = create_campaign(team, project, {"title": "Softmax", "idempotencyKey": "one", "budget": {"gpuSecondsLimit": 60}})
    args = (team, project, campaign.optimizationCampaignId)
    kwargs = dict(expected_version=1, command_key="authorize")
    with pytest.raises(PermissionError):
        authorize_campaign(*args, **kwargs)
    with server_operator_scope("reader", roles=("viewer",)):
        with pytest.raises(PermissionError):
            authorize_campaign(*args, **kwargs)
    with server_operator_scope("owner", roles=("operator",)):
        authorized = authorize_campaign(*args, **kwargs)
        assert authorized.budget.authorized and authorized.authorizedBy == "owner"
        assert authorize_campaign(*args, **kwargs) == authorized
