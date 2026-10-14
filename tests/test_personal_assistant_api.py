"""Typed personal-assistant API rejects privilege fields and unsafe payloads."""

import pytest
from fastapi.testclient import TestClient

from core.web.app import create_app
from core.web.control import CONTROL_TOKEN_HEADER, get_control_token
from core.web.services import agent_directory_service as directory
from core.web.services import personal_assistant_service as service
from tests.test_personal_assistant_service import (
    finance_env as _finance_env,
)
from tests.test_personal_assistant_service import (
    personal_env as _personal_env,
)

finance_env = _finance_env
personal_env = _personal_env


@pytest.fixture
def client(personal_env):
    return TestClient(create_app(), headers={CONTROL_TOKEN_HEADER: get_control_token()})


def _assistant():
    return {
        "agentId": "personal-agent",
        "displayName": "个人助理",
        "directSessionId": "personal-session",
        "status": "active",
        "setupStatus": "ready",
        "profile": "personal_assistant_v1",
        "renderer": "whale",
    }


def _overview():
    return {
        "generatedAt": "2026-10-14T00:00:00+00:00",
        "counts": {"agents": 1, "sessions": 1, "running": 1, "waiting": 0, "failed": 0},
        "agents": [
            {"id": "personal-agent", "displayName": "个人助理", "status": "active"}
        ],
        "sessions": [
            {
                "id": "personal-session",
                "agentId": "personal-agent",
                "title": "当前任务",
                "status": "running",
                "currentPhase": "reading",
            }
        ],
        "attention": [
            {
                "id": "attention-1",
                "kind": "approval",
                "title": "等待批准",
                "sessionId": "personal-session",
            }
        ],
    }


def test_registered_get_is_read_only_and_post_returns_only_assistant_envelope(
    client, monkeypatch
):
    def forbidden(*_args, **_kwargs):
        pytest.fail("GET provisioned an assistant")

    with monkeypatch.context() as guard:
        guard.setattr(service, "create_personal_assistant", forbidden)
        response = client.get("/api/personal-assistant")
        assert response.status_code == 200 and response.json() == {"assistant": None}
    created = client.post("/api/personal-assistant", json={})
    assert created.status_code == 200, created.text
    assert set(created.json()) == {"assistant"}
    assert set(created.json()["assistant"]) == set(_assistant())
    assert created.json()["assistant"]["displayName"].startswith("个人助理")
    assert created.json()["assistant"]["setupStatus"] == "ready"
    assert client.get("/api/personal-assistant").json() == created.json()


@pytest.mark.parametrize(
    "extra",
    [
        {"toolPolicy": {"allowedTools": ["cli_tool"]}},
        {"agentId": "other"},
        {"renderer": "other"},
    ],
)
def test_post_rejects_extra_request_fields_before_service_call(
    client, monkeypatch, extra
):
    calls = []
    monkeypatch.setattr(
        service,
        "create_personal_assistant",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )
    assert client.post("/api/personal-assistant", json=extra).status_code == 422
    assert calls == []


def test_post_passes_display_name_and_drops_created_service_metadata(
    client, monkeypatch
):
    names = []

    def create(display_name="个人助理"):
        names.append(display_name)
        return {"assistant": _assistant(), "created": True}

    monkeypatch.setattr(service, "create_personal_assistant", create)
    response = client.post("/api/personal-assistant", json={"displayName": "小鲸"})
    assert response.status_code == 200
    assert response.json() == {"assistant": _assistant()}
    assert names == ["小鲸"]


@pytest.mark.parametrize(
    "method,error,status",
    [
        ("get", directory.AgentStateConflictError("身份冲突"), 409),
        ("post", directory.AgentStateConflictError("身份冲突"), 409),
        ("post", directory.AgentDirectoryError("名称无效"), 422),
    ],
)
def test_directory_errors_map_to_public_status_codes(
    client, monkeypatch, method, error, status
):
    def fail(*_args, **_kwargs):
        raise error

    monkeypatch.setattr(
        service,
        "get_personal_assistant" if method == "get" else "create_personal_assistant",
        fail,
    )
    response = (
        client.get("/api/personal-assistant")
        if method == "get"
        else client.post("/api/personal-assistant", json={})
    )
    assert response.status_code == status
    assert response.json()["detail"] == str(error)


def test_post_requires_native_control_token(personal_env):
    response = TestClient(create_app()).post("/api/personal-assistant", json={})
    assert response.status_code in {401, 403}
    assert service.get_personal_assistant() == {"assistant": None}


def test_overview_route_returns_typed_safe_contract(client, monkeypatch):
    monkeypatch.setattr(service, "get_platform_overview", _overview)
    response = client.get("/api/personal-assistant/overview")
    assert response.status_code == 200
    assert response.json() == _overview()


@pytest.mark.parametrize("corruption", ["count", "renderer", "setupStatus"])
def test_response_models_reject_invalid_types_or_closed_values(
    personal_env, monkeypatch, corruption
):
    client = TestClient(
        create_app(),
        headers={CONTROL_TOKEN_HEADER: get_control_token()},
        raise_server_exceptions=False,
    )
    if corruption == "count":
        payload = _overview()
        payload["counts"]["running"] = "1"
        monkeypatch.setattr(service, "get_platform_overview", lambda: payload)
        url = "/api/personal-assistant/overview"
    else:
        row = _assistant()
        row[corruption] = "unrecognized"
        monkeypatch.setattr(
            service, "get_personal_assistant", lambda: {"assistant": row}
        )
        url = "/api/personal-assistant"
    assert client.get(url).status_code == 500
