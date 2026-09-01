from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from core.agent_plugins.virtual_human_life.manifest import VIRTUAL_HUMAN_TOOL_NAMES
from core.agent_plugins.virtual_human_life.geography import resolve_city_location
from core.agent_plugins.virtual_human_life.service import VirtualHumanLifeService
from core.web.services import agent_directory_service, tool_catalog
from core.web.services import virtual_human_life_service as virtual_human_facade
from core.web.services.virtual_human_life_service import (
    set_virtual_human_life_service_for_tests,
)
from tools.Key_Tools import create_key_tools
from tools.virtual_human_life_tools import (
    virtual_human_activity_tool,
    virtual_human_proactive_message_tool,
    virtual_human_reflection_tool,
    virtual_human_relationship_tool,
    virtual_human_schedule_tool,
    virtual_human_status_tool,
)


def test_virtual_human_tool_bundle_is_registered_in_key_tools_and_catalog() -> None:
    tools = create_key_tools()
    names = {getattr(item, "name", "") for item in tools}
    assert set(VIRTUAL_HUMAN_TOOL_NAMES).issubset(names)
    for name in VIRTUAL_HUMAN_TOOL_NAMES:
        assert tool_catalog.metadata_for_tool(name)["category"] == "virtual_life"
    bundles = {item["bundleId"]: item for item in tool_catalog.list_tool_bundles()}
    assert set(bundles["virtual_human_life"]["toolNames"]) == set(VIRTUAL_HUMAN_TOOL_NAMES)
    decision_tool = next(
        item
        for item in tools
        if getattr(item, "name", "") == "virtual_human_dialogue_decision_v2_tool"
    )
    assert set(decision_tool.args) == {
        "act",
        "reasonCode",
        "topicKey",
        "expectsUserReply",
        "referencedSourceKeys",
    }


def test_virtual_human_tools_fail_closed_until_current_agent_binding_is_enabled(
    tmp_path,
    monkeypatch,
) -> None:
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
    monkeypatch.setattr(
        agent_directory_service,
        "current_agent_runtime",
        lambda: {"agentId": "agent-a", "sessionId": "session-a"},
    )
    set_virtual_human_life_service_for_tests(service)
    try:
        blocked = json.loads(virtual_human_status_tool())
        assert blocked["ok"] is False
        assert blocked["error"] == "plugin_binding_disabled"
        assert service.plugin_root("agent-a").exists() is False

        service.set_binding("agent-a", enabled=True, expected_version=0)
        ready = json.loads(virtual_human_status_tool())
        assert ready["ok"] is True
        assert ready["snapshot"]["state"]["mood"]["label"] == "calm"
        mutation_without_idempotency = json.loads(
            virtual_human_activity_tool(
                action="cancel",
                expected_version=ready["snapshot"]["state"]["stateVersion"],
                activity_id=ready["snapshot"]["todaySchedule"]["activities"][0][
                    "activityId"
                ],
            )
        )
        assert mutation_without_idempotency["ok"] is False
        assert mutation_without_idempotency["error"] == "idempotency_key_required"
    finally:
        set_virtual_human_life_service_for_tests(None)


