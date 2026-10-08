"""Public proposal schema, ownership failures and approval semantics."""

from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.web.routes import financial_portfolio as routes
from core.web.routes.financial_rebalance_models import RebalanceProposal
from core.web.services.financial_rebalance.risk import RebalanceConflict
from tests.test_financial_paper_service import finance_env as _finance_env
from tests.test_financial_paper_service import paper_env as _paper_env
from tests.test_financial_rebalance import proposal_env as _proposal_env

finance_env = _finance_env
paper_env = _paper_env
proposal_env = _proposal_env


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(routes.router, prefix="/api")
    return TestClient(app)


def test_all_proposal_routes_declare_public_response_contracts(client):
    schema = client.get("/openapi.json").json()
    paths = {path: value for path, value in schema["paths"].items() if "/proposals" in path}
    assert len(paths) == 4
    for methods in paths.values():
        for operation in methods.values():
            assert "$ref" in operation["responses"]["200"]["content"]["application/json"]["schema"]
    fields = RebalanceProposal.model_fields
    assert {"planHash", "reportRefs", "targets", "riskChecks", "orders", "metrics", "execution", "policy"} <= set(fields)


def test_create_converts_uuid_and_keeps_exact_report_identity(client, monkeypatch):
    captured = []

    def create(agent, payload):
        captured.append((agent, payload))
        raise RebalanceConflict("expected test conflict")

    monkeypatch.setattr(routes.rebalance, "create_proposal", create)
    request_id = str(uuid4())
    response = client.post("/api/financial-portfolios/a/proposals", json={"clientRequestId": request_id, "symbols": ["sh600519"], "reports": [{"sessionId": "s", "turnId": "t"}], "instruction": "test"})
    assert response.status_code == 409
    assert captured[0][1]["clientRequestId"] == request_id
    assert captured[0][1]["reports"] == [{"sessionId": "s", "turnId": "t"}]


def test_approval_requires_hash_and_explicit_confirmation(client, monkeypatch):
    called = []
    monkeypatch.setattr(routes.rebalance, "approve_proposal", lambda *args: called.append(args))
    for body in ({"planHash": "a" * 64}, {"planHash": "a" * 64, "confirmSimulation": False}, {"planHash": "bad", "confirmSimulation": True}, {"planHash": "a" * 64, "confirmSimulation": True, "priceYuan": "1.00"}):
        assert client.post("/api/financial-portfolios/a/proposals/p/approve", json=body).status_code == 422
    assert called == []


def test_real_service_roundtrip_satisfies_public_contract(client, proposal_env):
    base = f"/api/financial-portfolios/{proposal_env['agentId']}/proposals"
    created = client.post(base, json=proposal_env["payload"])
    assert created.status_code == 200, created.text
    proposal = RebalanceProposal.model_validate(created.json())
    assert proposal.status == "ready"
    assert all(check.passed for check in proposal.riskChecks)
    assert proposal.orders[0].quantity > 0
    url = f"{base}/{proposal.proposalId}"
    approved = client.post(f"{url}/approve", json={"planHash": proposal.planHash, "confirmSimulation": True})
    assert approved.status_code == 200, approved.text
    assert RebalanceProposal.model_validate(approved.json()).status == "executed"
    assert client.get(url).json() == approved.json()
    assert client.get(base).json()["items"] == [approved.json()]
