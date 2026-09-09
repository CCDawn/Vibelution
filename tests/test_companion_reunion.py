from datetime import UTC, datetime

from core.agent_plugins.virtual_human_life.reunion import (
    project_reunion_context,
    project_shared_experiences,
)


def test_reunion_context_projects_utc_elapsed_and_character_local_day_gap() -> None:
    context = project_reunion_context(
        previous_user_arrived_at="2026-09-07T15:30:00+00:00",
        current_user_arrived_at="2026-09-07T16:15:00+00:00",
        local_now=datetime(2026, 9, 8, 8, 15, tzinfo=UTC),
        timezone_name="Asia/Shanghai",
        user_intent="small_talk",
    )

    assert context["previousUserArrivedAt"] == "2026-09-07T15:30:00+00:00"
    assert context["currentUserArrivedAt"] == "2026-09-07T16:15:00+00:00"
    assert context["elapsedSeconds"] == 2700
    assert context["localDayGap"] == 1
    assert context["resumeTopic"] == "small_talk"
    assert context["proactive"] is False
    assert context["userReturned"] is True


def test_reunion_context_does_not_infer_first_meeting_or_busy_sleep_from_gap() -> None:
    context = project_reunion_context(
        previous_user_arrived_at="",
        current_user_arrived_at="2026-09-08T00:15:00+00:00",
        local_now=datetime(2026, 9, 8, 8, 15, tzinfo=UTC),
        timezone_name="Asia/Shanghai",
        user_intent="small_talk",
    )

    assert context["previousUserArrivedAt"] == "unknown"
    assert context["currentUserArrivedAt"] == "2026-09-08T00:15:00+00:00"
    assert context["elapsedSeconds"] == "unknown"
    assert context["localDayGap"] == "unknown"
    assert "first" not in context
    assert "firstEver" not in context
    assert "busy" not in context
    assert "sleep" not in context
    assert "resumeTopic" not in context


def test_reunion_context_rejects_backwards_time_and_proactive_is_not_user_return() -> (
    None
):
    context = project_reunion_context(
        previous_user_arrived_at="2026-09-08T01:00:00+00:00",
        current_user_arrived_at="2026-09-08T00:15:00+00:00",
        local_now=datetime(2026, 9, 8, 8, 15, tzinfo=UTC),
        timezone_name="Asia/Shanghai",
        user_intent="small_talk",
        proactive=True,
    )

    assert context["previousUserArrivedAt"] == "2026-09-08T01:00:00+00:00"
    assert context["currentUserArrivedAt"] == "2026-09-08T00:15:00+00:00"
    assert context["elapsedSeconds"] == "unknown"
    assert context["localDayGap"] == "unknown"
    assert context["proactive"] is True
    assert context["userReturned"] is False
    assert "resumeTopic" not in context


def test_reunion_context_keeps_elapsed_utc_separate_from_local_cross_day() -> None:
    context = project_reunion_context(
        previous_user_arrived_at="2026-09-07T15:30:00+00:00",
        current_user_arrived_at="2026-09-07T16:30:00+00:00",
        local_now=datetime(2026, 9, 8, 0, 30, tzinfo=UTC),
        timezone_name="UTC",
        user_intent="acknowledgement",
    )

    assert context["elapsedSeconds"] == 3600
    assert context["localDayGap"] == 0
    assert context["resumeTopic"] == "acknowledgement"


def test_shared_experiences_require_session_bound_open_loop_and_successful_past_event() -> (
    None
):
    now = datetime(2026, 9, 8, 12, 0, tzinfo=UTC)
    shared_event = {
        "eventId": "life-shared-1",
        "kind": "activity_completed",
        "title": "一起讨论的旋律",
        "occurredAt": "2026-09-08T10:00:00+00:00",
        "outcome": {"status": "succeeded", "summary": "把副歌改得更明亮。"},
    }
    result = project_shared_experiences(
        open_loops=[
            {
                "loopId": "loop-shared",
                "topicKey": "music-collab",
                "status": "open",
                "sourceSessionId": "session-a",
                "sourceTurnIds": ["turn-a"],
                "sourceEventIds": ["life-shared-1"],
            },
            {
                "loopId": "loop-other-session",
                "topicKey": "private-topic",
                "status": "open",
                "sourceSessionId": "session-b",
                "sourceTurnIds": ["turn-b"],
                "sourceEventIds": ["life-private-1"],
            },
        ],
        completed_events=[shared_event],
        session_id="session-a",
        now=now,
    )

    assert result == [
        {
            "eventId": "life-shared-1",
            "title": "一起讨论的旋律",
            "outcomeSummary": "把副歌改得更明亮。",
            "occurredAt": "2026-09-08T10:00:00+00:00",
            "topicKey": "music-collab",
            "loopId": "loop-shared",
            "sourceKey": "life-event:life-shared-1",
            "factStatus": "completed",
        }
    ]


