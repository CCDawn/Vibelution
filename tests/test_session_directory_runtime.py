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


def _capture_directory_runtime_events(monkeypatch):
    events = []

    def capture(event_code, **kwargs):
        events.append(
            (
                event_code,
                kwargs.get("outcome"),
                dict(kwargs.get("fields") or {}),
            )
        )

    monkeypatch.setattr(directory_runtime, "_record", capture)
    return events


def test_preopen_failure_marks_current_generation_failed_and_wakes_waiters(
    monkeypatch, tmp_path
):
    directory_runtime.shutdown_session_directory_runtime()
    events = _capture_directory_runtime_events(monkeypatch)

    def fail_store_path(_project_root):
        raise RuntimeError("the private path value must not be logged")

    monkeypatch.setattr(directory_runtime, "conversation_store_path", fail_store_path)
    generation = directory_runtime.begin_directory_startup()
    try:
        status = directory_runtime.initialize_session_directory_runtime(
            project_root=tmp_path,
            migrate_legacy_chat_state=False,
            generation=generation,
        )

        assert status.status == "failed"
        assert status.error_type == "RuntimeError"
        assert directory_runtime.current_directory_runtime_status() == status
        assert directory_runtime.is_directory_ready()
        assert directory_runtime.wait_for_directory_startup(timeout=0) == "failed"
        failure_event = next(
            event for event in events if event[0] == "session_directory.runtime.failed"
        )
        assert failure_event[2]["errorType"] == "RuntimeError"
        assert str(tmp_path) not in repr(events)
    finally:
        directory_runtime.shutdown_session_directory_runtime()


def test_store_close_failure_does_not_mask_open_failure_or_leave_starting(
    monkeypatch, tmp_path
):
    directory_runtime.shutdown_session_directory_runtime()
    events = _capture_directory_runtime_events(monkeypatch)

    class FailedOpenStore:
        def __init__(self, *_args, **_kwargs):
            self._open = False

        def open(self, *, writer_timeout):
            raise TimeoutError("open failure detail must not be logged")

        def close(self, *, timeout=5):
            raise OSError("close failure detail must not be logged")

    monkeypatch.setattr("core.chat.conversation_store.ConversationStore", FailedOpenStore)
    generation = directory_runtime.begin_directory_startup()
    try:
        status = directory_runtime.initialize_session_directory_runtime(
            project_root=tmp_path,
            migrate_legacy_chat_state=False,
            generation=generation,
        )

        assert status.status == "failed"
        assert status.error_type == "TimeoutError"
        assert directory_runtime.is_directory_ready()
        assert directory_runtime.wait_for_directory_startup(timeout=0) == "failed"
        failure_event = next(
            event for event in events if event[0] == "session_directory.runtime.failed"
        )
        assert failure_event[2]["errorType"] == "TimeoutError"
        assert failure_event[2]["cleanupErrorType"] == "OSError"
        assert "open failure detail" not in repr(events)
        assert "close failure detail" not in repr(events)
        assert str(tmp_path) not in repr(events)
    finally:
        directory_runtime.shutdown_session_directory_runtime()


