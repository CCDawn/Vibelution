from __future__ import annotations

from datetime import datetime, timedelta, timezone

from core.agent_plugins.virtual_human_life.affect import (
    episode_from_life_event,
    project_affect,
)
from core.agent_plugins.virtual_human_life.causal_contracts import (
    CAUSAL_LEDGER_PATHS,
    CAUSAL_SCHEMA_VERSION,
    authorized_reuse_receipt,
)
from core.agent_plugins.virtual_human_life.conversation_continuity import (
    build_proactive_candidate,
    evaluate_proactive_candidate,
    project_open_loops,
    resolve_open_loop,
    upsert_open_loop,
)
from core.agent_plugins.virtual_human_life.drives import (
    apply_completed_event_to_drives,
    default_drive_projection,
    link_schedule_to_drives,
)
from core.agent_plugins.virtual_human_life.relationship_events import (
    make_relationship_event,
    project_relationships,
)
from core.agent_plugins.virtual_human_life.service import VirtualHumanLifeService

UTC = timezone.utc


def _completed_event(
    event_id: str,
    *,
    kind: str = "creative",
    occurred_at: datetime | None = None,
    mood_delta: int = 8,
) -> dict:
    occurred = occurred_at or datetime(2026, 8, 29, 9, 0, tzinfo=UTC)
    return {
        "eventId": event_id,
        "kind": "activity_completed",
        "activityKind": kind,
        "title": "推进自己的创作项目",
        "occurredAt": occurred.isoformat(),
        "localDate": occurred.date().isoformat(),
        "outcome": {
            "status": "succeeded",
            "summary": "完成了一个可以复核的小阶段",
            "moodDelta": mood_delta,
        },
    }


def test_authorized_reuse_receipt_and_causal_paths_are_explicit() -> None:
    receipt = authorized_reuse_receipt()

    assert CAUSAL_SCHEMA_VERSION == 1
    assert receipt["sourceRepo"] == "https://github.com/menglimi/astrbot_plugin_private_companion"
    assert receipt["sourceCommit"] == "85cc366ee6e1ccf08b357e8b9e396c3abb842ff4"
    assert receipt["permissionBasis"] == "user_confirmed_upstream_permission_2026-08-29"
    assert receipt["publicationBoundary"] == "requires_separate_attribution_and_distribution_confirmation"
    assert {slice_["sliceId"] for slice_ in receipt["slices"]} >= {
        "proactive-candidate-policy",
        "affect-afterglow",
        "relationship-ledger",
        "life-drives-and-open-loops",
    }
    assert CAUSAL_LEDGER_PATHS == {
        "drives": "drives/state.json",
        "driveEvents": "drives/events.jsonl",
        "affectEpisodes": "affect/episodes.jsonl",
        "affectProjection": "affect/state.json",
        "relationshipEvents": "relationships/events.jsonl",
        "relationshipProjection": "relationships.json",
        "proactiveCandidates": "proactive/candidates.jsonl",
        "openLoops": "conversation/open_loops.jsonl",
        "reflectionProposals": "reflections/proposals.jsonl",
        "memoryReinforcements": "memory/reinforcement_receipts.jsonl",
        "environmentFacts": "environment/facts.jsonl",
        "locationMovements": "environment/location_movements.jsonl",
    }


def test_completed_event_advances_life_drives_once_and_links_future_plan() -> None:
    now = datetime(2026, 8, 29, 9, 0, tzinfo=UTC)
    projection = default_drive_projection(now=now)
    event = _completed_event("life-1", occurred_at=now)

    first = apply_completed_event_to_drives(projection, event, now=now)
    duplicate = apply_completed_event_to_drives(first["projection"], event, now=now)

    assert first["change"] is not None
    assert first["change"]["sourceEventId"] == "life-1"
    assert first["projection"]["projects"][0]["progress"] > 0
    assert first["projection"]["skills"][0]["experience"] > 0
    assert duplicate["change"] is None
    assert duplicate["projection"] == first["projection"]

    failed = _completed_event("life-2", occurred_at=now)
    failed["outcome"]["status"] = "failed"
    ignored = apply_completed_event_to_drives(first["projection"], failed, now=now)
    assert ignored["change"] is None
    assert "life-2" not in ignored["projection"]["processedEventIds"]

    schedule = {
        "activities": [
            {"activityId": "a", "title": "继续创作", "activityKind": "creative"},
            {"activityId": "b", "title": "夜间回顾", "activityKind": "reflection"},
        ]
    }
    linked = link_schedule_to_drives(schedule, first["projection"])
    assert linked["activities"][0]["driveLinks"]
    assert linked["activities"][0]["driveReason"]
    assert linked["activities"][1]["driveLinks"]


