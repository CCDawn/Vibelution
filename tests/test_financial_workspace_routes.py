"""Workspace HTTP updates preserve partial sections and reject quote metadata."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.web.routes.financial_preferences import router
from core.web.services import financial_preferences_service as service


def test_workspace_patch_remains_partial_and_revision_checked(monkeypatch):
    app = FastAPI()
    app.include_router(router, prefix="/api")
    client = TestClient(app)
    seen = []
    def save(agent_id, revision, patch):
        seen.append((agent_id, revision, patch))
        return {"schemaVersion": 1, "agentId": agent_id, "revision": revision + 1, "updatedAt": "", "selectedStock": None, "watchlist": [], "profiles": [], "manualPositions": [], "reviewCases": []}
    monkeypatch.setattr(service, "update_workspace_settings", save)
    response = client.patch("/api/financial-preferences/agent-1/workspace", json={"expectedRevision": 3, "patch": {"watchlist": []}})
    assert response.status_code == 200 and seen == [("agent-1", 3, {"watchlist": []})]
    stock = {"symbol": "usAAPL", "ticker": "AAPL", "name": "Apple", "market": "NASDAQ", "price": 200}
    assert client.patch("/api/financial-preferences/agent-1/workspace", json={"expectedRevision": 4, "patch": {"selectedStock": stock}}).status_code == 422
    monkeypatch.setattr(service, "update_workspace_settings", lambda *args: (_ for _ in ()).throw(service.FinancialPreferenceError("版本冲突", 409)))
    assert client.patch("/api/financial-preferences/agent-1/workspace", json={"expectedRevision": 3, "patch": {"watchlist": []}}).status_code == 409
