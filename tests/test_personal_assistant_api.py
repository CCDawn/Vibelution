"""Typed personal-assistant API rejects privilege fields and unsafe payloads."""

import pytest
from fastapi.testclient import TestClient

from core.web.app import create_app
from core.web.control import CONTROL_TOKEN_HEADER, get_control_token
from core.web.services import agent_directory_service as directory
from core.web.services import personal_assistant_service as service
from core.web.services import personal_attention_service as attention
from core.web.services import session_service
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


def _overview(**_kwargs):
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
                "turnId": "worker-turn",
            }
        ],
        "pagination": {"offset": 0, "limit": 100, "nextOffset": None, "revision": "test-revision"},
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


@pytest.mark.parametrize("rows", [[], [
    {"id": "gate-1", "kind": "human_gate", "title": "等待审批",
     "actions": [{"label": "接受", "decision": "accept"}],
     "meta": {"teamId": "team-1", "runId": "run-7", "decisions": ["accept"]}},
    {"id": "review-1", "kind": "knowledge_review", "title": "知识待复核"},
]])
def test_human_attention_read_skips_session_overview_and_preserves_row_contract(
    client, monkeypatch, rows
):
    def forbidden(*_args, **_kwargs):
        pytest.fail("Notification read enumerated the Session overview")

    monkeypatch.setattr(service, "get_platform_overview", forbidden)
    monkeypatch.setattr(session_service, "list_sessions", forbidden)
    monkeypatch.setattr(session_service, "current_session_turn_id", forbidden)
    for index, name in enumerate((
        "collect_knowledge_review_attention", "collect_anomaly_attention",
        "_collect_human_gate_attention", "_collect_affair_reminder_attention",
    )):
        monkeypatch.setattr(attention, name, lambda index=index: rows[index:index + 1])
    response = client.get("/api/personal-assistant/human-attention")
    assert response.status_code == 200, response.text
    assert response.json() == {"humanAttention": rows}
    schema = client.app.openapi()["components"]["schemas"]["HumanAttentionResponse"]
    assert schema["required"] == ["humanAttention"]
    assert schema["properties"]["humanAttention"]["items"] == {
        "$ref": "#/components/schemas/Attention"
    }


def test_human_attention_response_rejects_unknown_notification_kinds(client, monkeypatch):
    monkeypatch.setattr(attention, "collect_human_attention", lambda: [
        {"id": "bad-1", "kind": "unrecognized", "title": "Invalid"}
    ])
    unchecked_client = TestClient(
        client.app, headers={CONTROL_TOKEN_HEADER: get_control_token()},
        raise_server_exceptions=False,
    )
    assert unchecked_client.get("/api/personal-assistant/human-attention").status_code == 500


def test_overview_route_passes_bounded_page_parameters(client, monkeypatch):
    calls = []
    monkeypatch.setattr(service, "get_platform_overview", lambda **kwargs: calls.append(kwargs) or _overview())
    assert client.get("/api/personal-assistant/overview?offset=100&limit=25").status_code == 200
    assert calls == [{"offset": 100, "limit": 25}]
    for query in ("offset=-1", "limit=0", "limit=101", "offset=oops"):
        assert client.get("/api/personal-assistant/overview?" + query).status_code == 422
    assert len(calls) == 1


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
        monkeypatch.setattr(service, "get_platform_overview", lambda **_kwargs: payload)
        url = "/api/personal-assistant/overview"
    else:
        row = _assistant()
        row[corruption] = "unrecognized"
        monkeypatch.setattr(
            service, "get_personal_assistant", lambda: {"assistant": row}
        )
        url = "/api/personal-assistant"
    assert client.get(url).status_code == 500


def test_settings_get_returns_typed_envelope(client):
    created = client.post("/api/personal-assistant", json={})
    assert created.status_code == 200
    response = client.get("/api/personal-assistant/settings")
    assert response.status_code == 200, response.text
    settings = response.json()["settings"]
    assert set(settings) == {
        "displayName",
        "preferences",
        "preferencesConfigured",
        "model",
    }
    assert set(settings["preferences"]) == {
        "characterId",
        "showStatus",
        "showTitles",
        "showCompletion",
        "idleMessage",
    }
    assert set(settings["model"]) == {"currentModelId", "choices"}
    assert settings["preferences"]["characterId"] == "dafeiyu"
    assert settings["preferencesConfigured"] is False


