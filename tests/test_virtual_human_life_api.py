from __future__ import annotations

import json
from datetime import datetime, timezone
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.agent_plugins.virtual_human_life.service import VirtualHumanLifeService
from core.web.routes import agent_plugins, virtual_human_life
from core.web.services.virtual_human_life_service import (
    _default_agent_persona_initializer,
    _default_conversation_receipt_resolver,
    _default_proactive_admission_resolver,
    _default_schedule_planner,
    _default_steward_provisioner,
    set_virtual_human_life_service_for_tests,
    stop_virtual_human_life_runtime,
)


def test_default_conversation_receipt_resolver_reads_native_user_event(
    monkeypatch,
) -> None:
    from core.chat.turn_journal import EVENT_USER_MESSAGE
    from core.web.services.session import journal_bridge

    monkeypatch.setattr(
        journal_bridge,
        "load_session_conversation_events_snapshot",
        lambda session_id: [
            SimpleNamespace(
                session_id=session_id,
                turn_id="turn-user",
                event_type=EVENT_USER_MESSAGE,
                correlation_id="submission-user",
                timestamp="2026-08-30T00:00:01+00:00",
                event_id="event-user",
            )
        ],
    )

    receipt = _default_conversation_receipt_resolver(
        "session-a",
        {"command": {"clientSubmissionId": "submission-user"}},
    )

    assert receipt == {
        "turnId": "turn-user",
        "acceptedAt": "2026-08-30T00:00:01+00:00",
        "receiptEventId": "event-user",
    }


def test_default_proactive_admission_resolver_reads_native_turn_start(
    monkeypatch,
) -> None:
    from core.chat.turn_journal import EVENT_TURN_STARTED
    from core.web.services.session import journal_bridge

    monkeypatch.setattr(
        journal_bridge,
        "load_session_conversation_events_snapshot",
        lambda session_id: [
            SimpleNamespace(
                session_id=session_id,
                turn_id="turn-proactive",
                event_type=EVENT_TURN_STARTED,
                correlation_id="delivery-token",
                timestamp="2026-08-30T00:00:02+00:00",
                event_id="event-proactive",
            )
        ],
    )

    receipt = _default_proactive_admission_resolver(
        "agent-a",
        {
            "sessionId": "session-a",
            "command": {
                "proactiveAttempt": {"delivery_token": "delivery-token"}
            },
        },
    )

    assert receipt == {
        "turnId": "turn-proactive",
        "admittedAt": "2026-08-30T00:00:02+00:00",
        "receiptEventId": "event-proactive",
    }


def test_default_steward_provisioner_reuses_one_hidden_native_session(monkeypatch) -> None:
    from core.web.services import agent_directory_service, session_service

    companion = {
        "agentId": "agent-companion",
        "displayName": "小洛",
        "status": "active",
        "primaryMode": "chat",
        "directSessionId": "session-companion",
        "llmBindings": {"dialogue": {"modelId": "model-dialogue"}},
        "metadata": {"virtualHumanCompanion": True},
    }
    agents = {companion["agentId"]: companion}
    create_calls: list[dict] = []
    update_calls: list[dict] = []

    def list_agents(*, include_archived=False, detail="full"):
        assert detail == "config"
        return [
            dict(agent)
            for agent in agents.values()
            if include_archived or agent.get("status") != "archived"
        ]

    def get_agent(agent_id: str, *, include_archived=False):
        agent = agents.get(agent_id)
        if not agent or (agent.get("status") == "archived" and not include_archived):
            return None
        return dict(agent)

    def create_chat_session(**kwargs):
        create_calls.append(dict(kwargs))
        steward = {
            "agentId": "agent-steward",
            "displayName": kwargs["title"],
            "status": "active",
            "primaryMode": "chat",
            "directSessionId": "session-steward",
            "llmBindings": kwargs["llm_bindings"],
            "metadata": {},
        }
        agents[steward["agentId"]] = steward
        return {
            "id": steward["directSessionId"],
            "agentId": steward["agentId"],
            "title": steward["displayName"],
        }

    def update_agent_instance(agent_id: str, **kwargs):
        update_calls.append({"agentId": agent_id, **kwargs})
        agents[agent_id] = {
            **agents[agent_id],
            "displayName": kwargs.get("display_name", agents[agent_id]["displayName"]),
            "llmBindings": kwargs.get("llm_bindings", agents[agent_id]["llmBindings"]),
            "primaryMode": kwargs.get("primary_mode", agents[agent_id]["primaryMode"]),
            "roleKey": kwargs.get("role_key", agents[agent_id].get("roleKey", "")),
            "promptTemplateId": kwargs.get(
                "prompt_template_id", agents[agent_id].get("promptTemplateId", "")
            ),
            "toolPolicy": kwargs.get("tool_policy", agents[agent_id].get("toolPolicy", {})),
            "metadata": {**agents[agent_id].get("metadata", {}), **kwargs.get("metadata", {})},
            "status": kwargs.get("status", agents[agent_id]["status"]),
        }
        return dict(agents[agent_id])

    monkeypatch.setattr(agent_directory_service, "list_agents", list_agents)
    monkeypatch.setattr(agent_directory_service, "get_agent", get_agent)
    monkeypatch.setattr(agent_directory_service, "update_agent_instance", update_agent_instance)
    monkeypatch.setattr(session_service, "create_chat_session", create_chat_session)

    binding = {"lifeWorld": {"setupState": "ready"}}
    first = _default_steward_provisioner(
        companion["agentId"], action="ensure", binding=binding
    )
    second = _default_steward_provisioner(
        companion["agentId"], action="ensure", binding=binding
    )

    assert first["created"] is True
    assert second["created"] is False
    assert first["agentId"] == second["agentId"] == "agent-steward"
    assert first["sessionId"] == second["sessionId"] == "session-steward"
    assert len(create_calls) == 1
    assert create_calls[0]["conversation_index_kind"] == "hidden"
    assert create_calls[0]["activate"] is False
    assert create_calls[0]["llm_bindings"] == companion["llmBindings"]
    configured = update_calls[-1]
    assert configured["prompt_template_id"] == "virtual_human_life_steward_v1"
    assert configured["metadata"]["lifeStewardForAgentId"] == companion["agentId"]
    assert configured["metadata"]["showInSessionIndex"] is False
    assert set(configured["tool_policy"]["allowedTools"]) == {
        "virtual_human_status_tool",
        "virtual_human_schedule_tool",
        "virtual_human_activity_tool",
    }


