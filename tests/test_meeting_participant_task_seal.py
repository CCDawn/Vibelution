"""Meeting-closure speaker task seal: room-bound speakers never idle forever.

Room-bound discussion speakers are hidden Child Sessions that never run a
turn of their own, so the ``child_session`` runtime task registered at
creation would stay ``idle`` in the active bucket forever (one topbar "空闲"
row per speaker per review round). Closing the meeting must seal them.
"""

from __future__ import annotations

import pytest

from core.web.services import team_service
from core.web.services.runtime_task_registry import (
    KIND_CHILD_SESSION,
    RuntimeTaskStore,
    new_snapshot,
)
from core.web.services.team_workflow import meeting_participant_tasks
from core.web.services.team_workflow import meeting_rounds as meetings
from core.web.services.team_workflow import personal_memory_candidates as memories


def _team(tmp_path, monkeypatch):
    monkeypatch.setattr(team_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(meetings, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(memories, "PROJECT_ROOT", tmp_path)
    return team_service.create_team(name="seal team")["teamId"]


def _store(tmp_path):
    return RuntimeTaskStore(tmp_path / "runtime_tasks")


def _register_child(store, task_id: str, status: str) -> None:
    store.register_task(
        new_snapshot(
            kind=KIND_CHILD_SESSION,
            task_id=task_id,
            status=status,
            parent_session_id="session-root-1",
            label=f"SCI-021｜候选预评审｜{task_id}",
        )
    )


def _patch_room(monkeypatch, room_id: str, session_ids: list[str]):
    detail = {
        "roomId": room_id,
        "participants": [
            {"agentId": f"agent-{index}", "sessionId": session_id}
            for index, session_id in enumerate(session_ids)
        ],
    }
    monkeypatch.setattr(
        meeting_participant_tasks,
        "_room_participant_session_ids",
        lambda resolved_room_id: list(session_ids)
        if resolved_room_id == room_id
        else [],
    )
    return detail


def test_seal_moves_only_idle_child_tasks_to_completed(tmp_path, monkeypatch):
    store = _store(tmp_path)
    _register_child(store, "session-idle-1", "idle")
    _register_child(store, "session-running-1", "running")
    _register_child(store, "session-queued-1", "queued")
    _register_child(store, "session-done-1", "completed")
    store.register_task(
        new_snapshot(
            kind="research_task",
            task_id="session-idle-2",
            status="idle",
        )
    )
    _patch_room(
        monkeypatch,
        "room-a",
        [
            "session-idle-1",
            "session-running-1",
            "session-queued-1",
            "session-done-1",
            "session-idle-2",
            "session-unknown-1",
        ],
    )

    report = meeting_participant_tasks.seal_room_participant_tasks(
        "room-a", store=store
    )

    assert report["sealed"] == 1
    assert report["skipped"] == 5
    assert report["sealedTaskIds"] == ["session-idle-1"]
    sealed = store.load_state("session-idle-1")
    assert sealed["status"] == "completed"
    assert (
        sealed["terminalReason"]
        == meeting_participant_tasks.SEAL_REASON_MEETING_CLOSED
    )
    assert store.load_state("session-running-1")["status"] == "running"
    assert store.load_state("session-queued-1")["status"] == "queued"
    assert store.load_state("session-done-1")["status"] == "completed"
    assert store.load_state("session-idle-2")["status"] == "idle"


def test_seal_is_idempotent_and_fail_open(tmp_path, monkeypatch):
    store = _store(tmp_path)
    _register_child(store, "session-idle-1", "idle")
    _patch_room(monkeypatch, "room-a", ["session-idle-1"])

    first = meeting_participant_tasks.seal_room_participant_tasks(
        "room-a", store=store
    )
    second = meeting_participant_tasks.seal_room_participant_tasks(
        "room-a", store=store
    )

    assert first["sealed"] == 1
    assert second["sealed"] == 0
    assert second["skipped"] == 1
    assert store.load_state("session-idle-1")["status"] == "completed"

    def _boom(room_id):
        raise RuntimeError("room store unreadable")

    monkeypatch.setattr(meeting_participant_tasks, "_room_participant_session_ids", _boom)
    failing = meeting_participant_tasks.seal_room_participant_tasks(
        "room-a", store=store
    )
    assert failing["sealed"] == 0
    assert store.load_state("session-idle-1")["status"] == "completed"


def test_seal_closed_meeting_requires_linked_room():
    report = meeting_participant_tasks.seal_closed_meeting_participant_tasks(
        {"linkedChatRoomId": ""}
    )
    assert report == {
        "roomId": "",
        "sealed": 0,
        "skipped": 0,
        "sealedTaskIds": [],
    }
    report = meeting_participant_tasks.seal_closed_meeting_participant_tasks(
        {"linkedChatRoomId": "room-b"}
    )
    assert report["roomId"] == "room-b"


def test_supersede_close_seals_room_speaker_tasks(tmp_path, monkeypatch):
    """The failed-discussion recovery close path triggers the speaker seal."""

    team_id = _team(tmp_path, monkeypatch)
    store = _store(tmp_path)
    _register_child(store, "session-speaker-1", "idle")
    meetings.create_meeting_round(
        team_id,
        {
            "program": "XH-202619",
            "theme": "cc-gpu-operator-001",
            "campaign": "cc-campaign-gpu-operator-001",
            "question": "SCI-021",
            "branch": "main",
            "workflow": "hypothesis_and_plan",
            "agentId": "agent-coordinator",
            "mode": "formal",
            "meetingRoundId": "meeting-seal-1",
            "meetingType": "hypothesis_review",
            "participants": ["agent-alpha", "agent-beta"],
            "discussionItemRefs": ["hypothesis_round:hround-demo-1"],
            "linkedChatRoomId": "room-seal-1",
        },
    )
    _patch_room(monkeypatch, "room-seal-1", ["session-speaker-1"])
    monkeypatch.setattr(
        meeting_participant_tasks, "_default_store", lambda: store
    )

    superseded = meetings.supersede_empty_discussion_meeting(team_id, "meeting-seal-1")

    assert superseded["status"] == "superseded"
    sealed = store.load_state("session-speaker-1")
    assert sealed["status"] == "completed"
    assert (
        sealed["terminalReason"]
        == meeting_participant_tasks.SEAL_REASON_MEETING_CLOSED
    )


def test_close_path_survives_seal_failure(tmp_path, monkeypatch):
    """A seal explosion must not roll back the committed closure."""

    team_id = _team(tmp_path, monkeypatch)
    meetings.create_meeting_round(
        team_id,
        {
            "program": "XH-202619",
            "theme": "cc-gpu-operator-001",
            "campaign": "cc-campaign-gpu-operator-001",
            "question": "SCI-021",
            "branch": "main",
            "workflow": "hypothesis_and_plan",
            "agentId": "agent-coordinator",
            "mode": "formal",
            "meetingRoundId": "meeting-seal-2",
            "meetingType": "hypothesis_review",
            "participants": ["agent-alpha"],
            "discussionItemRefs": ["hypothesis_round:hround-demo-1"],
            "linkedChatRoomId": "room-seal-2",
        },
    )

    def _boom(meeting_round, *, store=None):
        raise RuntimeError("registry exploded")

    monkeypatch.setattr(
        meeting_participant_tasks,
        "seal_closed_meeting_participant_tasks",
        _boom,
    )

    superseded = meetings.supersede_empty_discussion_meeting(
        team_id, "meeting-seal-2"
    )

    assert superseded["status"] == "superseded"
    record = meetings.get_meeting_round(team_id, "meeting-seal-2")["meetingRound"]
    assert record["status"] == "closed"
