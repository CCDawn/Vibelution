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
