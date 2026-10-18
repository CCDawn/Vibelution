import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.web.control import WebControlGuardMiddleware, CONTROL_TOKEN_HEADER, get_control_token
from core.web.routes import personal_assistant_computer as route


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("VIBELUTION_RESEARCH_OPERATOR_ROLES", "operator")
    app = FastAPI()
    app.add_middleware(WebControlGuardMiddleware)
    app.include_router(route.router, prefix="/api")
    return TestClient(app, headers={CONTROL_TOKEN_HEADER: get_control_token()})


def state():
    return {"available": True, "status": "ready", "message": "ready", "grantId": "grant",
            "window": {"selectionId": "selection", "title": "Test", "appName": "Test"}, "pending": None}


def test_operator_can_only_grant_returned_selection_and_exact_confirmation(client, monkeypatch):
    calls = []
    monkeypatch.setattr(route.service, "get_state", state)
    monkeypatch.setattr(route.service, "list_windows", lambda: {"windows": [state()["window"]]})
    monkeypatch.setattr(route.service, "grant_window", lambda *args: calls.append(args) or state())
    monkeypatch.setattr(route.service, "confirm", lambda *args: calls.append(args) or state())
    assert client.get("/api/personal-assistant/computer").json() == state()
    assert client.get("/api/personal-assistant/computer/windows").status_code == 200
    assert client.post("/api/personal-assistant/computer/grant", json={"selectionId": "selection", "allowVision": True}).status_code == 200
    assert client.post("/api/personal-assistant/computer/confirm", json={"grantId": "grant", "pendingId": "decision", "approved": False}).status_code == 200
    assert calls == [("selection", True), ("grant", "decision", False)]


@pytest.mark.parametrize("path", ["", "/windows", "/grant", "/control", "/confirm"])
def test_non_operator_and_agent_origin_cannot_control(client, monkeypatch, path):
    monkeypatch.setenv("VIBELUTION_RESEARCH_OPERATOR_ROLES", "viewer")
    method, payload = ("get", None) if path in {"", "/windows"} else ("post", {
        "/grant": {"selectionId": "selection", "allowVision": True},
        "/control": {"grantId": "grant", "action": "end"},
        "/confirm": {"grantId": "grant", "pendingId": "decision", "approved": True},
    }[path])
    kwargs = {"json": payload} if payload else {}
    assert getattr(client, method)("/api/personal-assistant/computer" + path, **kwargs).status_code == 403
    monkeypatch.setenv("VIBELUTION_RESEARCH_OPERATOR_ROLES", "admin")
    assert getattr(client, method)("/api/personal-assistant/computer" + path, headers={"X-OpenCode-Session": "agent-session"}, **kwargs).status_code == 403


@pytest.mark.parametrize("path,payload", [
    ("/grant", {"selectionId": "x", "allowVision": True, "pid": 123}),
    ("/grant", {"selectionId": "x", "allowVision": "true"}),
    ("/control", {"grantId": "x", "action": "click"}),
    ("/confirm", {"grantId": "x", "pendingId": "y", "approved": 1}),
])
def test_payload_cannot_add_window_identity_or_execution(client, path, payload):
    assert client.post("/api/personal-assistant/computer" + path, json=payload).status_code == 422


def test_missing_control_token_rejected_before_service(client):
    assert client.get("/api/personal-assistant/computer", headers={CONTROL_TOKEN_HEADER: "invalid"}).status_code == 403
