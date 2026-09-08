import json
from datetime import UTC, datetime, timedelta

import pytest

from core.agent_plugins.virtual_human_life.dialogue_context import (
    bind_interaction_receipt_turn,
    interaction_context_for_turn,
    record_interaction_receipt,
)
from core.agent_plugins.virtual_human_life.service import VirtualHumanLifeService


@pytest.fixture
def lived(tmp_path):
    clock = [datetime(2026, 9, 8, 8, tzinfo=UTC)]
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
        now_provider=lambda: clock[0],
    )
    service.set_binding(
        "agent-a",
        enabled=True,
        expected_version=0,
        config={"homeLocation": "CN-SHANGHAI"},
    )
    return service, clock


def arrive(service, clock, turn_id, *, created_at=None, content="好，按刚才的约定"):
    entry = {
        "entryId": "entry-" + turn_id,
        "sessionId": "session-a",
        "sourceKind": "user",
        "createdAt": (created_at or clock[0]).isoformat(),
        "arrivalSequence": 1,
        "command": {"content": content},
    }
    record_interaction_receipt(service.store, "agent-a", entry=entry, now=clock[0])
    bind_interaction_receipt_turn(
        service.store,
        "agent-a",
        session_id="session-a",
        entry_id=entry["entryId"],
        turn_id=turn_id,
        now=clock[0],
    )
    return entry


def test_reunion_uses_arrival_time_not_dequeue_or_receipt_rebinding(lived):
    service, clock = lived
    first = clock[0] - timedelta(days=1, minutes=20)
    arrive(service, clock, "t1", created_at=first)
    clock[0] += timedelta(minutes=40)
    second = clock[0] - timedelta(minutes=30)
    entry = arrive(service, clock, "t2", created_at=second)
    record_interaction_receipt(
        service.store, "agent-a", entry=entry, now=clock[0] + timedelta(hours=2)
    )
    bind_interaction_receipt_turn(
        service.store,
        "agent-a",
        session_id="session-a",
        entry_id=entry["entryId"],
        turn_id="t2",
        now=clock[0],
    )
    context = interaction_context_for_turn(
        service.store, "agent-a", session_id="session-a", run_id="t2"
    )
    assert context["previousUserArrivedAt"] == first.isoformat()
    assert context["currentUserArrivedAt"] == second.isoformat()
    stored = service.store.read_json("agent-a", "conversation/interaction_context.json")
    assert "好，按刚才的约定" not in json.dumps(stored, ensure_ascii=False)


def test_commitment_needs_later_user_turn_and_cancel_removes_schedule(lived):
    service, clock = lived
    arrive(service, clock, "propose")
    args = {
        "session_id": "session-a",
        "commitment_id": "film",
        "operation_id": "propose-film",
        "action": "propose",
        "title": "一起聊电影",
        "start_at": (clock[0] + timedelta(hours=2)).isoformat(),
        "end_at": (clock[0] + timedelta(hours=3)).isoformat(),
    }
    proposal = service.change_companion_commitment("agent-a", turn_id="propose", **args)
    assert proposal
    assert not any(
        row.get("eventId") == "film" for row in service.calendar_events("agent-a")
    )
    with pytest.raises(ValueError):
        service.change_companion_commitment(
            "agent-a",
            session_id="session-a",
            turn_id="propose",
            action="confirm",
            commitment_id="film",
            operation_id="self-confirm",
        )
    clock[0] += timedelta(minutes=1)
    arrive(service, clock, "confirm")
    result = service.change_companion_commitment(
        "agent-a",
        session_id="session-a",
        turn_id="confirm",
        action="confirm",
        commitment_id="film",
        operation_id="confirm-film",
    )
    assert result
    assert any(
        row.get("eventId") == "film" for row in service.calendar_events("agent-a")
    )
    with pytest.raises(RuntimeError):
        service.change_companion_commitment(
            "agent-a",
            session_id="ordinary",
            turn_id="confirm",
            action="cancel",
            commitment_id="film",
            operation_id="wrong-session",
        )
    service.change_companion_commitment(
        "agent-a",
        session_id="session-a",
        turn_id="confirm",
        action="cancel",
        commitment_id="film",
        operation_id="cancel-film",
    )
    assert not any(
        row.get("eventId") == "film" for row in service.calendar_events("agent-a")
    )


