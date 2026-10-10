"""HTTP rejects malformed plans before any model-backed child can be started."""
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.web.routes import financial_walk_forward as routes
from core.web.services import financial_backtest
from core.web.services.financial_backtest.contract import FinancialBacktestNotFound


@pytest.fixture
def http(monkeypatch):
    calls = []
    result = {
        "agentId": "owner", "workflowId": "workflow", "sourceRunId": "source", "status": "preview",
        "planHash": "a" * 64, "trainSessions": 126, "testSessions": 63, "stepSessions": 63,
        "maxTokens": 2000000, "estimatedTokens": 10000, "candidates": [{"candidateId": "cap-40", "maxPositionPct": 40}, {"candidateId": "cap-80", "maxPositionPct": 80}],
        "folds": [{"foldId": "f1", "trainStart": "2024-01-02", "trainEnd": "2024-06-28", "testStart": "2024-07-01", "testEnd": "2024-09-30", "status": "pending"}],
        "createdAt": "2026-10-10", "updatedAt": "2026-10-10", "notice": "独立测试，不回流选参",
    }
    service = SimpleNamespace()
    def invoke(name, *args):
        calls.append((name, args))
        if args[0] != "owner":
            raise FinancialBacktestNotFound("不存在")
        if name == "list_walk_forward_workflows":
            return {"items": [result]}
        return result
    for name in ("create_walk_forward_preview", "start_walk_forward", "get_walk_forward", "list_walk_forward_workflows", "stop_walk_forward", "resume_walk_forward", "export_walk_forward"):
        setattr(service, name, lambda *args, name=name: invoke(name, *args))
    monkeypatch.setattr(financial_backtest, "walk_forward_service", service, raising=False)
    app = FastAPI(); app.include_router(routes.router, prefix="/api")
    return TestClient(app), calls, result


def test_preview_is_typed_and_has_no_implicit_start(http):
    client, calls, result = http
    response = client.post("/api/financial-backtests/owner/runs/source/walk-forward-preview", json={"candidates": result["candidates"]})
    assert response.status_code == 200
    assert response.json()["status"] == "preview"
    assert response.json()["folds"][0]["metrics"] is None
    assert [row[0] for row in calls] == ["create_walk_forward_preview"]
    assert calls[0][1][:2] == ("owner", "source")


@pytest.mark.parametrize("override", [{"trainSessions": True}, {"maxTokens": 2000001}, {"stepSessions": 0}, {"unknown": "value"}, {"candidates": []}])
def test_invalid_plan_never_reaches_service(http, override):
    client, calls, result = http
    response = client.post("/api/financial-backtests/owner/runs/source/walk-forward-preview", json={"candidates": result["candidates"], **override})
    assert response.status_code == 422
    assert calls == []


def test_control_and_reads_preserve_owner_scope(http):
    client, calls, _ = http
    for action in ("start", "stop", "resume", "export"):
        assert client.post(f"/api/financial-backtests/owner/walk-forward/workflow/{action}").status_code == 200
    assert client.get("/api/financial-backtests/owner/walk-forward").json()["items"][0]["workflowId"] == "workflow"
    assert client.get("/api/financial-backtests/other/walk-forward/workflow").status_code == 404
    assert calls[-1] == ("get_walk_forward", ("other", "workflow"))