def test_default_steward_rollback_archives_only_the_created_pair(monkeypatch) -> None:
    from core.web.services import agent_directory_service

    steward = {
        "agentId": "agent-steward",
        "status": "active",
        "directSessionId": "session-steward",
        "metadata": {"lifeStewardForAgentId": "agent-companion"},
    }
    updates: list[dict] = []
    monkeypatch.setattr(
        agent_directory_service,
        "get_agent",
        lambda agent_id, include_archived=False: (
            dict(steward) if agent_id == steward["agentId"] else None
        ),
    )
    monkeypatch.setattr(
        agent_directory_service,
        "update_agent_instance",
        lambda agent_id, **kwargs: updates.append({"agentId": agent_id, **kwargs})
        or {**steward, **kwargs},
    )

    result = _default_steward_provisioner(
        "agent-companion",
        action="rollback",
        binding={},
        token={
            "created": True,
            "agentId": "agent-steward",
            "sessionId": "session-steward",
            "companionAgentId": "agent-companion",
        },
    )

    assert result["rolledBack"] is True
    assert updates == [{"agentId": "agent-steward", "status": "archived"}]


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


def test_new_binding_requires_canonical_city_and_creates_editable_life_draft(
    tmp_path,
) -> None:
    client, service = _client(tmp_path)
    try:
        locations = client.get("/api/agent-plugins/virtual-human-life/locations")
        assert locations.status_code == 200, locations.text
        assert any(row["locationId"] == "CN-SHANGHAI" for row in locations.json())

        missing_location = client.put(
            "/api/agents/agent-a/plugins/virtual-human-life/binding",
            json={
                "enabled": True,
                "expectedVersion": 0,
                "config": {"timezone": "Asia/Shanghai"},
            },
        )
        assert missing_location.status_code == 422
        assert "home location" in missing_location.json()["detail"].lower()
        assert service.binding_for("agent-a") is None

        enabled = client.put(
            "/api/agents/agent-a/plugins/virtual-human-life/binding",
            json={
                "enabled": True,
                "expectedVersion": 0,
                "config": {
                    "homeLocation": {"locationId": "CN-SHANGHAI"},
                    "lifeIdentityKind": "student",
                },
            },
        )
        assert enabled.status_code == 200, enabled.text
        binding = enabled.json()
        assert binding["configVersion"] == 1
        assert binding["homeLocation"]["cityName"] == "上海"
        assert binding["timezone"] == "Asia/Shanghai"
        assert binding["locationSetupRequired"] is False
        assert binding["lifeWorld"] == {
            "schemaVersion": 1,
            "setupState": "draft",
            "revision": 0,
        }

        snapshot = client.get(
            "/api/agents/agent-a/plugins/virtual-human-life/snapshot"
        ).json()
        assert snapshot["environment"]["localDate"] == "2026-08-27"
        assert snapshot["environment"]["weather"] is None
        assert snapshot["state"]["currentGeo"]["locationId"] == "CN-SHANGHAI"
        assert snapshot["lifeWorld"]["draft"]["payload"]["identity"]["kind"] == "student"
        assert snapshot["lifeWorld"]["facts"]["identities"] == []
    finally:
        set_virtual_human_life_service_for_tests(None)


def test_binding_transition_hides_and_restores_only_the_companion_directory_entry(
    tmp_path,
    monkeypatch,
) -> None:
    from core.web.services import virtual_human_life_service as facade

    agent = {
        "agentId": "agent-a",
        "status": "active",
        "primaryMode": "chat",
        "directSessionId": "session-a",
        "metadata": {},
    }
    calls: list[dict] = []

    def directory_manager(agent_id: str, *, action: str, restore=None):
        calls.append({"agentId": agent_id, "action": action, "restore": restore})
        if action == "hide":
            return {
                "conversationIndexKind": "personal_agent",
                "conversationIndexVisibility": "user_visible",
                "showInSessionIndex": True,
                "directSessionVisibility": "active_session",
            }
        return dict(restore or {})

    service = VirtualHumanLifeService(
        tmp_path,
        agent_loader=lambda agent_id, include_archived=False: (
            agent if agent_id == "agent-a" else None
        ),
        agent_lister=lambda: [agent],
        plugin_root_resolver=lambda agent_id: (
            tmp_path / "agents" / agent_id / "plugins" / "virtual-human-life"
        ),
        directory_visibility_manager=directory_manager,
        now_provider=lambda: datetime(2026, 8, 27, 9, 0, tzinfo=timezone.utc),
    )
    monkeypatch.setattr(
        facade,
        "_default_agent_persona_initializer",
        lambda _agent_id: {"initialized": False, "reason": "test"},
    )
    set_virtual_human_life_service_for_tests(service)
    try:
        enabled = facade.update_virtual_human_binding(
            "agent-a",
            enabled=True,
            expected_version=0,
            config={
                "homeLocation": {"locationId": "CN-SHANGHAI"},
                "lifeIdentityKind": "employee",
            },
        )
        assert calls == [{"agentId": "agent-a", "action": "hide", "restore": None}]
        assert enabled["directoryVisibility"] == {
            "state": "hidden",
            "restore": {
                "conversationIndexKind": "personal_agent",
                "conversationIndexVisibility": "user_visible",
                "showInSessionIndex": True,
                "directSessionVisibility": "active_session",
            },
        }

        disabled = facade.update_virtual_human_binding(
            "agent-a",
            enabled=False,
            expected_version=enabled["configVersion"],
            config=enabled,
        )
        assert disabled["enabled"] is False
        assert calls[-1] == {
            "agentId": "agent-a",
            "action": "restore",
            "restore": enabled["directoryVisibility"]["restore"],
        }
    finally:
        set_virtual_human_life_service_for_tests(None)