def test_shared_experience_requires_completed_owned_event_and_user_turn(lived):
    service, clock = lived
    arrive(service, clock, "t1")
    good = {
        "eventId": "song",
        "kind": "activity_completed",
        "title": "练习新歌",
        "occurredAt": clock[0].isoformat(),
        "outcome": {"status": "succeeded", "summary": "完成第一段"},
    }
    service.store.write_jsonl(
        "agent-a",
        "events/2026-09-08.jsonl",
        [good, {**good, "eventId": "failed", "outcome": {"status": "failed"}}],
    )
    with pytest.raises(ValueError):
        service.record_companion_shared_experience(
            "agent-a",
            session_id="session-a",
            turn_id="t1",
            event_id="failed",
            topic_key="song",
            summary="共同练习",
        )
    service.record_companion_shared_experience(
        "agent-a",
        session_id="session-a",
        turn_id="t1",
        event_id="song",
        topic_key="song",
        summary="一起讨论了这次练习",
    )
    segments = service.build_prompt_segments(
        "agent-a", session_id="session-a", run_id="t1"
    )
    text = json.dumps(segments, ensure_ascii=False)
    assert "sharedExperiences" in text and "完成第一段" in text
    loops = service.store.read_jsonl("agent-a", "conversation/open_loops.jsonl")
    assert loops[-1]["sourceSessionId"] == "session-a"
    assert loops[-1]["sourceTurnIds"] == ["t1"]
    before = json.dumps(loops, ensure_ascii=False)
    ordinary = service.build_prompt_segments(
        "agent-a", session_id="ordinary", run_id="t1"
    )
    ordinary_state = json.loads(ordinary[-1]["block"].split("\n")[-1])
    assert (
        not {"reunionContext", "sharedExperiences", "commitments"}
        & ordinary_state.keys()
    )
    assert (
        json.dumps(
            service.store.read_jsonl("agent-a", "conversation/open_loops.jsonl"),
            ensure_ascii=False,
        )
        == before
    )
    service.record_companion_shared_experience(
        "agent-a",
        session_id="session-a",
        turn_id="t1",
        event_id="song",
        topic_key="song",
        summary="一起讨论了这次练习",
    )
    assert service.store.read_jsonl("agent-a", "conversation/open_loops.jsonl") == loops
    clock[0] += timedelta(days=1)
    arrive(service, clock, "t2")
    state = json.loads(
        service.build_prompt_segments("agent-a", session_id="session-a", run_id="t2")[
            -1
        ]["block"].split("\n")[-1]
    )
    assert state["sharedExperiences"][0]["eventId"] == "song"
    assert state["reunionContext"]["elapsedSeconds"] == 86400
    assert "life-event:song" in service._dialogue_v2_allowed_source_keys("agent-a")


def test_missing_or_stale_native_turn_cannot_change_continuity(lived):
    service, clock = lived
    arrive(service, clock, "t1")
    with pytest.raises(RuntimeError):
        service.change_companion_commitment(
            "agent-a",
            session_id="session-a",
            turn_id="stale",
            action="propose",
            commitment_id="film",
            operation_id="stale-film",
        )
    with pytest.raises(RuntimeError):
        service.record_companion_shared_experience(
            "agent-a",
            session_id="session-a",
            turn_id="",
            event_id="song",
            topic_key="song",
            summary="none",
        )


