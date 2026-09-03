"""Digest-wait TTL stop-loss for awaiting_approval meetings (hypothesis-first).

Covers the SCI-001 B-track burn regression: a meeting whose Coordinator
digest draft has been waiting for operator approval past a configurable TTL
must stop producing automatic discussion rounds (no follow-up round, no
speaker LLM call), while approve/reject/close keep working unchanged, the
digest draft survives, and meetings with a persisted deadline keep deadline
semantics only.  Active discussions, fresh digests and DEV flows stay
behavior-identical.

All discussion content comes from fake runners (DEV fixtures); no real model
or network is involved.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from core.web.services import runtime_scene_service
from core.web.services.team_workflow import meeting_rounds as meetings
from core.web.services.team_workflow import meeting_runtime
from tests.test_research_workflow_meeting_runtime import (
    _closure_payload,
    _open_meeting,
)


class DeferredExecutor:
    """Swallow scheduler submissions so tests never drive real speakers."""

    def __init__(self):
        self.submissions: list[tuple[object, tuple[object, ...]]] = []

    def submit(self, callback, *args):
        self.submissions.append((callback, args))
        return object()


def _release_scheduled_job(team_id: str, meeting_round_id: str) -> None:
    key = (team_id, meeting_round_id)
    with meeting_runtime._MEETING_DISCUSSION_JOBS_LOCK:
        meeting_runtime._MEETING_DISCUSSION_JOBS.pop(key, None)
        meeting_runtime._MEETING_DISCUSSION_SESSIONS.pop(key, None)


def _meeting_record(**overrides) -> dict:
    now = datetime.now(timezone.utc)
    stale = (now - timedelta(minutes=90)).isoformat().replace("+00:00", "Z")
    record = {
        "meetingRoundId": "meeting-ttl-1",
        "status": "awaiting_approval",
        "chatRoomRoundIds": ["round-1"],
        "rounds": 3,
        "summaryStartedAt": stale,
        "digestDraft": {"summary": "draft", "contentHash": "a" * 8},
    }
    record.update(overrides)
    return record


def _capture_scene_events(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    captured: list[dict] = []

    def capture(*args, **kwargs):
        payload = dict(kwargs)
        payload["event_code"] = args[2] if len(args) > 2 else ""
        captured.append(payload)
        return None

    monkeypatch.setattr(
        runtime_scene_service,
        "record_runtime_scene_event_quietly",
        capture,
    )
    return captured


def _ttl_mute_dict() -> dict:
    return {
        "meetingStatus": "awaiting_approval",
        "digestAtMs": 1,
        "digestAt": "stale",
        "digestAtSource": "summaryStartedAt",
        "ttlMs": 1,
        "overdueMs": 1,
        "boundRoundCount": 1,
        "roundBudget": 3,
        "pausedRoundRange": [2, 3],
    }


def _start_bound_round(
    meeting_round: dict,
    selection: dict,
    *,
    room_id: str,
    team_id: str,
    discussion_round_index: int,
    agent_runner,
) -> dict:
    from core.web.services import chat_room_service

    return chat_room_service.start_chat_room_round(
        room_id,
        meeting_runtime._follow_up_topic(discussion_round_index),
        purpose="meeting",
        config=meeting_runtime._round_config(
            meeting_round,
            selection,
            discussion_round_index=discussion_round_index,
            team_id=team_id,
        ),
        agent_runner=agent_runner,
        background=False,
        max_topic_lines=meeting_runtime.MEETING_TOPIC_MAX_LINES,
    )


def test_digest_ttl_mute_engages_only_past_ttl():
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    # Digest waiting 90 minutes against the 45 minute default TTL.
    muted = meeting_runtime.meeting_digest_ttl_mute_state(
        _meeting_record(), now_ms=now_ms
    )
    assert muted is not None
    assert muted["meetingStatus"] == "awaiting_approval"
    assert muted["ttlMs"] == meeting_runtime.DEFAULT_MEETING_DIGEST_TTL_MS
    assert muted["overdueMs"] > 0
    assert muted["pausedRoundRange"] == [2, 3]

    # A fresh digest (within TTL) stays unmuted: normal approval flow.
    fresh = _meeting_record(
        summaryStartedAt=datetime.now(timezone.utc)
        .isoformat()
        .replace("+00:00", "Z")
    )
    assert meeting_runtime.meeting_digest_ttl_mute_state(fresh, now_ms=now_ms) is None


def test_digest_ttl_mute_deadline_takes_priority():
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    future = now_ms + 60 * 60 * 1000
    assert (
        meeting_runtime.meeting_digest_ttl_mute_state(
            _meeting_record(challengeDeadlineAtMs=future), now_ms=now_ms
        )
        is None
    )
    assert (
        meeting_runtime.meeting_digest_ttl_mute_state(
            _meeting_record(meetingDeadlineAtMs=future), now_ms=now_ms
        )
        is None
    )


def test_digest_ttl_mute_ignores_active_discussion_and_timestampless_records():
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    # Active discussion (open) never mutes, even with a stale-looking stamp.
    assert (
        meeting_runtime.meeting_digest_ttl_mute_state(
            _meeting_record(status="open"), now_ms=now_ms
        )
        is None
    )
    # Closed meetings are terminal; the mute is irrelevant there.
    assert (
        meeting_runtime.meeting_digest_ttl_mute_state(
            _meeting_record(status="closed"), now_ms=now_ms
        )
        is None
    )
    # Awaiting-approval records without any parsable digest timestamp stay
    # fail-open: the stop-loss never guesses.
    assert (
        meeting_runtime.meeting_digest_ttl_mute_state(
            _meeting_record(summaryStartedAt="", digestDraft=None, updatedAt=""),
            now_ms=now_ms,
        )
        is None
    )


def test_schedule_meeting_discussion_stops_after_digest_ttl(tmp_path, monkeypatch):
    team_id, agents, opened = _open_meeting(tmp_path, monkeypatch)
    meeting_round_id = opened["meetingRound"]["meetingRoundId"]
    agent_ids = list(agents.values())
    meetings.begin_meeting_summary(team_id, meeting_round_id, actor=agent_ids[0])
    meeting_runtime.draft_meeting_digest(team_id, meeting_round_id)
    monkeypatch.setattr(meeting_runtime, "_meeting_digest_ttl_ms", lambda: 1)
    monkeypatch.setattr(
        meeting_runtime, "_MEETING_DISCUSSION_EXECUTOR", DeferredExecutor()
    )
    events = _capture_scene_events(monkeypatch)

    result = meeting_runtime.schedule_meeting_discussion(team_id, meeting_round_id)

    assert result["status"] == "ttl_muted"
    assert result["meetingRoundId"] == meeting_round_id
    assert result["digestTtl"]["meetingStatus"] == "awaiting_approval"
    assert result["digestTtl"]["ttlMs"] == 1
    assert not meeting_runtime._MEETING_DISCUSSION_JOBS
    ttl_events = [
        event
        for event in events
        if event["event_code"] == "meeting_discussion.ttl_mute.engaged"
    ]
    assert len(ttl_events) == 1
    fields = ttl_events[0]["fields"]
    assert fields["meetingRoundId"] == meeting_round_id
    assert fields["surface"] == "schedule_meeting_discussion"
    assert fields["ttlMs"] == 1
    assert fields["digestAtMs"] > 0
    # 默认聊天轮数 2：已绑开场轮之后，TTL 静默暂停的剩余轮区间是 [2, 2]。
    assert fields["pausedRoundRange"] == [2, 2]
    # The pause never touches the meeting state machine or the draft.
    record = meetings.get_meeting_round(team_id, meeting_round_id)["meetingRound"]
    assert record["status"] == "awaiting_approval"
    assert str(record["digestDraft"].get("summary") or "").strip()


def test_schedule_meeting_discussion_normal_paths_unchanged(tmp_path, monkeypatch):
    team_id, agents, opened = _open_meeting(tmp_path, monkeypatch)
    meeting_round_id = opened["meetingRound"]["meetingRoundId"]
    executor = DeferredExecutor()
    monkeypatch.setattr(meeting_runtime, "_MEETING_DISCUSSION_EXECUTOR", executor)
    events = _capture_scene_events(monkeypatch)
    try:
        # Active discussion without a digest: the driver stays schedulable
        # exactly as before the TTL stop-loss existed.
        assert meeting_runtime.schedule_meeting_discussion(
            team_id, meeting_round_id
        )["status"] == "scheduled"
        assert len(executor.submissions) == 1
        assert not [
            event
            for event in events
            if event["event_code"] == "meeting_discussion.ttl_mute.engaged"
        ]
    finally:
        _release_scheduled_job(team_id, meeting_round_id)

    # Fresh digest inside the TTL: awaiting_approval keeps the historical
    # ``not_open`` refusal, with no TTL evidence.
    agent_ids = list(agents.values())
    meetings.begin_meeting_summary(team_id, meeting_round_id, actor=agent_ids[0])
    meeting_runtime.draft_meeting_digest(team_id, meeting_round_id)
    result = meeting_runtime.schedule_meeting_discussion(team_id, meeting_round_id)
    assert result["status"] == "not_open"
    assert not [
        event
        for event in events
        if event["event_code"] == "meeting_discussion.ttl_mute.engaged"
    ]


def test_ttl_pause_keeps_approval_reject_and_close_working(tmp_path, monkeypatch):
    team_id, agents, opened = _open_meeting(tmp_path, monkeypatch)
    meeting_round_id = opened["meetingRound"]["meetingRoundId"]
    agent_ids = list(agents.values())
    meetings.begin_meeting_summary(team_id, meeting_round_id, actor=agent_ids[0])
    meeting_runtime.draft_meeting_digest(team_id, meeting_round_id)
    monkeypatch.setattr(meeting_runtime, "_meeting_digest_ttl_ms", lambda: 1)

    assert meeting_runtime.schedule_meeting_discussion(team_id, meeting_round_id)[
        "status"
    ] == "ttl_muted"

    # Operator reject still reopens the summary loop ...
    rejected = meetings.reject_meeting_digest_draft(
        team_id, meeting_round_id, actor="operator", reason="需要补充分歧"
    )
    assert rejected["status"] == "summarizing"
    redrafted = meeting_runtime.draft_meeting_digest(team_id, meeting_round_id)
    assert redrafted["status"] == "awaiting_approval"

    # ... and operator approval still closes the meeting with the draft.
    approved = meetings.approve_meeting_closure(
        team_id, meeting_round_id, _closure_payload(agent_ids)
    )
    assert approved["meetingRound"]["status"] == "closed"


def test_ttl_stop_round_does_not_terminate_meeting(tmp_path, monkeypatch):
    team_id, agents, opened = _open_meeting(tmp_path, monkeypatch)
    meeting_round_id = opened["meetingRound"]["meetingRoundId"]
    meetings.begin_meeting_summary(
        team_id,
        meeting_round_id,
        actor=list(agents.values())[0],
    )

    room = {
        "roomId": opened["meetingRound"]["linkedChatRoomId"],
        "config": {"teamId": team_id},
    }
    round_payload = {
        "roundId": "round-ttl-stopped",
        "config": {"meetingRoundId": meeting_round_id, "teamId": team_id},
        "terminalReason": meeting_runtime.MEETING_DIGEST_TTL_STOP_REASON,
    }
    result = meeting_runtime.finalize_stopped_meeting_after_chat_round(
        room, round_payload
    )

    assert result["status"] == "ttl_mute_paused"
    record = meetings.get_meeting_round(team_id, meeting_round_id)["meetingRound"]
    assert record["status"] == "summarizing"
    assert "terminalReason" not in record


def test_meeting_bound_round_stops_before_first_speaker_after_ttl(
    tmp_path, monkeypatch
):
    team_id, agents, opened = _open_meeting(tmp_path, monkeypatch)
    meeting_round_id = opened["meetingRound"]["meetingRoundId"]
    room_id = opened["meetingRound"]["linkedChatRoomId"]
    agent_ids = list(agents.values())
    meetings.begin_meeting_summary(team_id, meeting_round_id, actor=agent_ids[0])
    meeting_runtime.draft_meeting_digest(team_id, meeting_round_id)
    monkeypatch.setattr(meeting_runtime, "_meeting_digest_ttl_ms", lambda: 1)

    speaker_calls: list[str] = []

    def counting_runner(participant, prompt, context):
        speaker_calls.append(str(participant.get("participantId") or ""))
        return {"status": "completed", "raw_output": "pass", "summary": "pass"}

    meeting_round = meetings.get_meeting_round(team_id, meeting_round_id)[
        "meetingRound"
    ]
    selection = meeting_runtime._selection_from_meeting(meeting_round)
    round_result = _start_bound_round(
        meeting_round,
        selection,
        room_id=room_id,
        team_id=team_id,
        discussion_round_index=2,
        agent_runner=counting_runner,
    )

    stopped_round = round_result["rounds"][-1]
    assert stopped_round["status"] == "stopped"
    assert stopped_round["terminalReason"] == (
        meeting_runtime.MEETING_DIGEST_TTL_STOP_REASON
    )
    assert speaker_calls == []
    record = meetings.get_meeting_round(team_id, meeting_round_id)["meetingRound"]
    assert record["status"] == "awaiting_approval"
    assert str(record["digestDraft"].get("summary") or "").strip()


def test_meeting_bound_round_keeps_completed_speakers_when_ttl_engages_mid_round(
    tmp_path, monkeypatch
):
    team_id, agents, opened = _open_meeting(tmp_path, monkeypatch)
    meeting_round_id = opened["meetingRound"]["meetingRoundId"]
    room_id = opened["meetingRound"]["linkedChatRoomId"]
    agent_ids = list(agents.values())
    meetings.begin_meeting_summary(team_id, meeting_round_id, actor=agent_ids[0])
    meeting_runtime.draft_meeting_digest(team_id, meeting_round_id)

    meeting_round = meetings.get_meeting_round(team_id, meeting_round_id)[
        "meetingRound"
    ]
    selection = meeting_runtime._selection_from_meeting(meeting_round)
    # Re-probe at every speaker boundary so the mute can engage mid-round.
    monkeypatch.setattr(
        "core.web.services.chat_room_service._MEETING_DIGEST_TTL_POLL_INTERVAL_SECONDS",
        0.0,
    )
    real_probe = meeting_runtime.meeting_digest_ttl_mute
    probe_calls: list[int] = []

    def engage_from_second_speaker(team_id_arg, meeting_round_id_arg):
        probe_calls.append(1)
        if len(probe_calls) >= 2:
            return _ttl_mute_dict()
        return real_probe(team_id_arg, meeting_round_id_arg)

    monkeypatch.setattr(
        meeting_runtime, "meeting_digest_ttl_mute", engage_from_second_speaker
    )

    speaker_calls: list[str] = []

    def counting_runner(participant, prompt, context):
        speaker_calls.append(str(participant.get("participantId") or ""))
        return {"status": "completed", "raw_output": "AGREE: 第一轮发言", "summary": "ok"}

    round_result = _start_bound_round(
        meeting_round,
        selection,
        room_id=room_id,
        team_id=team_id,
        discussion_round_index=2,
        agent_runner=counting_runner,
    )

    stopped_round = round_result["rounds"][-1]
    assert stopped_round["terminalReason"] == (
        meeting_runtime.MEETING_DIGEST_TTL_STOP_REASON
    )
    # The fence engaged at the second speaker boundary: the first completed
    # speaker stays persisted and no further speaker call happens.
    assert len(speaker_calls) == 1
    assert len(stopped_round["messages"]) == 1
    record = meetings.get_meeting_round(team_id, meeting_round_id)["meetingRound"]
    assert record["status"] == "awaiting_approval"