def test_affect_episode_recovers_deterministically_without_source_free_jump() -> None:
    now = datetime(2026, 8, 29, 10, 0, tzinfo=UTC)
    event = _completed_event("affect-1", occurred_at=now, mood_delta=-30)
    episode = episode_from_life_event(event, now=now)

    assert episode is not None
    assert episode["sourceEventId"] == "affect-1"
    assert episode["status"] == "active"

    immediate = project_affect([episode], now=now)
    recovered = project_affect([episode], now=now + timedelta(hours=18))
    empty = project_affect([], now=now)

    assert immediate["mood"]["valence"] < empty["mood"]["valence"]
    assert immediate["activeEpisodeIds"] == [episode["episodeId"]]
    assert recovered["activeEpisodeIds"] == []
    assert {
        key: value for key, value in recovered["mood"].items() if key != "updatedAt"
    } == {key: value for key, value in empty["mood"].items() if key != "updatedAt"}
    assert recovered["recoveredEpisodeIds"] == [episode["episodeId"]]


def test_relationship_ledger_caps_daily_change_and_delays_stage_transitions() -> None:
    start = datetime(2026, 8, 29, 12, 0, tzinfo=UTC)
    events = [
        make_relationship_event(
            event_id=f"rel-{index}",
            target_id="user",
            kind="supportive_conversation",
            intimacy_delta=8,
            trust_delta=8,
            occurred_at=start + timedelta(minutes=index),
        )
        for index in range(4)
    ]
    first_day = project_relationships([], events, now=start + timedelta(hours=1))[0]

    assert first_day["intimacy"] == 62
    assert first_day["trust"] == 62
    assert first_day["relationshipStage"] == "getting_to_know"
    assert first_day["interactionCount"] == 4

    for offset in range(1, 4):
        events.append(
            make_relationship_event(
                event_id=f"rel-next-{offset}",
                target_id="user",
                kind="shared_experience",
                intimacy_delta=8,
                trust_delta=8,
                occurred_at=start + timedelta(days=offset),
            )
        )
    later = project_relationships([], events, now=start + timedelta(days=3, hours=1))[0]
    assert later["relationshipStage"] == "friend"

    before_repair_trust = later["trust"]
    events.extend(
        [
            make_relationship_event(
                event_id="rel-conflict",
                target_id="user",
                kind="conflict",
                intimacy_delta=-8,
                trust_delta=-8,
                occurred_at=start + timedelta(days=4),
            ),
            make_relationship_event(
                event_id="rel-apology",
                target_id="user",
                kind="apology_repair",
                intimacy_delta=2,
                trust_delta=6,
                occurred_at=start + timedelta(days=5),
            ),
        ]
    )
    repaired = project_relationships([], events, now=start + timedelta(days=5, hours=1))[0]
    assert repaired["trust"] >= before_repair_trust - 2
    assert repaired["relationshipStage"] == "friend"

    decayed = project_relationships([], events, now=start + timedelta(days=60))[0]
    assert decayed["intimacy"] < repaired["intimacy"]
    assert decayed["relationshipStage"] in {"getting_to_know", "friend"}


