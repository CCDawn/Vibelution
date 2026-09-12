"""Focused tests for question-scoped conversation cleanup.

These tests own the seam between reset/retire and the session directory store:
inventory selection (visible + hidden rows, question-token boundaries), bulk
delete chunking, and per-step error isolation in the composed cleanup.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from core.chat.conversation_store import ConversationStore
from core.web.services.session import (
    directory_runtime,
    question_sessions,
    session_bulk_delete,
)
from core.web.services.team_workflow.research_runtime import (
    question_conversation_cleanup,
)


def _isolate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(tmp_path))
    monkeypatch.setattr(question_sessions, "PROJECT_ROOT", tmp_path)
    return directory_runtime.conversation_store_path(tmp_path)


def _seed_directory_sessions(
    store_path: Path, rows: list[tuple[str, str, bool]]
) -> None:
    store = ConversationStore(store_path)
    store.open()
    try:
        revision = str(
            store.repository.create_agent(
                agent_id="agent-a",
                display_name="Agent A",
                kind="assistant",
                config={"modelId": "test-model"},
                source="test",
            ).result(timeout=5)["configRevisionId"]
        )
        for session_id, title, hidden in rows:
            store.repository.upsert_directory_session(
                session_id=session_id,
                agent_id="agent-a",
                agent_config_revision_id=revision,
                title=title,
                hidden_from_index=hidden,
            ).result(timeout=5)
        store.writer.flush(timeout=5)
    finally:
        store.close()


def test_question_session_inventory_matches_token_and_includes_hidden_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store_path = _isolate(tmp_path, monkeypatch)
    _seed_directory_sessions(
        store_path,
        [
            ("session-team", "SCI-010 团队会话", False),
            ("session-child", "SCI-010 候选讨论（子会话）", True),
            ("session-other", "SCI-011 团队会话", False),
            ("session-prefix", "SCI-0100 团队会话", False),
            ("session-unbound", "普通会话", False),
        ],
    )

    summaries = question_sessions.list_question_session_summaries("SCI-010")

    assert {item["sessionId"] for item in summaries} == {
        "session-team",
        "session-child",
    }
    by_id = {item["sessionId"]: item for item in summaries}
    assert by_id["session-child"]["hiddenFromIndex"] is True
    assert by_id["session-team"]["hiddenFromIndex"] is False


def test_remove_question_sessions_for_question_targets_only_matching_sessions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _isolate(tmp_path, monkeypatch)
    requested: list[list[str]] = []

    def fake_bulk_delete(session_ids: list[str]) -> dict:
        requested.append(list(session_ids))
        return {
            "success": [
                {"sessionId": session_id, "deleted": True} for session_id in session_ids
            ],
            "skipped": [],
            "failed": [],
        }

    monkeypatch.setattr(
        session_bulk_delete, "bulk_delete_chat_sessions", fake_bulk_delete
    )
    monkeypatch.setattr(
        question_sessions,
        "list_question_session_summaries",
        lambda question_id: [
            {"sessionId": "session-team", "title": "SCI-010", "hiddenFromIndex": False},
            {"sessionId": "session-child", "title": "SCI-010", "hiddenFromIndex": True},
            {"sessionId": "session-team", "title": "SCI-010", "hiddenFromIndex": False},
        ],
    )

    result = question_sessions.remove_question_sessions_for_question("SCI-010")

    assert requested == [["session-team", "session-child"]]
    assert result["requestedSessionCount"] == 2
    assert result["removedSessionCount"] == 2
    assert result["removedSessionIds"] == ["session-team", "session-child"]


def test_remove_question_sessions_chunks_through_shared_bulk_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _isolate(tmp_path, monkeypatch)
    chunks: list[list[str]] = []

    def fake_bulk_delete(session_ids: list[str]) -> dict:
        chunks.append(list(session_ids))
        return {
            "success": [
                {"sessionId": session_id, "deleted": True} for session_id in session_ids
            ],
            "skipped": [],
            "failed": [],
        }

    monkeypatch.setattr(
        session_bulk_delete, "bulk_delete_chat_sessions", fake_bulk_delete
    )
    session_ids = [f"session-{index:03d}" for index in range(250)]

    result = question_sessions.remove_question_sessions(session_ids)

    assert [len(chunk) for chunk in chunks] == [100, 100, 50]
    assert [item for chunk in chunks for item in chunk] == session_ids
    assert result["requestedSessionCount"] == 250
    assert result["removedSessionCount"] == 250
    assert result["truncatedDetails"] is True
    assert len(result["removedSessionIds"]) == 50


def test_remove_question_sessions_retires_not_found_ghost_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _isolate(tmp_path, monkeypatch)
    from core.web.services.session import agent_sessions as session_module

    calls: list[tuple[str, str, str]] = []

    class FakeSessionService:
        def _retire_unopenable_directory_session(self, session_id, *, source):
            calls.append(("retire", session_id, source))

        def _mark_session_workspace_intentionally_deleted(self, session_id, *, reason):
            calls.append(("tombstone", session_id, reason))

    def fake_bulk_delete(session_ids: list[str]) -> dict:
        return {
            "success": [{"sessionId": session_ids[0], "deleted": True}],
            "skipped": [
                {"sessionId": session_ids[1], "reason": "not_found"},
                {"sessionId": session_ids[2], "reason": "busy"},
            ],
            "failed": [],
        }

    monkeypatch.setattr(
        session_bulk_delete, "bulk_delete_chat_sessions", fake_bulk_delete
    )
    monkeypatch.setattr(session_module, "_service", lambda: FakeSessionService())

    result = question_sessions.remove_question_sessions(
        ["session-live", "session-ghost", "session-busy"],
        retire_ghost_rows=True,
    )

    assert calls == [
        ("retire", "session-ghost", "question_conversation_cleanup"),
        ("tombstone", "session-ghost", "question_cleanup"),
    ]
    assert result["removedSessionCount"] == 2
    assert result["removedSessionIds"] == ["session-live", "session-ghost"]
    assert result["skippedSessions"] == [{"sessionId": "session-busy", "reason": "busy"}]
    assert result["failedSessions"] == []


def test_remove_question_sessions_archives_directory_rows_offline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store_path = _isolate(tmp_path, monkeypatch)
    _seed_directory_sessions(
        store_path,
        [
            ("session-team", "SCI-010 团队会话", False),
            ("session-child", "SCI-010 子会话", True),
            ("session-other", "SCI-011 团队会话", False),
        ],
    )

    def fake_bulk_delete(session_ids: list[str]) -> dict:
        return {
            "success": [{"sessionId": item, "deleted": True} for item in session_ids],
            "skipped": [],
            "failed": [],
        }

    monkeypatch.setattr(
        session_bulk_delete, "bulk_delete_chat_sessions", fake_bulk_delete
    )

    summaries = question_sessions.list_question_session_summaries("SCI-010")
    result = question_sessions.remove_question_sessions(
        [item["sessionId"] for item in summaries]
    )

    assert result["removedSessionCount"] == 2
    assert question_sessions.list_question_session_summaries("SCI-010") == []
    assert [
        item["sessionId"]
        for item in question_sessions.list_question_session_summaries("SCI-011")
    ] == ["session-other"]


def test_remove_question_conversations_isolates_step_failures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from core.web.services import chat_room_service

    monkeypatch.setattr(
        chat_room_service,
        "remove_chat_rooms_for_question",
        lambda team_id, question_id: (_ for _ in ()).throw(RuntimeError("room boom")),
    )
    monkeypatch.setattr(
        question_sessions,
        "remove_question_sessions_for_question",
        lambda question_id: {
            "requestedSessionCount": 1,
            "removedSessionCount": 1,
            "skippedSessionCount": 0,
            "failedSessionCount": 0,
            "removedSessionIds": ["session-a"],
            "skippedSessions": [],
            "failedSessions": [],
            "truncatedDetails": False,
        },
    )

    result = question_conversation_cleanup.remove_question_conversations(
        "research-team", "sci-010"
    )

    assert result["questionId"] == "SCI-010"
    assert result["sessions"]["removedSessionCount"] == 1
    assert result["rooms"]["removedRoomCount"] == 0
    assert len(result["errors"]) == 1
    assert result["errors"][0].startswith("chat rooms: ")


def test_preview_question_conversations_counts_rooms_and_sessions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store_path = _isolate(tmp_path, monkeypatch)
    _seed_directory_sessions(
        store_path,
        [
            ("session-team", "SCI-010 团队会话", False),
            ("session-child", "SCI-010 子会话", True),
        ],
    )
    from core.web.services import chat_room_service

    monkeypatch.setattr(
        chat_room_service,
        "list_chat_rooms_for_question",
        lambda team_id, question_id: [
            {"roomId": "room-a", "roundCount": 2, "messageCount": 5},
            {"roomId": "room-b", "roundCount": 1, "messageCount": 3},
        ],
    )

    preview = question_conversation_cleanup.preview_question_conversations(
        "research-team", "SCI-010"
    )

    assert preview["roomCount"] == 2
    assert preview["roundCount"] == 3
    assert preview["messageCount"] == 8
    assert preview["sessionCount"] == 2
    assert preview["visibleSessionCount"] == 1
    assert preview["hiddenSessionCount"] == 1
