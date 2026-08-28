from __future__ import annotations

from datetime import datetime, timedelta, timezone

from core.agent_plugins.virtual_human_life.domain import (
    apply_completed_event_to_state,
    apply_relationship_interaction_to_state,
    compute_event_salience,
    evolve_state_for_time,
)


def _state() -> dict:
    return {
        "energy": 50,
        "socialNeed": 40,
        "sleepState": "awake",
        "mood": {
            "label": "calm",
            "valence": 12,
            "arousal": 30,
            "stability": 70,
            "causeEventIds": [],
        },
        "lastStateEvolutionAt": "2026-08-27T09:00:00+00:00",
        "processedEventIds": [],
        "processedInteractionIds": [],
        "currentActivityId": "activity-1",
    }


def test_legacy_event_salience_is_explainable_and_explicit_score_wins() -> None:
    assert compute_event_salience(
        {
            "kind": "activity_completed",
            "title": "完成自己的创作项目",
            "outcome": {"status": "succeeded", "summary": "写出了一段新的旋律草稿。"},
        }
    ) >= 70
    assert compute_event_salience(
        {
            "kind": "activity_completed",
            "title": "整理桌面",
            "outcome": {"status": "succeeded", "summary": "完成", "salienceScore": 91},
        }
    ) == 91


def test_time_evolution_increases_social_drive_and_only_sleep_recovers_energy() -> None:
    now = datetime(2026, 8, 27, 13, 0, tzinfo=timezone.utc)
    awake = evolve_state_for_time(_state(), now=now)
    assert awake["energy"] == 46
    assert awake["socialNeed"] == 48

    sleeping = _state()
    sleeping["sleepState"] = "sleeping"
    recovered = evolve_state_for_time(sleeping, now=now)
    assert recovered["energy"] == 74
    assert recovered["socialNeed"] == 48


def test_time_evolution_waits_for_a_full_hour_and_preserves_subhour_remainder() -> None:
    state = _state()
    anchor = datetime(2026, 8, 27, 9, 0, tzinfo=timezone.utc)

    after_minute_heartbeat = evolve_state_for_time(
        state,
        now=anchor + timedelta(minutes=30),
    )
    assert after_minute_heartbeat["energy"] == 50
    assert after_minute_heartbeat["socialNeed"] == 40
    assert after_minute_heartbeat["lastStateEvolutionAt"] == anchor.isoformat()

    after_repeated_minute_heartbeat = evolve_state_for_time(
        after_minute_heartbeat,
        now=anchor + timedelta(minutes=59),
    )
    assert after_repeated_minute_heartbeat == after_minute_heartbeat

    after_full_hour = evolve_state_for_time(
        after_repeated_minute_heartbeat,
        now=anchor + timedelta(hours=1, minutes=20),
    )
    assert after_full_hour["energy"] == 49
    assert after_full_hour["socialNeed"] == 42
    assert after_full_hour["lastStateEvolutionAt"] == (anchor + timedelta(hours=1)).isoformat()


def test_time_evolution_initializes_an_empty_anchor_explicitly() -> None:
    state = _state()
    state["lastStateEvolutionAt"] = ""
    now = datetime(2026, 8, 27, 9, 0, tzinfo=timezone.utc)

    evolved = evolve_state_for_time(state, now=now)

    assert evolved["lastStateEvolutionAt"] == now.isoformat()


def test_activity_event_is_idempotent_and_structured_kind_guides_deltas() -> None:
    now = datetime(2026, 8, 27, 13, 0, tzinfo=timezone.utc)
    event = {
        "eventId": "event-creative-1",
        "activityId": "activity-1",
        "activityKind": "creative",
        "kind": "activity_completed",
        "outcome": {"status": "succeeded", "summary": "完成"},
    }
    first = apply_completed_event_to_state(_state(), event, now=now)
    repeated = apply_completed_event_to_state(first, event, now=now + timedelta(hours=2))
    assert first["energy"] == 38
    assert first["socialNeed"] == 50
    assert first["currentActivityId"] == ""
    assert repeated == first


def test_relationship_event_is_idempotent_and_reduces_social_need() -> None:
    now = datetime(2026, 8, 27, 9, 0, tzinfo=timezone.utc)
    first = apply_relationship_interaction_to_state(
        _state(),
        interaction_id="interaction-1",
        intimacy_delta=6,
        trust_delta=4,
        kind="supportive_conversation",
        now=now,
    )
    repeated = apply_relationship_interaction_to_state(
        first,
        interaction_id="interaction-1",
        intimacy_delta=6,
        trust_delta=4,
        kind="supportive_conversation",
        now=now + timedelta(hours=1),
    )
    assert first["socialNeed"] < 40
    assert repeated == first
