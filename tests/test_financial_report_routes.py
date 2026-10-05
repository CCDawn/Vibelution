"""HTTP contract for the financial report export route."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.web.routes.financial_reports import router
from core.web.services import financial_report_service as service


def test_export_route_uses_typed_payload_and_response(monkeypatch):
    app = FastAPI()
    app.include_router(router, prefix="/api")
    client = TestClient(app)
    monkeypatch.setattr(service, "export_financial_report", lambda agent_id, **values: {
        "sessionId": values["session_id"],
        "turnId": values["turn_id"],
        "format": values["format"],
        "fileName": "stock-research-2026-10-06.md",
        "mediaType": "text/markdown; charset=utf-8",
        "encoding": "utf8",
        "content": "## 结论\n研究结果",
    })
    response = client.post("/api/financial-reports/agent-1/export", json={
        "sessionId": "session-1", "turnId": "turn-1", "format": "markdown"
    })
    assert response.status_code == 200
    assert response.json()["content"] == "## 结论\n研究结果"
    assert response.json()["format"] == "markdown"


def test_export_route_maps_service_errors_and_rejects_unknown_formats(monkeypatch):
    app = FastAPI()
    app.include_router(router, prefix="/api")
    client = TestClient(app)
    monkeypatch.setattr(
        service,
        "export_financial_report",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(service.FinancialReportNotFound("未找到研究会话")),
    )
    missing = client.post("/api/financial-reports/agent-1/export", json={
        "sessionId": "session-1", "turnId": "turn-missing", "format": "markdown"
    })
    assert missing.status_code == 404
    invalid = client.post("/api/financial-reports/agent-1/export", json={
        "sessionId": "session-1", "turnId": "turn-1", "format": "exe"
    })
    assert invalid.status_code == 422
