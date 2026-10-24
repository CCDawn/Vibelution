"""Startup migration checks must not materialize the historical transcript state."""

from __future__ import annotations

import json

import pytest

from core.chat.conversation_store import ConversationStore, LegacyChatStateImporter
from core.web.services.session import directory_runtime


@pytest.fixture
def store(tmp_path):
    value = ConversationStore(tmp_path / "conversations.sqlite3")
    value.open()
    try:
        yield value
    finally:
        value.close()


def test_migration_probe_distinguishes_missing_root_empty_and_historical_rows(store):
    repository = store.repository
    assert repository.get_existing_chat_state_session_count() is None
    repository.replace_chat_state({"version": 1, "conversations": []}).result(timeout=5)
    assert repository.get_existing_chat_state_session_count() == 0
    repository.replace_chat_state({"version": 1, "conversations": [
        {"conversation_id": "history", "messages": [], "last_llm_payload_trace": {"large": "x" * 50_000}},
        {"conversation_id": "archived", "archive_state": {"status": "archived"}},
    ]}).result(timeout=5)
    assert repository.get_existing_chat_state_session_count() == 2


@pytest.mark.parametrize("count", [0, 2])
def test_completed_migration_never_decodes_payloads_or_runs_the_importer(store, tmp_path, monkeypatch, count):
    repository = store.repository
    repository.replace_chat_state({"version": 1, "conversations": [
        {"conversation_id": f"session-{index}", "last_llm_payload_trace": {"large": "x" * 50_000}}
        for index in range(count)
    ]}).result(timeout=5)
    before = repository.get_chat_state()

    def unexpected(*_args, **_kwargs):
        pytest.fail("Completed startup migration must only read root existence and row count")

    with monkeypatch.context() as patch:
        patch.setattr(repository, "get_chat_state", unexpected)
        patch.setattr(LegacyChatStateImporter, "import_file", unexpected)
        patch.setattr(json, "loads", unexpected)
        assert directory_runtime._migrate_legacy_chat_state_once(store, tmp_path) == (False, count, False)
    assert repository.get_chat_state() == before


def test_missing_root_still_imports_and_backs_up_legacy_state(store, tmp_path, monkeypatch):
    from core.ui import chat_state

    legacy_path = tmp_path / "legacy.json"
    legacy_path.write_text(json.dumps({"version": 1, "conversations": [
        {"conversation_id": "legacy-session", "title": "History"},
    ]}), encoding="utf-8")
    monkeypatch.setattr(chat_state, "chat_state_path", lambda _root: legacy_path)
    monkeypatch.setattr(chat_state, "formal_chat_state_path", lambda _root: legacy_path)
    monkeypatch.setattr(directory_runtime, "_record", lambda *_args, **_kwargs: None)
    migrated, count, backed_up = directory_runtime._migrate_legacy_chat_state_once(store, tmp_path)
    assert (migrated, count, backed_up) == (True, 1, True)
    assert store.repository.get_chat_state()["conversations"][0]["conversation_id"] == "legacy-session"
    assert directory_runtime._migrate_legacy_chat_state_once(store, tmp_path) == (False, 1, False)