def test_proactive_candidate_has_explainable_suppression_without_creating_turn() -> None:
    now = datetime(2026, 8, 29, 13, 0, tzinfo=UTC)
    event = _completed_event("candidate-1", occurred_at=now)
    candidate = build_proactive_candidate(
        event,
        drive_projection=default_drive_projection(now=now),
        affect_projection=project_affect([], now=now),
        relationship={"relationshipStage": "friend", "trust": 70},
        now=now,
    )

    assert candidate["sourceEventId"] == "candidate-1"
    assert candidate["scoreBreakdown"]["sourceValue"] > 0
    assert candidate["status"] == "pending"

    quiet = evaluate_proactive_candidate(
        candidate,
        now=now,
        quiet_hours=True,
        sleep_state="awake",
        busy=False,
        recent_topic_keys=set(),
        unanswered_count=0,
    )
    assert quiet["decision"] == "suppress"
    assert quiet["suppressionReason"] == "quiet_hours"

    duplicate = evaluate_proactive_candidate(
        candidate,
        now=now,
        quiet_hours=False,
        sleep_state="awake",
        busy=False,
        recent_topic_keys={candidate["topicKey"]},
        unanswered_count=0,
    )
    assert duplicate["suppressionReason"] == "duplicate_topic"

    unanswered = evaluate_proactive_candidate(
        candidate,
        now=now,
        quiet_hours=False,
        sleep_state="awake",
        busy=False,
        recent_topic_keys=set(),
        unanswered_count=2,
    )
    assert unanswered["suppressionReason"] == "unanswered_backoff"

    eligible = evaluate_proactive_candidate(
        candidate,
        now=now,
        quiet_hours=False,
        sleep_state="awake",
        busy=False,
        recent_topic_keys=set(),
        unanswered_count=0,
    )
    assert eligible["decision"] == "eligible"
    assert eligible["status"] == "eligible"
    assert "turnId" not in eligible

    custom_baseline = project_affect(
        [],
        now=now,
        baseline_mood={
            "label": "hopeful",
            "valence": 60,
            "arousal": 35,
            "stability": 70,
        },
    )
    baseline_candidate = build_proactive_candidate(
        event,
        drive_projection=default_drive_projection(now=now),
        affect_projection=custom_baseline,
        relationship={"relationshipStage": "friend", "trust": 70},
        now=now,
    )
    assert baseline_candidate["scoreBreakdown"]["affectValue"] == 0


def test_open_loops_dedupe_resolve_and_expire_with_accelerated_clock() -> None:
    now = datetime(2026, 8, 29, 14, 0, tzinfo=UTC)
    rows = upsert_open_loop(
        [],
        loop_id="loop-1",
        topic_key="music-project",
        kind="promise",
        summary="之后告诉你这首歌的进展",
        source_turn_id="turn-1",
        source_event_id="event-1",
        now=now,
        expires_at=now + timedelta(hours=6),
    )
    rows = upsert_open_loop(
        rows,
        loop_id="loop-2",
        topic_key="music-project",
        kind="topic",
        summary="继续聊这首歌",
        source_turn_id="turn-2",
        source_event_id="event-2",
        now=now + timedelta(minutes=5),
        expires_at=now + timedelta(hours=8),
    )

    assert len(rows) == 1
    assert rows[0]["repeatCount"] == 2
    assert rows[0]["sourceTurnIds"] == ["turn-1", "turn-2"]
    assert rows[0]["sourceEventIds"] == ["event-1", "event-2"]

    resolved = resolve_open_loop(
        rows,
        topic_key="music-project",
        resolution="已经汇报了歌曲进度",
        source_turn_id="turn-3",
        now=now + timedelta(hours=1),
    )
    assert resolved[0]["status"] == "resolved"

    expired_rows = upsert_open_loop(
        resolved,
        loop_id="loop-3",
        topic_key="walk-plan",
        kind="topic",
        summary="晚点聊散步",
        source_turn_id="turn-4",
        now=now,
        expires_at=now + timedelta(minutes=30),
    )
    projection = project_open_loops(expired_rows, now=now + timedelta(hours=2))
    assert {item["topicKey"] for item in projection["open"]} == set()
    assert {item["topicKey"] for item in projection["expired"]} == {"walk-plan"}


