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


def test_catalog_and_batch_http_contract_preserve_native_identity(monkeypatch):
    app = FastAPI()
    app.include_router(router, prefix="/api")
    client = TestClient(app)
    seen = []
    def listing(agent_id, **filters):
        seen.append((agent_id, filters))
        return {"items": [], "nextCursor": "20:0", "scannedSessions": 20, "order": "session_recency"}
    monkeypatch.setattr(service, "list_financial_reports", listing)
    response = client.get("/api/financial-reports/agent-1", params={"marketCode": "HK", "q": "00700", "dateFrom": "2026-10-01", "limit": 5})
    assert response.status_code == 200 and response.json()["nextCursor"] == "20:0"
    assert seen[0][1]["market_code"] == "HK" and seen[0][1]["date_from"] == "2026-10-01"
    opaque_cursor = "p1791270000000:1791270000000:session-20261006-173006-344152:0"
    continued = client.get("/api/financial-reports/agent-1", params={"cursor": opaque_cursor})
    assert continued.status_code == 200
    assert seen[-1][1]["cursor"] == opaque_cursor
    assert client.get("/api/financial-reports/agent-1", params={"cursor": "x" * 513}).status_code == 422
    monkeypatch.setattr(service, "export_financial_reports", lambda agent_id, **values: {"fileName": "stock-research-bundle.zip", "mediaType": "application/zip", "encoding": "base64", "content": "UEs=", "count": len(values["targets"])})
    target = {"sessionId": "session-1", "turnId": "old-turn"}
    response = client.post("/api/financial-reports/agent-1/export-batch", json={"targets": [target], "format": "markdown"})
    assert response.status_code == 200 and response.json()["count"] == 1
    for body in ({"targets": [target] * 21, "format": "markdown"}, {"targets": [target], "format": "pdf"}, {"targets": [{**target, "content": "client supplied"}], "format": "markdown"}):
        assert client.post("/api/financial-reports/agent-1/export-batch", json=body).status_code == 422