def test_settings_patch_roundtrip_updates_name_and_preferences(client):
    created = client.post("/api/personal-assistant", json={})
    assert created.status_code == 200
    payload = {
        "displayName": "小洛管家",
        "preferences": {"characterId": "xiaoluo", "showTitles": False},
    }
    patched = client.patch("/api/personal-assistant/settings", json=payload)
    assert patched.status_code == 200, patched.text
    settings = patched.json()["settings"]
    assert settings["displayName"] == "小洛管家"
    assert settings["preferences"]["characterId"] == "xiaoluo"
    assert settings["preferences"]["showTitles"] is False
    assert settings["preferencesConfigured"] is True
    assistant = client.get("/api/personal-assistant").json()["assistant"]
    assert assistant["renderer"] == "xiaoluo"


@pytest.mark.parametrize(
    "payload",
    [
        {"displayName": ""},
        {"displayName": "a" * 81},
        {"preferences": {"characterId": "hacker"}},
        {"preferences": {"showStatus": "yes"}},
        {"preferences": {"idleMessage": "x" * 49}},
        {"preferences": {"unknown": True}},
        {"modelId": "whatever"},
        {"renderer": "xiaoluo"},
    ],
)
def test_settings_patch_rejects_unsafe_payloads_before_service(client, monkeypatch, payload):
    def forbidden(*_args, **_kwargs):
        pytest.fail("invalid payload reached the service")

    monkeypatch.setattr(
        service, "update_personal_assistant_settings", forbidden
    )
    assert (
        client.patch("/api/personal-assistant/settings", json=payload).status_code
        == 422
    )


def test_settings_model_update_validates_and_maps_errors(client, monkeypatch):
    calls = []

    def update(model_id):
        calls.append(model_id)
        if model_id != "whale-xl":
            raise directory.AgentDirectoryError("所选模型不在可用模型列表中。")
        return {"model": {"currentModelId": "whale-xl", "choices": []}}

    monkeypatch.setattr(service, "update_personal_assistant_model", update)
    ok = client.patch(
        "/api/personal-assistant/settings/model", json={"modelId": "whale-xl"}
    )
    assert ok.status_code == 200 and ok.json() == {
        "model": {"currentModelId": "whale-xl", "choices": []}
    }
    rejected = client.patch(
        "/api/personal-assistant/settings/model", json={"modelId": "not-listed"}
    )
    assert rejected.status_code == 422
    assert rejected.json()["detail"] == "所选模型不在可用模型列表中。"
    assert calls == ["whale-xl", "not-listed"]
    for payload in ({"modelId": ""}, {"modelId": 5}, {}):
        assert (
            client.patch("/api/personal-assistant/settings/model", json=payload).status_code
            == 422
        )


def test_settings_get_maps_identity_conflict_to_409(client, monkeypatch):
    def fail():
        raise directory.AgentStateConflictError("身份冲突")

    monkeypatch.setattr(service, "get_personal_assistant_settings", fail)
    assert client.get("/api/personal-assistant/settings").status_code == 409


@pytest.mark.parametrize(
    "method,url,payload",
    [
        ("patch", "/api/personal-assistant/settings", {"displayName": "改名"}),
        ("patch", "/api/personal-assistant/settings/model", {"modelId": "whale-xl"}),
    ],
    ids=["settings", "model"],
)
def test_settings_and_model_patch_map_identity_conflict_to_409(
    client, monkeypatch, method, url, payload
):
    def fail(*_args, **_kwargs):
        raise directory.AgentStateConflictError("身份冲突")

    monkeypatch.setattr(
        service,
        "update_personal_assistant_settings" if method == "patch" and url.endswith("settings")
        else "update_personal_assistant_model",
        fail,
    )
    response = client.patch(url, json=payload)
    assert response.status_code == 409
    assert response.json()["detail"] == "身份冲突"


def test_assistant_projection_accepts_xiaoluo_renderer(client, monkeypatch):
    row = _assistant()
    row["renderer"] = "xiaoluo"
    monkeypatch.setattr(service, "get_personal_assistant", lambda: {"assistant": row})
    response = client.get("/api/personal-assistant")
    assert response.status_code == 200 and response.json()["assistant"]["renderer"] == "xiaoluo"