def test_stale_preopen_failure_cannot_replace_new_generation_status(monkeypatch, tmp_path):
    directory_runtime.shutdown_session_directory_runtime()
    old_constructor_started = threading.Event()
    release_old_constructor = threading.Event()
    stores = []
    old_result = []
    events = _capture_directory_runtime_events(monkeypatch)

    class FakeStore:
        def __init__(self, *_args, **_kwargs):
            self._open = False
            self.closed = False
            self.index = len(stores)
            stores.append(self)
            if self.index == 0:
                old_constructor_started.set()
                assert release_old_constructor.wait(timeout=3)
                raise OSError("stale generation failure")

        def open(self, *, writer_timeout):
            self._open = True
            return {"schemaVersion": 1}

        def close(self, *, timeout=5):
            self.closed = True
            self._open = False

    monkeypatch.setattr("core.chat.conversation_store.ConversationStore", FakeStore)
    monkeypatch.setattr(directory_runtime, "_import_agent_snapshots", lambda *_args: 0)
    monkeypatch.setattr(directory_runtime, "_migrate_legacy_chat_state_once", lambda *_args: (False, 0, False))
    monkeypatch.setattr(directory_runtime, "_restore_missing_personal_direct_sessions", lambda *_args: 0)

    old_generation = directory_runtime.begin_directory_startup()

    def run_old_generation():
        try:
            old_result.append(
                directory_runtime.initialize_session_directory_runtime(
                    project_root=Path(tmp_path) / "old",
                    generation=old_generation,
                )
            )
        except Exception as exc:  # capture baseline behavior without a thread warning
            old_result.append(exc)

    old_thread = threading.Thread(target=run_old_generation, daemon=True)
    old_thread.start()
    assert old_constructor_started.wait(timeout=2)

    directory_runtime.shutdown_session_directory_runtime()
    current_generation = directory_runtime.begin_directory_startup()
    try:
        current_status = directory_runtime.initialize_session_directory_runtime(
            project_root=Path(tmp_path) / "current",
            migrate_legacy_chat_state=False,
            generation=current_generation,
        )
        current_store = directory_runtime.get_open_directory_store()
        release_old_constructor.set()
        old_thread.join(timeout=3)

        assert not old_thread.is_alive()
        assert current_status.status == "ready"
        assert len(old_result) == 1
        assert getattr(old_result[0], "status", None) == "superseded"
        assert directory_runtime.current_directory_runtime_status().status == "ready"
        assert directory_runtime.get_open_directory_store() is current_store is stores[1]
        assert not current_store.closed
        assert str(tmp_path) not in repr(events)
    finally:
        release_old_constructor.set()
        old_thread.join(timeout=3)
        directory_runtime.shutdown_session_directory_runtime()


def test_startup_stage_events_pair_and_exclude_paths_or_session_data(monkeypatch, tmp_path):
    directory_runtime.shutdown_session_directory_runtime()
    events = _capture_directory_runtime_events(monkeypatch)

    class FakeStore:
        def __init__(self, *_args, **_kwargs):
            self._open = False

        def open(self, *, writer_timeout):
            self._open = True
            return {"schemaVersion": 1}

        def close(self, *, timeout=5):
            self._open = False

    monkeypatch.setattr("core.chat.conversation_store.ConversationStore", FakeStore)
    monkeypatch.setattr(directory_runtime, "_import_agent_snapshots", lambda *_args: 0)
    monkeypatch.setattr(directory_runtime, "_migrate_legacy_chat_state_once", lambda *_args: (False, 0, False))
    monkeypatch.setattr(directory_runtime, "_restore_missing_personal_direct_sessions", lambda *_args: 0)
    generation = directory_runtime.begin_directory_startup()
    try:
        status = directory_runtime.initialize_session_directory_runtime(
            project_root=tmp_path,
            generation=generation,
        )
        stage_events = [
            event for event in events if event[0].startswith("session_directory.runtime.stage.")
        ]
        started = [event for event in stage_events if event[0].endswith(".started")]
        finished = [event for event in stage_events if event[0].endswith(".finished")]
        started_stages = [event[2]["stage"] for event in started]
        finished_stages = [event[2]["stage"] for event in finished]

        assert status.status == "ready"
        assert started_stages == finished_stages
        assert {
            "conversation_store_import",
            "project_root_resolve",
            "store_construction",
            "store_open",
            "store_publish",
            "agent_import",
            "legacy_migration",
            "direct_session_restore",
        }.issubset(set(started_stages))
        for event in stage_events:
            assert set(event[2]).issubset(
                {"stage", "generation", "durationMs", "errorType"}
            )
        assert str(tmp_path) not in repr(events)
        assert "sessionId" not in repr(events)
    finally:
        directory_runtime.shutdown_session_directory_runtime()
