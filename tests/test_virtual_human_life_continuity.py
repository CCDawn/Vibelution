from datetime import UTC, datetime

from core.agent_plugins.virtual_human_life.embodiment import resolve_embodiment
from core.agent_plugins.virtual_human_life.expression_policy import (
    project_expression_rules,
)
from core.agent_plugins.virtual_human_life.interests import project_interests
from core.agent_plugins.virtual_human_life.life_feed import build_life_feed
from core.agent_plugins.virtual_human_life.service import VirtualHumanLifeService
from core.agent_plugins.virtual_human_life.social_circle import upsert_npc
from core.agent_plugins.virtual_human_life.world_model import (
    record_important_item,
    record_place_visit,
)


def test_interests_only_grow_from_successful_outcome_backed_activities() -> None:
    events = [
        {
            "eventId": "event-planned",
            "kind": "activity_planned",
            "activityKind": "reading",
            "title": "读一本小说",
        },
        {
            "eventId": "event-failed",
            "kind": "activity_failed",
            "activityKind": "creative",
            "title": "画一张速写",
            "outcome": {"status": "failed", "summary": "没有完成"},
        },
        {
            "eventId": "event-reading",
            "kind": "activity_completed",
            "activityKind": "reading",
            "title": "读完一章小说",
            "occurredAt": "2026-08-29T10:00:00+00:00",
            "outcome": {
                "status": "succeeded",
                "kind": "verified_tool_outcome",
                "summary": "读完并留下三条读书笔记。",
                "salienceScore": 72,
            },
        },
        {
            "eventId": "event-reading",
            "kind": "activity_completed",
            "activityKind": "reading",
            "title": "重复回放",
            "outcome": {
                "status": "succeeded",
                "kind": "verified_tool_outcome",
                "summary": "重复事件不应再次成长。",
            },
        },
    ]

    projection = project_interests(events)

    assert projection["processedEventIds"] == ["event-reading"]
    assert projection["items"] == [
        {
            "interestKey": "reading",
            "label": "阅读",
            "experience": 8,
            "level": 1,
            "completedCount": 1,
            "lastOutcomeSummary": "读完并留下三条读书笔记。",
            "lastPracticedAt": "2026-08-29T10:00:00+00:00",
            "sourceEventIds": ["event-reading"],
        }
    ]


def test_world_catalog_keeps_stable_places_routes_and_source_backed_items() -> None:
    now = datetime(2026, 8, 29, 12, 0, tzinfo=UTC)
    catalog: dict = {}

    catalog = record_place_visit(
        catalog,
        place_id="library",
        label="社区图书馆",
        source_event_id="event-visit-1",
        occurred_at=now,
        route_from="home",
        route_minutes=20,
        living_space=False,
    )
    catalog = record_place_visit(
        catalog,
        place_id="library",
        label="社区图书馆",
        source_event_id="event-visit-1",
        occurred_at=now,
        route_from="home",
        route_minutes=20,
    )
    catalog = record_important_item(
        catalog,
        item_id="notebook-blue",
        label="蓝色旋律本",
        place_id="home",
        source_kind="activity_outcome",
        source_ref="event-creative-1",
        significance="记录原创旋律",
        recorded_at=now,
    )

    assert catalog["places"][0]["visitCount"] == 1
    assert catalog["places"][0]["sourceEventIds"] == ["event-visit-1"]
    assert catalog["routes"][0]["fromPlaceId"] == "home"
    assert catalog["routes"][0]["toPlaceId"] == "library"
    assert catalog["importantItems"][0]["sourceRef"] == "event-creative-1"


def test_social_circle_profiles_are_stable_npcs_not_agent_records() -> None:
    now = datetime(2026, 8, 29, 12, 0, tzinfo=UTC)
    catalog: dict = {}

    catalog = upsert_npc(
        catalog,
        npc_id="npc-lin",
        display_name="林溪",
        role="图书馆认识的朋友",
        traits=["安静", "喜欢推理小说"],
        source_kind="lived_event",
        source_ref="event-social-1",
        now=now,
    )
    catalog = upsert_npc(
        catalog,
        npc_id="npc-lin",
        display_name="林溪",
        role="图书馆认识的朋友",
        traits=["喜欢推理小说", "细心"],
        source_kind="lived_event",
        source_ref="event-social-2",
        now=now,
    )

    npc = catalog["npcs"][0]
    assert npc["npcId"] == "npc-lin"
    assert npc["kind"] == "npc"
    assert "agentId" not in npc
    assert npc["traits"] == ["安静", "喜欢推理小说", "细心"]
    assert npc["sourceRefs"] == ["event-social-1", "event-social-2"]


