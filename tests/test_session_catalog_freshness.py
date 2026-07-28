from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.chat.session_catalog import SessionCatalogStore
from core.ui.chat_state import chat_state_path, load_chat_state, save_chat_state


@pytest.fixture(autouse=True)
def _isolated_data_home(tmp_path, monkeypatch):
    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(tmp_path / "operator-data"))


def _store(tmp_path: Path) -> SessionCatalogStore:
    store = SessionCatalogStore(
        tmp_path / "catalog" / "session_catalog.sqlite3",
        workspace_key="workspace-test",
    )
    store.initialize()
    return store


def test_chat_state_save_assigns_monotonic_revision_under_stale_payload(tmp_path):
    stale_payload = {
        "version": 1,
        "state_revision": 999,
        "conversations": [],
    }

    save_chat_state(tmp_path, stale_payload)
    first = load_chat_state(tmp_path)
    save_chat_state(tmp_path, stale_payload)
    second = load_chat_state(tmp_path)

    assert first["state_revision"] == 1
    assert second["state_revision"] == 2


def test_load_cleanup_advances_state_revision(tmp_path):
    path = chat_state_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "state_revision": 4,
                "conversations": [
                    {
                        "conversation_id": "session-a",
                        "messages": [{"role": "user", "content": "legacy"}],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    cleaned = load_chat_state(tmp_path)

    assert cleaned["state_revision"] == 5
    assert "messages" not in cleaned["conversations"][0]
    assert json.loads(path.read_text(encoding="utf-8"))["state_revision"] == 5


def test_dirty_catalog_marks_local_sentinel_and_only_clears_after_reconcile(tmp_path):
    store = _store(tmp_path)

    assert store.mark_dirty(
        "session-a",
        reason="canonical_mutation",
        source_revision="state:1",
        observed_at="2026-07-28T00:00:00Z",
    )
    store.mark_untrusted("catalog_write_failed")

    assert store.dirty_session_count() == 1
    assert store.untrusted_sentinel_path.exists()
    assert store.clear_untrusted_after_reconcile() is False

    store.clear_dirty_sessions(["session-a"])
    assert store.clear_untrusted_after_reconcile() is True
    assert not store.untrusted_sentinel_path.exists()
