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


def test_query_session_summaries_serves_bounded_startup_empty_page(monkeypatch):
    """Mid-startup queries stay non-blocking but never look like real empty data."""

    observed_timeouts: list[float] = []

    def fake_wait(*, timeout):
        observed_timeouts.append(timeout)
        return "starting"

    monkeypatch.setattr(
        directory_bridge.directory_runtime,
        "wait_for_directory_startup",
        fake_wait,
    )

    payload = directory_bridge.query_session_summaries()

    assert payload is not None
    assert payload["items"] == []
    assert payload["nextCursor"] == ""
    # The wait must stay the bounded startup backstop, not the 30s full wait.
    assert observed_timeouts == [directory_bridge.directory_runtime.LIST_QUERY_STARTUP_WAIT_SECONDS]


def test_list_session_summaries_serves_bounded_startup_empty_page(monkeypatch):
    monkeypatch.setattr(
        directory_bridge.directory_runtime,
        "wait_for_directory_startup",
        lambda *, timeout: "starting",
    )

    assert directory_bridge.list_session_summaries() == []


def test_query_session_summaries_proceeds_past_gate_once_startup_resolves(monkeypatch):
    """A wait that resolves to a terminal phase must reach the store read path."""

    degraded_sources: list[str] = []
    monkeypatch.setattr(
        directory_bridge,
        "note_session_read_degraded",
        lambda *, source, error_type="": degraded_sources.append(source),
    )
    monkeypatch.setattr(
        directory_bridge.directory_runtime,
        "wait_for_directory_startup",
        lambda *, timeout: "ready",
    )
    monkeypatch.setattr(
        directory_bridge.directory_runtime,
        "get_open_directory_store",
        lambda: None,
    )

    # A missing store on the resolved path reports degraded instead of serving
    # the startup empty page, proving the gate no longer holds the query.
    assert directory_bridge.query_session_summaries() is None
    assert degraded_sources == ["session query"]
