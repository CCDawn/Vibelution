"""Archive runtime rows commit together without rewriting sibling sessions."""

from __future__ import annotations

import pytest

from core.chat.conversation_store import ConversationStore
from core.chat.conversation_store.repository import WorkspaceChatStateDao
from core.infrastructure import developer_sandbox
from core.ui import chat_state


def _store(tmp_path):
    store = ConversationStore(tmp_path / "conversations.sqlite3")
    store.open()
    return store


def test_runtime_batch_uses_one_writer_and_preserves_siblings(tmp_path, monkeypatch):
    store = _store(tmp_path)
    try:
        store.repository.replace_chat_state({"conversations": [
            {"conversation_id": "a", "title": "A"},
            {"conversation_id": "b", "title": "B"},
            {"conversation_id": "peer", "title": "Peer"},
        ]}).result(timeout=3)
        peer = store.repository.get_session_runtime_state("peer")
        submitted = []
        original_submit = store.repository._writer.submit

        def submit(*args, **kwargs):
            submitted.append(kwargs)
            return original_submit(*args, **kwargs)

        monkeypatch.setattr(store.repository._writer, "submit", submit)
        result = store.repository.upsert_session_runtime_states([
            {"conversation_id": "a", "title": "A sealed", "read_only": True},
            {"conversation_id": "b", "title": "B sealed", "read_only": True},
        ], activate_session_id="b").result(timeout=3)

        assert len(submitted) == 1 and submitted[0]["force_flush"] is True
        assert result["sessionIds"] == ["a", "b"]
        assert store.repository.get_active_session_id() == "b"
        assert store.repository.get_session_runtime_state("a")["read_only"] is True
        assert store.repository.get_session_runtime_state("b")["read_only"] is True
        assert store.repository.get_session_runtime_state("peer") == peer
    finally:
        store.close()


def test_runtime_batch_failure_rolls_back_earlier_rows(tmp_path, monkeypatch):
    store = _store(tmp_path)
    try:
        store.repository.upsert_session_runtime_state("a", {"conversation_id": "a", "title": "A"}).result(timeout=3)
        original_upsert = WorkspaceChatStateDao.upsert_one

        def upsert(self, session_id, *args, **kwargs):
            if session_id == "b":
                raise ValueError("second row rejected")
            return original_upsert(self, session_id, *args, **kwargs)

        monkeypatch.setattr(WorkspaceChatStateDao, "upsert_one", upsert)
        with pytest.raises(ValueError, match="second row rejected"):
            store.repository.upsert_session_runtime_states([
                {"conversation_id": "a", "title": "must roll back"},
                {"conversation_id": "b", "title": "B"},
            ]).result(timeout=3)
        assert store.repository.get_session_runtime_state("a")["title"] == "A"
        assert store.repository.get_session_runtime_state("b") is None
    finally:
        store.close()


def test_save_runtime_batch_invalidates_read_cache_and_notifies_each_row(tmp_path, monkeypatch):
    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(tmp_path / "operator"))
    monkeypatch.setattr(developer_sandbox, "is_developer_mode_enabled", lambda: False)
    notifications = []
    with chat_state.borrow_chat_state_store(tmp_path):
        chat_state.save_session_chat_state(tmp_path, "a", {"conversation_id": "a", "title": "old"})
        assert chat_state.load_session_chat_state(tmp_path, "a")["title"] == "old"
        monkeypatch.setattr(chat_state, "notify_session_catalog_dirty", lambda *args: notifications.append(args))
        chat_state.save_session_chat_states(tmp_path, [
            {"conversation_id": "a", "title": "new"},
            {"conversation_id": "b", "title": "B"},
        ], activate_session_id="b")
        assert chat_state.load_session_chat_state(tmp_path, "a")["title"] == "new"
        assert chat_state.load_active_conversation_id(tmp_path) == "b"
    assert {entry[1] for entry in notifications} == {"a", "b", chat_state.CATALOG_GLOBAL_DIRTY_SESSION_ID}
