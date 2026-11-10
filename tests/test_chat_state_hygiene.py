"""Orphan chat-state pruning keeps anything that might still hold a session."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from core.chat.conversation_store import ConversationStore
from core.web.services.session import conversation_index, chat_state_hygiene


def _open_store(root: Path) -> ConversationStore:
    store = ConversationStore(root / "workspace" / "chat" / "conversations.sqlite3")
    store.open()
    return store


def _write_chat_state(store: ConversationStore, conversations: list[dict[str, Any]]) -> None:
    store.repository.replace_chat_state(
        {"version": 1, "conversations": conversations}
    ).result(timeout=5)


@pytest.fixture()
def store(tmp_path: Path):
    opened = _open_store(tmp_path)
    try:
        yield opened
    finally:
        opened.close()


def test_prunes_row_with_no_directory_row_no_files_and_no_messages(
    tmp_path: Path, store: ConversationStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_chat_state(store, [{"conversation_id": "ghost", "title": "ghost"}])
    monkeypatch.setattr(
        conversation_index,
        "_session_workspace_dir_if_present",
        lambda session_id: None,
    )

    summary = chat_state_hygiene.prune_orphan_chat_state_sessions(tmp_path)

    assert summary["orphanCandidateCount"] == 1
    assert summary["prunedCount"] == 1
    assert summary["keptWithContentCount"] == 0
    assert store.repository.list_session_runtime_ids() == []


def test_keeps_row_that_still_carries_messages(
    tmp_path: Path, store: ConversationStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_chat_state(
        store,
        [
            {
                "conversation_id": "chatty",
                "messages": [{"role": "user", "content": "keep me"}],
            }
        ],
    )
    monkeypatch.setattr(
        conversation_index,
        "_session_workspace_dir_if_present",
        lambda session_id: None,
    )

    summary = chat_state_hygiene.prune_orphan_chat_state_sessions(tmp_path)

    assert summary["orphanCandidateCount"] == 1
    assert summary["prunedCount"] == 0
    assert summary["keptWithContentCount"] == 1
    assert store.repository.list_session_runtime_ids() == ["chatty"]


def test_keeps_row_whose_workspace_still_has_files(
    tmp_path: Path, store: ConversationStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_chat_state(store, [{"conversation_id": "worked", "title": "worked"}])
    workspace = tmp_path / "workspace" / "sessions" / "worked"
    workspace.mkdir(parents=True)
    (workspace / "artifact.txt").write_text("payload", encoding="utf-8")
    monkeypatch.setattr(
        conversation_index,
        "_session_workspace_dir_if_present",
        lambda session_id: workspace if session_id == "worked" else None,
    )

    summary = chat_state_hygiene.prune_orphan_chat_state_sessions(tmp_path)

    assert summary["prunedCount"] == 0
    assert summary["keptWithContentCount"] == 1
    assert store.repository.list_session_runtime_ids() == ["worked"]