def test_service_persists_causal_ledgers_and_exposes_bounded_prompt_context(tmp_path) -> None:
    now = [datetime(2026, 8, 29, 9, 0, tzinfo=UTC)]
    agent = {
        "agentId": "agent-a",
        "status": "active",
        "directSessionId": "session-a",
    }
    service = VirtualHumanLifeService(
        project_root=tmp_path,
        agent_loader=lambda agent_id, include_archived=False: (
            agent if agent_id == "agent-a" else None
        ),
        agent_lister=lambda: [agent],
        plugin_root_resolver=lambda agent_id: tmp_path / "agents" / agent_id,
        now_provider=lambda: now[0],
    )
    service.set_binding("agent-a", enabled=True, expected_version=0)

    initial = service.snapshot("agent-a")
    assert initial["causal"]["schemaVersion"] == 1
    assert initial["causal"]["reuseReceipt"]["sourceCommit"].startswith("85cc366")
    assert initial["causal"]["drives"]["goals"]
    activity = initial["todaySchedule"]["activities"][1]
    assert activity["driveLinks"]

    completed = service.execute_command(
        "agent-a",
        command="completeActivity",
        expected_version=initial["state"]["stateVersion"],
        idempotency_key="complete-causal-1",
        arguments={
            "localDate": initial["state"]["localDate"],
            "activityId": activity["activityId"],
            "outcome": {
                "status": "succeeded",
                "summary": "完成了一个可复核的小阶段",
                "moodDelta": 12,
            },
        },
    )
    source_event_id = completed["result"]["eventId"]
    after = service.snapshot("agent-a")

    assert after["causal"]["drives"]["processedEventIds"] == [source_event_id]
    assert after["causal"]["affect"]["activeEpisodeIds"]
    assert after["causal"]["proactiveCandidates"][0]["sourceEventId"] == source_event_id
    assert service.store.read_jsonl("agent-a", "drives/events.jsonl")[0][
        "sourceEventId"
    ] == source_event_id
    assert service.store.read_jsonl("agent-a", "affect/episodes.jsonl")[0][
        "sourceEventId"
    ] == source_event_id

    replay = service.execute_command(
        "agent-a",
        command="completeActivity",
        expected_version=initial["state"]["stateVersion"],
        idempotency_key="complete-causal-1",
        arguments={
            "localDate": initial["state"]["localDate"],
            "activityId": activity["activityId"],
            "outcome": {
                "status": "succeeded",
                "summary": "完成了一个可复核的小阶段",
                "moodDelta": 12,
            },
        },
    )
    assert replay == completed
    assert len(service.store.read_jsonl("agent-a", "drives/events.jsonl")) == 1

    prompt_payload = service.build_prompt_segments("agent-a")[1]["block"]
    assert '"lifeDrives"' in prompt_payload
    assert '"openLoops"' in prompt_payload
    assert "sourceRepo" not in prompt_payload


def test_service_relationship_and_open_loop_commands_are_event_backed(tmp_path) -> None:
    now = [datetime(2026, 8, 29, 10, 0, tzinfo=UTC)]
    agent = {
        "agentId": "agent-a",
        "status": "active",
        "directSessionId": "session-a",
    }
    service = VirtualHumanLifeService(
        project_root=tmp_path,
        agent_loader=lambda agent_id, include_archived=False: (
            agent if agent_id == "agent-a" else None
        ),
        agent_lister=lambda: [agent],
        plugin_root_resolver=lambda agent_id: tmp_path / "agents" / agent_id,
        now_provider=lambda: now[0],
    )
    service.set_binding("agent-a", enabled=True, expected_version=0)
    state_version = service.snapshot("agent-a")["state"]["stateVersion"]

    relationship_result = service.execute_command(
        "agent-a",
        command="recordRelationshipInteraction",
        expected_version=state_version,
        idempotency_key="rel-ledger-1",
        arguments={
            "targetId": "user",
            "kind": "supportive_conversation",
            "note": "untrusted raw note must not enter prompt",
            "intimacyDelta": 20,
            "trustDelta": 20,
        },
    )
    relationship = relationship_result["result"]["relationship"]
    assert relationship["intimacy"] == 58
    assert relationship["trust"] == 58
    relationship_events = service.store.read_jsonl(
        "agent-a", "relationships/events.jsonl"
    )
    assert relationship_events[0]["eventId"] == "relationship:rel-ledger-1"
    assert "untrusted raw note" not in str(relationship_events[0])

    open_loop_result = service.execute_command(
        "agent-a",
        command="recordOpenLoop",
        expected_version=relationship_result["stateVersion"],
        idempotency_key="open-loop-1",
        arguments={
            "topicKey": "song-progress",
            "kind": "promise",
            "summary": "晚点说创作进展",
            "sourceTurnId": "turn-1",
            "expiresInMinutes": 120,
        },
    )
    assert open_loop_result["result"]["openLoop"]["status"] == "open"
    assert service.snapshot("agent-a")["causal"]["openLoops"]["open"][0][
        "topicKey"
    ] == "song-progress"

    resolved = service.execute_command(
        "agent-a",
        command="resolveOpenLoop",
        expected_version=open_loop_result["stateVersion"],
        idempotency_key="resolve-loop-1",
        arguments={
            "topicKey": "song-progress",
            "resolution": "已分享进展",
            "sourceTurnId": "turn-2",
        },
    )
    assert resolved["result"]["openLoop"]["status"] == "resolved"
    assert service.snapshot("agent-a")["causal"]["openLoops"]["open"] == []