def test_life_steward_tools_resolve_only_the_paired_companion_runtime(
    tmp_path,
    monkeypatch,
) -> None:
    companion = {
        "agentId": "agent-companion",
        "status": "active",
        "directSessionId": "session-companion",
        "metadata": {"virtualHumanCompanion": True},
    }
    steward = {
        "agentId": "agent-steward",
        "status": "active",
        "directSessionId": "session-steward",
        "metadata": {"lifeStewardForAgentId": companion["agentId"]},
    }
    agents = {companion["agentId"]: companion, steward["agentId"]: steward}
    service = VirtualHumanLifeService(
        tmp_path,
        agent_loader=lambda agent_id, include_archived=False: agents.get(agent_id),
        agent_lister=lambda: list(agents.values()),
        plugin_root_resolver=lambda agent_id: (
            tmp_path / "agents" / agent_id / "plugins" / "virtual-human-life"
        ),
        now_provider=lambda: datetime(2026, 8, 30, 1, 0, tzinfo=timezone.utc),
    )
    enabled = service.set_binding(
        companion["agentId"],
        enabled=True,
        expected_version=0,
        config={
            "homeLocation": resolve_city_location("CN-SHANGHAI"),
            "lifeIdentityKind": "employee",
        },
    )
    draft = service.ensure_life_world_draft(
        companion["agentId"],
        identity_kind="employee",
        idempotency_key="steward-test-draft",
    )
    service.confirm_life_world_draft(
        companion["agentId"],
        draft_id=draft["draftId"],
        expected_revision=draft["revision"],
        idempotency_key="steward-test-confirm",
    )
    current = service.binding_for(companion["agentId"])
    service.set_binding(
        companion["agentId"],
        enabled=True,
        expected_version=current["configVersion"],
        config={
            **current,
            "steward": {
                "enabled": True,
                "agentId": steward["agentId"],
                "sessionId": steward["directSessionId"],
                "promptPackId": "virtual_human_life_steward_v1",
                "toolBundleId": "virtual_human_life_steward",
                "provisioningState": "ready",
            },
        },
    )
    runtime = {
        "agentId": companion["agentId"],
        "sessionId": companion["directSessionId"],
        "agent": companion,
    }
    monkeypatch.setattr(agent_directory_service, "current_agent_runtime", lambda: runtime)
    set_virtual_human_life_service_for_tests(service)
    try:
        life_world = service.life_world_projection(companion["agentId"])
        account = life_world["facts"]["accounts"][0]
        companion_write = json.loads(
            virtual_human_activity_tool(
                action="record_transaction",
                expected_version=0,
                expected_world_revision=life_world["revision"],
                account_id=account["accountId"],
                amount_minor=-2599,
                currency=account["currency"],
                category="daily_expense",
                description="人物不能绕过生活管家直接记账",
                occurred_at="2026-08-30T09:05:00+08:00",
                idempotency_key="companion-direct-expense",
            )
        )
        assert companion_write["ok"] is False
        assert companion_write["error"] == "life_steward_required"

        runtime.update(
            {
                "agentId": steward["agentId"],
                "sessionId": steward["directSessionId"],
                "agent": steward,
            }
        )
        status = json.loads(virtual_human_status_tool())
        assert status["ok"] is True
        assert status["agentId"] == companion["agentId"]
        assert status["runtimeAgentId"] == steward["agentId"]
        assert status["snapshot"]["agentId"] == companion["agentId"]

        life_world = service.life_world_projection(companion["agentId"])
        account = life_world["facts"]["accounts"][0]
        transaction = json.loads(
            virtual_human_activity_tool(
                action="record_transaction",
                expected_version=0,
                expected_world_revision=life_world["revision"],
                account_id=account["accountId"],
                amount_minor=-2599,
                currency=account["currency"],
                category="daily_expense",
                description="购买生活用品",
                occurred_at="2026-08-30T09:10:00+08:00",
                idempotency_key="steward-expense-1",
            )
        )
        assert transaction["ok"] is True
        assert transaction["lifeWorldResult"]["amountMinor"] == -2599

        item = json.loads(
            virtual_human_activity_tool(
                action="upsert_life_item",
                expected_version=0,
                expected_world_revision=transaction["lifeWorldResult"]["worldRevision"],
                item_id="item-headphones",
                item_category="electronics",
                item_name="无线耳机",
                item_brand="星声",
                item_model="Air 2",
                item_status="active",
                item_location="home",
                acquired_at="2026-08-30",
                idempotency_key="steward-item-1",
            )
        )
        assert item["ok"] is True, item
        assert item["lifeWorldResult"]["item"]["name"] == "无线耳机"

        runtime["sessionId"] = "session-wrong"
        blocked = json.loads(virtual_human_status_tool())
        assert blocked["ok"] is False
        assert "pair" in blocked["message"].lower()
    finally:
        set_virtual_human_life_service_for_tests(None)


