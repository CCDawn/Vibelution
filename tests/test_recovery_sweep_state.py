"""Watermark records the sweep completion, not its start."""

from __future__ import annotations

from types import SimpleNamespace

from core.web.services.session import recovery_sweep_state as state


def _store(tmp_path):
    return SimpleNamespace(root=tmp_path / "work_runs")


def test_watermark_records_completion_moment(tmp_path) -> None:
    store = _store(tmp_path)
    state.record_sweep_watermark(
        store,
        started_at_ns=100,
        completed_at_ns=900,
        scanned_session_count=3,
        resumed_count=1,
    )

    assert state.load_sweep_watermark_ns(store) == 900


def test_watermark_keeps_sessions_written_during_the_pass(tmp_path) -> None:
    store = _store(tmp_path)
    state.record_sweep_watermark(
        store,
        started_at_ns=100,
        completed_at_ns=900,
        dirty_session_ids=["session-a", "session-a", "session-b"],
        scanned_session_count=2,
        resumed_count=0,
    )

    assert state.load_watermark_dirty_session_ids(store) == {"session-a", "session-b"}


def test_missing_watermark_reports_nothing_dirty(tmp_path) -> None:
    assert state.load_watermark_dirty_session_ids(_store(tmp_path)) == set()
