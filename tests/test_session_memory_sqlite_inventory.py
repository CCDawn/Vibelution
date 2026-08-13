from __future__ import annotations

from pathlib import Path

from core.web.services import memory_service


def test_chat_session_memory_inventory_points_to_sqlite_control_plane(tmp_path: Path):
    store_path = tmp_path / "workspace" / "chat" / "conversations.sqlite3"
    store_path.parent.mkdir(parents=True, exist_ok=True)
    store_path.write_bytes(b"sqlite-control-placeholder")

    section = memory_service._chat_session_memory_section(tmp_path)
    chat_item = next(item for item in section["items"] if item["id"] == "chat-state")

    assert chat_item["title"] == "conversations.sqlite3 / chat control state"
    assert chat_item["path"] == "workspace/chat/conversations.sqlite3"
    assert "chat_state.json" not in chat_item["path"]
    assert '"legacyChatStateJson": "migration_input_only"' in chat_item["content"]
    assert '"transcriptSource": "workspace/sessions/*/turn_journal.jsonl"' in chat_item["content"]


def test_chat_session_memory_signature_tracks_sqlite_wal_not_legacy_json(tmp_path: Path):
    store_path = tmp_path / "workspace" / "chat" / "conversations.sqlite3"
    store_path.parent.mkdir(parents=True, exist_ok=True)
    store_path.write_bytes(b"sqlite")
    before = memory_service._memory_overview_section_signature(
        tmp_path,
        "chat-session-memory",
    )

    Path(f"{store_path}-wal").write_bytes(b"wal-change")
    after = memory_service._memory_overview_section_signature(
        tmp_path,
        "chat-session-memory",
    )

    assert before != after
