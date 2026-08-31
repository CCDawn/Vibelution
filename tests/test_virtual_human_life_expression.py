import json
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from core.agent_plugins.virtual_human_life.dialogue_context import (
    project_companion_dialogue_context,
)
from core.agent_plugins.virtual_human_life.interaction_expression import (
    build_companion_expression_decision,
    classify_companion_user_intent,
)
from core.agent_plugins.virtual_human_life.service import VirtualHumanLifeService
from core.agent_plugins.virtual_human_life.storage import VirtualHumanLifeStore


@pytest.mark.parametrize(
    ("intent", "expected_validation"),
    [
        ("acknowledgement", "acknowledge"),
        ("correction", "acknowledge_then_correct"),
        ("support", "validate_then_support"),
        ("end", "respectful_close"),
    ],
)
def test_priority_intents_never_add_a_companion_question(
    intent: str,
    expected_validation: str,
) -> None:
    decision = build_companion_expression_decision(
        relationship={"relationshipStage": "close"},
        affect={"mood": {"valence": 68, "stability": 82}},
        energy=92,
        user_intent=intent,
        turn_ordinal=3,
    )

    assert decision["questionBudget"] == 0
    assert decision["followup"] is False
    assert decision["validationStyle"] == expected_validation


def test_relationship_stage_caps_address_memory_humor_and_disclosure() -> None:
    initial = build_companion_expression_decision(
        relationship={"relationshipStage": "getting_to_know"},
        affect={"mood": {"valence": 70, "stability": 80}},
        energy=88,
        user_intent="small_talk",
        turn_ordinal=3,
    )
    close = build_companion_expression_decision(
        relationship={"relationshipStage": "close"},
        affect={"mood": {"valence": 70, "stability": 80}},
        energy=88,
        user_intent="small_talk",
        turn_ordinal=3,
    )

    assert initial["addressStyle"] == "neutral_or_name"
    assert initial["memoryMention"] == "current_turn_only"
    assert initial["selfDisclosure"] == "light"
    assert close["addressStyle"] == "confirmed_personal"
    assert close["memoryMention"] == "relevant_shared"
    assert close["selfDisclosure"] == "reciprocal"
    assert initial["humorMode"] in {"off", "light"}
    assert close["humorMode"] == "light"


def test_low_energy_and_negative_unstable_affect_only_tighten_expression() -> None:
    decision = build_companion_expression_decision(
        relationship={"relationshipStage": "close"},
        affect={
            "mood": {"valence": -42, "stability": 24},
            "activeEpisodes": [{"targetId": "self", "episodeId": "episode-work"}],
        },
        energy=18,
        user_intent="small_talk",
        turn_ordinal=3,
    )

    assert decision["responseLength"] == "brief"
    assert decision["questionBudget"] == 0
    assert decision["humorMode"] == "off"
    assert decision["topicInitiative"] == "reply_only"
    assert decision["emotionalAttribution"] == "not_user_responsibility"


def test_question_budget_allows_only_two_or_three_of_eight_small_talk_turns() -> None:
    budgets = [
        build_companion_expression_decision(
            relationship={"relationshipStage": "friend"},
            affect={"mood": {"valence": 8, "stability": 72}},
            energy=70,
            user_intent="small_talk",
            turn_ordinal=turn,
        )["questionBudget"]
        for turn in range(1, 9)
    ]

    assert all(budget in {0, 1} for budget in budgets)
    assert 2 <= sum(budgets) <= 3


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("嗯嗯，知道了", "acknowledgement"),
        ("不对，今天是周二", "correction"),
        ("我今天真的很难受", "support"),
        ("先聊到这里吧，晚安", "end"),
        ("你能帮我整理一下吗", "help_request"),
        ("今天路边的花开了", "small_talk"),
    ],
)
def test_user_intent_classifier_is_bounded_and_deterministic(
    text: str,
    expected: str,
) -> None:
    assert classify_companion_user_intent(text) == expected