def test_enabled_legacy_binding_reconciles_companion_directory_visibility_once(
    tmp_path,
) -> None:
    from core.web.services import virtual_human_life_service as facade

    agent = {
        "agentId": "agent-a",
        "status": "active",
        "primaryMode": "chat",
        "directSessionId": "session-a",
        "metadata": {
            "conversationIndexKind": "personal_agent",
            "conversationIndexVisibility": "user_visible",
            "showInSessionIndex": True,
            "directSessionVisibility": "active_session",
        },
    }
    calls: list[dict] = []

    def directory_manager(agent_id: str, *, action: str, restore=None):
        calls.append({"agentId": agent_id, "action": action, "restore": restore})
        assert action == "hide"
        previous = dict(agent["metadata"])
        agent["metadata"].update({
            "conversationIndexKind": "hidden",
            "conversationIndexVisibility": "hidden",
            "showInSessionIndex": False,
            "virtualHumanCompanion": True,
        })
        return previous

    service = VirtualHumanLifeService(
        tmp_path,
        agent_loader=lambda agent_id, include_archived=False: (
            agent if agent_id == "agent-a" else None
        ),
        agent_lister=lambda: [agent],
        plugin_root_resolver=lambda agent_id: (
            tmp_path / "agents" / agent_id / "plugins" / "virtual-human-life"
        ),
        directory_visibility_manager=directory_manager,
        now_provider=lambda: datetime(2026, 8, 27, 9, 0, tzinfo=timezone.utc),
    )
    legacy = service.set_binding(
        "agent-a",
        enabled=True,
        expected_version=0,
        config={},
    )

    migrated = facade._reconcile_enabled_companion_directory_visibility(
        service,
        agent_id="agent-a",
        binding=legacy,
    )

    assert calls == [{"agentId": "agent-a", "action": "hide", "restore": None}]
    assert migrated["directoryVisibility"] == {
        "state": "hidden",
        "restore": {
            "conversationIndexKind": "personal_agent",
            "conversationIndexVisibility": "user_visible",
            "showInSessionIndex": True,
            "directSessionVisibility": "active_session",
        },
    }
    assert migrated["configVersion"] == legacy["configVersion"] + 1

    reconciled_again = facade._reconcile_enabled_companion_directory_visibility(
        service,
        agent_id="agent-a",
        binding=migrated,
    )

    assert reconciled_again == migrated
    assert calls == [{"agentId": "agent-a", "action": "hide", "restore": None}]