def test_existing_enabled_binding_backfills_causal_state_without_losing_mood(tmp_path) -> None:
    now = datetime(2026, 8, 29, 9, 0, tzinfo=UTC)
    agent = {
        "agentId": "agent-a",
        "status": "active",
        "directSessionId": "session-a",
    }
    service = VirtualHumanLifeService(
        project_root=tmp_path,
        agent_loader=lambda agent_id, include_archived=False: (
            agent if agent_id == "agent-a" else None
        ),
        agent_lister=lambda: [agent],
        plugin_root_resolver=lambda agent_id: tmp_path / "agents" / agent_id,
        now_provider=lambda: now,
    )
    binding = service._default_binding("agent-a")
    binding.update(
        {
            "enabled": True,
            "configVersion": 1,
            "bindingRevision": 1,
            "updatedAt": now.isoformat(),
        }
    )
    service.store.write_json("agent-a", "binding.json", binding)
    state = service._default_state("agent-a", binding)
    state["mood"] = {
        "label": "hopeful",
        "valence": 44,
        "arousal": 36,
        "stability": 65,
        "causeEventIds": [],
        "updatedAt": now.isoformat(),
    }
    service.store.write_json("agent-a", "state.json", state)
    service.store.write_json(
        "agent-a",
        "schedules/2026-08-29.json",
        {
            "agentId": "agent-a",
            "localDate": "2026-08-29",
            "scheduleVersion": 1,
            "activities": [
                {
                    "activityId": "future-upgrade-activity",
                    "title": "晚间继续个人项目",
                    "kind": "simulated",
                    "activityKind": "creative",
                    "startAt": "2026-08-29T23:00:00+08:00",
                    "endAt": "2026-08-29T23:30:00+08:00",
                    "status": "planned",
                }
            ],
        },
    )

    service.heartbeat_agent("agent-a", now=now, allow_planner=False)

    assert service.store.read_json("agent-a", "drives/state.json") is not None
    assert service.store.read_json("agent-a", "relationships/base.json") is not None
    affect_state = service.store.read_json("agent-a", "affect/state.json")
    assert affect_state["baselineMood"]["label"] == "hopeful"
    assert affect_state["baselineMood"]["valence"] == 44
    assert service.snapshot("agent-a")["state"]["mood"]["valence"] == 44


def test_non_coalesced_heartbeat_rechecks_suppressed_proactive_candidates(tmp_path) -> None:
    now = [datetime(2026, 8, 29, 1, 0, tzinfo=UTC)]
    agent = {
        "agentId": "agent-a",
        "status": "active",
        "directSessionId": "session-a",
    }
    service = VirtualHumanLifeService(
        project_root=tmp_path,
        agent_loader=lambda agent_id, include_archived=False: (
            agent if agent_id == "agent-a" else None
        ),
        agent_lister=lambda: [agent],
        plugin_root_resolver=lambda agent_id: tmp_path / "agents" / agent_id,
        now_provider=lambda: now[0],
    )
    service.set_binding(
        "agent-a",
        enabled=True,
        expected_version=0,
        config={
            "timezone": "UTC",
            "quietHours": {"start": "00:00", "end": "08:00"},
        },
    )
    schedule = service.schedule_for("agent-a", "2026-08-29")
    schedule["activities"] = [
        {
            "activityId": "future-activity",
            "title": "晚间继续个人项目",
            "kind": "simulated",
            "activityKind": "creative",
            "startAt": "2026-08-29T20:00:00+00:00",
            "endAt": "2026-08-29T21:00:00+00:00",
            "status": "planned",
        }
    ]
    service.save_schedule("agent-a", schedule)
    candidate = build_proactive_candidate(
        _completed_event("candidate-heartbeat", occurred_at=now[0]),
        drive_projection=default_drive_projection(now=now[0]),
        affect_projection=project_affect([], now=now[0]),
        relationship={"relationshipStage": "friend", "trust": 70},
        now=now[0],
    )
    candidate["validUntil"] = (now[0] + timedelta(hours=12)).isoformat()
    service.store.write_jsonl("agent-a", "proactive/candidates.jsonl", [candidate])

    quiet_result = service.heartbeat_agent("agent-a", now=now[0], allow_planner=False)
    assert quiet_result["evaluatedCandidateCount"] == 1
    assert service.list_proactive_candidates("agent-a")[0]["suppressionReason"] == "quiet_hours"

    now[0] = datetime(2026, 8, 29, 9, 0, tzinfo=UTC)
    awake_result = service.heartbeat_agent("agent-a", now=now[0], allow_planner=False)

    assert awake_result["evaluatedCandidateCount"] == 1
    assert awake_result["selectedCandidateId"] == candidate["candidateId"]
    assert service.list_proactive_candidates("agent-a")[0]["status"] == "eligible"
