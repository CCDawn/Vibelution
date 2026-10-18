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
        ("misunderstanding", "acknowledge_then_restate"),
        ("restate_request", "restate_current_understanding"),
        ("user_impatient", "acknowledge_then_stop"),
        ("end_topic", "respectful_close"),
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
    )

    assert decision["questionBudget"] == 0
    assert decision["validationStyle"] == expected_validation
    assert decision["initiative"] == "reply_only"
    assert decision["selfDisclosure"] == "none"


def test_misunderstanding_intents_close_the_topic_without_disclosure_or_humor() -> None:
    for intent in ("misunderstanding", "restate_request", "user_impatient", "end_topic"):
        decision = build_companion_expression_decision(
            relationship={"relationshipStage": "close"},
            affect={"mood": {"valence": 60, "stability": 80}},
            energy=85,
            user_intent=intent,
        )
        assert decision["questionBudget"] == 0
        assert decision["selfDisclosure"] == "none"
        assert decision["topicInitiative"] == "reply_only"
        # A single misunderstanding never punishes the relationship stage or
        # changes long-term style; it only tightens this one reply.
        assert "relationship_stage:close" in decision["reasonCodes"]
        assert decision["responseLength"] in {"brief", "compact"}


def test_relationship_stage_caps_address_memory_humor_and_disclosure() -> None:
    initial = build_companion_expression_decision(
        relationship={"relationshipStage": "getting_to_know"},
        affect={"mood": {"valence": 70, "stability": 80}},
        energy=88,
        user_intent="small_talk",
    )
    close = build_companion_expression_decision(
        relationship={"relationshipStage": "close"},
        affect={"mood": {"valence": 70, "stability": 80}},
        energy=88,
        user_intent="small_talk",
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
    )

    assert decision["responseLength"] == "brief"
    assert decision["questionBudget"] == 0
    assert decision["humorMode"] == "off"
    assert decision["topicInitiative"] == "reply_only"
    assert decision["emotionalAttribution"] == "not_user_responsibility"


def test_question_budget_is_a_per_turn_bound_without_any_cadence() -> None:
    eligible = build_companion_expression_decision(
        relationship={"relationshipStage": "friend"},
        affect={"mood": {"valence": 8, "stability": 72}},
        energy=70,
        user_intent="small_talk",
    )
    capped = build_companion_expression_decision(
        relationship={"relationshipStage": "getting_to_know"},
        affect={"mood": {"valence": -40, "stability": 20}},
        energy=20,
        user_intent="small_talk",
    )

    # Retired mechanical rhythm: the budget no longer depends on any arrival
    # ordinal or modulo cadence. It stays a 0/1 resource bound driven by
    # stage, intent, affect and reviewed preferences, so "no mechanical
    # rhythm" never degrades into unbounded questioning.
    assert eligible["questionBudget"] == 1
    assert capped["questionBudget"] == 0
    assert "followup" not in eligible


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("嗯嗯，知道了", "acknowledgement"),
        ("不对，今天是周二", "correction"),
        ("我今天真的很难受", "support"),
        ("先聊到这里吧，晚安", "end"),
        ("你能帮我整理一下吗", "help_request"),
        ("今天路边的花开了", "small_talk"),
        ("你误会了，我是说周五的演出", "misunderstanding"),
        ("我不是这个意思", "misunderstanding"),
        ("你刚才说的我没听懂，再说一遍", "restate_request"),
        ("什么意思，再解释一下", "restate_request"),
        ("别问了，你烦不烦", "user_impatient"),
        ("我都说了几遍了，说重点", "user_impatient"),
        ("这个话题就到这吧", "end_topic"),
        ("不聊这个了，换个话题", "end_topic"),
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
            "outcome": {
                "status": "succeeded",
                "summary": "喝了豆浆。",
                "kind": "verified_tool_outcome",
                "evidence": {
                    "kind": "native_tool_execution",
                    "sessionId": "session-a",
                    "turnId": "turn-breakfast",
                    "toolCallIds": ["breakfast-tool-call"],
                    "receiptEventIds": ["breakfast-tool-succeeded"],
                },
            },
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