def test_life_draft_update_and_confirm_provisions_one_hidden_steward(
    tmp_path,
    monkeypatch,
) -> None:
    from core.web.services import virtual_human_life_service as facade

    agent = {
        "agentId": "agent-a",
        "status": "active",
        "primaryMode": "chat",
        "directSessionId": "session-a",
        "metadata": {},
    }
    steward_calls: list[dict] = []

    def steward_provisioner(agent_id: str, *, action: str, binding, token=None):
        steward_calls.append({"agentId": agent_id, "action": action, "token": token})
        assert binding["lifeWorld"]["setupState"] == "ready"
        return {
            "enabled": True,
            "agentId": "agent-steward-a",
            "sessionId": "session-steward-a",
            "promptPackId": "virtual_human_life_steward_v1",
            "toolBundleId": "virtual_human_life_steward",
            "provisioningState": "ready",
            "created": action == "ensure",
            "rollbackToken": {"agentId": "agent-steward-a"},
        }

    service = VirtualHumanLifeService(
        tmp_path,
        agent_loader=lambda agent_id, include_archived=False: (
            agent if agent_id == "agent-a" else None
        ),
        agent_lister=lambda: [agent],
        plugin_root_resolver=lambda agent_id: (
            tmp_path / "agents" / agent_id / "plugins" / "virtual-human-life"
        ),
        directory_visibility_manager=lambda _agent_id, **_kwargs: {
            "conversationIndexKind": "personal_agent",
            "conversationIndexVisibility": "user_visible",
            "showInSessionIndex": True,
            "directSessionVisibility": "active_session",
        },
        steward_provisioner=steward_provisioner,
        now_provider=lambda: datetime(2026, 8, 27, 9, 0, tzinfo=timezone.utc),
    )
    monkeypatch.setattr(
        facade,
        "_default_agent_persona_initializer",
        lambda _agent_id: {"initialized": False, "reason": "test"},
    )
    set_virtual_human_life_service_for_tests(service)
    app = FastAPI()
    app.include_router(agent_plugins.router, prefix="/api")
    app.include_router(virtual_human_life.router, prefix="/api")
    client = TestClient(app)
    try:
        enabled = client.put(
            "/api/agents/agent-a/plugins/virtual-human-life/binding",
            json={
                "enabled": True,
                "expectedVersion": 0,
                "config": {
                    "homeLocation": {"locationId": "CN-SHANGHAI"},
                    "lifeIdentityKind": "employee",
                },
            },
        ).json()
        draft = service.life_world_projection("agent-a")["draft"]

        updated = client.put(
            "/api/agents/agent-a/plugins/virtual-human-life/life-world/draft",
            json={
                "agentId": "agent-a",
                "draftId": draft["draftId"],
                "expectedRevision": draft["revision"],
                "idempotencyKey": "api-edit-life-draft",
                "patch": {
                    "identity": {"roleTitle": "交互设计师"},
                    "affiliations": [{"name": "星河产品工作室"}],
                },
            },
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["revision"] == 2

        confirmed = client.post(
            "/api/agents/agent-a/plugins/virtual-human-life/life-world/confirm",
            json={
                "agentId": "agent-a",
                "draftId": draft["draftId"],
                "expectedDraftRevision": 2,
                "expectedBindingVersion": enabled["configVersion"],
                "idempotencyKey": "api-confirm-life-world",
            },
        )
        assert confirmed.status_code == 200, confirmed.text
        payload = confirmed.json()
        assert payload["binding"]["configVersion"] == enabled["configVersion"] + 1
        assert payload["binding"]["lifeWorld"]["setupState"] == "ready"
        assert payload["binding"]["steward"] == {
            "enabled": True,
            "agentId": "agent-steward-a",
            "sessionId": "session-steward-a",
            "promptPackId": "virtual_human_life_steward_v1",
            "toolBundleId": "virtual_human_life_steward",
            "provisioningState": "ready",
        }
        assert payload["lifeWorld"]["facts"]["identities"][0]["roleTitle"] == "交互设计师"
        assert payload["lifeWorld"]["facts"]["affiliations"][0]["name"] == "星河产品工作室"
        tomorrow = service.schedule_for("agent-a", "2026-08-28")
        assert tomorrow["planningMode"] == "identity_confirmed_refresh"
        assert tomorrow["identityConstraint"]["kind"] == "employee"
        assert any(
            "上班" in str(activity.get("title") or "")
            for activity in tomorrow["activities"]
        )
        assert steward_calls == [
            {"agentId": "agent-a", "action": "ensure", "token": None}
        ]

        replay = client.post(
            "/api/agents/agent-a/plugins/virtual-human-life/life-world/confirm",
            json={
                "agentId": "agent-a",
                "draftId": draft["draftId"],
                "expectedDraftRevision": 2,
                "expectedBindingVersion": enabled["configVersion"],
                "idempotencyKey": "api-confirm-life-world",
            },
        )
        assert replay.status_code == 200, replay.text
        assert replay.json() == payload
        assert len(steward_calls) == 1

        active_reanchor = client.put(
            "/api/agents/agent-a/plugins/virtual-human-life/binding",
            json={
                "enabled": True,
                "expectedVersion": payload["binding"]["configVersion"],
                "config": {
                    **payload["binding"],
                    "homeLocation": {"locationId": "CN-BEIJING"},
                    "lifeIdentityKind": "student",
                },
            },
        )
        assert active_reanchor.status_code == 409, active_reanchor.text
        unchanged = service.binding_for("agent-a")
        assert unchanged["enabled"] is True
        assert unchanged["configVersion"] == payload["binding"]["configVersion"]
        assert unchanged["homeLocation"]["locationId"] == "CN-SHANGHAI"

        disabled_response = client.put(
            "/api/agents/agent-a/plugins/virtual-human-life/binding",
            json={
                "enabled": False,
                "expectedVersion": payload["binding"]["configVersion"],
                "config": payload["binding"],
            },
        )
        assert disabled_response.status_code == 200, disabled_response.text
        disabled = disabled_response.json()

        reanchor = client.put(
            "/api/agents/agent-a/plugins/virtual-human-life/binding",
            json={
                "enabled": True,
                "expectedVersion": disabled["configVersion"],
                "config": {
                    **disabled,
                    "homeLocation": {"locationId": "CN-BEIJING"},
                    "lifeIdentityKind": "student",
                },
            },
        )
        assert reanchor.status_code == 409, reanchor.text
        restored = service.binding_for("agent-a")
        assert restored["enabled"] is False
        assert restored["homeLocation"]["locationId"] == "CN-SHANGHAI"
        assert service.life_world_projection("agent-a")["setupState"] == "ready"
    finally:
        set_virtual_human_life_service_for_tests(None)


def test_life_world_confirmation_rolls_back_when_steward_provisioning_fails(
    tmp_path,
    monkeypatch,
) -> None:
    from core.web.services import virtual_human_life_service as facade

    agent = {
        "agentId": "agent-a",
        "status": "active",
        "primaryMode": "chat",
        "directSessionId": "session-a",
        "metadata": {},
    }
    service = VirtualHumanLifeService(
        tmp_path,
        agent_loader=lambda agent_id, include_archived=False: (
            agent if agent_id == "agent-a" else None
        ),
        agent_lister=lambda: [agent],
        plugin_root_resolver=lambda agent_id: (
            tmp_path / "agents" / agent_id / "plugins" / "virtual-human-life"
        ),
        directory_visibility_manager=lambda _agent_id, **_kwargs: {
            "conversationIndexKind": "personal_agent",
            "conversationIndexVisibility": "user_visible",
            "showInSessionIndex": True,
            "directSessionVisibility": "active_session",
        },
        steward_provisioner=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("steward unavailable")
        ),
        now_provider=lambda: datetime(2026, 8, 27, 9, 0, tzinfo=timezone.utc),
    )
    monkeypatch.setattr(
        facade,
        "_default_agent_persona_initializer",
        lambda _agent_id: {"initialized": False, "reason": "test"},
    )
    set_virtual_human_life_service_for_tests(service)
    app = FastAPI()
    app.include_router(agent_plugins.router, prefix="/api")
    app.include_router(virtual_human_life.router, prefix="/api")
    client = TestClient(app)
    try:
        enabled = client.put(
            "/api/agents/agent-a/plugins/virtual-human-life/binding",
            json={
                "enabled": True,
                "expectedVersion": 0,
                "config": {
                    "homeLocation": {"locationId": "CN-SHANGHAI"},
                    "lifeIdentityKind": "student",
                },
            },
        ).json()
        draft = service.life_world_projection("agent-a")["draft"]
        failed = client.post(
            "/api/agents/agent-a/plugins/virtual-human-life/life-world/confirm",
            json={
                "agentId": "agent-a",
                "draftId": draft["draftId"],
                "expectedDraftRevision": draft["revision"],
                "expectedBindingVersion": enabled["configVersion"],
                "idempotencyKey": "api-confirm-failing-steward",
            },
        )

        assert failed.status_code == 422
        projection = service.life_world_projection("agent-a")
        assert projection["setupState"] == "draft"
        assert projection["facts"]["identities"] == []
        assert service.binding_for("agent-a")["steward"]["provisioningState"] == "missing"
    finally:
        set_virtual_human_life_service_for_tests(None)