def test_prompt_injects_expression_time_and_fact_status_without_a_second_turn(
    tmp_path,
) -> None:
    clock = datetime(2026, 9, 1, 1, 30, tzinfo=UTC)
    agent = {
        "agentId": "agent-a",
        "status": "active",
        "directSessionId": "session-a",
    }
    submissions: list[dict] = []

    def submit(**kwargs):
        submissions.append(kwargs)
        return {"accepted": True, "turnId": "turn-1", "status": "running"}

    service = VirtualHumanLifeService(
        tmp_path,
        agent_loader=lambda agent_id, include_archived=False: (
            agent if agent_id == "agent-a" else None
        ),
        agent_lister=lambda: [agent],
        plugin_root_resolver=lambda agent_id: (
            tmp_path / "agents" / agent_id / "plugins" / "virtual-human-life"
        ),
        conversation_submitter=submit,
        now_provider=lambda: clock,
    )
    service.set_binding(
        "agent-a",
        enabled=True,
        expected_version=0,
        config={"homeLocation": "CN-SHANGHAI"},
    )
    state = service.snapshot("agent-a")["state"]
    state.update(
        {
            "currentActivityId": "class-1",
            "energy": 76,
            "mood": {
                "label": "calm",
                "valence": 12,
                "arousal": 30,
                "stability": 74,
            },
        }
    )
    service.store.write_json("agent-a", "state.json", state)
    service.save_schedule(
        "agent-a",
        {
            "localDate": "2026-09-01",
            "activities": [
                {
                    "activityId": "class-1",
                    "title": "上专业课",
                    "status": "active",
                    "startAt": "2026-09-01T01:00:00+00:00",
                    "endAt": "2026-09-01T02:00:00+00:00",
                },
                {
                    "activityId": "lunch-1",
                    "title": "去食堂吃午饭",
                    "status": "planned",
                    "startAt": "2026-09-01T04:00:00+00:00",
                    "endAt": "2026-09-01T04:40:00+00:00",
                },
                {
                    "activityId": "stale-plan-1",
                    "title": "已经错过的早间计划",
                    "status": "planned",
                    "startAt": "2026-09-01T00:20:00+00:00",
                    "endAt": "2026-09-01T00:40:00+00:00",
                },
            ],
        },
    )
    service.save_schedule(
        "agent-a",
        {
            "localDate": "2026-09-02",
            "activities": [
                {
                    "activityId": "library-1",
                    "title": "去图书馆复习",
                    "status": "planned",
                    "startAt": "2026-09-02T01:00:00+00:00",
                    "endAt": "2026-09-02T03:00:00+00:00",
                }
            ],
        },
    )
    service.store.append_jsonl(
        "agent-a",
        "events/2026-09-01.jsonl",
        {
            "eventId": "event-breakfast",
            "kind": "activity_completed",
            "title": "吃过早餐",
            "occurredAt": "2026-09-01T00:15:00+00:00",
            "outcome": {"status": "succeeded", "summary": "喝了豆浆。"},
        },
    )
    service.store.append_jsonl(
        "agent-a",
        "events/2026-09-01.jsonl",
        {
            "eventId": "event-failed",
            "kind": "activity_failed",
            "title": "没赶上的晨跑",
            "occurredAt": "2026-09-01T00:30:00+00:00",
            "outcome": {"status": "failed", "summary": "没有发生。"},
        },
    )

    result = service.queue_conversation_message(
        "agent-a",
        session_id="session-a",
        client_submission_id="submission-1",
        content="不对，今天是周二",
    )
    segments = service.build_prompt_segments(
        "agent-a",
        session_id="session-a",
        run_id=result["turnId"],
    )
    block = segments[1]["block"]
    payload = json.loads(block[block.index("{") :])

    assert len(submissions) == 1
    assert payload["timeContext"] == {
        "localDate": "2026-09-01",
        "localWeekday": "tuesday",
        "localTime": "09:30",
        "timezone": "Asia/Shanghai",
    }
    assert payload["currentActivity"]["activityId"] == "class-1"
    assert payload["completedExperiences"] == [
        {
            "eventId": "event-breakfast",
            "title": "吃过早餐",
            "occurredAt": "2026-09-01T00:15:00+00:00",
            "outcomeSummary": "喝了豆浆。",
            "factStatus": "completed",
        }
    ]
    assert {item["activityId"] for item in payload["futurePlans"]} == {
        "lunch-1",
        "library-1",
    }
    assert all(
        item["factStatus"] == "planned_not_occurred" for item in payload["futurePlans"]
    )
    assert (
        payload["expressionDecision"]["validationStyle"] == "acknowledge_then_correct"
    )
    assert payload["expressionDecision"]["questionBudget"] == 0
    assert payload["interactionContext"]["userIntent"] == "correction"
    assert "content" not in payload["interactionContext"]
    receipt = service.store.read_json(
        "agent-a", "conversation/interaction_context.json"
    )
    assert receipt is not None
    assert "不对，今天是周二" not in json.dumps(receipt, ensure_ascii=False)


@pytest.mark.parametrize(
    ("utc_now", "expected_date", "expected_weekday", "expected_time"),
    [
        (datetime(2026, 9, 1, 3, 30, tzinfo=UTC), "2026-08-31", "monday", "23:30"),
        (datetime(2026, 3, 8, 6, 30, tzinfo=UTC), "2026-03-08", "sunday", "01:30"),
        (datetime(2026, 3, 8, 7, 30, tzinfo=UTC), "2026-03-08", "sunday", "03:30"),
    ],
)
def test_dialogue_time_context_handles_cross_midnight_and_dst(
    tmp_path,
    utc_now: datetime,
    expected_date: str,
    expected_weekday: str,
    expected_time: str,
) -> None:
    store = VirtualHumanLifeStore(
        tmp_path,
        plugin_root_resolver=lambda agent_id: tmp_path / "agents" / agent_id,
    )
    local_now = utc_now.astimezone(ZoneInfo("America/New_York"))

    projection = project_companion_dialogue_context(
        store,
        "agent-a",
        binding={"timezone": "America/New_York"},
        state={},
        causal={},
        today_schedule={},
        tomorrow_schedule={},
        local_now=local_now,
        session_id="session-a",
        run_id="turn-a",
        proactive=False,
    )

    assert projection["timeContext"]["localDate"] == expected_date
    assert projection["timeContext"]["localWeekday"] == expected_weekday
    assert projection["timeContext"]["localTime"] == expected_time
    assert projection["timeContext"]["timezone"] == "America/New_York"
