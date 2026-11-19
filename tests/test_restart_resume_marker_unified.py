"""Contract tests for the unified restart-resume marker path.

The marker used to be written by whichever shutdown step still saw a running
snapshot, which meant an operator restart that stopped its turns first wrote
nothing. The stop entrypoint is now the single write point, so these tests pin
the merge semantics and the fact that the entrypoint records restart reasons.
"""

from __future__ import annotations

from pathlib import Path

from core.web.services.session import restart_resume_pending


class _Store:
    def __init__(self, root: Path) -> None:
        self.root = root


def _store(tmp_path: Path) -> _Store:
    root = tmp_path / "work_runs"
    root.mkdir()
    return _Store(root)


def test_append_keeps_entries_recorded_by_an_earlier_stop(tmp_path):
    store = _store(tmp_path)
    restart_resume_pending.record_pending_restart_resume(
        store, [{"sessionId": "session-a", "turnId": "turn-1"}]
    )

    restart_resume_pending.append_pending_restart_resume(
        store, [{"sessionId": "session-b", "turnId": "turn-2"}]
    )

    assert restart_resume_pending.load_pending_restart_resume(store) == {
        "session-a": {"turn-1"},
        "session-b": {"turn-2"},
    }


def test_append_merges_repeats_without_duplicating(tmp_path):
    store = _store(tmp_path)

    restart_resume_pending.append_pending_restart_resume(
        store, [{"sessionId": "session-a", "turnId": "turn-1"}]
    )
    restart_resume_pending.append_pending_restart_resume(
        store, [{"sessionId": "session-a", "turnId": "turn-1"}]
    )

    assert restart_resume_pending.load_pending_restart_resume(store) == {
        "session-a": {"turn-1"},
    }


def test_stop_entrypoint_is_the_only_restart_marker_writer():
    control_source = (
        Path(__file__).resolve().parents[1]
        / "core/web/services/session/control.py"
    ).read_text(encoding="utf-8", errors="replace")

    assert '_RESTART_RESUME_REASONS = frozenset({"electron_user_restart"})' in control_source
    assert "s.append_restart_resume_pending(conversation_id, stop_turn_id)" in control_source
    # Close and shutdown stay out of the marker: those are operator decisions.
    assert "electron_user_close" not in control_source.split("_RESTART_RESUME_REASONS")[1].split("\n")[0]
    assert "runtime_shutdown" not in control_source.split("_RESTART_RESUME_REASONS")[1].split("\n")[0]


class _KindStore:
    """Work-run store stub returning snapshots per kind."""

    def __init__(self, root: Path, snapshots: dict[str, list[dict]]) -> None:
        self.root = root
        self._snapshots = snapshots

    def load_active_snapshots(self, kind: str) -> list[dict]:
        return list(self._snapshots.get(kind, []))


def test_agent_run_snapshots_join_the_restart_marker(tmp_path, monkeypatch):
    from core.web.services import session_service

    store = _KindStore(
        tmp_path / "work_runs",
        {
            "chat_turn": [
                {"sessionId": "session-chat", "runId": "session-chat-1"},
            ],
            "agent_run": [
                {
                    "sessionId": "session-agent",
                    "runId": "agent-20261027-1",
                    "sourceRunId": "session-agent-1",
                    "status": "running",
                },
            ],
        },
    )
    monkeypatch.setattr(session_service, "_WORK_RUN_STORE", store)

    session_service.record_restart_resume_pending(replace=True)

    assert restart_resume_pending.load_pending_restart_resume(store) == {
        "session-chat": {"session-chat-1"},
        "session-agent": {"session-agent-1"},
    }


def test_agent_run_without_source_run_is_skipped(tmp_path, monkeypatch):
    from core.web.services import session_service

    store = _KindStore(
        tmp_path / "work_runs",
        {"agent_run": [{"sessionId": "session-agent", "sourceRunId": ""}]},
    )
    monkeypatch.setattr(session_service, "_WORK_RUN_STORE", store)

    session_service.record_restart_resume_pending(replace=True)

    assert restart_resume_pending.load_pending_restart_resume(store) == {}


def test_agent_run_respects_the_requester_exclusion(tmp_path, monkeypatch):
    from core.web.services import session_service

    store = _KindStore(
        tmp_path / "work_runs",
        {
            "agent_run": [
                {
                    "sessionId": "session-agent",
                    "runId": "agent-20261027-1",
                    "sourceRunId": "session-agent-1",
                },
            ],
        },
    )
    monkeypatch.setattr(session_service, "_WORK_RUN_STORE", store)

    session_service.record_restart_resume_pending(
        replace=True, exclude_turn_ids={"session-agent-1"}
    )

    assert restart_resume_pending.load_pending_restart_resume(store) == {}


def test_empty_shutdown_snapshot_keeps_the_marker_the_stops_wrote(tmp_path, monkeypatch):
    """An empty drain snapshot must not erase turns the stop path recorded."""

    from core.web.services import session_service

    store = _store(tmp_path)
    restart_resume_pending.record_pending_restart_resume(
        store, [{"sessionId": "session-a", "turnId": "turn-1"}]
    )

    class _EmptyStore:
        def __init__(self, root):
            self.root = root

        def load_active_snapshots(self, kind):
            return []

    monkeypatch.setattr(session_service, "_WORK_RUN_STORE", _EmptyStore(store.root))
    session_service.record_restart_resume_pending(replace=True)

    assert restart_resume_pending.load_pending_restart_resume(store) == {
        "session-a": {"turn-1"},
    }
