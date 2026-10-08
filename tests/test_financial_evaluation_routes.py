"""Shared HTTP/DTO shape and integration boundaries for evaluation workflows."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.web.routes.financial_reports import router
from core.web.services import financial_report_service as service
from core.web.services.financial_preferences_service import FinancialPreferenceError


def _client():
    app = FastAPI()
    app.include_router(router, prefix="/api")
    return TestClient(app)


def test_claim_response_matches_frontend_shape_and_rejects_extra_input(monkeypatch):
    row = {"id": "check-1", "agentId": "a", "sessionId": "s", "turnId": "t", "symbol": "sz000001", "analysisDate": "2026-10-01", "dueDate": "2026-10-09", "direction": "up", "thresholdPct": 3, "claimText": "上涨至少3%", "status": "pending", "registeredBeforeDue": True, "retrospective": False, "outcome": None, "checkedAt": None, "revision": 1, "evidence": None, "error": None, "lesson": None}
    calls = []
    monkeypatch.setattr(service, "create_report_validation", lambda agent, payload: (calls.append((agent, payload)), row)[1])
    payload = {key: row[key] for key in ("sessionId", "turnId", "symbol", "dueDate", "direction", "thresholdPct", "claimText")}
    payload["clientRequestId"] = "e4a17e5b-ea69-4ba9-a5f5-a5b425c2b113"
    client = _client()
    response = client.post("/api/financial-reports/a/validations", json=payload)
    assert response.status_code == 200
    assert response.json() == row
    assert calls[0][0] == "a"
    assert client.post("/api/financial-reports/a/validations", json={**payload, "outcome": "hit"}).status_code == 422
    assert client.post("/api/financial-reports/a/validations", json={**payload, "thresholdPct": True}).status_code == 422
    assert len(calls) == 1


def test_evaluation_maps_private_owner_errors(monkeypatch):
    def missing(*_):
        raise FinancialPreferenceError("不属于当前助手", 404)
    monkeypatch.setattr(service, "check_report_validation", missing)
    response = _client().post("/api/financial-reports/a/validations/wrong/check")
    assert response.status_code == 404
    assert response.json()["detail"] == "不属于当前助手"


def test_backtest_schema_has_the_required_ts_fields():
    schemas = _client().get("/openapi.json").json()["components"]["schemas"]
    required = set(schemas["BacktestResult"]["required"])
    assert {"symbol", "metrics", "equity", "trades", "startDate", "endDate", "window", "source", "sourceUrl", "fetchedAt", "dataHash", "notice", "adjustment"} <= required
    assert {"totalReturnPct", "benchmarkReturnPct", "excessReturnPct", "maxDrawdownPct", "tradeCount", "fees"} <= set(schemas["BacktestMetrics"]["required"])
    assert set(schemas["ClaimEvidence"]["required"]) == {"baseDate", "baseClose", "dueDateQuoteDate", "dueClose", "returnPct", "sourceUrl", "fetchedAt", "seriesHash"}


def test_managed_outcome_worker_obeys_stop_budget_and_cooldown(monkeypatch):
    from core.web.services.financial_jobs.runtime import FinancialResearchJobsWorker
    from core.web.services.financial_report import validation
    calls = []
    monkeypatch.setattr(validation, "process_due_for_agent", lambda owner, **kw: (calls.append((owner, kw["max_checks"])), 1)[1])
    worker = FinancialResearchJobsWorker(assistant_loader=lambda: ["a", "b", "c"])
    worker._check_report_outcomes(should_stop=lambda: True)
    assert not calls
    worker._check_report_outcomes(should_stop=lambda: False)
    assert calls == [("a", 2), ("b", 1)]
    worker._check_report_outcomes(should_stop=lambda: False)
    assert len(calls) == 2


def test_team_primary_prompt_reads_owner_lessons_with_historical_cutoff(monkeypatch):
    from core.web.services.financial_report import validation
    from core.web.services.financial_team import runs
    seen = []
    def context(owner, symbol, *, analysis_cutoff):
        seen.append((owner, symbol, analysis_cutoff))
        return [{"id": "lesson-1", "text": "优先核对价格证据", "refs": [{"type": "item", "id": "evaluation-1"}]}]
    monkeypatch.setattr(validation, "reflection_context", context)
    prompt = runs._primary_role_prompt({"assistantAgentId": "a", "symbol": "sz000001", "researchDate": "2026-10-08", "periodDays": 30, "depth": "brief"}, "market")
    assert seen == [("a", "sz000001", "2026-10-08")]
    assert "confirmed_research_lesson" in prompt
    assert "UNTRUSTED_REFERENCE_MATERIALS_JSON_BEGIN" in prompt
    assert "优先核对价格证据" in prompt
