from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.web.control import CONTROL_TOKEN_HEADER, get_control_token
from core.web.routes import evolution
from core.web.services.self_evolution_autonomous_loop_service import AutonomousLoopConflictError
from core.web.services.team_workflow.research_runtime.operator_authorization import current_server_operator


@pytest.fixture
def env(monkeypatch):
    calls = []
    def start(body):
        calls.append((body, current_server_operator()))
        return {"runId": "campaign-1", "status": "queued"}
    owner = SimpleNamespace(start_campaign=start, active_campaign=lambda: None,
                            get_campaign=lambda value: {"runId": value, "status": "completed"},
                            cancel_campaign=lambda value: start({"stop": value}),
                            revoke_campaign=lambda value: start({"revoke": value}))
    monkeypatch.setattr(evolution, "default_orchestrator", lambda: owner)
    app = FastAPI()
    app.include_router(evolution.router, prefix="/api")
    return TestClient(app, headers={CONTROL_TOKEN_HEADER: get_control_token()}), calls, owner


def _body(**extra):
    return {"goal": "improve bounded files", "idempotencyKey": "campaign-1",
            "localIntegration": {"acknowledge": True, "allowedFiles": ["core/example.py"],
                                 "teamId": "existing-team", "validForSeconds": 300}, **extra}


def test_campaign_start_binds_server_operator_and_keeps_default_budget(env):
    client, calls, _ = env
    result = client.post("/api/evolution/self/campaigns", json=_body(),
                         headers={"X-Vibelution-Operator-Id": "forged"})
    assert result.status_code == 202
    assert calls[0][0]["rounds"] == 3
    assert calls[0][1].operator_id != "forged"
    assert current_server_operator() is None


def test_campaign_can_reference_existing_team_recovery_binding(env):
    client, calls, _ = env
    response = client.post("/api/evolution/self/campaigns", json=_body(
        roleBindingFlowId="harness-diagnosis-v1"))
    assert response.status_code == 202
    assert calls[0][0]["roleBindingFlowId"] == "harness-diagnosis-v1"


@pytest.mark.parametrize("value", ["", "../flow", " flow", "flow/other", 1, True])
def test_campaign_rejects_invalid_binding_reference(env, value):
    client, calls, _ = env
    assert client.post("/api/evolution/self/campaigns", json=_body(
        roleBindingFlowId=value)).status_code == 422
    assert calls == []


@pytest.mark.parametrize("extra", [{"rounds": 11}, {"rounds": True}, {"rounds": "3"},
                                   {"operatorId": "forged"}, {"_campaignSource": {}}, {"idempotencyKey": ""}])
def test_campaign_request_rejects_invalid_or_private_fields(env, extra):
    client, calls, _ = env
    assert client.post("/api/evolution/self/campaigns", json=_body(**extra)).status_code == 422
    assert calls == []


@pytest.mark.parametrize("action", ["stop", "revoke_local_integration"])
def test_campaign_actions_require_control_and_privileged_server_operator(env, monkeypatch, action):
    client, calls, _ = env
    url = "/api/evolution/self/campaigns/campaign-1/actions"
    assert client.post(url, json={"action": action}, headers={CONTROL_TOKEN_HEADER: "bad"}).status_code == 403
    monkeypatch.setenv("VIBELUTION_RESEARCH_OPERATOR_ROLES", "reader")
    assert client.post(url, json={"action": action}).status_code == 403
    assert client.post("/api/evolution/self/campaigns", json=_body()).status_code == 403
    assert calls == []
    monkeypatch.setenv("VIBELUTION_RESEARCH_OPERATOR_ROLES", "operator")
    assert client.post(url, json={"action": action}).status_code == 200
    assert calls[0][1].operator_id


def test_campaign_conflict_maps_to_409_and_reads_return_typed_envelopes(env):
    client, _, owner = env
    def conflict(body):
        raise AutonomousLoopConflictError("key conflict")
    owner.start_campaign = conflict
    assert client.post("/api/evolution/self/campaigns", json=_body()).status_code == 409
    assert client.get("/api/evolution/self/campaigns/active").json() is None
    assert client.get("/api/evolution/self/campaigns/campaign-1").json()["status"] == "completed"
