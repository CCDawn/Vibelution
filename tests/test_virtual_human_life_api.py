from __future__ import annotations

from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.agent_plugins.virtual_human_life.service import VirtualHumanLifeService
from core.web.routes import agent_plugins, virtual_human_life
from core.web.services.virtual_human_life_service import (
    _default_agent_persona_initializer,
    set_virtual_human_life_service_for_tests,
    stop_virtual_human_life_runtime,
)


def _client(tmp_path) -> tuple[TestClient, VirtualHumanLifeService]:
    agent = {"agentId": "agent-a", "status": "active", "directSessionId": "session-a"}
    service = VirtualHumanLifeService(
        tmp_path,
        agent_loader=lambda agent_id, include_archived=False: (
            agent if agent_id == "agent-a" else None
        ),
        agent_lister=lambda: [agent],
        plugin_root_resolver=lambda agent_id: (
            tmp_path / "agents" / agent_id / "plugins" / "virtual-human-life"
        ),
        now_provider=lambda: datetime(2026, 8, 27, 9, 0, tzinfo=timezone.utc),
    )
    set_virtual_human_life_service_for_tests(service)
    app = FastAPI()
    app.include_router(agent_plugins.router, prefix="/api")
    app.include_router(virtual_human_life.router, prefix="/api")
    return TestClient(app), service


def test_agent_plugin_and_virtual_human_routes_are_typed_and_agent_scoped(tmp_path) -> None:
    client, service = _client(tmp_path)
    try:
        catalog = client.get("/api/agent-plugins/catalog")
        assert catalog.status_code == 200
        assert catalog.json()[0]["pluginId"] == "virtual-human-life"

        before = client.get("/api/agents/agent-a/plugins")
        assert before.status_code == 200
        assert before.json()["plugins"][0]["binding"] is None
        assert service.plugin_root("agent-a").exists() is False

        enabled = client.put(
            "/api/agents/agent-a/plugins/virtual-human-life/binding",
            json={
                "enabled": True,
                "expectedVersion": 0,
                "config": {"timezone": "Asia/Shanghai"},
            },
        )
        assert enabled.status_code == 200, enabled.text
        assert enabled.json()["enabled"] is True

        companions = client.get(
            "/api/agent-plugins/virtual-human-life/companions"
        )
        assert companions.status_code == 200, companions.text
        assert companions.json() == [
            {
                "agentId": "agent-a",
                "agentCode": "",
                "displayName": "agent-a",
                "directSessionId": "session-a",
                "avatarImageUrl": "",
                "personaProfile": {},
                "status": "active",
                "snapshot": companions.json()[0]["snapshot"],
            }
        ]
        assert companions.json()[0]["snapshot"]["bound"] is True

        snapshot = client.get(
            "/api/agents/agent-a/plugins/virtual-human-life/snapshot"
        )
        assert snapshot.status_code == 200
        state_version = snapshot.json()["state"]["stateVersion"]
        activity_id = next(
            item["activityId"]
            for item in snapshot.json()["todaySchedule"]["activities"]
            if item["status"] == "planned"
        )

        command = client.post(
            "/api/agents/agent-a/plugins/virtual-human-life/commands",
            json={
                "agentId": "agent-a",
                "command": "skipActivity",
                "expectedVersion": state_version,
                "idempotencyKey": "api-skip-first",
                "arguments": {"activityId": activity_id},
            },
        )
        assert command.status_code == 200, command.text
        assert command.json()["result"]["activity"]["status"] == "skipped"
    finally:
        set_virtual_human_life_service_for_tests(None)


def test_companion_lobby_omits_unbound_and_sessionless_agents(tmp_path) -> None:
    agents = [
        {
            "agentId": "enabled",
            "agentCode": "nora",
            "displayName": "Nora",
            "status": "active",
            "directSessionId": "session-nora",
            "personaProfile": {"personality": "calm"},
        },
        {
            "agentId": "unbound",
            "status": "active",
            "directSessionId": "session-unbound",
        },
        {
            "agentId": "sessionless",
            "status": "active",
            "directSessionId": "",
        },
    ]
    service = VirtualHumanLifeService(
        tmp_path,
        agent_loader=lambda agent_id, include_archived=False: next(
            (item for item in agents if item["agentId"] == agent_id),
            None,
        ),
        agent_lister=lambda: agents,
        plugin_root_resolver=lambda agent_id: (
            tmp_path / "agents" / agent_id / "plugins" / "virtual-human-life"
        ),
        now_provider=lambda: datetime(2026, 8, 27, 9, 0, tzinfo=timezone.utc),
    )
    set_virtual_human_life_service_for_tests(service)
    app = FastAPI()
    app.include_router(agent_plugins.router, prefix="/api")
    client = TestClient(app)
    try:
        service.set_binding("enabled", enabled=True, expected_version=0)
        service.set_binding("sessionless", enabled=True, expected_version=0)

        response = client.get(
            "/api/agent-plugins/virtual-human-life/companions"
        )

        assert response.status_code == 200, response.text
        assert [item["agentId"] for item in response.json()] == ["enabled"]
        assert response.json()[0]["displayName"] == "Nora"
        assert response.json()[0]["personaProfile"]["personality"] == "calm"
    finally:
        set_virtual_human_life_service_for_tests(None)


