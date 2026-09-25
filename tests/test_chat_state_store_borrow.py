"""Meeting opens reuse one conversation store instead of opening it per read."""

from __future__ import annotations

from pathlib import Path

import pytest

import core.chat.conversation_store.database as conversation_database
from core.chat.conversation_store import ConversationStore
from core.ui.chat_state import borrow_chat_state_store, load_session_chat_state
from core.web.services.session import directory_runtime


@pytest.fixture
def _count_store_opens(monkeypatch: pytest.MonkeyPatch) -> dict[str, int]:
    calls = {"n": 0}
    original = conversation_database.ConversationDatabase.initialize

    def counting(self):
        calls["n"] += 1
        return original(self)

    monkeypatch.setattr(conversation_database.ConversationDatabase, "initialize", counting)
    return calls


def test_borrow_reuses_one_store_for_repeated_session_reads(
    tmp_path: Path,
    _count_store_opens: dict[str, int],
) -> None:
    with borrow_chat_state_store(tmp_path):
        assert load_session_chat_state(tmp_path, "missing-a") is None
        assert load_session_chat_state(tmp_path, "missing-b") is None
        with borrow_chat_state_store(tmp_path):
            assert load_session_chat_state(tmp_path, "missing-c") is None

    assert _count_store_opens["n"] == 1


def test_borrow_leaves_a_live_directory_store_open(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    _count_store_opens: dict[str, int],
) -> None:
    live = ConversationStore(tmp_path / "live.sqlite3")
    live.open()
    root = tmp_path.resolve()
    monkeypatch.setattr(directory_runtime, "get_open_directory_store", lambda: live)
    monkeypatch.setattr(directory_runtime, "directory_store_project_root", lambda: root)
    opens_after_live = _count_store_opens["n"]

    try:
        with borrow_chat_state_store(tmp_path):
            assert load_session_chat_state(tmp_path, "missing") is None
        assert live._open is True
        assert _count_store_opens["n"] == opens_after_live
    finally:
        live.close()
