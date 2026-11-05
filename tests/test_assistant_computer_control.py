"""Launcher transport tests use only a fictitious operator/window backend."""
from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from core.assistant_runtime import computer_control


TOKEN = "test-launcher-token-0123456789"
HEADERS = {"Authorization": "Bearer " + TOKEN}
STATE = {"available": True, "status": "idle", "message": "", "grantId": None, "window": None, "pending": None, "authorizationRequest": None}


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


def test_authorization_request_is_available_only_to_launcher_operator(client, monkeypatch):
    http, _ = client
    request = {"id": "request", "agentId": "assistant", "sessionId": "session", "turnId": "turn"}
    monkeypatch.setattr(computer_control.service, "get_state", lambda: {**STATE, "authorizationRequest": request})
    path = "/api/assistant/computer"
    assert http.get(path).status_code == 401
    assert http.get(path, headers={**HEADERS, "Origin": "https://example.test"}).status_code == 403
    assert http.get(path, headers=HEADERS).json()["authorizationRequest"] == request


def test_launcher_grant_passes_exact_request_binding_and_rejects_null(client):
    http, calls = client
    path = "/api/assistant/computer/grant"
    assert http.post(path, json={"selectionId": "fake-selection", "allowVision": True, "authorizationRequestId": "req"}, headers=HEADERS).status_code == 200
    assert calls == [("grant", ("fake-selection", True, "req"))]
    assert http.post(path, json={"selectionId": "fake-selection", "allowVision": True, "authorizationRequestId": None}, headers=HEADERS).status_code == 422


def test_launcher_never_retries_a_rejected_bound_grant(client, monkeypatch):
    http, _ = client
    calls = []
    def fail(*args):
        calls.append(args)
        raise ValueError("expired request")
    monkeypatch.setattr(computer_control.service, "grant_window", fail)
    result = http.post("/api/assistant/computer/grant", json={"selectionId": "fake-selection", "allowVision": True,
                       "authorizationRequestId": "expired"}, headers=HEADERS)
    # An unclassified request refusal is not a state change: it must not ask
    # the operator to refresh-and-retry the identical request.
    assert result.status_code == 422 and calls == [("fake-selection", True, "expired")]
    assert result.json()["detail"]["code"] == "ASSISTANT_COMPUTER_REQUEST_INVALID"
    assert "expired request" not in result.text


def test_native_error_does_not_leak_detail(client, monkeypatch):
    http, _ = client
    def fail(*args):
        raise ValueError("sensitive native payload")
    monkeypatch.setattr(computer_control.service, "grant_window", fail)
    result = http.post("/api/assistant/computer/grant", json={"selectionId": "fake-selection", "allowVision": True}, headers=HEADERS)
    assert result.status_code == 422
    assert "sensitive" not in result.text


def test_driver_state_and_request_failures_stay_distinguishable(client, monkeypatch):
    """Regression: all service failures used to fold into one 409 refresh-and-
    retry, so the desktop could not tell a recoverable driver outage apart from
    moved operator state or a request that can never bind again."""
    http, _ = client
    path = "/api/assistant/computer/grant"
    body = {"selectionId": "fake-selection", "allowVision": True}

    def driver_down(*args):
        raise computer_control.service.CuaDriverError("PRIVATE_DRIVER_SENTINEL")

    def state_moved(*args):
        raise computer_control.service.adapter.ComputerBlocked("授权已变化", "grant changed")

    monkeypatch.setattr(computer_control.service, "grant_window", driver_down)
    driver = http.post(path, json=body, headers=HEADERS)
    monkeypatch.setattr(computer_control.service, "grant_window", state_moved)
    state = http.post(path, json=body, headers=HEADERS)
    monkeypatch.setattr(computer_control.service, "grant_window", lambda *args: (_ for _ in ()).throw(ValueError("refused")))
    invalid = http.post(path, json=body, headers=HEADERS)
    assert (driver.status_code, state.status_code, invalid.status_code) == (503, 409, 422)
    assert [row.json()["detail"]["code"] for row in (driver, state, invalid)] == [
        "ASSISTANT_COMPUTER_DRIVER_UNAVAILABLE", "ASSISTANT_COMPUTER_STATE_CHANGED", "ASSISTANT_COMPUTER_REQUEST_INVALID"]
    for row in (driver, state, invalid):
        assert "PRIVATE_DRIVER_SENTINEL" not in row.text and "grant changed" not in row.text


def test_launcher_host_mounts_computer_controls_behind_private_boundary(monkeypatch):
    from core.assistant_runtime.host import create_app
    from tests.test_assistant_runtime_host import Native
    monkeypatch.setattr(computer_control.service, "get_state", lambda: dict(STATE))
    app = create_app(native=Native(), token=TOKEN)
    with TestClient(app, base_url="http://127.0.0.1") as http:
        assert http.get("/api/assistant/computer").status_code == 401
        assert http.get("/api/assistant/computer", headers={**HEADERS, "Origin": "https://example.test"}).status_code == 403
        assert http.get("/api/assistant/computer", headers=HEADERS).json() == STATE