def test_virtual_human_command_rejects_agent_id_mismatch_and_stale_version(tmp_path) -> None:
    client, _service = _client(tmp_path)
    try:
        client.put(
            "/api/agents/agent-a/plugins/virtual-human-life/binding",
            json={"enabled": True, "expectedVersion": 0, "config": {}},
        )
        mismatch = client.post(
            "/api/agents/agent-a/plugins/virtual-human-life/commands",
            json={
                "agentId": "agent-b",
                "command": "pauseLife",
                "expectedVersion": 1,
                "idempotencyKey": "mismatch",
                "arguments": {},
            },
        )
        assert mismatch.status_code == 422

        stale = client.post(
            "/api/agents/agent-a/plugins/virtual-human-life/commands",
            json={
                "agentId": "agent-a",
                "command": "pauseLife",
                "expectedVersion": 0,
                "idempotencyKey": "stale",
                "arguments": {},
            },
        )
        assert stale.status_code == 409
    finally:
        set_virtual_human_life_service_for_tests(None)


def test_virtual_human_reads_reject_unknown_agent_and_invalid_query(tmp_path) -> None:
    client, _service = _client(tmp_path)
    try:
        assert client.get("/api/agents/missing-agent/plugins").status_code == 404
        assert (
            client.get(
                "/api/agents/missing-agent/plugins/virtual-human-life/snapshot"
            ).status_code
            == 404
        )

        enabled = client.put(
            "/api/agents/agent-a/plugins/virtual-human-life/binding",
            json={"enabled": True, "expectedVersion": 0, "config": {}},
        )
        assert enabled.status_code == 200
        assert (
            client.get(
                "/api/agents/agent-a/plugins/virtual-human-life/events",
                params={"localDate": "../../escape"},
            ).status_code
            == 422
        )
        assert (
            client.get(
                "/api/agents/agent-a/plugins/virtual-human-life/diary",
                params={"limit": 0},
            ).status_code
            == 422
        )
    finally:
        set_virtual_human_life_service_for_tests(None)


def test_virtual_human_json_routes_declare_response_models() -> None:
    for route in [*agent_plugins.router.routes, *virtual_human_life.router.routes]:
        assert route.response_model is not None, route.path
        assert route.response_model_exclude_unset is True, route.path


def test_host_stop_fences_open_delivery_and_requests_session_cancellation(
    tmp_path,
    monkeypatch,
) -> None:
    client, service = _client(tmp_path)
    del client
    cancelled: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "core.web.services.session_service.cancel_virtual_human_proactive_turns",
        lambda agent_id, *, reason: cancelled.append((agent_id, reason)) or [],
    )
    service.proactive_submitter = lambda **_payload: {
        "accepted": True,
        "turnId": "turn-host-stop",
    }
    try:
        service.set_binding("agent-a", enabled=True, expected_version=0)
        attempt = service.request_proactive_message(
            "agent-a",
            reason="宿主停止前尚未送达",
        )

        stop_virtual_human_life_runtime()

        assert service.proactive_attempt(
            "agent-a", attempt["deliveryToken"]
        )["status"] == "cancelled"
        assert cancelled == [("agent-a", "host_stop")]
    finally:
        set_virtual_human_life_service_for_tests(None)


def test_enabling_virtual_human_initializes_only_an_unconfigured_persona(
    monkeypatch,
) -> None:
    from core.web.services import agent_directory_service

    agent = {
        "agentId": "agent-a",
        "displayName": "洛天依",
        "personaProfile": {},
        "metadata": {},
    }
    updates: list[dict] = []
    monkeypatch.setattr(
        agent_directory_service,
        "get_agent",
        lambda agent_id, **_kwargs: agent if agent_id == "agent-a" else None,
    )
    monkeypatch.setattr(
        agent_directory_service,
        "update_agent_instance",
        lambda agent_id, **payload: updates.append({"agentId": agent_id, **payload})
        or {**agent, "personaProfile": payload["persona_profile"]},
    )

    result = _default_agent_persona_initializer("agent-a")

    assert result["initialized"] is True
    assert updates[0]["agentId"] == "agent-a"
    assert "洛天依" in updates[0]["persona_profile"]["background"]
    assert "独立" in updates[0]["persona_profile"]["identityNotes"]
    assert "第一人称" in updates[0]["persona_profile"]["communicationStyle"]


def test_virtual_human_persona_initializer_preserves_user_authored_or_cleared_profile(
    monkeypatch,
) -> None:
    from core.web.services import agent_directory_service

    updates: list[dict] = []
    monkeypatch.setattr(
        agent_directory_service,
        "update_agent_instance",
        lambda agent_id, **payload: updates.append({"agentId": agent_id, **payload}),
    )
    agents = {
        "custom": {
            "agentId": "custom",
            "displayName": "自定义人物",
            "personaProfile": {"personality": "用户已经写好的性格"},
            "metadata": {},
        },
        "cleared": {
            "agentId": "cleared",
            "displayName": "清空人物",
            "personaProfile": {},
            "metadata": {"personaProfileDefaultsDisabled": True},
        },
    }
    monkeypatch.setattr(
        agent_directory_service,
        "get_agent",
        lambda agent_id, **_kwargs: agents.get(agent_id),
    )

    assert _default_agent_persona_initializer("custom")["reason"] == "already_configured"
    assert _default_agent_persona_initializer("cleared")["reason"] == "defaults_disabled"
    assert updates == []