def test_commitment_completion_requires_its_own_activity_outcome(lived):
    service, clock = lived
    arrive(service, clock, "t1")
    start = (clock[0] + timedelta(hours=1)).isoformat()
    end = (clock[0] + timedelta(hours=2)).isoformat()
    service.change_companion_commitment(
        "agent-a",
        session_id="session-a",
        turn_id="t1",
        action="propose",
        commitment_id="film",
        operation_id="p",
        title="聊电影",
        start_at=start,
        end_at=end,
    )
    arrive(service, clock, "t2")
    service.change_companion_commitment(
        "agent-a",
        session_id="session-a",
        turn_id="t2",
        action="confirm",
        commitment_id="film",
        operation_id="c",
    )
    schedule = service.schedule_for("agent-a", "2026-09-08")
    activity = next(
        item for item in schedule["activities"] if item.get("calendarEventId") == "film"
    )
    good = {
        "eventId": "result",
        "activityId": activity["activityId"],
        "kind": "activity_completed",
        "occurredAt": clock[0].isoformat(),
        "outcome": {"status": "succeeded", "summary": "聊过了电影"},
    }
    service.store.write_jsonl(
        "agent-a",
        "events/2026-09-08.jsonl",
        [good, {**good, "eventId": "unrelated", "activityId": "other"}],
    )
    with pytest.raises(ValueError):
        service.change_companion_commitment(
            "agent-a",
            session_id="session-a",
            turn_id="t2",
            action="complete",
            commitment_id="film",
            operation_id="done-wrong",
            source_event_id="unrelated",
        )
    result = service.change_companion_commitment(
        "agent-a",
        session_id="session-a",
        turn_id="t2",
        action="complete",
        commitment_id="film",
        operation_id="done",
        source_event_id="result",
    )
    assert result["commitmentState"] == "completed"
    assert (
        service.store.read_jsonl("agent-a", "calendar/events.jsonl")[-1][
            "sourceEventId"
        ]
        == "result"
    )


def test_existing_tool_binds_new_actions_to_speaking_user_turn(lived, monkeypatch):
    from core.web.services import virtual_human_life_service as gateway
    from tools import virtual_human_life_tools as tool

    service, clock = lived
    arrive(service, clock, "t1")
    runtime = {"agentId": "agent-a", "sessionId": "session-a", "turnId": "t1"}
    monkeypatch.setattr(tool, "_service", lambda: service)
    monkeypatch.setattr(tool, "_runtime_context", lambda: runtime)
    monkeypatch.setattr(
        gateway,
        "resolve_virtual_human_runtime_target",
        lambda *args, **kwargs: {"targetAgentId": "agent-a"},
    )
    result = json.loads(
        tool.virtual_human_schedule_tool(
            action="propose_commitment",
            event_id="film",
            idempotency_key="p",
            title="聊电影",
            start_at=(clock[0] + timedelta(hours=1)).isoformat(),
            end_at=(clock[0] + timedelta(hours=2)).isoformat(),
        )
    )
    assert result["ok"] and result["commitment"]["commitmentState"] == "pending"
    assert not json.loads(
        tool.virtual_human_schedule_tool(
            action="upsert_calendar",
            event_id="film",
            calendar_kind="commitment",
            idempotency_key="bypass",
        )
    )["ok"]
    runtime["sessionId"] = "ordinary"
    assert not json.loads(
        tool.virtual_human_schedule_tool(
            action="confirm_commitment", event_id="film", idempotency_key="c"
        )
    )["ok"]
    runtime.update(agentId="steward", sessionId="session-a")
    assert not json.loads(
        tool.virtual_human_schedule_tool(
            action="confirm_commitment", event_id="film", idempotency_key="c"
        )
    )["ok"]
    runtime.update(agentId="agent-a", sessionId="session-a")
    good = {
        "eventId": "song",
        "kind": "activity_completed",
        "occurredAt": clock[0].isoformat(),
        "outcome": {"status": "succeeded", "summary": "完成第一段"},
    }
    service.store.write_jsonl("agent-a", "events/2026-09-08.jsonl", [good])
    result = json.loads(
        tool.virtual_human_proactive_message_tool(
            action="record_shared_experience",
            source_event_id="song",
            source_turn_id="forged",
            topic_key="song",
            summary="聊过这首歌",
        )
    )
    assert result["ok"] and result["sharedExperience"]["sourceTurnIds"] == ["t1"]
    binding = service.binding_for("agent-a")
    service.set_binding(
        "agent-a", enabled=False, expected_version=binding["bindingRevision"]
    )
    assert not json.loads(
        tool.virtual_human_proactive_message_tool(
            action="record_shared_experience",
            source_event_id="song",
            topic_key="song",
            summary="再次讨论",
        )
    )["ok"]