def test_active_agent_runtime_carries_virtual_human_binding_fence(
    tmp_path,
    monkeypatch,
) -> None:
    agent = {
        "agentId": "agent-a",
        "status": "active",
        "directSessionId": "session-a",
        "toolPolicyId": "tool-agent-a",
        "toolPolicy": {
            "policyId": "tool-agent-a",
            "policyVersion": 1,
            "allowedTools": [],
            "blockedTools": [],
            "preferredTools": [],
            "networkAccess": "restricted",
            "mutationAccess": "controlled",
            "delegationAccess": "none",
            "maxCallsPerTurn": 4,
            "approvalOverrides": {},
        },
        "metadata": {},
        "configRevision": 1,
        "configHash": "config-agent-a",
        "permissionPreset": "request_approval",
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
        now_provider=lambda: datetime(2026, 8, 27, 9, 0, tzinfo=timezone.utc),
    )
    monkeypatch.setattr(
        agent_directory_service,
        "get_agent",
        lambda agent_id, **_kwargs: agent if agent_id == "agent-a" else None,
    )
    set_virtual_human_life_service_for_tests(service)
    try:
        with agent_directory_service.active_agent_runtime(
            "agent-a", session_id="session-a", turn_id="turn-a"
        ) as runtime:
            assert runtime["externallyBlockedTools"] == list(VIRTUAL_HUMAN_TOOL_NAMES)

        service.set_binding("agent-a", enabled=True, expected_version=0)
        with agent_directory_service.active_agent_runtime(
            "agent-a", session_id="session-a", turn_id="turn-b"
        ) as runtime:
            assert runtime["externallyBlockedTools"] == []
    finally:
        set_virtual_human_life_service_for_tests(None)


def test_active_agent_runtime_allows_the_paired_life_steward_tool_bundle(
    tmp_path,
    monkeypatch,
) -> None:
    companion = {
        "agentId": "agent-companion",
        "status": "active",
        "directSessionId": "session-companion",
        "metadata": {"virtualHumanCompanion": True},
    }
    steward = {
        "agentId": "agent-steward",
        "status": "active",
        "directSessionId": "session-steward",
        "toolPolicyId": "virtual-human-life-steward",
        "toolPolicy": {
            "policyId": "virtual-human-life-steward",
            "policyVersion": 1,
            "allowedTools": list(VIRTUAL_HUMAN_TOOL_NAMES),
            "blockedTools": [],
            "preferredTools": [],
            "networkAccess": "restricted",
            "mutationAccess": "controlled",
            "delegationAccess": "none",
            "maxCallsPerTurn": 4,
            "approvalOverrides": {},
        },
        "metadata": {"lifeStewardForAgentId": companion["agentId"]},
        "configRevision": 1,
        "configHash": "config-steward",
        "permissionPreset": "request_approval",
    }
    agents = {companion["agentId"]: companion, steward["agentId"]: steward}
    service = VirtualHumanLifeService(
        tmp_path,
        agent_loader=lambda agent_id, include_archived=False: agents.get(agent_id),
        agent_lister=lambda: list(agents.values()),
        plugin_root_resolver=lambda agent_id: (
            tmp_path / "agents" / agent_id / "plugins" / "virtual-human-life"
        ),
        now_provider=lambda: datetime(2026, 8, 30, 1, 0, tzinfo=timezone.utc),
    )
    service.set_binding(companion["agentId"], enabled=True, expected_version=0)
    current = service.binding_for(companion["agentId"])
    service.set_binding(
        companion["agentId"],
        enabled=True,
        expected_version=current["configVersion"],
        config={
            **current,
            "steward": {
                "enabled": True,
                "agentId": steward["agentId"],
                "sessionId": steward["directSessionId"],
                "promptPackId": "virtual_human_life_steward_v1",
                "toolBundleId": "virtual_human_life_steward",
                "provisioningState": "ready",
            },
        },
    )
    monkeypatch.setattr(
        agent_directory_service,
        "get_agent",
        lambda agent_id, **_kwargs: agents.get(agent_id),
    )
    set_virtual_human_life_service_for_tests(service)
    try:
        with agent_directory_service.active_agent_runtime(
            steward["agentId"],
            session_id=steward["directSessionId"],
            turn_id="turn-steward",
        ) as runtime:
            assert runtime["externallyBlockedTools"] == []
            assert set(runtime["toolPolicy"]["allowedTools"]) == set(
                VIRTUAL_HUMAN_TOOL_NAMES
            )
    finally:
        set_virtual_human_life_service_for_tests(None)


