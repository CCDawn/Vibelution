from concurrent.futures import Future
from types import SimpleNamespace

import pytest

from core.web.services.session import directory_bridge


@pytest.mark.parametrize("terminal_status", ["needs_continue", "paused_limit", "failed", "ready"])
def test_directory_sync_preserves_canonical_last_turn_status(monkeypatch, terminal_status):
    writes = []

    def upsert(**values):
        writes.append(values)
        done = Future()
        done.set_result(None)
        return done

    monkeypatch.setattr(directory_bridge.directory_runtime, "get_open_directory_store", lambda: SimpleNamespace(
        repository=SimpleNamespace(upsert_directory_session=upsert),
    ))
    monkeypatch.setattr(directory_bridge, "_ensure_agent_revision", lambda *_: "revision-a")
    directory_bridge.sync_conversation_record({
        "conversation_id": "session-a", "agent_id": "agent-a", "title": "A",
        "last_turn_status": terminal_status,
    })
    assert writes[0]["status"] == terminal_status


def test_archive_directory_session_safe_can_return_before_archive_finishes(monkeypatch):
    pending_archive = Future()
    archived_session_ids = []

    def schedule_archive(session_id):
        archived_session_ids.append(session_id)
        return pending_archive

    repository = SimpleNamespace(
        archive_directory_session=schedule_archive,
    )
    monkeypatch.setattr(
        directory_bridge.directory_runtime,
        "get_open_directory_store",
        lambda: SimpleNamespace(repository=repository),
    )

    returned = directory_bridge.archive_directory_session_safe("session-live", wait=False)

    assert returned is pending_archive
    assert pending_archive.done() is False
    assert archived_session_ids == ["session-live"]


def test_archive_directory_session_safe_returns_failed_future_when_dispatch_fails(monkeypatch):
    def fail_archive_dispatch(_session_id):
        raise OSError("simulated writer queue failure")

    monkeypatch.setattr(
        directory_bridge.directory_runtime,
        "get_open_directory_store",
        lambda: SimpleNamespace(
            repository=SimpleNamespace(archive_directory_session=fail_archive_dispatch),
        ),
    )

    returned = directory_bridge.archive_directory_session_safe("session-live", wait=False)

    assert returned is not None
    assert isinstance(returned.exception(), OSError)