def test_shared_experiences_exclude_unlinked_private_invalid_and_future_rows() -> None:
    now = datetime(2026, 9, 8, 12, 0, tzinfo=UTC)
    open_loop = {
        "loopId": "loop-1",
        "topicKey": "shared-topic",
        "status": "open",
        "sourceSessionId": "session-a",
        "sourceTurnIds": ["turn-a"],
        "sourceEventIds": ["life-shared", "life-future", "life-failed"],
    }
    events = [
        {
            "eventId": "life-shared",
            "kind": "activity_completed",
            "title": "共同完成",
            "occurredAt": "2026-09-08T11:00:00+00:00",
            "outcome": {"status": "succeeded", "summary": "已完成。"},
        },
        {
            "eventId": "life-future",
            "kind": "activity_completed",
            "title": "尚未发生",
            "occurredAt": "2026-09-08T13:00:00+00:00",
            "outcome": {"status": "succeeded", "summary": "未来事件。"},
        },
        {
            "eventId": "life-failed",
            "kind": "activity_completed",
            "title": "失败活动",
            "occurredAt": "2026-09-08T09:00:00+00:00",
            "outcome": {"status": "failed", "summary": "没有完成。"},
        },
        {
            "eventId": "life-plan",
            "kind": "activity_planned",
            "title": "纯计划",
            "occurredAt": "2026-09-08T08:00:00+00:00",
        },
        {
            "eventId": "life-private",
            "kind": "activity_completed",
            "title": "人物独自活动",
            "occurredAt": "2026-09-08T10:30:00+00:00",
            "outcome": {"status": "succeeded", "summary": "只属于人物自己的经历。"},
        },
        {
            "eventId": "life-no-turn",
            "kind": "activity_completed",
            "title": "没有来源回合",
            "occurredAt": "2026-09-08T10:45:00+00:00",
            "outcome": {"status": "succeeded", "summary": "缺少 sourceTurnIds。"},
        },
    ]

    result = project_shared_experiences(
        open_loops=[
            open_loop,
            {
                "loopId": "loop-no-turn",
                "topicKey": "missing-turn",
                "status": "open",
                "sourceSessionId": "session-a",
                "sourceTurnIds": [],
                "sourceEventIds": ["life-no-turn"],
            },
        ],
        completed_events=events,
        session_id="session-a",
        now=now,
    )

    assert [item["eventId"] for item in result] == ["life-shared"]
    assert all(item["factStatus"] == "completed" for item in result)
    assert all(item["eventId"] != "life-private" for item in result)


def test_shared_experiences_allow_resolved_loop_but_not_expired_loop() -> None:
    now = datetime(2026, 9, 8, 12, 0, tzinfo=UTC)
    events = [
        {
            "eventId": "life-resolved",
            "kind": "activity_completed",
            "title": "已解决的话题",
            "occurredAt": "2026-09-08T10:00:00+00:00",
            "outcome": {"status": "succeeded", "summary": "后来完成了。"},
        },
        {
            "eventId": "life-expired",
            "kind": "activity_completed",
            "title": "过期未完成",
            "occurredAt": "2026-09-08T09:00:00+00:00",
            "outcome": {"status": "succeeded", "summary": "不应伪造承诺完成。"},
        },
    ]

    result = project_shared_experiences(
        open_loops=[
            {
                "loopId": "loop-resolved",
                "topicKey": "resolved-topic",
                "status": "resolved",
                "sourceSessionId": "session-a",
                "sourceTurnIds": ["turn-a"],
                "sourceEventIds": ["life-resolved"],
            },
            {
                "loopId": "loop-expired",
                "topicKey": "expired-topic",
                "status": "open",
                "expiresAt": "2026-09-08T11:00:00+00:00",
                "sourceSessionId": "session-a",
                "sourceTurnIds": ["turn-a"],
                "sourceEventIds": ["life-expired"],
            },
        ],
        completed_events=events,
        session_id="session-a",
        now=now,
    )

    assert [item["eventId"] for item in result] == ["life-resolved"]
    assert result[0]["loopId"] == "loop-resolved"


def test_shared_experiences_are_recent_deduplicated_and_bounded() -> None:
    now = datetime(2026, 9, 8, 20, 0, tzinfo=UTC)
    event_ids = [f"life-{index}" for index in range(8)]
    events = [
        {
            "eventId": event_id,
            "kind": "activity_completed",
            "title": f"活动 {index}",
            "occurredAt": f"2026-09-08T{12 + index:02d}:00:00+00:00",
            "outcome": {"status": "succeeded", "summary": f"结果 {index}"},
        }
        for index, event_id in enumerate(event_ids)
    ]
    events.append(dict(events[-1]))
    result = project_shared_experiences(
        open_loops=[
            {
                "loopId": "loop-all",
                "topicKey": "all",
                "status": "open",
                "sourceSessionId": "session-a",
                "sourceTurnIds": ["turn-a"],
                "sourceEventIds": event_ids,
            }
        ],
        completed_events=events,
        session_id="session-a",
        now=now,
    )

    assert len(result) == 6
    assert [item["eventId"] for item in result] == [
        "life-7",
        "life-6",
        "life-5",
        "life-4",
        "life-3",
        "life-2",
    ]
    assert len({item["eventId"] for item in result}) == len(result)