def test_life_feed_is_a_read_only_projection_of_lived_events_and_artifacts() -> None:
    feed = build_life_feed(
        events=[
            {
                "eventId": "event-done",
                "kind": "activity_completed",
                "activityKind": "creative",
                "title": "完成一段旋律",
                "occurredAt": "2026-08-29T11:00:00+00:00",
                "outcome": {
                    "status": "succeeded",
                    "summary": "把午后的雨声写进了一段旋律。",
                },
            },
            {
                "eventId": "event-plan",
                "kind": "activity_planned",
                "title": "准备画画",
            },
        ],
        diary_entries=[
            {
                "diaryEntryId": "diary-1",
                "title": "雨天创作",
                "content": "今天留下了一个很喜欢的动机。",
                "writtenAt": "2026-08-29T12:00:00+00:00",
                "sourceEventIds": ["event-done"],
            }
        ],
        artifact_receipts=[
            {
                "artifactId": "art-1",
                "kind": "audio",
                "title": "雨声旋律草稿",
                "status": "succeeded",
                "createdAt": "2026-08-29T11:30:00+00:00",
                "sourceEventIds": ["event-done"],
                "localRef": "artifacts/rain-melody.wav",
            },
            {
                "artifactId": "art-failed",
                "status": "failed",
                "sourceEventIds": ["event-done"],
            },
        ],
    )

    assert [item["kind"] for item in feed] == ["diary", "artifact", "life_event"]
    assert {item["sourceEventIds"][0] for item in feed} == {"event-done"}
    assert all("event-plan" not in item["sourceEventIds"] for item in feed)


def test_expression_rules_are_ranked_and_explain_why_they_apply() -> None:
    projection = project_expression_rules(
        [
            {
                "ruleId": "habit-emoji",
                "scope": "habit",
                "priority": 20,
                "condition": {"mood": "happy"},
                "action": {"style": "use_light_emoji"},
            },
            {
                "ruleId": "relationship-boundary",
                "scope": "relationship_boundary",
                "priority": 5,
                "condition": {"relationshipStage": "getting_to_know"},
                "action": {"style": "avoid_overfamiliar_address"},
            },
            {
                "ruleId": "safety-no-secret",
                "scope": "identity_safety",
                "priority": 1,
                "condition": {"sensitiveRequest": True},
                "action": {"style": "keep_private_boundaries"},
            },
        ],
        context={
            "mood": "happy",
            "relationshipStage": "getting_to_know",
            "sensitiveRequest": True,
        },
    )

    assert [item["ruleId"] for item in projection["applied"]] == [
        "safety-no-secret",
        "relationship-boundary",
        "habit-emoji",
    ]
    assert projection["applied"][0]["explanation"] == (
        "identity_safety matched sensitiveRequest=True"
    )


def test_embodiment_is_optional_and_falls_back_to_existing_portrait() -> None:
    unavailable = resolve_embodiment(
        {
            "enabled": True,
            "providerId": "live2d-local",
            "mode": "live2d",
            "assetRef": "assets/character.model3.json",
        },
        authorized_assets=[],
        provider_health={"live2d-local": {"available": True}},
    )
    healthy = resolve_embodiment(
        {
            "enabled": True,
            "providerId": "live2d-local",
            "mode": "live2d",
            "assetRef": "assets/character.model3.json",
        },
        authorized_assets=[
            {
                "assetRef": "assets/character.model3.json",
                "licenseReceipt": "user-owned-asset",
            }
        ],
        provider_health={"live2d-local": {"available": True}},
    )

    assert unavailable["activeMode"] == "portrait"
    assert unavailable["fallbackReason"] == "asset_not_authorized"
    assert healthy["activeMode"] == "live2d"
    assert healthy["providerId"] == "live2d-local"
    assert healthy["textChatUnaffected"] is True