def test_active_agent_runtime_fallback_blocks_the_manifest_tool_bundle(
    monkeypatch,
) -> None:
    agent = {
        "agentId": "agent-a",
        "status": "active",
        "directSessionId": "session-a",
        "toolPolicyId": "tool-agent-a",
        "toolPolicy": {
            "policyId": "tool-agent-a",
            "policyVersion": 1,
            "allowedTools": list(VIRTUAL_HUMAN_TOOL_NAMES),
            "blockedTools": [],
            "preferredTools": [],
            "networkAccess": "restricted",
            "mutationAccess": "controlled",
            "delegationAccess": "none",
            "maxCallsPerTurn": 4,
            "approvalOverrides": {},
        },
        "metadata": {},
        "configRevision": 1,
        "configHash": "config-agent-a",
        "permissionPreset": "request_approval",
    }
    monkeypatch.setattr(
        agent_directory_service,
        "get_agent",
        lambda agent_id, **_kwargs: agent if agent_id == "agent-a" else None,
    )
    monkeypatch.setattr(
        virtual_human_facade,
        "virtual_human_binding",
        lambda _agent_id: (_ for _ in ()).throw(RuntimeError("binding unavailable")),
    )

    with agent_directory_service.active_agent_runtime(
        "agent-a", session_id="session-a", turn_id="turn-a"
    ) as runtime:
        assert runtime["externallyBlockedTools"] == list(VIRTUAL_HUMAN_TOOL_NAMES)
        assert "virtual_human_reflection_tool" in runtime["externallyBlockedTools"]


def test_virtual_human_activity_tool_can_record_a_failed_activity(
    tmp_path,
    monkeypatch,
) -> None:
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
    monkeypatch.setattr(
        agent_directory_service,
        "current_agent_runtime",
        lambda: {"agentId": "agent-a", "sessionId": "session-a"},
    )
    set_virtual_human_life_service_for_tests(service)
    try:
        service.set_binding("agent-a", enabled=True, expected_version=0)
        snapshot = service.snapshot("agent-a")
        activity_id = snapshot["todaySchedule"]["activities"][0]["activityId"]

        payload = json.loads(
            virtual_human_activity_tool(
                action="fail",
                expected_version=snapshot["state"]["stateVersion"],
                activity_id=activity_id,
                reason="授权工具执行失败",
                idempotency_key="fail-first-activity",
            )
        )

        assert payload["ok"] is True
        assert payload["commandResult"]["result"]["activity"]["status"] == "failed"
        assert service.list_events("agent-a", date="2026-08-27") == []
    finally:
        set_virtual_human_life_service_for_tests(None)


def test_virtual_human_schedule_tool_can_propose_a_permission_gated_activity(
    tmp_path,
    monkeypatch,
) -> None:
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
        now_provider=lambda: datetime(2026, 8, 27, 0, 0, tzinfo=timezone.utc),
    )
    monkeypatch.setattr(
        agent_directory_service,
        "current_agent_runtime",
        lambda: {"agentId": "agent-a", "sessionId": "session-a"},
    )
    set_virtual_human_life_service_for_tests(service)
    try:
        service.set_binding("agent-a", enabled=True, expected_version=0)
        state_version = service.snapshot("agent-a")["state"]["stateVersion"]

        payload = json.loads(
            virtual_human_schedule_tool(
                local_date="2026-08-27",
                action="propose_tool_activity",
                expected_version=state_version,
                title="生成一张生活插画",
                start_at="2026-08-27T13:00:00+08:00",
                end_at="2026-08-27T14:00:00+08:00",
                required_tool_names=["generate_image_tool"],
                idempotency_key="propose-life-image",
            )
        )

        assert payload["ok"] is True
        activity = payload["commandResult"]["result"]["activity"]
        assert activity["kind"] == "tool"
        assert activity["requiredToolNames"] == ["generate_image_tool"]
        assert activity["executionPolicy"] == "agent_tool_policy"
    finally:
        set_virtual_human_life_service_for_tests(None)