def test_life_world_confirmation_archives_created_steward_when_binding_commit_fails(
    tmp_path,
    monkeypatch,
) -> None:
    from core.web.services import virtual_human_life_service as facade

    agent = {
        "agentId": "agent-a",
        "status": "active",
        "primaryMode": "chat",
        "directSessionId": "session-a",
        "metadata": {},
    }
    steward_calls: list[dict] = []

    def steward_provisioner(agent_id: str, *, action: str, binding, token=None):
        steward_calls.append(
            {
                "agentId": agent_id,
                "action": action,
                "token": token,
            }
        )
        if action == "rollback":
            return {"rolledBack": True}
        return {
            "enabled": True,
            "agentId": "agent-steward-a",
            "sessionId": "session-steward-a",
            "promptPackId": "virtual_human_life_steward_v1",
            "toolBundleId": "virtual_human_life_steward",
            "provisioningState": "ready",
            "created": True,
            "rollbackToken": {
                "created": True,
                "agentId": "agent-steward-a",
                "sessionId": "session-steward-a",
                "companionAgentId": "agent-a",
            },
        }

    service = VirtualHumanLifeService(
        tmp_path,
        agent_loader=lambda agent_id, include_archived=False: (
            agent if agent_id == "agent-a" else None
        ),
        agent_lister=lambda: [agent],
        plugin_root_resolver=lambda agent_id: (
            tmp_path / "agents" / agent_id / "plugins" / "virtual-human-life"
        ),
        directory_visibility_manager=lambda _agent_id, **_kwargs: {
            "conversationIndexKind": "personal_agent",
            "conversationIndexVisibility": "user_visible",
            "showInSessionIndex": True,
            "directSessionVisibility": "active_session",
        },
        steward_provisioner=steward_provisioner,
        now_provider=lambda: datetime(2026, 8, 27, 9, 0, tzinfo=timezone.utc),
    )
    monkeypatch.setattr(
        facade,
        "_default_agent_persona_initializer",
        lambda _agent_id: {"initialized": False, "reason": "test"},
    )
    set_virtual_human_life_service_for_tests(service)
    app = FastAPI()
    app.include_router(agent_plugins.router, prefix="/api")
    app.include_router(virtual_human_life.router, prefix="/api")
    client = TestClient(app)
    try:
        enabled = client.put(
            "/api/agents/agent-a/plugins/virtual-human-life/binding",
            json={
                "enabled": True,
                "expectedVersion": 0,
                "config": {
                    "homeLocation": {"locationId": "CN-SHANGHAI"},
                    "lifeIdentityKind": "student",
                },
            },
        ).json()
        draft = service.life_world_projection("agent-a")["draft"]
        original_set_binding = service.set_binding

        def failing_steward_binding_commit(
            agent_id: str,
            *,
            enabled: bool,
            expected_version: int,
            config=None,
        ):
            steward = config.get("steward") if isinstance(config, dict) else {}
            if (
                isinstance(steward, dict)
                and steward.get("provisioningState") == "ready"
            ):
                raise RuntimeError("binding write unavailable")
            return original_set_binding(
                agent_id,
                enabled=enabled,
                expected_version=expected_version,
                config=config,
            )

        monkeypatch.setattr(service, "set_binding", failing_steward_binding_commit)

        failed = client.post(
            "/api/agents/agent-a/plugins/virtual-human-life/life-world/confirm",
            json={
                "agentId": "agent-a",
                "draftId": draft["draftId"],
                "expectedDraftRevision": draft["revision"],
                "expectedBindingVersion": enabled["configVersion"],
                "idempotencyKey": "api-confirm-failing-binding-commit",
            },
        )

        assert failed.status_code == 422
        assert steward_calls == [
            {"agentId": "agent-a", "action": "ensure", "token": None},
            {
                "agentId": "agent-a",
                "action": "rollback",
                "token": {
                    "created": True,
                    "agentId": "agent-steward-a",
                    "sessionId": "session-steward-a",
                    "companionAgentId": "agent-a",
                },
            },
        ]
        projection = service.life_world_projection("agent-a")
        assert projection["setupState"] == "draft"
        assert projection["facts"]["identities"] == []
        binding = service.binding_for("agent-a")
        assert binding["configVersion"] == enabled["configVersion"]
        assert binding["steward"]["provisioningState"] == "missing"
        assert binding["steward"]["agentId"] == ""
        assert binding["steward"]["sessionId"] == ""
    finally:
        set_virtual_human_life_service_for_tests(None)


