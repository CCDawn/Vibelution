from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from core.agent_plugins.virtual_human_life.calendar import (
    append_calendar_change,
    project_calendar_for_date,
)
from core.agent_plugins.virtual_human_life.rhythms import (
    apply_completed_activity_to_rhythm,
    default_rhythm_projection,
    project_rhythm_state,
)
from core.agent_plugins.virtual_human_life.service import VirtualHumanLifeService

UTC = timezone.utc


def test_calendar_expands_recurrence_exception_cancellation_and_conflicts() -> None:
    events: list[dict] = []
    events = append_calendar_change(
        events,
        {
            "operation": "upsert",
            "eventId": "calendar-weekly-creative",
            "title": "每周创作",
            "kind": "recurring",
            "startAt": "2026-09-01T19:00:00+08:00",
            "endAt": "2026-09-01T20:30:00+08:00",
            "timezone": "Asia/Shanghai",
            "recurrence": {"frequency": "weekly", "byWeekday": [1]},
        },
    )
    events = append_calendar_change(
        events,
        {
            "operation": "upsert",
            "eventId": "calendar-anniversary",
            "title": "重要纪念日",
            "kind": "anniversary",
            "startAt": "2026-09-08T19:30:00+08:00",
            "endAt": "2026-09-08T20:30:00+08:00",
            "timezone": "Asia/Shanghai",
            "recurrence": {"frequency": "yearly", "month": 9, "day": 8},
        },
    )
    events = append_calendar_change(
        events,
        {
            "operation": "exception",
            "eventId": "calendar-weekly-creative",
            "occurrenceDate": "2026-09-08",
            "reason": "旅行取消本次活动",
        },
    )
    events = append_calendar_change(
        events,
        {
            "operation": "upsert",
            "eventId": "calendar-conflict",
            "title": "冲突安排",
            "kind": "one_off",
            "startAt": "2026-09-08T19:45:00+08:00",
            "endAt": "2026-09-08T20:15:00+08:00",
            "timezone": "Asia/Shanghai",
        },
    )
    projected = project_calendar_for_date(events, "2026-09-08", timezone_name="Asia/Shanghai")
    assert [item["calendarEventId"] for item in projected["occurrences"]] == [
        "calendar-anniversary",
        "calendar-conflict",
    ]
    assert projected["conflicts"][0]["eventIds"] == [
        "calendar-anniversary",
        "calendar-conflict",
    ]

    cancelled = append_calendar_change(
        events,
        {
            "operation": "cancel",
            "eventId": "calendar-conflict",
            "reason": "改期",
        },
    )
    after_cancel = project_calendar_for_date(
        cancelled, "2026-09-08", timezone_name="Asia/Shanghai"
    )
    assert [item["calendarEventId"] for item in after_cancel["occurrences"]] == [
        "calendar-anniversary",
    ]
    assert after_cancel["conflicts"] == []


def test_rhythm_needs_recover_and_single_late_sleep_does_not_change_chronotype() -> None:
    initial = default_rhythm_projection(
        now=datetime(2026, 9, 1, 12, tzinfo=UTC), timezone_name="Asia/Shanghai"
    )
    late_sleep = {
        "eventId": "event-late-sleep",
        "kind": "activity_completed",
        "activityKind": "sleep",
        "occurredAt": "2026-08-31T22:00:00+00:00",
        "outcome": {"status": "succeeded", "summary": "临时熬夜后补觉"},
    }
    after_one = apply_completed_activity_to_rhythm(
        initial, late_sleep, now=datetime(2026, 8, 31, 22, tzinfo=UTC)
    )
    assert after_one["chronotype"]["label"] == "balanced"
    assert after_one["chronotype"]["evidenceCount"] == 1
    assert after_one["chronotype"]["adaptationStatus"] == "stable"

    repeated = [
        {
            **late_sleep,
            "eventId": f"event-late-sleep-{index}",
            "occurredAt": f"2026-09-0{index - 1}T22:00:00+00:00",
        }
        for index in (2, 3)
    ]
    adapted = after_one
    for event in repeated:
        adapted = apply_completed_activity_to_rhythm(
            adapted,
            event,
            now=datetime.fromisoformat(event["occurredAt"]),
        )
    assert adapted["chronotype"]["evidenceCount"] == 3
    assert adapted["chronotype"]["label"] == "evening"
    assert adapted["chronotype"]["adaptationStatus"] == "adapted"

    projected = project_rhythm_state(
        adapted,
        now=datetime(2026, 9, 4, 1, tzinfo=UTC),
        timezone_name="Asia/Shanghai",
    )
    assert after_one["needs"]["sleep"]["level"] < initial["needs"]["sleep"]["level"]
    assert projected["needs"]["sleep"]["level"] > adapted["needs"]["sleep"]["level"]
    assert projected["circadian"]["localHour"] == 9