def test_proactive_tool_reuses_existing_bundle_for_open_loop_lifecycle(
    tmp_path,
    monkeypatch,
) -> None:
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
    monkeypatch.setattr(
        agent_directory_service,
        "current_agent_runtime",
        lambda: {"agentId": "agent-a", "sessionId": "session-a"},
    )
    set_virtual_human_life_service_for_tests(service)
    try:
        service.set_binding("agent-a", enabled=True, expected_version=0)
        state_version = service.snapshot("agent-a")["state"]["stateVersion"]

        recorded = json.loads(
            virtual_human_proactive_message_tool(
                action="record_open_loop",
                expected_version=state_version,
                idempotency_key="promise-song-progress",
                topic_key="song-progress",
                loop_kind="promise",
                summary="晚点分享歌曲进展",
                source_turn_id="turn-1",
                source_event_id="event-song-progress",
                expires_in_minutes=120,
            )
        )
        assert recorded["ok"] is True
        assert recorded["commandResult"]["result"]["openLoop"]["status"] == "open"
        assert recorded["commandResult"]["result"]["openLoop"]["sourceEventIds"] == [
            "event-song-progress"
        ]

        resolved = json.loads(
            virtual_human_proactive_message_tool(
                action="resolve_open_loop",
                expected_version=recorded["commandResult"]["stateVersion"],
                idempotency_key="resolve-song-progress",
                topic_key="song-progress",
                resolution="已经分享了进展",
                source_turn_id="turn-2",
            )
        )
        assert resolved["ok"] is True
        assert resolved["commandResult"]["result"]["openLoop"]["status"] == "resolved"
    finally:
        set_virtual_human_life_service_for_tests(None)


def test_activity_tool_requires_environment_provenance_and_preserves_travel_time(
    tmp_path,
    monkeypatch,
) -> None:
    agent = {"agentId": "agent-a", "status": "active", "directSessionId": "session-a"}
    clock = [datetime(2026, 8, 29, 12, 0, tzinfo=timezone.utc)]
    service = VirtualHumanLifeService(
        tmp_path,
        agent_loader=lambda agent_id, include_archived=False: (
            agent if agent_id == "agent-a" else None
        ),
        agent_lister=lambda: [agent],
        plugin_root_resolver=lambda agent_id: (
            tmp_path / "agents" / agent_id / "plugins" / "virtual-human-life"
        ),
        now_provider=lambda: clock[0],
    )
    monkeypatch.setattr(
        agent_directory_service,
        "current_agent_runtime",
        lambda: {"agentId": "agent-a", "sessionId": "session-a"},
    )
    set_virtual_human_life_service_for_tests(service)
    try:
        service.set_binding("agent-a", enabled=True, expected_version=0)
        version = service.snapshot("agent-a")["state"]["stateVersion"]

        missing_source = json.loads(
            virtual_human_activity_tool(
                action="record_environment",
                expected_version=version,
                fact_key="weather.current",
                fact_value="晴",
                source_kind="tool",
                source_ref="",
                idempotency_key="weather-without-receipt",
            )
        )
        assert missing_source["ok"] is False
        assert "sourceRef" in missing_source["message"]

        recorded = json.loads(
            virtual_human_activity_tool(
                action="record_environment",
                expected_version=version,
                fact_key="weather.current",
                fact_value="晴，28°C",
                source_kind="tool",
                source_ref="weather-tool:receipt-1",
                confidence=96,
                idempotency_key="weather-with-receipt",
            )
        )
        assert recorded["ok"] is True
        fact = recorded["commandResult"]["result"]["environmentFact"]
        assert fact["sourceKind"] == "tool"
        assert fact["sourceRef"] == "weather-tool:receipt-1"

        started = json.loads(
            virtual_human_activity_tool(
                action="start_move",
                expected_version=recorded["commandResult"]["stateVersion"],
                movement_id="move-library",
                destination="library",
                travel_minutes=30,
                source_kind="schedule_outcome",
                source_ref="activity:walk-to-library",
                idempotency_key="start-library-move",
            )
        )
        assert started["ok"] is True
        assert service.snapshot("agent-a")["state"]["currentLocation"] == "home"
        assert service.snapshot("agent-a")["state"]["movingTo"] == "library"

        clock[0] += timedelta(minutes=20)
        too_early = json.loads(
            virtual_human_activity_tool(
                action="complete_move",
                expected_version=started["commandResult"]["stateVersion"],
                movement_id="move-library",
                idempotency_key="complete-library-move-early",
            )
        )
        assert too_early["ok"] is False
        assert "earliestArrivalAt" in too_early["message"]
        assert service.snapshot("agent-a")["state"]["currentLocation"] == "home"

        clock[0] += timedelta(minutes=10)
        arrived = json.loads(
            virtual_human_activity_tool(
                action="complete_move",
                expected_version=started["commandResult"]["stateVersion"],
                movement_id="move-library",
                idempotency_key="complete-library-move",
            )
        )
        assert arrived["ok"] is True
        assert service.snapshot("agent-a")["state"]["currentLocation"] == "library"
    finally:
        set_virtual_human_life_service_for_tests(None)


