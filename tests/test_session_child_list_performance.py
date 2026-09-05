from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

import core.chat.conversation_store.database as conversation_database
from core.chat.conversation_store import ConversationStore
from core.web.services import session_service
from core.web.services.session import directory_bridge


@pytest.fixture
def safe_sqlite_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        conversation_database.sqlite3,
        "sqlite_version_info",
        (3, 51, 3),
    )


def _open_store(tmp_path: Path) -> ConversationStore:
    store = ConversationStore(tmp_path / "workspace" / "chat" / "conversations.sqlite3")
    store.open()
    return store


def _create_agent(store: ConversationStore) -> str:
    result = store.repository.create_agent(
        agent_id="agent-a",
        display_name="Agent A",
        kind="assistant",
        config={"modelId": "test-model"},
        source="test",
    ).result(timeout=3)
    return str(result["configRevisionId"])


def test_repository_lists_only_direct_children_from_parent_index(
    tmp_path: Path,
    safe_sqlite_runtime: None,
) -> None:
    store = _open_store(tmp_path)
    try:
        revision = _create_agent(store)
        store.repository.create_session(
            session_id="session-root",
            agent_id="agent-a",
            agent_config_revision_id=revision,
            title="Root",
        ).result(timeout=3)
        for session_id in ("session-child-a", "session-child-b"):
            store.repository.create_session(
                session_id=session_id,
                agent_id="agent-a",
                agent_config_revision_id=revision,
                parent_session_id="session-root",
                session_kind="child",
                hidden_from_index=True,
                title=session_id,
            ).result(timeout=3)
        store.repository.create_session(
            session_id="session-grandchild",
            agent_id="agent-a",
            agent_config_revision_id=revision,
            parent_session_id="session-child-a",
            session_kind="child",
            hidden_from_index=True,
            title="Grandchild",
        ).result(timeout=3)

        rows = store.repository.list_child_sessions("session-root")

        assert {row["sessionId"] for row in rows} == {
            "session-child-a",
            "session-child-b",
        }
        assert all(row["parentSessionId"] == "session-root" for row in rows)
    finally:
        store.close()


def test_directory_bridge_resolves_root_before_listing_direct_children(
    tmp_path: Path,
    safe_sqlite_runtime: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _open_store(tmp_path)
    try:
        revision = _create_agent(store)
        store.repository.create_session(
            session_id="session-root",
            agent_id="agent-a",
            agent_config_revision_id=revision,
            title="Root",
        ).result(timeout=3)
        for session_id, parent_session_id in (
            ("session-child-a", "session-root"),
            ("session-child-b", "session-root"),
            ("session-grandchild", "session-child-a"),
        ):
            store.repository.create_session(
                session_id=session_id,
                agent_id="agent-a",
                agent_config_revision_id=revision,
                parent_session_id=parent_session_id,
                session_kind="child",
                hidden_from_index=True,
                title=session_id,
            ).result(timeout=3)

        monkeypatch.setattr(
            directory_bridge.directory_runtime,
            "wait_for_directory_startup",
            lambda **kwargs: "ready",
        )
        monkeypatch.setattr(
            directory_bridge.directory_runtime,
            "get_open_directory_store",
            lambda: store,
        )
        monkeypatch.setattr(
            directory_bridge,
            "_service",
            lambda: SimpleNamespace(_agent_lookup_for_conversations=lambda: {}),
        )
        monkeypatch.setattr(
            directory_bridge,
            "_summary_from_directory_row",
            lambda row, **kwargs: {
                "id": row["sessionId"],
                "updatedAt": str(row["recencyAtMs"]),
            },
        )

        payload = directory_bridge.list_child_session_summaries("session-grandchild")

        assert payload is not None
        assert payload["rootSessionId"] == "session-root"
        assert {item["id"] for item in payload["items"]} == {
            "session-child-a",
            "session-child-b",
        }
    finally:
        store.close()


def test_list_child_sessions_never_reads_or_locks_full_chat_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorded_scene_events: list[tuple[tuple, dict]] = []

    class ForbiddenChatStateLock:
        def __enter__(self):
            pytest.fail("child-session listing must not acquire _CHAT_STATE_LOCK")

        def __exit__(self, exc_type, exc, traceback):
            return False

    monkeypatch.setattr(session_service, "_CHAT_STATE_LOCK", ForbiddenChatStateLock())
    monkeypatch.setattr(
        session_service,
        "load_chat_state",
        lambda *args, **kwargs: pytest.fail(
            "child-session listing must not read the full chat state"
        ),
    )
    monkeypatch.setattr(
        directory_bridge,
        "list_child_session_summaries",
        lambda session_id: {
            "rootSessionId": "session-root",
            "items": [
                {"id": "session-child-b", "updatedAt": "2026-09-05T03:00:00"},
                {"id": "session-child-a", "updatedAt": "2026-09-05T02:00:00"},
            ],
        },
    )
    monkeypatch.setattr(
        session_service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: recorded_scene_events.append((args, kwargs))
        or {"accepted": True},
    )

    children = session_service.list_child_sessions("session-child-a")

    assert [item["id"] for item in children] == [
        "session-child-b",
        "session-child-a",
    ]
    event_fields = recorded_scene_events[0][1]["fields"]
    assert event_fields["rootSessionId"] == "session-root"
    assert event_fields["projectionSource"] == "conversation_store_parent_index"
    assert "chatStateWaitMs" not in event_fields
    assert "chatStateReadMs" not in event_fields
