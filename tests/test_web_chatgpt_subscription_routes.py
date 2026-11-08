from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.llm.chatgpt_subscription import ChatGPTSubscriptionError
from core.web.routes import chatgpt_subscription as routes
from core.web.services import chatgpt_subscription_service as service


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(routes.router, prefix="/api")
    with TestClient(app) as result:
        yield result


def test_status_has_explicit_safe_response_and_discards_internal_fields(client, monkeypatch):
    monkeypatch.setattr(service, "subscription_status", lambda: {
        "state": "connected", "connected": True,
        "account": {"subject": "subject-test", "email": "demo@example.test", "access_token": "synthetic-token"},
        "access_token": "synthetic-token", "refresh_token": "synthetic-refresh",
    })
    response = client.get("/api/config/chatgpt-subscription/status")
    assert response.status_code == 200
    assert response.json()["account"] == {"subject": "subject-test", "email": "demo@example.test"}
    assert "synthetic-token" not in response.text and "synthetic-refresh" not in response.text


def test_login_start_and_cancel_delegate_without_accepting_arbitrary_settings(client, monkeypatch):
    started = {"attemptId": "a" * 32, "authorizationUrl": "https://auth.openai.com/api/accounts/authorize?state=demo", "expiresAt": "2026-11-06T12:00:00Z"}
    monkeypatch.setattr(service, "start_subscription_login", lambda: started)
    seen = []
    monkeypatch.setattr(service, "cancel_subscription_login", lambda attempt: seen.append(attempt) or {"cancelled": True})
    assert client.post("/api/config/chatgpt-subscription/login").json() == started
    assert client.post("/api/config/chatgpt-subscription/cancel", json={"attemptId": "a" * 32}).json() == {"cancelled": True}
    assert seen == ["a" * 32]
    assert client.post("/api/config/chatgpt-subscription/cancel", json={"attemptId": "a" * 32, "token": "fake"}).status_code == 422


def test_public_error_is_a_fixed_actionable_code(client, monkeypatch):
    def fail():
        raise ChatGPTSubscriptionError("permission_missing")
    monkeypatch.setattr(service, "subscription_models", fail)
    response = client.get("/api/config/chatgpt-subscription/models")
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "permission_missing"
    assert "token" not in response.text


def test_disconnect_reports_remote_revocation_uncertainty(client, monkeypatch):
    monkeypatch.setattr(service, "disconnect_subscription", lambda: {"revocationConfirmed": False})
    assert client.post("/api/config/chatgpt-subscription/logout").json() == {"revocationConfirmed": False}


def test_models_are_safe_metadata_and_do_not_change_active_configuration(client, monkeypatch):
    monkeypatch.setattr(service, "subscription_models", lambda: {
        "models": [{"slug": "example-model", "context_window": 1000, "access_token": "synthetic-token"}],
        "provider": {"credential_ref": "oauth:chatgpt"},
    })
    response = client.get("/api/config/chatgpt-subscription/models")
    assert response.status_code == 200
    assert response.json()["models"][0]["slug"] == "example-model"
    assert "synthetic-token" not in response.text


def test_account_audit_contains_only_the_action(monkeypatch):
    from types import SimpleNamespace
    events = []
    manager = SimpleNamespace(start_login=lambda: {"authorizationUrl": "https://auth.openai.com/authorize?state=example"})
    monkeypatch.setattr(service, "get_chatgpt_subscription_auth", lambda: manager)
    monkeypatch.setattr(service, "record_runtime_scene_event", lambda *args, **kwargs: events.append(kwargs))
    service.start_subscription_login()
    assert events[0]["fields"] == {"action": "login_started"}
    assert "authorize" not in str(events)