def test_schedule_tool_maintains_long_term_calendar_without_claiming_execution(
    tmp_path,
    monkeypatch,
) -> None:
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
        now_provider=lambda: datetime(2026, 8, 29, 3, 0, tzinfo=timezone.utc),
    )
    monkeypatch.setattr(
        agent_directory_service,
        "current_agent_runtime",
        lambda: {"agentId": "agent-a", "sessionId": "session-a"},
    )
    set_virtual_human_life_service_for_tests(service)
    try:
        service.set_binding("agent-a", enabled=True, expected_version=0)
        version = service.snapshot("agent-a")["state"]["stateVersion"]
        created = json.loads(
            virtual_human_schedule_tool(
                action="upsert_calendar",
                expected_version=version,
                idempotency_key="calendar-weekly-reading",
                event_id="weekly-reading",
                local_date="2026-08-29",
                title="每周阅读",
                calendar_kind="recurring",
                start_at="2026-08-29T19:00:00+08:00",
                end_at="2026-08-29T20:00:00+08:00",
                recurrence={"frequency": "weekly", "byWeekday": [5]},
                source_kind="agent",
                source_ref="self-plan:weekly-reading",
            )
        )
        assert created["ok"] is True
        occurrence = created["commandResult"]["result"]["calendar"]["occurrences"][0]
        assert occurrence["calendarEventId"] == "weekly-reading"
        schedule_activity = next(
            item
            for item in service.snapshot("agent-a")["todaySchedule"]["activities"]
            if item.get("calendarEventId") == "weekly-reading"
        )
        assert schedule_activity["status"] == "planned"
        assert schedule_activity.get("outcome") is None
    finally:
        set_virtual_human_life_service_for_tests(None)


def test_full_life_tools_record_only_source_backed_world_npc_and_artifact(
    tmp_path,
    monkeypatch,
) -> None:
    agent = {"agentId": "agent-a", "status": "active", "directSessionId": "session-a"}
    now = datetime(2026, 8, 29, 12, 0, tzinfo=timezone.utc)
    service = VirtualHumanLifeService(
        tmp_path,
        agent_loader=lambda agent_id, include_archived=False: (
            agent if agent_id == "agent-a" else None
        ),
        agent_lister=lambda: [agent],
        plugin_root_resolver=lambda agent_id: (
            tmp_path / "agents" / agent_id / "plugins" / "virtual-human-life"
        ),
        now_provider=lambda: now,
    )
    monkeypatch.setattr(
        agent_directory_service,
        "current_agent_runtime",
        lambda: {"agentId": "agent-a", "sessionId": "session-a"},
    )
    set_virtual_human_life_service_for_tests(service)
    try:
        service.set_binding("agent-a", enabled=True, expected_version=0)
        service.store.append_jsonl(
            "agent-a",
            "events/2026-08-29.jsonl",
            {
                "eventId": "event-reading-1",
                "agentId": "agent-a",
                "kind": "activity_completed",
                "activityKind": "reading",
                "title": "图书馆阅读",
                "localDate": "2026-08-29",
                "occurredAt": now.isoformat(),
                "outcome": {
                    "status": "succeeded",
                    "kind": "verified_tool_outcome",
                    "summary": "读完并留下三条笔记。",
                },
            },
        )
        version = service.snapshot("agent-a")["state"]["stateVersion"]
        place = json.loads(
            virtual_human_activity_tool(
                action="record_place_visit",
                expected_version=version,
                idempotency_key="record-library",
                place_id="library",
                place_label="社区图书馆",
                route_from="home",
                route_minutes=20,
                source_ref="event-reading-1",
            )
        )
        assert place["ok"] is True
        version = place["commandResult"]["stateVersion"]
        item = json.loads(
            virtual_human_activity_tool(
                action="record_important_item",
                expected_version=version,
                idempotency_key="record-notebook",
                item_id="notebook-blue",
                item_label="蓝色笔记本",
                place_id="home",
                source_kind="activity_outcome",
                source_ref="event-reading-1",
                significance="记录读书和旋律笔记",
            )
        )
        assert item["ok"] is True
        version = item["commandResult"]["stateVersion"]
        artifact = json.loads(
            virtual_human_activity_tool(
                action="record_artifact_receipt",
                expected_version=version,
                idempotency_key="record-reading-note",
                artifact_id="reading-note",
                artifact_kind="note",
                artifact_title="三条读书笔记",
                artifact_summary="整理了今天最喜欢的三个段落。",
                source_event_ids=["event-reading-1"],
                local_ref="artifacts/reading-note.md",
            )
        )
        assert artifact["ok"] is True
        version = artifact["commandResult"]["stateVersion"]
        npc = json.loads(
            virtual_human_relationship_tool(
                action="upsert_npc",
                expected_version=version,
                idempotency_key="record-npc-lin",
                npc_id="npc-lin",
                display_name="林溪",
                role="图书馆认识的朋友",
                traits=["安静", "喜欢推理小说"],
                source_kind="lived_event",
                source_ref="event-reading-1",
            )
        )
        assert npc["ok"] is True
        causal = service.snapshot("agent-a")["causal"]
        assert causal["world"]["places"][0]["placeId"] == "library"
        assert causal["world"]["importantItems"][0]["itemId"] == "notebook-blue"
        assert causal["socialCircle"]["npcs"][0]["kind"] == "npc"
        assert any(row["kind"] == "artifact" for row in causal["lifeFeed"])
    finally:
        set_virtual_human_life_service_for_tests(None)