def test_agent_plugin_and_virtual_human_routes_are_typed_and_agent_scoped(tmp_path) -> None:
    client, service = _client(tmp_path)
    try:
        catalog = client.get("/api/agent-plugins/catalog")
        assert catalog.status_code == 200
        assert catalog.json()[0]["pluginId"] == "virtual-human-life"
        location_schema = client.app.openapi()["paths"][
            "/api/agent-plugins/virtual-human-life/locations"
        ]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
        assert location_schema["items"]["$ref"].endswith(
            "/VirtualHumanLocationResponse"
        )

        before = client.get("/api/agents/agent-a/plugins")
        assert before.status_code == 200
        assert before.json()["plugins"][0]["binding"] is None
        assert service.plugin_root("agent-a").exists() is False

        enabled = client.put(
            "/api/agents/agent-a/plugins/virtual-human-life/binding",
            json={
                "enabled": True,
                "expectedVersion": 0,
                "config": {"homeLocation": {"locationId": "CN-SHANGHAI"}},
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
        assert snapshot.json()["causal"]["schemaVersion"] == 1
        assert snapshot.json()["todayCalendar"]["localDate"] == "2026-08-27"
        assert snapshot.json()["tomorrowCalendar"]["localDate"] == "2026-08-28"
        assert snapshot.json()["rhythms"]["chronotype"]["label"] == "balanced"
        assert snapshot.json()["causal"]["socialCircle"]["npcs"] == []
        assert isinstance(snapshot.json()["causal"]["lifeFeed"], list)
        assert all(
            item["sourceEventIds"]
            for item in snapshot.json()["causal"]["lifeFeed"]
        )
        assert snapshot.json()["causal"]["embodiment"]["activeMode"] == "portrait"
        assert snapshot.json()["state"]["locationStatus"] == "stationary"
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


def test_companion_message_endpoint_queues_without_registering_normal_session_routes(
    tmp_path,
) -> None:
    agent = {"agentId": "agent-a", "status": "active", "directSessionId": "session-a"}
    submitted: list[dict] = []
    busy = [True]

    def submitter(**payload):
        if busy[0]:
            return {"accepted": False, "busy": True}
        submitted.append(dict(payload))
        return {
            "accepted": True,
            "turnId": "turn-a",
            "acceptedAt": "2026-08-30T00:00:00+00:00",
        }

    service = VirtualHumanLifeService(
        tmp_path,
        agent_loader=lambda agent_id, include_archived=False: (
            agent if agent_id == "agent-a" else None
        ),
        agent_lister=lambda: [agent],
        plugin_root_resolver=lambda agent_id: (
            tmp_path / "agents" / agent_id / "plugins" / "virtual-human-life"
        ),
        conversation_submitter=submitter,
        auto_mailbox_dispatch=False,
        now_provider=lambda: datetime(2026, 8, 30, 0, 0, tzinfo=timezone.utc),
    )
    service.set_binding("agent-a", enabled=True, expected_version=0, config={})
    set_virtual_human_life_service_for_tests(service)
    app = FastAPI()
    app.include_router(virtual_human_life.router, prefix="/api")
    client = TestClient(app)
    try:
        queued = client.post(
            "/api/agents/agent-a/plugins/virtual-human-life/sessions/session-a/messages",
            json={
                "clientSubmissionId": "submission-a",
                "content": "我可以在你说话时继续发消息",
                "contentUtf8Base64": "5oiR5Y+v5Lul",
                "attachmentIds": ["artifact-image-a"],
                "references": [{"sessionId": "session-reference-a"}],
            },
        )

        assert queued.status_code == 202, queued.text
        assert queued.json()["queued"] is True
        assert queued.json()["accepted"] is False
        assert queued.json()["queueSequence"] == 1
        assert submitted == []
        assert client.post(
            "/api/sessions/session-a/messages",
            json={"content": "ordinary route is intentionally absent"},
        ).status_code == 404

        busy[0] = False
        accepted = service.dispatch_conversation_mailbox_once(
            "agent-a", session_id="session-a"
        )
        assert accepted["accepted"] is True
        assert submitted == [
            {
                "session_id": "session-a",
                "content": "我可以在你说话时继续发消息",
                "client_submission_id": "submission-a",
                "content_utf8_base64": "5oiR5Y+v5Lul",
                "attachment_ids": ["artifact-image-a"],
                "references": [{"sessionId": "session-reference-a"}],
                "mental_model_enabled": None,
                "runtime_status_enabled": None,
                "turn_status_tail": None,
            }
        ]
    finally:
        set_virtual_human_life_service_for_tests(None)


def test_enabling_at_nightly_time_keeps_provisional_schedule_without_planner(
    tmp_path,
    monkeypatch,
) -> None:
    from core.web.services import virtual_human_life_service as facade

    agent = {
        "agentId": "agent-a",
        "status": "active",
        "directSessionId": "session-a",
    }
    planner_calls: list[dict] = []
    service = VirtualHumanLifeService(
        tmp_path,
        agent_loader=lambda agent_id, include_archived=False: (
            agent if agent_id == "agent-a" else None
        ),
        agent_lister=lambda: [agent],
        plugin_root_resolver=lambda agent_id: (
            tmp_path / "agents" / agent_id / "plugins" / "virtual-human-life"
        ),
        schedule_planner=lambda context: planner_calls.append(context) or {
            "activities": [
                {
                    "title": "被错误调用的规划",
                    "startAt": "09:00",
                    "endAt": "10:00",
                }
            ]
        },
        now_provider=lambda: datetime(2026, 8, 27, 15, 0, tzinfo=timezone.utc),
    )
    monkeypatch.setattr(
        facade,
        "_default_agent_persona_initializer",
        lambda _agent_id: {"initialized": False, "reason": "test"},
    )
    set_virtual_human_life_service_for_tests(service)
    try:
        binding = facade.update_virtual_human_binding(
            "agent-a",
            enabled=True,
            expected_version=0,
            config={"homeLocation": {"locationId": "CN-SHANGHAI"}},
        )

        assert binding["enabled"] is True
        assert planner_calls == []
        tomorrow = service.schedule_for("agent-a", "2026-08-28")
        assert tomorrow["planningMode"] == "deterministic_mvp"
        assert tomorrow.get("plannerStatus") is None
    finally:
        set_virtual_human_life_service_for_tests(None)


def test_companion_lobby_omits_unbound_and_sessionless_agents(tmp_path, monkeypatch) -> None:
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
    monkeypatch.setattr(
        "core.web.services.agent_plugin_service._native_session_activity_by_id",
        lambda *_args, **_kwargs: {
            "session-nora": {
                "id": "session-nora",
                "status": "ready",
                "currentPhase": "ready",
                "lastTurnStatus": "completed",
                "terminalReason": "success",
                "taskSummary": "刚刚给你发了一条消息",
                "updatedAt": "2026-08-27T09:01:00Z",
                "lastActive": "2026-08-27T09:01:00Z",
                "agentInboxPendingCount": 0,
                "activityStamp": "turn:turn-nora-1:turn_completed",
            }
        },
    )
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
        assert response.json()[0]["sessionActivity"] == {
            "id": "session-nora",
            "status": "ready",
            "currentPhase": "ready",
            "lastTurnStatus": "completed",
            "terminalReason": "success",
            "taskSummary": "刚刚给你发了一条消息",
            "updatedAt": "2026-08-27T09:01:00Z",
            "lastActive": "2026-08-27T09:01:00Z",
            "agentInboxPendingCount": 0,
            "activityStamp": "turn:turn-nora-1:turn_completed",
        }
        monkeypatch.setattr(
            service,
            "snapshot",
            lambda _agent_id: (_ for _ in ()).throw(AssertionError("activity endpoint must stay lightweight")),
        )
        activity_response = client.get(
            "/api/agent-plugins/virtual-human-life/companion-activity"
        )
        assert activity_response.status_code == 200, activity_response.text
        assert activity_response.json() == [{
            "agentId": "enabled",
            "displayName": "Nora",
            "directSessionId": "session-nora",
            "sessionActivity": response.json()[0]["sessionActivity"],
        }]
    finally:
        set_virtual_human_life_service_for_tests(None)


def test_companion_activity_reuses_hidden_native_session_summary(monkeypatch) -> None:
    calls: list[dict[str, object]] = []

    def fake_query_sessions(**kwargs):
        calls.append(kwargs)
        return {
            "items": [{
                "id": "session-nora",
                "status": "ready",
                "currentPhase": "ready",
                "taskSummary": "一起去散步吧",
                "updatedAt": "2026-08-27T09:01:00Z",
                "messages": [{"role": "assistant", "content": "must not leak"}],
                "workspacePath": "private/path",
            }],
        }

    monkeypatch.setattr(
        "core.web.services.session_service.query_sessions",
        fake_query_sessions,
    )
    monkeypatch.setattr(
        "core.web.services.session_service.list_sessions",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("Companion activity must not enumerate every Session")
        ),
    )
    from types import SimpleNamespace

    monkeypatch.setattr(
        "core.web.services.session.journal_bridge.load_session_conversation_events_snapshot",
        lambda session_id: [
            SimpleNamespace(
                event_type="turn_completed",
                turn_id="turn-nora-1",
                sequence=8,
            )
        ] if session_id == "session-nora" else [],
    )
    from core.web.services.agent_plugin_service import _native_session_activity_by_id

    assert _native_session_activity_by_id([{
        "agentId": "agent-nora",
        "directSessionId": "session-nora",
    }]) == {
        "session-nora": {
            "id": "session-nora",
            "status": "ready",
            "currentPhase": "ready",
            "taskSummary": "一起去散步吧",
            "updatedAt": "2026-08-27T09:01:00Z",
            "activityStamp": "turn:turn-nora-1:turn_completed",
        }
    }
    assert calls == [{"limit": 1, "agent_id": "agent-nora"}]


def test_virtual_human_command_rejects_agent_id_mismatch_and_stale_version(tmp_path) -> None:
    client, _service = _client(tmp_path)
    try:
        client.put(
            "/api/agents/agent-a/plugins/virtual-human-life/binding",
            json={
                "enabled": True,
                "expectedVersion": 0,
                "config": {"homeLocation": {"locationId": "CN-SHANGHAI"}},
            },
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


def test_operator_can_review_reflection_through_agent_scoped_command(tmp_path) -> None:
    client, service = _client(tmp_path)
    try:
        enabled = client.put(
            "/api/agents/agent-a/plugins/virtual-human-life/binding",
            json={
                "enabled": True,
                "expectedVersion": 0,
                "config": {"homeLocation": {"locationId": "CN-SHANGHAI"}},
            },
        )
        assert enabled.status_code == 200, enabled.text
        service.store.append_jsonl(
            "agent-a",
            "events/2026-08-27.jsonl",
            {
                "eventId": "event-review-api",
                "agentId": "agent-a",
                "kind": "activity_completed",
                "activityKind": "creative",
                "title": "完成一段独立创作",
                "localDate": "2026-08-27",
                "occurredAt": "2026-08-27T09:00:00+00:00",
                "outcome": {"status": "succeeded", "summary": "完成并保存了作品。"},
            },
        )
        proposal = service.record_reflection_proposal(
            "agent-a",
            proposal_id="reflection-review-api",
            source_kind="lived_event",
            target_kind="self_narrative",
            text="我开始相信自己能独立完成创作。",
            source_event_ids=["event-review-api"],
        )
        assert proposal["status"] == "pending"
        expected_version = service.snapshot("agent-a")["state"]["stateVersion"]
        payload = {
            "agentId": "agent-a",
            "command": "reviewReflectionProposal",
            "expectedVersion": expected_version,
            "idempotencyKey": "operator-review-api-v1",
            "arguments": {
                "proposalId": proposal["proposalId"],
                "decision": "approve",
                "reviewerKind": "operator",
            },
        }

        reviewed = client.post(
            "/api/agents/agent-a/plugins/virtual-human-life/commands",
            json=payload,
        )
        duplicate = client.post(
            "/api/agents/agent-a/plugins/virtual-human-life/commands",
            json=payload,
        )

        assert reviewed.status_code == 200, reviewed.text
        assert duplicate.status_code == 200, duplicate.text
        assert duplicate.json() == reviewed.json()
        assert reviewed.json()["result"]["proposal"]["status"] == "approved"
        causal = service.snapshot("agent-a")["causal"]["reflections"]
        assert causal["pendingCount"] == 0
        assert causal["approvedCount"] == 1
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
            json={
                "enabled": True,
                "expectedVersion": 0,
                "config": {"homeLocation": {"locationId": "CN-SHANGHAI"}},
            },
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


def test_virtual_human_memories_are_agent_scoped_and_health_fails_closed(
    tmp_path,
) -> None:
    agents = {
        "agent-a": {
            "agentId": "agent-a",
            "status": "active",
            "directSessionId": "session-a",
            "personaProfile": {"personality": "安静"},
        },
        "agent-b": {
            "agentId": "agent-b",
            "status": "active",
            "directSessionId": "session-b",
        },
    }
    episodes = {
        "agent-a": [
            {
                "episodeId": "episode-a",
                "text": "A 的长期记忆",
                "occurredAt": "2026-08-27T12:00:00Z",
                "refs": [{"type": "item", "id": "event-a"}],
            }
        ],
        "agent-b": [
            {
                "episodeId": "episode-b",
                "text": "B 的长期记忆",
                "occurredAt": "2026-08-27T12:00:00Z",
                "refs": [{"type": "item", "id": "event-b"}],
            }
        ],
    }
    service = VirtualHumanLifeService(
        tmp_path,
        agent_loader=lambda agent_id, include_archived=False: agents.get(agent_id),
        agent_lister=lambda: list(agents.values()),
        plugin_root_resolver=lambda agent_id: (
            tmp_path / "agents" / agent_id / "plugins" / "virtual-human-life"
        ),
        episodic_lister=lambda agent_id, limit=500: episodes.get(agent_id, []),
        runtime_acceptance_provider=lambda: False,
        now_provider=lambda: datetime(2026, 8, 27, 9, 0, tzinfo=timezone.utc),
    )
    service.set_binding("agent-a", enabled=True, expected_version=0)
    service.set_binding("agent-b", enabled=True, expected_version=0)
    service.store.append_jsonl(
        "agent-a",
        "memory/promotion_receipts.jsonl",
        {
            "receiptId": "receipt-a",
            "episodeId": "episode-a",
            "sourceEventIds": ["event-a"],
            "salienceScore": 88,
            "occurredAt": "2026-08-27T12:00:00Z",
            "promotedAt": "2026-08-27T13:00:00Z",
        },
    )
    service.store.append_jsonl(
        "agent-b",
        "memory/promotion_receipts.jsonl",
        {
            "receiptId": "receipt-b",
            "episodeId": "episode-b",
            "sourceEventIds": ["event-b"],
            "salienceScore": 91,
            "occurredAt": "2026-08-27T12:00:00Z",
            "promotedAt": "2026-08-27T13:00:00Z",
        },
    )
    set_virtual_human_life_service_for_tests(service)
    app = FastAPI()
    app.include_router(virtual_human_life.router, prefix="/api")
    client = TestClient(app)
    try:
        memories_a = client.get(
            "/api/agents/agent-a/plugins/virtual-human-life/memories"
        )
        assert memories_a.status_code == 200, memories_a.text
        assert memories_a.json()[0]["agentId"] == "agent-a"
        assert memories_a.json()[0]["text"] == "A 的长期记忆"
        assert client.get(
            "/api/agents/missing/plugins/virtual-human-life/memories"
        ).status_code == 404

        snapshot = client.get(
            "/api/agents/agent-a/plugins/virtual-human-life/snapshot"
        )
        assert snapshot.status_code == 200, snapshot.text
        health = snapshot.json()["health"]
        assert health["heartbeatEnabled"] is False
        assert health["personaInitialized"] is True
        assert "独立存在的虚构人物" not in json.dumps(snapshot.json(), ensure_ascii=False)
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
        "core.web.services.session_service.cancel_agent_plugin_proactive_turns",
        lambda agent_id, *, plugin_id, reason: cancelled.append((agent_id, reason)) or [],
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


def test_default_schedule_planner_reuses_agent_dialogue_route_without_tools(
    monkeypatch,
) -> None:
    import config.settings as settings_module
    import core.llm as llm_module
    import core.llm.agent_runtime as agent_runtime_module
    from core.web.services import agent_directory_service

    agent = {
        "agentId": "agent-a",
        "displayName": "独立人物",
        "status": "active",
        "llmBindings": {"dialogue": {"modelId": "model-dialogue"}},
        "personaProfile": {
            "personality": "有自己的兴趣和边界。",
            "identityNotes": "独立存在的虚构人物，不是用户本人。",
        },
    }
    calls: dict[str, object] = {}
    monkeypatch.setattr(
        agent_directory_service,
        "get_agent",
        lambda agent_id, **_kwargs: agent if agent_id == "agent-a" else None,
    )
    monkeypatch.setattr(
        agent_directory_service,
        "agent_dialogue_model_id",
        lambda value: value["llmBindings"]["dialogue"]["modelId"],
    )
    config = object()
    monkeypatch.setattr(settings_module, "get_config", lambda: config)
    resolved = SimpleNamespace(
        runtime_profile_id="primary",
        config=config,
        model_id="model-dialogue",
    )
    monkeypatch.setattr(
        agent_runtime_module,
        "resolve_agent_llm",
        lambda *_args, **_kwargs: resolved,
    )
    client = object()
    def fake_get_llm_client(**kwargs):
        calls["clientKwargs"] = kwargs
        return client

    monkeypatch.setattr(llm_module, "get_llm_client", fake_get_llm_client)

    def fake_invoke(_client, messages, *, tools, context, metadata):
        calls["messages"] = messages
        calls["tools"] = tools
        calls["context"] = context
        calls["metadata"] = metadata
        return SimpleNamespace(
            content=(
                "```json\n"
                '{"activities":[{"title":"写歌","activityKind":"creative",'
                '"startAt":"09:30","endAt":"10:30"}]}\n'
                "```"
            )
        )

    monkeypatch.setattr(llm_module, "invoke_llm", fake_invoke)

    result = _default_schedule_planner(
        {
            "agentId": "agent-a",
            "localDate": "2026-08-30",
            "timezone": "Asia/Shanghai",
            "state": {"energy": 76, "socialNeed": 42},
            "recentDiary": [
                {
                    "localDate": "2026-08-29",
                    "title": "完成一段旋律",
                    "content": "留下了一个很喜欢的动机。",
                }
            ],
            "lifeWorld": {
                "setupState": "confirmed",
                "revision": 3,
                "facts": {
                    "identities": [
                        {
                            "kind": "student",
                            "roleTitle": "本科生",
                            "stage": "大二",
                        }
                    ],
                    "affiliations": [
                        {
                            "organizationKind": "school",
                            "name": "临江大学",
                            "role": "数字媒体专业学生",
                        }
                    ],
                    "routines": [
                        {
                            "dayType": "weekday",
                            "startTime": "08:00",
                            "endTime": "12:00",
                            "title": "上午课程",
                            "activityKind": "study",
                        }
                    ],
                },
            },
            "constraints": {"allowedActivityKinds": ["creative"]},
        }
    )

    assert result["activities"][0]["activityKind"] == "creative"
    assert calls["tools"] == []
    assert calls["context"].conversation_bound is False
    assert calls["context"].agent_id == "agent-a"
    payload = json.loads(calls["messages"][1]["content"])
    assert payload["recentDiary"][0]["summary"] == "留下了一个很喜欢的动机。"
    assert payload["confirmedLifeConstraints"] == {
        "setupState": "confirmed",
        "revision": 3,
        "identities": [
            {"kind": "student", "roleTitle": "本科生", "stage": "大二"}
        ],
        "affiliations": [
            {
                "organizationKind": "school",
                "name": "临江大学",
                "role": "数字媒体专业学生",
            }
        ],
        "routines": [
            {
                "dayType": "weekday",
                "startTime": "08:00",
                "endTime": "12:00",
                "title": "上午课程",
                "activityKind": "study",
            }
        ],
    }
    assert payload["constraints"]["allowedExecutionKinds"] == ["simulated"]
