import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.web.routes.team_workflows.operator_optimization import router
from core.web.services import team_service, team_workflow_orchestration_service as service
from core.web.services.team_workflow.operator_optimization.commands import authorize_campaign
from core.web.services.team_workflow.operator_optimization.store import create_campaign
from core.web.services.team_workflow.research_runtime import run_creation
from core.web.services.team_workflow.research_runtime import workflow_artifact_store as artifacts
from core.web.services.team_workflow.research_runtime.operator_authorization import server_operator_scope
from tests._support.team_workflow.cases_experiment import _use_tmp_project_root
from tests._support.workflow_ledger_helpers import open_ledger_store
from tests.test_operator_optimization_rounds import activity, ready


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


def test_prepare_baseline_through_http_binds_the_run_used_to_start(tmp_path, monkeypatch):
    from core.web.routes.team_workflows import research_runtime as runtime_routes
    from core.web.services.team_workflow.operator_optimization import baseline

    team, project = setup_team(tmp_path, monkeypatch)
    campaign = create_campaign(team, project, {
        "title": "Softmax", "idempotencyKey": "create", "budget": {"gpuSecondsLimit": 60},
    })
    path = (f"/teams/{team}/workflow-orchestration/research-projects/{project}"
            f"/operator-experiments/{campaign.optimizationCampaignId}")
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    monkeypatch.setattr("core.web.control.validate_control_request", lambda request: None)
    monkeypatch.setattr(artifacts, "_path", lambda team, kind: tmp_path / "artifacts" / team / f"{kind}.jsonl")
    monkeypatch.setattr(baseline, "inspect_cuda_environment", lambda: {"deviceKind": "cuda", "deviceName": "fixture"})
    monkeypatch.setattr(run_creation, "research_workflow_data_root", lambda: tmp_path)
    monkeypatch.setattr(run_creation, "effective_binding_layers", lambda team, layers, **kwargs: layers)
    ledger = open_ledger_store(tmp_path / "ledger.sqlite")
    monkeypatch.setattr(run_creation, "get_write_store", lambda: ledger)

    try:
        authorization = client.post(path + "/authorize", json={
            "expectedCampaignVersion": 1, "idempotencyKey": "authorize",
        })
        assert authorization.status_code == 200, authorization.text
        payload = {
            "expectedCampaignVersion": authorization.json()["revision"], "idempotencyKey": "prepare",
            "protocol": {"protocolId": "p1", "split": "tuning", "cases": [
                {"caseId": "s1", "rows": 128, "columns": 512, "dtype": "float32", "seed": 1},
            ]},
        }
        monkeypatch.setattr("core.web.control.validate_control_request", lambda request: "forbidden")
        assert client.post(path + "/baseline", json=payload).status_code == 403
        monkeypatch.setattr("core.web.control.validate_control_request", lambda request: None)
        response = client.post(path + "/baseline", json=payload)
        assert response.status_code == 200, response.text
        prepared = response.json()
        run_id = prepared["baselineRunId"]
        assert prepared["baselineVersions"][0]["runId"] == run_id
        assert ledger.get_run(run_id).status == "created"
        assert client.post(path + "/baseline", json=payload).json() == prepared

        submitted = []

        def submit(**kwargs):
            submitted.append(kwargs)
            return {"commandId": "start", "runId": kwargs["run_id"], "status": "accepted"}

        monkeypatch.setattr(runtime_routes, "_submit_workflow_command", submit)
        start = client.post(path + "/baseline/start", json={"expectedRunVersion": 1, "idempotencyKey": "start"})
        assert start.status_code == 200, start.text
        assert start.json()["runId"] == run_id
        assert submitted[0]["node_id"] == "operator_baseline"
        assert client.post(path + "/baseline/start", json={
            "expectedRunVersion": 1, "idempotencyKey": "start", "baselineRunId": run_id,
        }).json() == start.json()
        assert client.post(path + "/baseline/start", json={
            "expectedRunVersion": 1, "idempotencyKey": "start", "baselineRunId": "unrelated-run",
        }).status_code == 404
    finally:
        ledger.close()


def test_public_round_preparation_requires_authorization_and_only_creates_first_round(activity, ready, monkeypatch):
    team, project, campaign_id = activity
    campaign, _, create_calls = ready
    path = (f"/teams/{team}/workflow-orchestration/research-projects/{project}"
            f"/operator-experiments/{campaign_id}/rounds")
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    payload = {"expectedCampaignVersion": campaign.revision, "idempotencyKey": "first-round"}
    monkeypatch.setattr("core.web.control.validate_control_request", lambda request: "forbidden")
    assert client.post(path, json=payload).status_code == 403
    monkeypatch.setattr("core.web.control.validate_control_request", lambda request: None)
    first = client.post(path, json=payload)
    assert first.status_code == 200, first.text
    assert first.json()["rounds"][0]["runId"] == first.json()["activeRunId"]
    assert client.post(path, json=payload).json() == first.json()
    second = client.post(path, json={"expectedCampaignVersion": first.json()["revision"], "idempotencyKey": "second"})
    assert second.status_code == 409
    assert len(create_calls) == 1


def test_stage2_migration_api_requires_explicit_v2_action(tmp_path, monkeypatch):
    from core.web.services.team_workflow.operator_optimization import migration

    team, project = setup_team(tmp_path, monkeypatch)
    campaign = create_campaign(
        team,
        project,
        {"title": "Migration", "idempotencyKey": "one"},
    )
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    path = (
        f"/teams/{team}/workflow-orchestration/research-projects/{project}"
        f"/operator-experiments/{campaign.optimizationCampaignId}/stage2-migrations"
    )
    payload = {
        "expectedCampaignVersion": 1,
        "idempotencyKey": "migrate",
        "sourceRunId": "run-stage2",
        "initialAction": "discuss",
    }
    monkeypatch.setattr("core.web.control.validate_control_request", lambda request: None)
    calls = []

    def migrate(*args, **kwargs):
        calls.append((args, kwargs))
        return campaign

    monkeypatch.setattr(migration, "migrate_stage2_run_to_stage3", migrate)
    assert client.post(path, json=payload).status_code == 200
    assert calls == [
        (
            (team, project, campaign.optimizationCampaignId),
            {
                "source_run_id": "run-stage2",
                "initial_action": "discuss",
                "expected_version": 1,
                "command_key": "migrate",
            },
        )
    ]
    assert client.post(path, json={**payload, "initialAction": "continue"}).status_code == 422