def test_injected_clock_crosses_midnight_without_waiting_days_and_keeps_agents_isolated(
    tmp_path: Path,
) -> None:
    """One deterministic accelerated scene replaces a literal multi-day wait."""

    clock = [datetime(2026, 8, 29, 13, 50, tzinfo=UTC)]  # 21:50 in Shanghai
    agents = {
        agent_id: {
            "agentId": agent_id,
            "status": "active",
            "directSessionId": f"session-{agent_id}",
        }
        for agent_id in ("agent-a", "agent-b")
    }
    episodes: list[dict] = []

    def write_episode(
        agent_id: str,
        *,
        kind: str,
        text: str,
        refs: list[dict],
        occurred_at: str,
    ) -> dict:
        episode = {
            "agentId": agent_id,
            "episodeId": f"episode-{agent_id}-{len(episodes) + 1}",
            "kind": kind,
            "text": text,
            "refs": refs,
            "occurredAt": occurred_at,
        }
        episodes.append(episode)
        return episode

    service = VirtualHumanLifeService(
        project_root=tmp_path,
        agent_loader=lambda agent_id, include_archived=False: agents.get(agent_id),
        agent_lister=lambda: list(agents.values()),
        plugin_root_resolver=lambda agent_id: (
            tmp_path / "agents" / agent_id / "plugins" / "virtual-human-life"
        ),
        episodic_writer=write_episode,
        episodic_lister=lambda agent_id, limit=500: [
            item for item in episodes if item["agentId"] == agent_id
        ][-limit:],
        now_provider=lambda: clock[0],
    )
    binding_config = {
        "timezone": "Asia/Shanghai",
        "nightlyPlanningTime": "22:30",
        "quietHours": {"start": "22:00", "end": "07:00"},
    }
    service.set_binding(
        "agent-a", enabled=True, expected_version=0, config=binding_config
    )
    service.set_binding(
        "agent-b", enabled=True, expected_version=0, config=binding_config
    )

    before_a = service.snapshot("agent-a")
    activity = before_a["todaySchedule"]["activities"][1]
    completed = service.execute_command(
        "agent-a",
        command="completeActivity",
        expected_version=before_a["state"]["stateVersion"],
        idempotency_key="accelerated-complete-creative",
        arguments={
            "localDate": before_a["state"]["localDate"],
            "activityId": activity["activityId"],
            "outcome": {
                "status": "succeeded",
                "summary": "完成并保存了一段可以继续发展的原创旋律。",
                "salienceScore": 90,
                "moodDelta": 24,
            },
        },
    )
    event_id = completed["result"]["eventId"]
    after_activity = service.snapshot("agent-a")
    assert after_activity["causal"]["drives"]["projects"][0]["progress"] > 0
    assert after_activity["causal"]["affect"]["activeEpisodeIds"]
    source_affect_id = next(
        item["episodeId"]
        for item in service.store.read_jsonl("agent-a", "affect/episodes.jsonl")
        if item["sourceEventId"] == event_id
    )

    relationship = service.execute_command(
        "agent-a",
        command="recordRelationshipInteraction",
        expected_version=completed["stateVersion"],
        idempotency_key="accelerated-supportive-talk",
        arguments={
            "targetId": "user",
            "kind": "supportive_conversation",
            "intimacyDelta": 8,
            "trustDelta": 8,
            "sourceTurnId": "turn-supportive",
        },
    )
    loop = service.execute_command(
        "agent-a",
        command="recordOpenLoop",
        expected_version=relationship["stateVersion"],
        idempotency_key="accelerated-open-loop",
        arguments={
            "topicKey": "melody-progress",
            "kind": "promise",
            "summary": "明天继续把旋律写完整",
            "sourceTurnId": "turn-supportive",
            "sourceEventId": event_id,
            "expiresInMinutes": 2_880,
        },
    )
    assert loop["result"]["openLoop"]["sourceEventIds"] == [event_id]

    environment = service.execute_command(
        "agent-a",
        command="recordEnvironmentFact",
        expected_version=loop["stateVersion"],
        idempotency_key="accelerated-weather",
        arguments={
            "factKey": "weather.current",
            "value": "小雨，24°C",
            "sourceKind": "tool",
            "sourceRef": "weather-tool:accelerated-scene",
            "confidence": 95,
        },
    )
    moving = service.execute_command(
        "agent-a",
        command="startLocationMove",
        expected_version=environment["stateVersion"],
        idempotency_key="accelerated-start-move",
        arguments={
            "movementId": "accelerated-move-home-studio",
            "destination": "home-studio",
            "travelMinutes": 30,
            "sourceKind": "schedule_outcome",
            "sourceRef": f"event:{event_id}",
        },
    )
    assert service.snapshot("agent-a")["state"]["currentLocation"] == "home"

    clock[0] += timedelta(minutes=30)
    arrived = service.execute_command(
        "agent-a",
        command="completeLocationMove",
        expected_version=moving["stateVersion"],
        idempotency_key="accelerated-complete-move",
        arguments={"movementId": "accelerated-move-home-studio"},
    )
    assert arrived["result"]["locationMovement"]["status"] == "completed"
    assert service.snapshot("agent-a")["state"]["currentLocation"] == "home-studio"

    clock[0] = datetime(2026, 8, 29, 14, 31, tzinfo=UTC)  # 22:31 local
    nightly = service.heartbeat_agent("agent-a", now=clock[0])
    nighttime = service.snapshot("agent-a")
    # The deterministic day may contain other already elapsed simulated
    # activities.  The contract is that the source-backed event participates
    # once, not that it is the only lived event reviewed that night.
    assert nightly["pendingReflectionCount"] >= 1
    assert nightly["acceptedReflectionCount"] == 0
    assert nightly["reinforcedMemoryCount"] == 0
    pending = next(
        item
        for item in service.list_reflection_proposals("agent-a")
        if event_id in item.get("sourceEventIds", [])
        and item["status"] == "pending"
    )
    approved = service.review_reflection_proposal(
        "agent-a",
        proposal_id=pending["proposalId"],
        decision="approve",
        reviewer_kind="operator",
        review_note="加速场景中完成来源审核。",
        now=clock[0],
    )
    assert approved["proposal"]["status"] == "approved"
    assert approved["reinforcementReceipt"]["sourceEventIds"] == [event_id]
    nighttime = service.snapshot("agent-a")
    assert nighttime["causal"]["proactiveCandidates"][-1][
        "suppressionReason"
    ] == "quiet_hours"
    memory = next(
        item
        for item in service.list_memories("agent-a")
        if event_id in item["sourceEventIds"]
    )
    assert memory["sourceEventIds"] == [event_id]
    assert memory["scoreBreakdown"]["unresolved"] > 0
    assert memory["scoreBreakdown"]["reinforcement"] > 0
    assert memory["reinforcedAt"]

    conflict = service.execute_command(
        "agent-a",
        command="recordRelationshipInteraction",
        expected_version=nighttime["state"]["stateVersion"],
        idempotency_key="accelerated-conflict",
        arguments={
            "targetId": "user",
            "kind": "conflict",
            "intimacyDelta": -8,
            "trustDelta": -8,
            "sourceTurnId": "turn-conflict",
        },
    )
    trust_after_conflict = conflict["result"]["relationship"]["trust"]

    clock[0] = datetime(2026, 8, 29, 16, 30, tzinfo=UTC)  # 00:30 next day
    after_midnight = service.heartbeat_agent("agent-a", now=clock[0])
    assert after_midnight["agentId"] == "agent-a"
    assert service.snapshot("agent-a")["state"]["localDate"] == "2026-08-30"

    clock[0] = datetime(2026, 8, 30, 4, 0, tzinfo=UTC)  # 12:00 next day
    repaired = service.execute_command(
        "agent-a",
        command="recordRelationshipInteraction",
        expected_version=service.snapshot("agent-a")["state"]["stateVersion"],
        idempotency_key="accelerated-repair",
        arguments={
            "targetId": "user",
            "kind": "apology_repair",
            "intimacyDelta": 2,
            "trustDelta": 6,
            "sourceTurnId": "turn-repair",
        },
    )
    service.heartbeat_agent("agent-a", now=clock[0])
    final_a = service.snapshot("agent-a")
    assert repaired["result"]["relationship"]["trust"] > trust_after_conflict
    assert repaired["result"]["relationship"]["relationshipStage"] == "getting_to_know"
    assert source_affect_id not in final_a["causal"]["affect"]["activeEpisodeIds"]
    assert source_affect_id in final_a["causal"]["affect"]["recoveredEpisodeIds"]

    untouched_b = service.snapshot("agent-b")
    assert untouched_b["state"]["localDate"] == "2026-08-29"
    assert untouched_b["state"]["currentLocation"] == "home"
    assert untouched_b["causal"]["environment"]["currentFacts"] == []
    assert untouched_b["causal"]["reflections"]["acceptedCount"] == 0
    assert untouched_b["causal"]["drives"]["projects"][0]["progress"] == 0
    assert service.list_events("agent-b", date="2026-08-29") == []