def test_service_projects_full_life_continuity_without_creating_npc_agents(tmp_path) -> None:
    clock = datetime(2026, 8, 29, 12, 0, tzinfo=UTC)
    agent = {
        "agentId": "agent-a",
        "status": "active",
        "directSessionId": "session-a",
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
        embodiment_health_provider=lambda _agent_id: {
            "live2d-local": {"available": True}
        },
        now_provider=lambda: clock,
    )
    service.set_binding("agent-a", enabled=True, expected_version=0)
    event = {
        "eventId": "event-reading-1",
        "agentId": "agent-a",
        "activityId": "reading-1",
        "kind": "activity_completed",
        "activityKind": "reading",
        "title": "读完一章小说",
        "localDate": "2026-08-29",
        "occurredAt": clock.isoformat(),
        "outcome": {
            "status": "succeeded",
            "kind": "verified_tool_outcome",
            "summary": "读完并留下三条笔记。",
            "salienceScore": 72,
        },
    }
    service.store.append_jsonl("agent-a", "events/2026-08-29.jsonl", event)

    state_version = service.snapshot("agent-a")["state"]["stateVersion"]

    def execute(command: str, key: str, arguments: dict) -> dict:
        nonlocal state_version
        result = service.execute_command(
            "agent-a",
            command=command,
            expected_version=state_version,
            idempotency_key=key,
            arguments=arguments,
        )
        state_version = result["stateVersion"]
        return result

    execute(
        "recordPlaceVisit",
        "visit-library",
        {
            "placeId": "library",
            "label": "社区图书馆",
            "sourceEventId": event["eventId"],
            "routeFrom": "home",
            "routeMinutes": 20,
        },
    )
    execute(
        "recordImportantItem",
        "record-notebook",
        {
            "itemId": "notebook-blue",
            "label": "蓝色笔记本",
            "placeId": "home",
            "sourceKind": "activity_outcome",
            "sourceRef": event["eventId"],
            "significance": "记录读书和旋律笔记",
        },
    )
    execute(
        "upsertNpc",
        "npc-lin",
        {
            "npcId": "npc-lin",
            "displayName": "林溪",
            "role": "图书馆认识的朋友",
            "traits": ["安静", "喜欢推理小说"],
            "sourceKind": "lived_event",
            "sourceRef": event["eventId"],
        },
    )
    execute(
        "recordArtifactReceipt",
        "artifact-reading-note",
        {
            "artifactId": "artifact-reading-note",
            "kind": "note",
            "title": "三条读书笔记",
            "summary": "整理了今天最喜欢的三个段落。",
            "status": "succeeded",
            "sourceEventIds": [event["eventId"]],
            "localRef": "artifacts/reading-note.md",
        },
    )
    execute(
        "setExpressionRules",
        "expression-rules",
        {
            "rules": [
                {
                    "ruleId": "habit-gentle-summary",
                    "scope": "habit",
                    "priority": 10,
                    "condition": {},
                    "action": {"style": "share_small_lived_detail"},
                }
            ]
        },
    )
    execute(
        "setEmbodimentConfig",
        "embodiment-live2d",
        {
            "enabled": True,
            "providerId": "live2d-local",
            "mode": "live2d",
            "assetRef": "assets/character.model3.json",
            "assetLicenseReceipt": "user-owned-asset",
        },
    )

    causal = service.snapshot("agent-a")["causal"]
    assert causal["interests"]["items"][0]["interestKey"] == "reading"
    assert causal["world"]["places"][0]["placeId"] == "library"
    assert causal["world"]["importantItems"][0]["itemId"] == "notebook-blue"
    assert causal["socialCircle"]["npcs"][0]["kind"] == "npc"
    assert "agentId" not in causal["socialCircle"]["npcs"][0]
    assert service.agent_lister() == [agent]
    assert any(item["kind"] == "artifact" for item in causal["lifeFeed"])
    assert causal["expression"]["applied"][0]["ruleId"] == "habit-gentle-summary"
    assert causal["embodiment"]["activeMode"] == "live2d"
