"""Launcher transport tests use only a fictitious operator/window backend."""
from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from core.assistant_runtime import computer_control


TOKEN = "test-launcher-token-0123456789"
HEADERS = {"Authorization": "Bearer " + TOKEN}
STATE = {"available": True, "status": "idle", "message": "", "grantId": None, "window": None, "pending": None}


@pytest.fixture
def client(monkeypatch):
    calls = []
    fake = computer_control.service
    monkeypatch.setattr(fake, "get_state", lambda: dict(STATE))
    monkeypatch.setattr(fake, "list_windows", lambda: {"windows": [{"selectionId": "fake-selection", "title": "Fake", "appName": "Fake app"}]})
    monkeypatch.setattr(fake, "grant_window", lambda *args: calls.append(("grant", args)) or dict(STATE))
    monkeypatch.setattr(fake, "control", lambda *args: calls.append(("control", args)) or dict(STATE))
    monkeypatch.setattr(fake, "confirm", lambda *args: calls.append(("confirm", args)) or dict(STATE))
    app = FastAPI()
    app.include_router(computer_control.create_router(TOKEN))
    with TestClient(app, base_url="http://127.0.0.1") as test_client:
        yield test_client, calls


def test_only_main_bearer_without_browser_origin_can_use_operator_transport(client):
    http, calls = client
    path = "/api/assistant/computer/grant"
    body = {"selectionId": "fake-selection", "allowVision": True}
    assert http.post(path, json=body).status_code == 401
    assert http.post(path, json=body, headers={**HEADERS, "Origin": "https://example.test"}).status_code == 403
    assert http.post("http://example.test" + path, json=body, headers=HEADERS).status_code == 403
    assert calls == []


def test_operator_commands_are_closed_and_strict(client):
    http, calls = client
    base = "/api/assistant/computer"
    assert http.get(base, headers=HEADERS).json() == STATE
    assert http.post(base + "/windows", headers=HEADERS).json()["windows"][0]["selectionId"] == "fake-selection"
    assert http.get(base + "/windows", headers=HEADERS).status_code == 405
    assert http.post(base + "/grant", json={"selectionId": "fake-selection", "allowVision": "true"}, headers=HEADERS).status_code == 422
    assert http.post(base + "/grant", json={"selectionId": "fake-selection", "allowVision": True, "owner": "model"}, headers=HEADERS).status_code == 422
    assert http.post(base + "/confirm", json={"grantId": "g", "pendingId": "p", "approved": 1}, headers=HEADERS).status_code == 422
    assert http.post(base + "/control", json={"grantId": "g", "action": "click"}, headers=HEADERS).status_code == 422
    assert http.post(base + "/execute", json={}, headers=HEADERS).status_code == 404
    assert calls == []
    assert http.post(base + "/grant", json={"selectionId": "fake-selection", "allowVision": True}, headers=HEADERS).status_code == 200
    assert http.post(base + "/control", json={"grantId": "g", "action": "pause"}, headers=HEADERS).status_code == 200
    assert http.post(base + "/confirm", json={"grantId": "g", "pendingId": "p", "approved": False}, headers=HEADERS).status_code == 200
    assert calls == [("grant", ("fake-selection", True)), ("control", ("g", "pause")), ("confirm", ("g", "p", False))]


def test_native_error_does_not_leak_detail(client, monkeypatch):
    http, _ = client
    def fail(*args):
        raise ValueError("sensitive native payload")
    monkeypatch.setattr(computer_control.service, "grant_window", fail)
    result = http.post("/api/assistant/computer/grant", json={"selectionId": "fake-selection", "allowVision": True}, headers=HEADERS)
    assert result.status_code == 409
    assert "sensitive" not in result.text


def test_launcher_host_mounts_computer_controls_behind_private_boundary(monkeypatch):
    from core.assistant_runtime.host import create_app
    from tests.test_assistant_runtime_host import Native
    monkeypatch.setattr(computer_control.service, "get_state", lambda: dict(STATE))
    app = create_app(native=Native(), token=TOKEN)
    with TestClient(app, base_url="http://127.0.0.1") as http:
        assert http.get("/api/assistant/computer").status_code == 401
        assert http.get("/api/assistant/computer", headers={**HEADERS, "Origin": "https://example.test"}).status_code == 403
        assert http.get("/api/assistant/computer", headers=HEADERS).json() == STATE
