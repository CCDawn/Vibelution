"""Public transport contract for frozen AI backtests and explicit recovery."""
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.web.routes import financial_backtests as routes
from core.web.routes.financial_backtest_models import FinancialBacktestRun
from core.web.services.financial_backtest.contract import (
    FinancialBacktestConflict,
    FinancialBacktestNotFound,
)
from core.web.services.financial_backtest.data import BacktestDataError


def client():
    app = FastAPI()
    app.include_router(routes.router, prefix="/api")
    return TestClient(app)


def preview():
    return {
        "agentId": "a", "previewId": str(uuid4()), "expiresAt": "2099-01-01T00:00:00Z", "symbol": "sz000001",
        "dateCoverage": {"requestedStartDate": "2026-09-01", "requestedEndDate": "2026-09-03", "actualStartDate": "2026-09-01", "actualEndDate": "2026-09-03", "availableStartDate": "2026-08-01", "availableEndDate": "2026-09-03", "tradingDays": 3, "warmupBars": 20, "providerWindows": [{"startDate": "2026-01-01", "endDate": "2026-12-31", "rawBars": 40, "qfqBars": 40, "calendarBars": 40}], "complete": True, "tradingCalendarStatus": "tencent_index_checked"},
        "decisionSchedule": ["2026-09-01"], "decisionCount": 1, "maxDecisions": 10, "maxTokens": 20000, "estimatedTokens": 1000, "reservedOutputTokens": 256, "modelId": "provider/model", "paramsHash": "a" * 64, "dataHash": "b" * 64, "actionsStatus": "clear", "actionDates": [], "canStart": True, "blockReason": None, "warnings": [], "source": "腾讯财经", "sourceUrl": "https://gu.qq.com/sz000001/gp", "fetchedAt": "2026-10-08", "adjustment": "raw", "notice": "模拟研究", "params": {"strategy": "趋势", "initialCash": 100000, "maxPositionPct": 80, "decisionInterval": 5, "commissionBps": 3, "minimumCommission": 5, "slippageBps": 5, "maxDecisions": 10, "maxTokens": 20000},
    }


def run():
    source = preview()
    kept = {key: source[key] for key in ("agentId", "symbol", "modelId", "paramsHash", "dataHash", "params", "dateCoverage", "actionsStatus", "actionDates", "source", "sourceUrl", "fetchedAt", "adjustment", "notice", "warnings", "maxTokens", "estimatedTokens")}
    return {**kept, "runId": str(uuid4()), "clientRequestId": str(uuid4()), "status": "paused_unknown", "progress": 0, "currentDecisionDate": "2026-09-01", "decisionCount": 1, "completedDecisionCount": 0, "callsUsed": 1, "tokensUsed": 1000, "tokensReserved": 1000, "decisions": [], "metrics": None, "equity": [], "trades": [], "orders": [], "startedAt": "2026-10-08", "updatedAt": "2026-10-08", "completedAt": None, "terminalReason": "结果不明", "errorCode": "unknown", "uncertainDecisionDate": "2026-09-01", "tokenAccounting": "reserved"}


def test_preview_response_preserves_calendar_evidence_and_never_starts_a_model(monkeypatch):
    response = preview()
    calls = []
    monkeypatch.setattr(routes.service, "create_financial_backtest_preview", lambda owner, payload: (calls.append((owner, payload)) or response))
    monkeypatch.setattr(routes.service, "start_financial_backtest_run", lambda *args: pytest.fail("Preview must not start a run"))
    result = client().post("/api/financial-backtests/a/preview", json={"symbol": "000001", "startDate": "2026-09-01", "endDate": "2026-09-03", "strategy": "趋势"})
    assert result.status_code == 200
    assert result.json()["dateCoverage"]["providerWindows"][0]["calendarBars"] == 40
    assert result.json()["dateCoverage"]["tradingCalendarStatus"] == "tencent_index_checked"
    assert calls[0][0] == "a"


def test_start_and_resume_forward_exact_immutable_identifiers(monkeypatch):
    response = run()
    calls = []
    monkeypatch.setattr(routes.service, "start_financial_backtest_run", lambda *args: (calls.append(args) or response))
    monkeypatch.setattr(routes.service, "resume_financial_backtest_run", lambda *args, **kwargs: (calls.append((args, kwargs)) or response))
    browser = client()
    request_id, preview_id = str(uuid4()), str(uuid4())
    created = browser.post("/api/financial-backtests/a/runs", json={"clientRequestId": request_id, "previewId": preview_id})
    assert created.status_code == 200
    assert calls[0] == ("a", request_id, preview_id)
    resumed = browser.post(f"/api/financial-backtests/a/runs/{response['runId']}/resume", json={"retryUnknownDecisionDate": "2026-09-01", "confirmPossibleDuplicateCharge": True})
    assert resumed.status_code == 200
    assert resumed.json()["status"] == "paused_unknown"
    assert calls[1] == (("a", response["runId"]), {"retry_unknown_decision_date": "2026-09-01", "confirm_possible_duplicate_charge": True})


@pytest.mark.parametrize("error,status", [(FinancialBacktestNotFound("不存在"), 404), (FinancialBacktestConflict("需确认"), 409), (BacktestDataError("数据缺口"), 422)])
def test_domain_failures_remain_explicit_http_failures(monkeypatch, error, status):
    def fail(*args):
        raise error
    monkeypatch.setattr(routes.service, "get_financial_backtest_run", fail)
    result = client().get("/api/financial-backtests/a/runs/r")
    assert result.status_code == status
    assert result.json()["detail"] == str(error)


@pytest.mark.parametrize("field,value", [("maxTokens", True), ("initialCash", "100000"), ("decisionInterval", 1.5), ("maxPositionPct", 101)])
def test_http_rejects_coercion_and_unsafe_numeric_parameters(monkeypatch, field, value):
    monkeypatch.setattr(routes.service, "create_financial_backtest_preview", lambda *args: pytest.fail("invalid request reached service"))
    result = client().post("/api/financial-backtests/a/preview", json={"symbol": "000001", "startDate": "2026-09-01", "endDate": "2026-09-03", "strategy": "趋势", field: value})
    assert result.status_code == 422


def test_public_model_rejects_invented_recovery_states():
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        FinancialBacktestRun.model_validate({**run(), "status": "uncertain"})
