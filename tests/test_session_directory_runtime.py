from __future__ import annotations

import threading
from pathlib import Path

from core.web.services.session import directory_runtime


def test_superseded_directory_initializer_cannot_publish_over_new_generation(monkeypatch, tmp_path):
    directory_runtime.shutdown_session_directory_runtime()
    old_open_started = threading.Event()
    finish_old_open = threading.Event()
    stores = []

    class FakeStore:
        def __init__(self, *_args, **_kwargs):
            self._open = False
            self.closed = False
            self.index = len(stores)
            stores.append(self)

        def open(self, *, writer_timeout):
            if self.index == 0:
                old_open_started.set()
                assert finish_old_open.wait(timeout=3)
            self._open = True
            return {"schemaVersion": 1}

        def close(self, *, timeout=5):
            self.closed = True
            self._open = False

    monkeypatch.setattr("core.chat.conversation_store.ConversationStore", FakeStore)
    monkeypatch.setattr(directory_runtime, "_import_agent_snapshots", lambda *_args: 0)
    monkeypatch.setattr(directory_runtime, "_restore_missing_personal_direct_sessions", lambda *_args: 0)
    monkeypatch.setattr(directory_runtime, "_record", lambda *_args, **_kwargs: None)

    old_generation = directory_runtime.begin_directory_startup()
    old_result: list[object] = []
    old_thread = threading.Thread(
        target=lambda: old_result.append(
            directory_runtime.initialize_session_directory_runtime(
                project_root=Path(tmp_path) / "old",
                migrate_legacy_chat_state=False,
                generation=old_generation,
            )
        ),
        daemon=True,
    )
    old_thread.start()
    assert old_open_started.wait(timeout=2)

    directory_runtime.shutdown_session_directory_runtime()
    current_generation = directory_runtime.begin_directory_startup()
    current_status = directory_runtime.initialize_session_directory_runtime(
        project_root=Path(tmp_path) / "current",
        migrate_legacy_chat_state=False,
        generation=current_generation,
    )
    current_store = directory_runtime.get_open_directory_store()
    assert current_status.status == "ready"
    assert current_store is stores[1]

    finish_old_open.set()
    old_thread.join(timeout=3)
    try:
        assert not old_thread.is_alive()
        assert old_result[0].status == "superseded"
        assert stores[0].closed
        assert not current_store.closed
        assert directory_runtime.get_open_directory_store() is current_store
        assert directory_runtime.current_directory_runtime_status().status == "ready"
    finally:
        directory_runtime.shutdown_session_directory_runtime()


def test_is_directory_ready_holds_only_mid_startup_and_never_wedges():
    directory_runtime.shutdown_session_directory_runtime()
    try:
        # Unknown / never-started runtime (including pytest skips) stays open.
        assert directory_runtime.is_directory_ready()
        directory_runtime.begin_directory_startup()
        assert not directory_runtime.is_directory_ready()
        # Every terminal phase opens the gate so a broken startup cannot block
        # first paint forever.
        directory_runtime.shutdown_session_directory_runtime()
        assert directory_runtime.is_directory_ready()
    finally:
        directory_runtime.shutdown_session_directory_runtime()


def test_list_query_startup_wait_is_a_bounded_backstop():
    # Strictly bounded: never the old always-empty 0s gate, never the 30s
    # STARTING_WAIT_SECONDS hang that would stall bootstrap first paint.
    assert 0 < directory_runtime.LIST_QUERY_STARTUP_WAIT_SECONDS < directory_runtime.STARTING_WAIT_SECONDS