def test_reflection_tool_can_propose_but_cannot_self_approve(
    tmp_path,
    monkeypatch,
) -> None:
    agent = {"agentId": "agent-a", "status": "active", "directSessionId": "session-a"}
    now = datetime(2026, 8, 29, 12, 0, tzinfo=timezone.utc)
    service = VirtualHumanLifeService(
        tmp_path,
        agent_loader=lambda agent_id, include_archived=False: (
            agent if agent_id == "agent-a" else None
        ),
        agent_lister=lambda: [agent],
        plugin_root_resolver=lambda agent_id: (
            tmp_path / "agents" / agent_id / "plugins" / "virtual-human-life"
        ),
        now_provider=lambda: now,
    )
    monkeypatch.setattr(
        agent_directory_service,
        "current_agent_runtime",
        lambda: {"agentId": "agent-a", "sessionId": "session-a"},
    )
    set_virtual_human_life_service_for_tests(service)
    try:
        service.set_binding("agent-a", enabled=True, expected_version=0)
        service.store.append_jsonl(
            "agent-a",
            "events/2026-08-29.jsonl",
            {
                "eventId": "event-lived-1",
                "kind": "activity_completed",
                "localDate": "2026-08-29",
                "occurredAt": now.isoformat(),
                "outcome": {"status": "succeeded", "summary": "完成了第一次独立创作。"},
            },
        )
        version = service.snapshot("agent-a")["state"]["stateVersion"]
        proposed = json.loads(
            virtual_human_reflection_tool(
                action="propose",
                proposal_id="reflection-first-creation",
                source_kind="lived_event",
                target_kind="self_narrative",
                text="我开始相信自己能完成独立创作。",
                source_event_ids=["event-lived-1"],
                expected_version=version,
                idempotency_key="propose-first-creation",
            )
        )
        assert proposed["ok"] is True
        assert proposed["commandResult"]["result"]["reflectionProposal"]["status"] == "pending"

        blocked = json.loads(virtual_human_reflection_tool(action="approve"))
        assert blocked["ok"] is False
        assert blocked["error"] == "invalid_action"
        assert service.list_reflection_proposals("agent-a")[0]["status"] == "pending"
    finally:
        set_virtual_human_life_service_for_tests(None)


def test_relationship_tool_without_arguments_preserves_legacy_read_behavior(
    tmp_path,
    monkeypatch,
) -> None:
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
    )
    monkeypatch.setattr(
        agent_directory_service,
        "current_agent_runtime",
        lambda: {"agentId": "agent-a", "sessionId": "session-a"},
    )
    set_virtual_human_life_service_for_tests(service)
    try:
        service.set_binding("agent-a", enabled=True, expected_version=0)

        payload = json.loads(virtual_human_relationship_tool())

        assert payload["ok"] is True
        assert payload["status"] == "ready"
        assert payload["relationships"][0]["targetId"] == "user"
    finally:
        set_virtual_human_life_service_for_tests(None)
