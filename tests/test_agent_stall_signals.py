#!/usr/bin/env python3
from agent import (
    _reset_stall_signal_reported,
    _stall_signal_threshold_events,
)


def _telemetry(**values) -> dict:
    base = {
        "consecutive_tool_only_steps": 0,
        "consecutive_bookkeeping_tool_only_steps": 0,
        "no_new_evidence_steps": 0,
        "delegation_failures": 0,
    }
    base.update(values)
    return base


def test_no_events_below_threshold():
    telemetry = _telemetry(no_new_evidence_steps=2, delegation_failures=1)
    assert _stall_signal_threshold_events(telemetry, {}) == []


def test_events_when_crossing_threshold():
    telemetry = _telemetry(no_new_evidence_steps=3, consecutive_tool_only_steps=4)
    events = _stall_signal_threshold_events(telemetry, {})
    assert sorted(events) == ["consecutive_tool_only_steps", "no_new_evidence_steps"]


def test_reported_signals_are_not_repeated_while_growing():
    telemetry = _telemetry(no_new_evidence_steps=3)
    reported = {key: True for key in _stall_signal_threshold_events(telemetry, {})}

    assert _stall_signal_threshold_events(_telemetry(no_new_evidence_steps=5), reported) == []
    assert _stall_signal_threshold_events(_telemetry(no_new_evidence_steps=3), reported) == []


def test_reset_allows_re_report_after_progress():
    telemetry = _telemetry(no_new_evidence_steps=3)
    reported = {key: True for key in _stall_signal_threshold_events(telemetry, {})}

    reported = _reset_stall_signal_reported(_telemetry(no_new_evidence_steps=0), reported)
    assert _stall_signal_threshold_events(_telemetry(no_new_evidence_steps=3), reported) == [
        "no_new_evidence_steps"
    ]


def test_reset_keeps_other_reported_signals():
    telemetry = _telemetry(no_new_evidence_steps=3, delegation_failures=4)
    reported = {key: True for key in _stall_signal_threshold_events(telemetry, {})}

    reported = _reset_stall_signal_reported(_telemetry(no_new_evidence_steps=0, delegation_failures=4), reported)
    assert "no_new_evidence_steps" not in reported
    assert "delegation_failures" in reported


def test_round_state_telemetry_integration():
    from core.orchestration.round_state import RoundStateController

    state = RoundStateController(max_iterations=8)
    state.note_response_tools(2, visible_text="", tool_names=["get_git_status_summary_tool"])
    state.note_response_tools(1, visible_text="", tool_names=["task_list_tool"])
    state.note_response_tools(1, visible_text="", tool_names=["get_memory_summary_tool"])
    telemetry = state.runtime_telemetry()

    assert telemetry["consecutive_bookkeeping_tool_only_steps"] == 3
    events = _stall_signal_threshold_events(telemetry, {})
    assert "consecutive_bookkeeping_tool_only_steps" in events

    state.note_response_tools(1, visible_text="progress text", tool_names=["get_core_context_tool"])
    telemetry = state.runtime_telemetry()
    assert telemetry["consecutive_bookkeeping_tool_only_steps"] == 0
